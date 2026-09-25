"""Paid OpenAI speaker diarization followed by local acoustic gender analysis."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
import time
from typing import Any

from services.speaker_gender import detect_speaker_gender_aggregated
from runtime_paths import bin_path, subprocess_hidden_kwargs


class OpenAISpeakerAnalysisService:
    DEFAULT_MODEL = "gpt-4o-transcribe-diarize"

    @staticmethod
    def _chat_completion_with_retry(client, **kwargs):
        """Retry TPM throttling using the delay returned by OpenAI.

        Vision character resolution can require several chronological batches.
        A later batch may cross the per-minute token window even though the
        account still has credit.  Treat only HTTP 429 as retryable; all other
        API failures remain visible immediately.
        """
        try:
            max_attempts = max(1, min(8, int(os.getenv("OPENAI_RATE_LIMIT_RETRIES", "5"))))
        except (TypeError, ValueError):
            max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                message = str(exc or "")
                is_rate_limit = status_code == 429 or "rate limit" in message.lower() or "error code: 429" in message.lower()
                if not is_rate_limit or attempt >= max_attempts:
                    raise
                match = re.search(r"try again in\s+([0-9.]+)s", message, flags=re.IGNORECASE)
                requested_wait = float(match.group(1)) if match else 0.0
                delay = max(requested_wait + 0.75, min(60.0, 2.0 ** attempt))
                delay = min(90.0, delay)
                print(
                    "[OpenAI Rate Limit] TPM window is full; "
                    f"waiting {delay:.2f}s before retry {attempt + 1}/{max_attempts}."
                )
                time.sleep(delay)
        raise RuntimeError("OpenAI retry loop ended unexpectedly")

    @classmethod
    def is_configured(cls) -> bool:
        return bool(str(os.getenv("OPENAI_API_KEY", "") or "").strip())

    @classmethod
    def cache_key(cls) -> str:
        model = str(os.getenv("OPENAI_DIARIZATION_MODEL", cls.DEFAULT_MODEL) or cls.DEFAULT_MODEL).strip()
        return f"openai-speaker-analysis-v1|{model}"

    @staticmethod
    def _value(item: Any, name: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    def analyze(self, audio_path: str, *, video_path: str = "") -> dict[str, Any]:
        if not audio_path or not os.path.isfile(audio_path):
            raise RuntimeError("Không tìm thấy âm thanh để OpenAI phân tích người nói.")
        api_key = str(os.getenv("OPENAI_API_KEY", "") or "").strip()
        if not api_key:
            raise RuntimeError("Chưa cấu hình OPENAI_API_KEY.")

        from openai import OpenAI

        model = str(os.getenv("OPENAI_DIARIZATION_MODEL", self.DEFAULT_MODEL) or self.DEFAULT_MODEL).strip()
        # Speaker analysis must use the official OpenAI endpoint.  Translation
        # providers may independently point OPENAI_BASE_URL at compatible APIs.
        client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format="diarized_json",
                chunking_strategy="auto",
            )

        raw_segments = list(self._value(response, "segments", []) or [])
        label_map: dict[str, str] = {}
        turns: list[dict[str, Any]] = []
        for segment in raw_segments:
            raw_label = str(self._value(segment, "speaker", "") or "").strip()
            if not raw_label:
                continue
            if raw_label not in label_map:
                label_map[raw_label] = f"SPEAKER_{len(label_map):02d}"
            start = max(0.0, float(self._value(segment, "start", 0.0) or 0.0))
            end = max(start, float(self._value(segment, "end", start) or start))
            if end - start < 0.05:
                continue
            turns.append({
                "start": start,
                "end": end,
                "speaker": label_map[raw_label],
                "text": str(self._value(segment, "text", "") or "").strip(),
            })

        if not turns:
            raise RuntimeError("OpenAI không trả về lượt nói nào từ âm thanh này.")

        result = self.postprocess(audio_path, turns, model=model)
        if video_path and os.path.isfile(video_path):
            result = self.apply_visual_voice_cast(client, video_path, result)
        return result

    @staticmethod
    def _frame_data_url(video_path: str, at_seconds: float) -> str:
        command = [
            str(bin_path("ffmpeg", "ffmpeg.exe")), "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, at_seconds):.3f}", "-i", video_path,
            "-frames:v", "1", "-vf", "scale=512:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        ]
        completed = subprocess.run(command, capture_output=True, check=True, **subprocess_hidden_kwargs())
        if not completed.stdout:
            return ""
        encoded = base64.b64encode(completed.stdout).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @staticmethod
    def _stabilize_singleton_speakers(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge a one-turn fragment when the same speaker clearly surrounds it."""
        normalized = [dict(turn) for turn in sorted(turns, key=lambda x: float(x.get("start", 0.0)))]
        counts: dict[str, int] = {}
        for turn in normalized:
            speaker = str(turn.get("speaker", "") or "")
            counts[speaker] = counts.get(speaker, 0) + 1
        for index in range(1, len(normalized) - 1):
            current = normalized[index]
            speaker = str(current.get("speaker", "") or "")
            previous = normalized[index - 1]
            following = normalized[index + 1]
            surrounding = str(previous.get("speaker", "") or "")
            if counts.get(speaker, 0) != 1 or not surrounding:
                continue
            if surrounding != str(following.get("speaker", "") or ""):
                continue
            left_gap = float(current.get("start", 0.0)) - float(previous.get("end", 0.0))
            right_gap = float(following.get("start", 0.0)) - float(current.get("end", 0.0))
            if left_gap <= 2.0 and right_gap <= 2.0:
                current["speaker"] = surrounding
        return normalized

    def postprocess(self, audio_path: str, turns: list[dict[str, Any]], *, model: str = "") -> dict[str, Any]:
        turns = self._stabilize_singleton_speakers(turns)

        speakers: list[dict[str, Any]] = []
        for speaker in sorted({str(turn["speaker"]) for turn in turns}):
            samples = [turn for turn in turns if turn["speaker"] == speaker]
            profile = detect_speaker_gender_aggregated(audio_path, samples)
            speakers.append({
                "speaker": speaker,
                "gender": str(profile.get("gender", "unknown") or "unknown"),
                "confidence": float(profile.get("confidence", 0.0) or 0.0),
                "median_pitch": float(profile.get("median_pitch", 0.0) or 0.0),
                "pitch_q25": float(profile.get("pitch_q25", 0.0) or 0.0),
                "turn_count": len(samples),
                "duration": round(sum(float(x["end"]) - float(x["start"]) for x in samples), 3),
            })

        counts = {"male": 0, "female": 0, "unknown": 0}
        for speaker in speakers:
            gender = speaker["gender"] if speaker["gender"] in counts else "unknown"
            counts[gender] += 1
        summary = {
            "provider": "openai",
            "model": model or self.DEFAULT_MODEL,
            "speaker_count": len(speakers),
            "male_count": counts["male"],
            "female_count": counts["female"],
            "unknown_count": counts["unknown"],
            "speakers": speakers,
        }
        return {"summary": summary, "turns": turns}

    def apply_visual_voice_cast(self, client, video_path: str, result: dict[str, Any]) -> dict[str, Any]:
        """Use representative video frames to choose a masculine/feminine TTS category."""
        summary = dict(result.get("summary") or {})
        turns = list(result.get("turns") or [])
        speakers = list(summary.get("speakers") or [])
        content: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                "Choose a Vietnamese dubbing voice category for the visibly speaking role in each labeled frame. "
                "Return JSON only: {\"speakers\": {\"SPEAKER_00\": \"male\" or \"female\" or \"unknown\"}}. "
                "This is voice casting, not a claim about anyone's identity. If the active speaker is not visible, use unknown."
            ),
        }]
        included: list[str] = []
        for profile in speakers:
            speaker = str(profile.get("speaker", "") or "")
            candidates = sorted(
                (turn for turn in turns if str(turn.get("speaker", "") or "") == speaker),
                key=lambda turn: float(turn.get("end", 0.0)) - float(turn.get("start", 0.0)),
                reverse=True,
            )
            if not candidates:
                continue
            turn = candidates[0]
            midpoint = (float(turn.get("start", 0.0)) + float(turn.get("end", 0.0))) / 2.0
            data_url = self._frame_data_url(video_path, midpoint)
            if not data_url:
                continue
            included.append(speaker)
            content.append({"type": "text", "text": f"{speaker}, time {midpoint:.2f}s:"})
            content.append({"type": "image_url", "image_url": {"url": data_url, "detail": "low"}})
        if not included:
            return result

        vision_model = str(os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()
        response = self._chat_completion_with_retry(
            client,
            model=vision_model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=160,
        )
        raw = str(response.choices[0].message.content or "{}")
        payload = json.loads(raw)
        casts = dict(payload.get("speakers") or {})
        for profile in speakers:
            speaker = str(profile.get("speaker", "") or "")
            visual = str(casts.get(speaker, "unknown") or "unknown").strip().lower()
            if visual in {"male", "female"}:
                profile["gender"] = visual
                profile["confidence"] = 0.98
                profile["gender_source"] = "openai-vision"

        counts = {"male": 0, "female": 0, "unknown": 0}
        for profile in speakers:
            gender = str(profile.get("gender", "unknown") or "unknown")
            counts[gender if gender in counts else "unknown"] += 1
        summary.update({
            "speakers": speakers,
            "male_count": counts["male"],
            "female_count": counts["female"],
            "unknown_count": counts["unknown"],
            "vision_model": vision_model,
            "visual_analysis_version": 1,
        })
        return {"summary": summary, "turns": turns}

    def analyze_visual(self, video_path: str, result: dict[str, Any]) -> dict[str, Any]:
        from openai import OpenAI

        api_key = str(os.getenv("OPENAI_API_KEY", "") or "").strip()
        if not api_key:
            return result
        client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
        return self.apply_visual_voice_cast(client, video_path, result)

    def resolve_characters(self, video_path: str, result: dict[str, Any]) -> dict[str, Any]:
        """Resolve diarized speech turns to stable visual Character IDs."""
        from openai import OpenAI
        from services import CharacterSegmentSplitter

        if not video_path or not os.path.isfile(video_path):
            return result
        api_key = str(os.getenv("OPENAI_API_KEY", "") or "").strip()
        if not api_key:
            return result
        turns = [dict(turn) for turn in list(result.get("turns") or [])]
        instruction: dict[str, Any] = {
            "type": "text",
            "text": (
                "You are resolving characters in a short drama for voice dubbing. Each labeled image is sampled "
                "during one speech turn. Identify the visibly active speaking character, keep the same character_id "
                "across costume and scene changes by facial identity, and allow one audio_speaker to map to multiple "
                "characters. Do not count silent bystanders. If exact identity is uncertain, character_id may be "
                "UNKNOWN, but voice_category must still be male or female whenever all plausible visible speakers "
                "share that category; use unknown voice_category only when gender itself is genuinely ambiguous. "
                "A single audio turn can contain a speaker change. For every sampled timestamp, decide who is actively "
                "speaking (prefer visible lip activity, not merely who is on screen). If the active character changes "
                "inside a turn, return multiple time spans with the boundary near the sampled timestamps. "
                "Return JSON only as {\"turns\":[{\"turn_index\":0,\"character_id\":\"CHAR_01\","
                "\"voice_category\":\"male|female|unknown\",\"confidence\":0.0,\"spans\":[{\"start\":0.0,"
                "\"end\":1.0,\"character_id\":\"CHAR_01\",\"voice_category\":\"male\",\"confidence\":0.9}]}],"
                "\"characters\":[...]}. Omit spans only when there is no usable temporal evidence."
            ),
        }
        included: list[int] = []
        turn_content: dict[int, list[dict[str, Any]]] = {}
        for index, turn in enumerate(turns):
            start = float(turn.get("start", 0.0) or 0.0)
            end = float(turn.get("end", start) or start)
            duration = max(0.05, end - start)
            sample_count = max(3, min(7, int(math.ceil(duration / 0.8))))
            sample_times = [
                start + duration * ((sample_index + 0.5) / sample_count)
                for sample_index in range(sample_count)
            ]
            frame_samples = [
                (at, url) for at in sample_times
                if (url := self._frame_data_url(video_path, at))
            ]
            if not frame_samples:
                continue
            included.append(index)
            block: list[dict[str, Any]] = []
            label = (
                f"turn_index={index}; audio_speaker={turn.get('speaker', '')}; "
                f"time={start:.2f}-{end:.2f}; transcript={str(turn.get('text', '') or '')[:100]}"
            )
            block.append({"type": "text", "text": label})
            for frame_time, frame_url in frame_samples:
                block.append({"type": "text", "text": f"frame_time={frame_time:.3f}"})
                block.append({"type": "image_url", "image_url": {"url": frame_url, "detail": "low"}})
            turn_content[index] = block
        if not included:
            return result

        client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
        model = str(os.getenv("OPENAI_CHARACTER_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()
        try:
            batch_size = max(2, min(10, int(os.getenv("OPENAI_CHARACTER_BATCH_SIZE", "6"))))
        except (TypeError, ValueError):
            batch_size = 6
        assignments: dict[int, dict[str, Any]] = {}
        for offset in range(0, len(included), batch_size):
            batch_indexes = included[offset:offset + batch_size]
            content: list[dict[str, Any]] = [instruction]
            if assignments:
                # Batch-local labels are unsafe unless the next request can
                # see the same face. Supply one visual anchor per known CHAR,
                # not only a textual turn index from an earlier request.
                known_by_character: dict[str, tuple[int, dict[str, Any]]] = {}
                for key, value in sorted(assignments.items()):
                    known_id = str(value.get("character_id", "UNKNOWN") or "UNKNOWN").strip().upper()
                    if known_id.startswith("CHAR_") and known_id not in known_by_character:
                        known_by_character[known_id] = (key, value)
                known = [
                    {
                        "turn_index": key,
                        "character_id": character_id,
                        "voice_category": value.get("voice_category", "unknown"),
                    }
                    for character_id, (key, value) in list(known_by_character.items())[-8:]
                ]
                content.append({
                    "type": "text",
                    "text": "Reference identities from earlier chronological batches follow. Reuse an existing character_id only when the face matches its reference; keep its voice_category/gender unchanged: " + json.dumps(known),
                })
                for character_id, (known_index, value) in list(known_by_character.items())[-8:]:
                    reference_images = [
                        block for block in turn_content.get(known_index, [])
                        if block.get("type") == "image_url"
                    ]
                    if reference_images:
                        content.append({"type": "text", "text": f"identity_reference={character_id}"})
                        content.append(reference_images[0])
            for turn_index in batch_indexes:
                content.extend(turn_content[turn_index])
            print(
                f"[Character Resolver] Vision batch {offset // batch_size + 1}/"
                f"{math.ceil(len(included) / batch_size)} ({len(batch_indexes)} turns)."
            )
            response = self._chat_completion_with_retry(
                client,
                model=model,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=max(900, len(batch_indexes) * 130),
            )
            raw_payload = str(response.choices[0].message.content or "{}").strip()
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Vision batch returned invalid JSON at turn indexes {batch_indexes}: {raw_payload[:180]}"
                ) from exc
            batch_assignments = {
                int(item.get("turn_index")): item
                for item in list(payload.get("turns") or [])
                if str(item.get("turn_index", "")).lstrip("-").isdigit()
                and int(item.get("turn_index")) in batch_indexes
            }
            if not batch_assignments:
                raise RuntimeError(
                    f"Vision batch returned no usable character assignments for turn indexes {batch_indexes}."
                )
            assignments.update(batch_assignments)
        turns, split_stats = CharacterSegmentSplitter.split_turns(turns, assignments)
        for index, turn in enumerate(turns):
            # Phase 3 pieces already carry a visual active-speaker assignment.
            # Whole-turn fallback remains compatible with Phase 1 responses.
            if bool(turn.get("phase3_segment")):
                continue
            original_index = next(
                (
                    old_index for old_index, old_turn in enumerate(list(result.get("turns") or []))
                    if float(old_turn.get("start", 0.0) or 0.0) <= float(turn.get("start", 0.0) or 0.0)
                    and float(old_turn.get("end", 0.0) or 0.0) >= float(turn.get("end", 0.0) or 0.0)
                ),
                index,
            )
            item = assignments.get(original_index) or {}
            character_id = str(item.get("character_id", "UNKNOWN") or "UNKNOWN").strip().upper()
            confidence = float(item.get("confidence", 0.0) or 0.0)
            category = str(item.get("voice_category", "unknown") or "unknown").strip().lower()
            if confidence < 0.65:
                character_id, category = "UNKNOWN", "unknown"
            elif not character_id.startswith("CHAR_"):
                # Preserve reliable gender evidence without inventing an
                # identity match. This is enough for gender-based Smart Cast.
                character_id = (
                    f"CHAR_GENDER_{category.upper()}_{original_index:04d}"
                    if category in {"male", "female"} else "UNKNOWN"
                )
            turn["character_id"] = character_id
            turn["character_gender"] = category if category in {"male", "female"} else "unknown"
            turn["character_confidence"] = max(0.0, min(1.0, confidence))
            turn["character_source"] = "visual" if character_id != "UNKNOWN" else "unresolved"

        registry: dict[str, dict[str, Any]] = {}
        for turn_index, turn in enumerate(turns):
            character_id = str(turn.get("character_id", "UNKNOWN") or "UNKNOWN")
            if character_id == "UNKNOWN":
                continue
            entry = registry.setdefault(character_id, {
                "character_id": character_id,
                "audio_speakers": set(),
                "gender_votes": [],
                "turn_indices": [],
            })
            entry["audio_speakers"].add(str(turn.get("speaker", "") or ""))
            entry["gender_votes"].append(str(turn.get("character_gender", "unknown") or "unknown"))
            entry["turn_indices"].append(turn_index)
        characters = []
        for character_id, entry in sorted(registry.items()):
            votes = entry.pop("gender_votes")
            gender = max(("male", "female", "unknown"), key=lambda value: votes.count(value))
            entry["audio_speakers"] = sorted(entry["audio_speakers"])
            entry["gender"] = gender
            characters.append(entry)

        # Gender belongs to a character, not to an individual subtitle turn.
        # Normalize every turn to the registry decision so one CHAR can never
        # alternate between a male and female TTS voice.
        gender_by_character = {
            str(item.get("character_id", "")): str(item.get("gender", "unknown"))
            for item in characters
        }
        for turn in turns:
            character_id = str(turn.get("character_id", "UNKNOWN") or "UNKNOWN")
            if character_id in gender_by_character:
                turn["character_gender"] = gender_by_character[character_id]

        result = dict(result)
        result["turns"] = turns
        result["characters"] = characters
        result["character_summary"] = {
            "character_count": len(characters),
            "male_count": sum(1 for item in characters if item.get("gender") == "male"),
            "female_count": sum(1 for item in characters if item.get("gender") == "female"),
            "unknown_character_count": sum(1 for item in characters if item.get("gender") == "unknown"),
            "unknown_turn_count": sum(1 for turn in turns if turn.get("character_id") == "UNKNOWN"),
            "split_turn_count": int(split_stats.get("split_turn_count", 0) or 0),
            "created_span_count": int(split_stats.get("created_span_count", 0) or 0),
            "model": model,
            "version": CharacterSegmentSplitter.VERSION,
        }
        return result
