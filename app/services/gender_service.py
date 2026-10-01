"""Offline, Windows-native gender inference for OCR subtitle timestamps."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from runtime_paths import temp_path


class GenderService:
    """Load the packaged detector once and classify subtitle intervals in batch."""

    _detector = None
    _load_lock = Lock()
    _inference_lock = Lock()

    def __init__(self, package_dir: str | os.PathLike[str] | None = None):
        root = Path(__file__).resolve().parents[2]
        candidates = [
            Path(package_dir) if package_dir else None,
            root / "ai_models" / "gender_ai",
            root / "gender_voice_ai_windows_package",
        ]
        self.package_dir = next((path.resolve() for path in candidates if path and path.is_dir()), None)
        if self.package_dir is None:
            raise RuntimeError(
                "Không tìm thấy gói Gender AI. Hãy đặt nó tại "
                "gender_voice_ai_windows_package hoặc ai_models/gender_ai."
            )
        self.classifier_path = self.package_dir / "gender_classifier.joblib"
        self.runtime_models = self.package_dir / "runtime_models"
        if not self.classifier_path.is_file() or not self.runtime_models.is_dir():
            raise RuntimeError("Gói Gender AI thiếu classifier hoặc runtime_models.")
        self.accept_confidence = float(os.getenv("GENDER_AI_ACCEPT_CONFIDENCE", "0.65"))

    def load(self, progress: Callable[[str], None] | None = None):
        if type(self)._detector is not None:
            return type(self)._detector
        notify = progress or (lambda _message: None)
        with type(self)._load_lock:
            if type(self)._detector is not None:
                return type(self)._detector
            notify("Đang nạp Gender AI offline (lần đầu có thể mất vài phút)…")
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            package_text = str(self.package_dir)
            if package_text not in sys.path:
                sys.path.insert(0, package_text)
            try:
                from gender_detector import GenderDetector
            except ImportError as exc:
                raise RuntimeError(
                    "Thiếu thư viện Gender AI. Hãy cài torch, torchaudio, "
                    "speechbrain và transformers vào .venv."
                ) from exc
            import torch
            try:
                torch.set_num_threads(min(8, os.cpu_count() or 4))
            except Exception:
                pass
            type(self)._detector = GenderDetector(
                gender_model_path=self.classifier_path,
                cache_dir=self.runtime_models,
                device="cpu",
                min_gender_confidence=self.accept_confidence,
            )
            notify("Đã nạp Gender AI offline.")
            return type(self)._detector

    @staticmethod
    def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
        raw = dict(result or {})
        status = str(raw.get("status", "") or "").strip().lower()
        gender = str(raw.get("gender", "unknown") or "unknown").strip().lower()
        confidence = float(raw.get("confidence", 0.0) or 0.0)
        if status == "music_or_non_speech":
            gender, skip_tts = "none", True
        elif gender in {"male", "female"}:
            skip_tts = False
        else:
            gender, skip_tts = "unknown", False
        return {
            **raw,
            "gender": gender,
            "confidence": confidence,
            "skip_tts": skip_tts,
            "source": "gender-ai-windows",
        }

    @staticmethod
    def _audio_digest(audio_path: str) -> str:
        digest = hashlib.sha256()
        with open(audio_path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _cache_file(self, audio_path: str, cues: list[dict[str, Any]]) -> Path:
        payload = {
            "version": 3,
            "audio": self._audio_digest(audio_path),
            "cues": [
                (str(cue.get("id", index)), round(float(cue.get("start", 0.0)), 3), round(float(cue.get("end", 0.0)), 3))
                for index, cue in enumerate(cues, start=1)
            ],
            "classifier": self.classifier_path.stat().st_size,
        }
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        directory = Path(temp_path("gender_ai_cache"))
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{key}.json"

    @staticmethod
    def _vad_aware_attempts(
        cues: list[dict[str, Any]],
        vad_intervals: list[dict[str, Any]] | None = None,
        pad: float = 0.06,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        meta_by_id: dict[str, dict[str, Any]] = {}
        intervals = vad_intervals or []

        for index, cue in enumerate(cues, start=1):
            cue_id = str(cue.get("id", index))
            start = max(0.0, float(cue.get("start", 0.0) or 0.0))
            end = max(start, float(cue.get("end", start) or start))
            sub_dur = max(0.01, end - start)

            # Tìm các khoảng VAD speech giao nhau với slot
            overlaps = []
            for v in intervals:
                vs = float(v.get("start", 0.0) or 0.0)
                ve = float(v.get("end", 0.0) or 0.0)
                ov_s = max(start, vs)
                ov_e = min(end, ve)
                if ov_e > ov_s:
                    overlaps.append((vs, ve, ov_s, ov_e))

            if overlaps:
                min_sp = min(o[2] for o in overlaps)
                max_sp = max(o[3] for o in overlaps)
                # Clamp chặt trong subtitle slot
                ext_start = max(start, min_sp - pad)
                ext_end = min(end, max_sp + pad)
                speech_dur = round(ext_end - ext_start, 3)
                speech_ratio = round(speech_dur / sub_dur, 3)
                tag = "vad_clamped"
            else:
                ext_start = start
                ext_end = end
                speech_dur = 0.0
                speech_ratio = 0.0
                tag = "no_speech_in_slot"

            is_confirmed_speech = (speech_dur >= 0.40 and speech_ratio >= 0.35)
            attempts.append({
                "id": f"{cue_id}:vad",
                "start": ext_start,
                "end": ext_end,
                "skip_ast": is_confirmed_speech,
                "is_confirmed_speech": is_confirmed_speech,
            })
            meta_by_id[cue_id] = {
                "speech_duration": speech_dur,
                "speech_ratio": speech_ratio,
                "extraction_tag": tag,
                "slot_duration": round(sub_dur, 3),
            }

        return attempts, meta_by_id

    def detect_cues(
        self,
        audio_path: str,
        cues: list[dict[str, Any]],
        *,
        vad_intervals: list[dict[str, Any]] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        notify = progress or (lambda _message: None)
        clean_cues = [dict(cue) for cue in cues]
        if not clean_cues:
            return []

        # Kiểm tra cache đã có sẵn cho audio và danh sách timestamps này chưa
        cache_path = self._cache_file(audio_path, clean_cues)
        if cache_path.is_file():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                if isinstance(cached_data, list) and len(cached_data) == len(clean_cues):
                    cached_by_id = {str(c.get("id")): c for c in cached_data}
                    resolved = []
                    for idx, cue in enumerate(clean_cues, start=1):
                        cid = str(cue.get("id", idx))
                        if cid in cached_by_id:
                            resolved.append({**cue, **cached_by_id[cid]})
                        else:
                            break
                    if len(resolved) == len(clean_cues):
                        print(f"[GenderService] Tận dụng cache AI ({len(resolved)} câu thoại) từ {cache_path.name}")
                        return resolved
            except Exception as e:
                print(f"[GenderService] Cache read notice: {e}")

        detector = self.load(notify)
        attempts, meta_by_id = self._vad_aware_attempts(clean_cues, vad_intervals)
        notify(f"Đang nhận diện Nam/Nữ cho {len(clean_cues)} câu bằng Gender AI…")
        with type(self)._inference_lock:
            raw_results = list(detector.detect_segments(audio_path, attempts) or [])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for result in raw_results:
            base_id = str(result.get("id", "")).split(":", 1)[0]
            grouped.setdefault(base_id, []).append(dict(result))

        resolved = []
        for index, cue in enumerate(clean_cues, start=1):
            cue_id = str(cue.get("id", index))
            res = (grouped.get(cue_id) or [{}])[0]
            meta = meta_by_id.get(cue_id, {})
            sp_dur = float(meta.get("speech_duration", 0.0) or 0.0)
            sp_ratio = float(meta.get("speech_ratio", 0.0) or 0.0)

            pred_gender = str(res.get("gender", "") or "").lower()
            conf = float(res.get("confidence", 0.0) or 0.0)
            male_p = float(res.get("male_probability", 0.0) or 0.0)
            female_p = float(res.get("female_probability", 0.0) or 0.0)
            music_score = float(res.get("music_score", 0.0) or 0.0)
            speech_score = float(res.get("speech_score", 0.0) or 0.0)

            if pred_gender in {"male", "female"}:
                raw_gender = pred_gender
            elif male_p > female_p and male_p >= 0.50:
                raw_gender = "male"
                conf = male_p
            elif female_p > male_p and female_p >= 0.50:
                raw_gender = "female"
                conf = female_p
            else:
                raw_gender = "unknown"

            # Đánh giá Audio Quality & Raw Confidence Trust
            if sp_dur >= 1.2 and music_score < 0.35 and sp_ratio >= 0.50:
                audio_qual = "clean"
                raw_trust = "HIGH"
            elif sp_dur < 0.80 or sp_ratio < 0.35 or music_score >= 0.40:
                audio_qual = "low"
                raw_trust = "LOW"
            else:
                audio_qual = "low"
                raw_trust = "MEDIUM"

            resolved.append({
                **cue,
                "id": cue.get("id", index),
                "gender": raw_gender,
                "confidence": conf,
                "raw_gender": raw_gender,
                "raw_gender_confidence": conf,
                "raw_confidence_trust": raw_trust,
                "final_gender": raw_gender,
                "final_decision_confidence": conf,
                "decision_mode": "raw_audio",
                "audio_quality": audio_qual,
                "speech_duration": sp_dur,
                "speech_ratio": sp_ratio,
                "music_score": music_score,
                "speech_score": speech_score,
                "gender_reason": ["raw_audio_inference"],
                "status": "ok" if raw_gender in {"male", "female"} else "unknown",
                "skip_tts": False,
                "source": "gender-ai-windows",
            })

        # Lưu kết quả tính toán vào cache để tái sử dụng ngay lập tức
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(resolved, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[GenderService] Cache write notice: {e}")

        return resolved
