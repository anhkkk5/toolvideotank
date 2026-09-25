"""WhissleAI Mandarin gender classification aggregated per diarized speaker."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import requests

from runtime_paths import bin_path, subprocess_hidden_kwargs, temp_path


class WhissleClient:
    def __init__(self, base_url: str | None = None, timeout: int | None = None):
        self.base_url = str(base_url or os.getenv("WHISSLE_BASE_URL", "http://localhost:8002")).rstrip("/")
        self.timeout = int(timeout or os.getenv("WHISSLE_TIMEOUT_SECONDS", "60"))

    def health_check(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/health", timeout=5).ok
        except requests.RequestException:
            return False

    def detect_gender(self, audio_path: str) -> dict[str, Any]:
        with open(audio_path, "rb") as handle:
            response = requests.post(
                f"{self.base_url}/asr/transcribe",
                files={"file": (os.path.basename(audio_path), handle, "audio/wav")},
                timeout=self.timeout,
            )
        response.raise_for_status()
        data = response.json()
        tags = data.get("tags") or {}
        raw = str(tags.get("gender", "NONE") if isinstance(tags, dict) else "NONE").upper()
        gender = {"MALE": "male", "FEMALE": "female"}.get(raw, "unknown")
        return {"gender": gender, "raw_gender": raw, "text": str(data.get("text", "") or ""), "raw": data}


class WhissleGenderService:
    def __init__(self, client: WhissleClient | None = None):
        self.client = client or WhissleClient()
        self.min_duration = float(os.getenv("GENDER_MIN_SEGMENT_SECONDS", "1.0"))
        self.preferred_min = float(os.getenv("GENDER_PREFERRED_MIN_SECONDS", "2.0"))
        self.preferred_max = float(os.getenv("GENDER_PREFERRED_MAX_SECONDS", "8.0"))
        self.target_samples = int(os.getenv("GENDER_TARGET_SAMPLES_PER_SPEAKER", "5"))
        self.min_consensus = float(os.getenv("GENDER_MIN_CONSENSUS", "0.65"))

    @staticmethod
    def _mark_overlaps(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = [{**turn, "is_overlap": False} for turn in turns]
        for index, first in enumerate(result):
            for second in result[index + 1:]:
                if first.get("speaker") == second.get("speaker"):
                    continue
                if max(float(first["start"]), float(second["start"])) < min(float(first["end"]), float(second["end"])):
                    first["is_overlap"] = True
                    second["is_overlap"] = True
        return result

    def _select(self, turns: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for turn in self._mark_overlaps(turns):
            duration = max(0.0, float(turn.get("end", 0.0)) - float(turn.get("start", 0.0)))
            speaker = str(turn.get("speaker", "") or "")
            if speaker and duration >= self.min_duration and not turn.get("is_overlap"):
                grouped[speaker].append({**turn, "duration": duration})
        selected = {}
        for speaker, items in grouped.items():
            items.sort(
                key=lambda item: (
                    self.preferred_min <= item["duration"] <= self.preferred_max,
                    min(item["duration"], self.preferred_max),
                ),
                reverse=True,
            )
            selected[speaker] = items[: self.target_samples]
        return selected

    @staticmethod
    def _crop(source_audio: str, output_path: str, start: float, end: float) -> None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(bin_path("ffmpeg", "ffmpeg.exe")), "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, start):.3f}", "-i", source_audio,
            "-t", f"{max(0.05, end - start):.3f}",
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", output_path,
        ]
        subprocess.run(command, check=True, capture_output=True, **subprocess_hidden_kwargs())

    @staticmethod
    def _cache_key(source_audio: str, turns: list[dict[str, Any]]) -> str:
        audio_hash = hashlib.sha256()
        with open(source_audio, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                audio_hash.update(block)
        payload = {
            "audio_sha256": audio_hash.hexdigest(),
            "turns": [(x.get("speaker"), round(float(x.get("start", 0)), 3), round(float(x.get("end", 0)), 3)) for x in turns],
            "version": 1,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def analyze(
        self,
        source_audio: str,
        turns: list[dict[str, Any]],
        *,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, dict[str, Any]]:
        notify = progress or (lambda _message: None)
        if not self.client.health_check():
            raise RuntimeError(
                f"Không kết nối được WhissleAI tại {self.client.base_url}. "
                "Hãy khởi động server Mandarin rồi kiểm tra lại /health."
            )
        cache_dir = Path(temp_path("gender_cache"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{self._cache_key(source_audio, turns)}.json"
        if cache_file.is_file():
            try:
                return dict(json.loads(cache_file.read_text(encoding="utf-8")).get("profiles") or {})
            except Exception:
                pass

        selected = self._select(turns)
        profiles: dict[str, dict[str, Any]] = {}
        work_dir = Path(temp_path("gender_segments", cache_file.stem[:16]))
        for speaker_index, (speaker, samples) in enumerate(sorted(selected.items()), start=1):
            predictions = []
            for sample_index, segment in enumerate(samples, start=1):
                notify(
                    f"Whissle: speaker {speaker_index}/{len(selected)}, "
                    f"mẫu {sample_index}/{len(samples)}…"
                )
                output = work_dir / speaker / f"{sample_index:03d}.wav"
                self._crop(source_audio, str(output), float(segment["start"]), float(segment["end"]))
                result = self.client.detect_gender(str(output))
                predictions.append({**segment, **result})
                print(f"[Whissle Gender] {speaker} {segment['duration']:.2f}s => {result['raw_gender']}")

            seconds = {"male": 0.0, "female": 0.0}
            for prediction in predictions:
                gender = str(prediction.get("gender", "unknown"))
                if gender in seconds:
                    seconds[gender] += float(prediction.get("duration", 0.0))
            evidence = seconds["male"] + seconds["female"]
            winner = max(seconds, key=seconds.get) if evidence else "unknown"
            consensus = seconds.get(winner, 0.0) / evidence if evidence else 0.0
            gender = winner if evidence and consensus >= self.min_consensus else "unknown"
            profiles[speaker] = {
                "gender": gender,
                "consensus": round(consensus, 3),
                "male_seconds": round(seconds["male"], 3),
                "female_seconds": round(seconds["female"], 3),
                "sample_count": len(predictions),
                "source": "whissle",
                "samples": predictions,
            }
            print(f"[Whissle Gender] {speaker} final={gender} consensus={consensus:.2f}")

        for speaker in {str(turn.get("speaker", "") or "") for turn in turns}:
            profiles.setdefault(speaker, {
                "gender": "unknown", "consensus": 0.0, "male_seconds": 0.0,
                "female_seconds": 0.0, "sample_count": 0, "source": "whissle-no-clean-sample", "samples": [],
            })
        cache_file.write_text(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2), encoding="utf-8")
        return profiles
