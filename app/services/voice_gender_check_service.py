"""Standalone burned-subtitle to acoustic voice-gender inspection."""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any, Callable

from services.engine_runtime import EngineRuntime
from services.gender_service import GenderService
from services.subtitle_merge_service import SubtitleMergeService
from services.subtitle_translation_service import SubtitleTranslationService


class VoiceGenderCheckService:
    """Orchestrate audio extraction, OCR reading, deduplication, translation, and gender AI."""

    def run(
        self,
        video_path: str,
        *,
        existing_cues: list[dict[str, Any]] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if not video_path or not os.path.isfile(video_path):
            raise RuntimeError("Không tìm thấy video gốc để kiểm tra.")
        notify = progress or (lambda _message: None)
        engine = EngineRuntime()

        with tempfile.TemporaryDirectory(prefix="capcap_voice_gender_") as temp_dir:
            audio_path = os.path.join(temp_dir, "source_audio.wav")
            notify("Đang tách âm thanh gốc…")
            if not engine.extract_audio(video_path, audio_path) or not os.path.isfile(audio_path):
                raise RuntimeError("Không thể tách âm thanh từ video gốc.")

            vad_intervals: list[dict[str, Any]] = []
            asr_segments: list[dict[str, Any]] = []
            raw_cues: list[dict[str, Any]] = []

            # Định nghĩa hàm xử lý âm thanh (VAD + SenseVoice ASR)
            def _process_audio_features():
                local_vad = []
                local_asr = []
                try:
                    import soundfile as sf
                    from vad_processor import get_speech_segments
                    audio_data, sr = sf.read(audio_path, dtype="float32")
                    if audio_data.ndim > 1:
                        audio_data = audio_data.mean(axis=-1)
                    local_vad = get_speech_segments(audio_data, sr=sr)
                    print(f"[Voice Gender Check] VAD detected {len(local_vad)} speech intervals.")
                except Exception as e:
                    print(f"[Voice Gender Check] VAD notice: {e}")
                    local_vad = []

                try:
                    from runtime_paths import models_path
                    sensevoice_dir = str(models_path("sensevoice"))
                    raw = engine.transcribe_audio_sensevoice(audio_path, sensevoice_dir, language="zh")
                    local_asr = [dict(s) for s in (raw or [])]
                    print(f"[Voice Gender Check] ASR SenseVoice detected {len(local_asr)} segments.")
                except Exception as e:
                    print(f"[Voice Gender Check] ASR SenseVoice notice: {e}")
                    local_asr = []

                return local_vad, local_asr

            # Định nghĩa hàm đọc phụ đề video qua OCR
            def _process_video_ocr():
                region = str(os.getenv("OCR_SUBTITLE_REGION", "bottom") or "bottom")
                return list(engine.transcribe_video_ocr(video_path, region=region) or [])

            # Tối ưu hóa: Nếu đã có existing_cues hợp lệ, tái sử dụng ngay và chỉ phân tích audio
            has_valid_existing = bool(
                existing_cues and isinstance(existing_cues, list) and len(existing_cues) > 0
                and any(str(c.get("text", "") or "").strip() for c in existing_cues)
            )

            if has_valid_existing:
                notify("Tái sử dụng phụ đề đã nhận diện, đang phân tích giọng nói (ASR + VAD)…")
                raw_cues = [dict(c) for c in (existing_cues or []) if str(c.get("text", "") or "").strip()]
                vad_intervals, asr_segments = _process_audio_features()
            else:
                # Chạy SONG SONG tác vụ Audio (VAD + ASR) và Video (OCR) để giảm 50% thời gian chờ
                notify("Đang xử lý song song: Đọc phụ đề video (OCR) và nhận diện giọng nói (ASR/VAD)…")
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    fut_audio = executor.submit(_process_audio_features)
                    fut_ocr = executor.submit(_process_video_ocr)

                    vad_intervals, asr_segments = fut_audio.result()
                    raw_cues = fut_ocr.result()

            cues = [dict(cue) for cue in raw_cues if str(cue.get("text", "") or "").strip()]
            cues = self._filter_ocr_noise(cues)

            # 1. OCR Merge / Dedup with adaptive max_gap and strict text rules
            cues = SubtitleMergeService.merge_cues(cues)
            from services.fuzzy_duplicate_service import FuzzyDuplicateService
            cues = FuzzyDuplicateService.merge_fuzzy_cues(cues, vad_intervals=vad_intervals)
            if not cues:
                raise RuntimeError(
                    "Không đọc được phụ đề gốc. Hãy bấm OCR, đặt khung đúng vùng phụ đề rồi chạy lại."
                )

            # 2. Multimodal Fusion (OCR + ASR + VAD) loại bỏ chữ rác bao bì/logo
            notify("Đang kết hợp OCR, ASR và VAD (Multimodal Fusion)…")
            from services.hybrid_audio_ocr_fusion import classify_ocr_segments_multimodal
            cues = classify_ocr_segments_multimodal(cues, vad_speech_intervals=vad_intervals, asr_segments=asr_segments)

            # Assign consecutive IDs for tracking
            indexed_cues = [
                {**cue, "id": cue.get("id", index)}
                for index, cue in enumerate(cues, start=1)
            ]

            # 3. Audio-First: Nhận diện giọng nói vật lý bằng Gender AI offline trước
            notify("Đang nhận diện âm học giọng nói (Gender AI Audio-First)…")
            speech_cues = [c for c in indexed_cues if c.get("status") != "static_text" and not c.get("is_noise")]
            static_cues = [c for c in indexed_cues if c.get("status") == "static_text" or c.get("is_noise")]
            for sc in static_cues:
                sc["gender"] = "none"
                sc["skip_tts"] = True
                sc["confidence"] = 1.0

            if speech_cues:
                try:
                    detected_speech = GenderService().detect_cues(
                        audio_path,
                        speech_cues,
                        vad_intervals=vad_intervals,
                        progress=notify,
                    )
                except Exception as g_err:
                    print(f"[Voice Gender Check] GenderService acoustic fallback: {g_err}")
                    from services.speaker_gender import detect_speaker_gender_aggregated
                    detected_speech = []
                    for cue in speech_cues:
                        res = detect_speaker_gender_aggregated(audio_path, [cue])
                        g = res.get("gender", "unknown")
                        detected_speech.append({
                            **cue,
                            "gender": g,
                            "confidence": res.get("confidence", 0.7),
                            "raw_gender": g,
                            "raw_gender_confidence": res.get("confidence", 0.7),
                            "final_gender": g,
                        })
            else:
                detected_speech = []

            id_to_cue = {}
            for c in (detected_speech + static_cues):
                raw_id = c.get("id")
                id_to_cue[raw_id] = c
                id_to_cue[str(raw_id)] = c

            detected = []
            for c in indexed_cues:
                cid = c.get("id")
                matched = id_to_cue.get(cid) or id_to_cue.get(str(cid))
                detected.append(matched if matched else c)

            # 4. Xác lập Mốc Âm Học (Acoustic Anchors) & Quán tính lời thoại (Continuation Inertia)
            for i, c in enumerate(detected):
                dur = float(c.get("end", 0.0)) - float(c.get("start", 0.0))
                c["duration"] = round(dur, 2)
                if i > 0:
                    prev = detected[i - 1]
                    gap = round(float(c.get("start", 0.0)) - float(prev.get("end", 0.0)), 3)
                    prev_g = str(prev.get("raw_gender") or "").lower()
                    prev_conf = float(prev.get("raw_gender_confidence", 0.0) or 0.0)
                    if prev_conf > 1.0:
                        prev_conf /= 100.0
                    curr_g = str(c.get("raw_gender") or "").lower()
                    curr_conf = float(c.get("raw_gender_confidence", 0.0) or 0.0)
                    if curr_conf > 1.0:
                        curr_conf /= 100.0

                    # Quán tính lời thoại: Chỉ áp dụng khi câu này cùng giới tính hoặc âm học câu này yếu/unknown (< 75%)
                    # Tuyệt đối không ép quán tính khi câu này đã có âm thanh đối lập rõ rệt (>= 75%)
                    is_opposing = (curr_g in {"male", "female"} and curr_g != prev_g and curr_conf >= 0.75)
                    if gap <= 0.60 and dur <= 1.2 and prev_g in {"male", "female"} and prev_conf >= 0.85:
                        if not is_opposing:
                            c["continuation_gender"] = prev_g

                # Gán nhãn sơ bộ cho DeepSeek dựa trên mốc âm học đáng tin cậy
                rg = str(c.get("raw_gender") or "").lower()
                rc = float(c.get("raw_gender_confidence", 0.0) or 0.0)
                if rc > 1.0:
                    rc /= 100.0
                cont_g = c.get("continuation_gender")

                if cont_g in {"male", "female"}:
                    c["speaker_label"] = "Nam" if cont_g == "male" else "Nữ"
                    c["gender"] = cont_g
                elif rg in {"male", "female"} and rc >= 0.88 and dur >= 1.2:
                    c["speaker_label"] = "Nam" if rg == "male" else "Nữ"
                    c["gender"] = rg
                else:
                    c["speaker_label"] = "Chưa rõ"
                    c["gender"] = "unknown"

            # 5. Dịch kịch bản & phân vai ngữ cảnh (DeepSeek AI với Mốc Âm Học)
            notify("Đang dịch kịch bản & phân tích vai nhân vật (DeepSeek AI)…")
            try:
                import dotenv
                dotenv.load_dotenv(override=False)
            except Exception:
                pass

            deepseek_key = str(os.getenv("DEEPSEEK_API_KEY", "")).strip()
            translated_cues = []
            deepseek_genders: dict[int, str] = {}

            from services.subtitle_translation_service import SubtitleTranslationService
            if deepseek_key:
                try:
                    from services.deepseek_service import DeepSeekService
                    ds_svc = DeepSeekService(api_key=deepseek_key)
                    sub_trans_svc = SubtitleTranslationService(ds_svc)
                    translated_cues, _ = sub_trans_svc.translate_with_deepseek(
                        detected,
                        overwrite_manual=True,
                        progress=lambda msg, cur, tot: notify(f"DeepSeek đang dịch & phân vai ngữ cảnh ({cur}/{tot})…"),
                    )
                    for tc in translated_cues:
                        cid = tc.get("id")
                        g = str(tc.get("gender", "") or "").lower().strip()
                        if g in {"male", "female"}:
                            deepseek_genders[cid] = g
                except Exception as ds_err:
                    print(f"[Voice Gender Check] DeepSeek translation warning: {ds_err}")
                    translated_cues = []

            if not translated_cues:
                translated_cues = SubtitleTranslationService().translate_cues(
                    detected,
                    target_lang="vi",
                    progress=notify,
                )

            # Ghép lại bản dịch vào detected
            trans_by_id = {c.get("id"): c for c in translated_cues}
            merged_cues = []
            for c in detected:
                cid = c.get("id")
                tc = trans_by_id.get(cid) or {}
                merged_cues.append({
                    **c,
                    "translated_text": tc.get("translated_text", c.get("translated_text", "")),
                    "is_noise": tc.get("is_noise", c.get("is_noise", False)),
                    "deepseek_gender": deepseek_genders.get(cid, ""),
                })

            # 6. Anchor-Based Temporal Smoothing kết hợp DeepSeek Continuity
            from services.temporal_gender_smoothing import TemporalGenderSmoothingService
            continuity_groups = []
            if deepseek_genders:
                cur_grp = []
                cur_g = None
                for cue in merged_cues:
                    cid = cue.get("id")
                    dg = deepseek_genders.get(cid)
                    if dg and dg == cur_g:
                        cur_grp.append(cid)
                    else:
                        if len(cur_grp) >= 2:
                            continuity_groups.append({"ids": cur_grp, "same_speaker_likelihood": 0.95})
                        cur_grp = [cid] if dg else []
                        cur_g = dg
                if len(cur_grp) >= 2:
                    continuity_groups.append({"ids": cur_grp, "same_speaker_likelihood": 0.95})

            smoothed_detected = TemporalGenderSmoothingService.smooth(
                merged_cues,
                continuity_groups=continuity_groups
            )

            # 7. Decision Fusion Logic (Nơi DUY NHẤT quyết định final_gender)
            from services.decision_fusion_service import DecisionFusionService
            final_fused_cues = DecisionFusionService.fuse(
                smoothed_detected,
                deepseek_genders=deepseek_genders,
                deepseek_continuity=continuity_groups,
            )

            # 7. Assemble Voice Check Result
            rows: list[dict[str, Any]] = []
            counts = {"male": 0, "female": 0, "none": 0, "unknown": 0}
            for index, cue in enumerate(final_fused_cues, start=1):
                gender = str(cue.get("final_gender") or cue.get("gender", "unknown") or "unknown").lower()
                source = str(cue.get("source", "gender-ai-windows") or "gender-ai-windows")
                confidence = float(cue.get("final_decision_confidence") or cue.get("confidence", 0.0) or 0.0)
                # If confidence is in [0, 1], express as percentage (e.g. 98.7)
                confidence_pct = round(confidence * 100.0 if confidence <= 1.0 else confidence, 1)

                raw_g = str(cue.get("raw_gender", gender) or gender).lower()
                raw_c = float(cue.get("raw_gender_confidence", 0.0) or 0.0)
                raw_c_pct = round(raw_c * 100.0 if raw_c <= 1.0 else raw_c, 1)

                if gender not in {"male", "female", "none"}:
                    gender = "unknown"
                counts[gender] += 1

                cue_text = str(cue.get("text", "") or cue.get("original_text", "") or "").strip()
                translated_text = str(cue.get("translated_text", "") or "").strip()
                merged_from = list(cue.get("merged_from") or [cue.get("id", index)])

                raw_id = str(cue.get("id", index) or index).split(":", 1)[0]
                try:
                    cue_id = int(raw_id)
                except (ValueError, TypeError):
                    cue_id = index

                rows.append({
                    "id": cue_id,
                    "index": index,
                    "start": round(float(cue.get("start", 0.0) or 0.0), 3),
                    "end": round(float(cue.get("end", 0.0) or 0.0), 3),
                    "original_text": cue_text,
                    "text": cue_text,
                    "translated_text": translated_text,
                    "speaker": str(cue.get("speaker", "") or "").strip(),
                    "gender": gender,
                    "confidence": confidence_pct,
                    "raw_gender": raw_g,
                    "raw_gender_confidence": raw_c_pct,
                    "final_gender": gender,
                    "final_decision_confidence": confidence_pct,
                    "decision_mode": str(cue.get("decision_mode", "raw_audio")),
                    "audio_quality": str(cue.get("audio_quality", "clean")),
                    "speech_duration": float(cue.get("speech_duration", 0.0) or 0.0),
                    "speech_ratio": float(cue.get("speech_ratio", 0.0) or 0.0),
                    "music_score": float(cue.get("music_score", 0.0) or 0.0),
                    "gender_reason": list(cue.get("gender_reason", []) or []),
                    "alignment_confidence": 1.0,
                    "source": source,
                    "status": str(cue.get("status", "ok") or "ok"),
                    "merged_from": merged_from,
                    "skip_tts": bool(cue.get("skip_tts", False)),
                })

        return {
            "video_path": os.path.abspath(video_path),
            "rows": rows,
            "counts": counts,
            "speaker_profiles": {},
        }

    @staticmethod
    def _filter_ocr_noise(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove Latin hallucinations when the burned subtitles are CJK.

        OCR can interpret clothing, railings, compression blocks, or an overlay
        behind the subtitle as long English phrases. This filter is deliberately
        enabled only when CJK is clearly the dominant subtitle script.
        """
        texts = [str(cue.get("text", "") or "").strip() for cue in cues]
        cjk_chars = sum(len(re.findall(r"[\u3400-\u9fff]", text)) for text in texts)
        cjk_cues = sum(bool(re.search(r"[\u3400-\u9fff]", text)) for text in texts)
        cjk_dominant = cjk_chars >= 6 and cjk_cues >= max(2, len(texts) * 0.5)
        if not cjk_dominant:
            return cues

        cleaned: list[dict[str, Any]] = []
        for cue in cues:
            item = dict(cue)
            text = str(item.get("text", "") or "").strip()
            if not re.search(r"[\u3400-\u9fff]", text):
                continue
            text = re.sub(r"[A-Za-z]+(?:[ '\u2019-][A-Za-z]+)*", " ", text)
            text = re.sub(r"\s+", " ", text).strip(" ,.;:|_-")
            if text:
                item["text"] = text
                cleaned.append(item)
        return cleaned

    @staticmethod
    def _merge_fuzzy_duplicate_cues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ủy quyền sang FuzzyDuplicateService độc lập theo kiến trúc Clean Architecture."""
        from services.fuzzy_duplicate_service import FuzzyDuplicateService
        return FuzzyDuplicateService.merge_fuzzy_cues(cues)
