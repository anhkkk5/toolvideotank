from __future__ import annotations

import re


class SegmentRegroupService:
    @staticmethod
    def is_cjk(text: str) -> bool:
        for ch in str(text or ""):
            if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff':
                return True
        return False

    @classmethod
    def join_words(cls, words: list[dict], original_text: str = "") -> str:
        if not words:
            return ""
        texts = [str(w.get("text", "") or "").strip() for w in words]
        texts = [t for t in texts if t]
        if not texts:
            return ""
        sample = "".join(texts)
        if cls.is_cjk(sample):
            return "".join(texts)
        else:
            return " ".join(texts)

    @staticmethod
    def split_text_by_punctuation(text: str, duration: float = 0.0) -> list[str]:
        """Split text into sentences while keeping punctuation attached."""
        text = str(text or "").strip()
        if not text:
            return []
        chunks = re.split(r'([.?!。？！]+)', text)
        parts = []
        for i in range(0, len(chunks), 2):
            sentence = chunks[i].strip()
            punct = chunks[i + 1] if i + 1 < len(chunks) else ""
            combined = (sentence + punct).strip()
            if combined:
                parts.append(combined)
        # If terminal punctuation didn't split or segment is long, split on commas/semicolons
        if len(parts) <= 1 or (duration > 4.0 and len(parts) < 3):
            comma_chunks = re.split(r'([,，;；]+)', text)
            comma_parts = []
            for i in range(0, len(comma_chunks), 2):
                sentence = comma_chunks[i].strip()
                punct = comma_chunks[i + 1] if i + 1 < len(comma_chunks) else ""
                combined = (sentence + punct).strip()
                if combined:
                    comma_parts.append(combined)
            if len(comma_parts) > len(parts):
                parts = comma_parts
        return parts if parts else [text]

    def split_segment_by_sentences(self, segment: dict, *, max_duration_seconds: float = 6.0) -> list[dict]:
        """Split a single segment containing multiple sentences or dialogue turns into subsegments."""
        words = list(segment.get("words") or [])
        text = str(segment.get("text", "") or "").strip()
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))

        if not text or end <= start:
            return [self._clone_segment(segment)]

        duration = end - start
        term_puncts = set(".?!。？！")
        comma_puncts = set(",，;；")

        # Strategy 1: Word-level timestamps available
        if words and len(words) >= 2:
            sub_word_groups = []
            curr_group = []

            for i, w in enumerate(words):
                curr_group.append(w)
                w_text = str(w.get("text", "") or "").strip()
                is_last_word = (i == len(words) - 1)

                has_term = any(w_text.endswith(p) for p in term_puncts)
                has_comma = any(w_text.endswith(p) for p in comma_puncts)
                has_pause = False
                if not is_last_word:
                    next_w = words[i + 1]
                    gap = float(next_w.get("start", 0.0)) - float(w.get("end", 0.0))
                    if gap >= 0.35 or (has_comma and gap >= 0.18):
                        has_pause = True

                curr_dur = float(curr_group[-1].get("end", 0.0)) - float(curr_group[0].get("start", 0.0))
                # Break on terminal punct, audible pause, or comma when duration >= 1.8s
                should_break = (has_term or has_pause or (has_comma and curr_dur >= 1.8))
                if should_break and curr_dur >= 0.5 and not is_last_word:
                    sub_word_groups.append(curr_group)
                    curr_group = []

            if curr_group:
                if sub_word_groups and (float(curr_group[-1].get("end", 0.0)) - float(curr_group[0].get("start", 0.0))) < 0.35:
                    sub_word_groups[-1].extend(curr_group)
                else:
                    sub_word_groups.append(curr_group)

            if len(sub_word_groups) > 1:
                result = []
                for g in sub_word_groups:
                    seg = self._clone_segment(segment)
                    seg["start"] = round(float(g[0].get("start", 0.0)), 3)
                    seg["end"] = round(float(g[-1].get("end", 0.0)), 3)
                    seg["words"] = g
                    seg["text"] = self.join_words(g, text)
                    seg["tts_text"] = seg["text"]
                    result.append(seg)
                return result

        # Strategy 2: Text has multiple sentences with punctuation or commas
        sentences = self.split_text_by_punctuation(text, duration=duration)
        if len(sentences) > 1:
            total_len = sum(max(1, len(s)) for s in sentences)
            duration = end - start
            result = []
            curr_time = start
            for i, s in enumerate(sentences):
                s_dur = duration * (len(s) / total_len)
                seg = self._clone_segment(segment)
                seg["start"] = round(curr_time, 3)
                curr_time += s_dur
                seg["end"] = round(curr_time if i < len(sentences) - 1 else end, 3)
                seg["text"] = s
                seg["tts_text"] = s
                seg["words"] = []
                result.append(seg)
            return result

        return [self._clone_segment(segment)]

    def regroup(self, segments: list[dict], *, max_gap_seconds: float = 0.35, max_duration_seconds: float = 8.0) -> list[dict]:
        regrouped: list[dict] = []
        for segment in segments or []:
            text = str(segment.get("text", "") or "").strip()
            if not text:
                continue
            # Split segment into individual sentences if multiple exist
            split_pieces = self.split_segment_by_sentences(segment, max_duration_seconds=max_duration_seconds)
            for piece in split_pieces:
                regrouped.append(piece)

        normalized = []
        for index, segment in enumerate(regrouped, start=1):
            payload = self._clone_segment(segment)
            payload["id"] = index
            payload["text"] = self._normalize_sentence_text(payload.get("text", ""))
            payload["tts_text"] = payload.get("tts_text", payload["text"])
            normalized.append(payload)
        return normalized

    def _clone_segment(self, segment: dict) -> dict:
        payload = {
            "start": float(segment.get("start", 0.0)),
            "end": float(segment.get("end", 0.0)),
            "text": str(segment.get("text", "") or "").strip(),
        }
        if segment.get("tts_text") is not None:
            payload["tts_text"] = str(segment.get("tts_text") or "").strip()
        if segment.get("words"):
            payload["words"] = list(segment.get("words") or [])
        if segment.get("chunk_id"):
            payload["chunk_id"] = segment.get("chunk_id")
        if segment.get("speaker"):
            payload["speaker"] = str(segment.get("speaker") or "")
        if segment.get("manual_highlights"):
            payload["manual_highlights"] = list(segment.get("manual_highlights") or [])
        if segment.get("auto_highlights"):
            payload["auto_highlights"] = list(segment.get("auto_highlights") or [])
        return payload

    def _normalize_sentence_text(self, text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "").strip())
        return value
