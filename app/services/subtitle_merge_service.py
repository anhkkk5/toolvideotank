"""Dedicated service for merging and deduplicating subtitle cues.

Follows strict rules:
- Adaptive max_gap based on sampling interval: max(0.7, sample_interval + 0.2)
- Strict text equality or very high similarity (>= 0.90) with minimal length difference
- NO raw substring containment (prevents merging distinct dialogue lines like '我喜欢你' and '我真的很喜欢你')
- Preserves audit trail via 'merged_from' list of original cue IDs
"""

from __future__ import annotations

import difflib
import re
from typing import Any


class SubtitleMergeService:
    """Consolidate repeated on-screen subtitle cues into single continuous segments."""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Strip whitespace and punctuation for fair text comparison."""
        return re.sub(
            r"[\s\.,?!:;\"'，。？！：；…—_~`/\\[\]()（）{}]+",
            "",
            str(text or ""),
        ).strip().lower()

    @classmethod
    def are_cues_near_duplicate(
        cls,
        text1: str,
        text2: str,
        min_similarity: float = 0.90,
    ) -> bool:
        """Determine if two subtitle texts represent the exact same spoken line.

        Rules:
        1. Exact match after stripping whitespace and punctuation -> True.
        2. High string similarity (>= 0.90) and length difference <= 1 character
           (handles minor OCR glyph flicker) -> True.
        3. Raw substring containment is intentionally NOT allowed:
           distinct lines like '我喜欢你' vs '我真的很喜欢你' must remain separate.
        """
        t1 = cls.normalize_text(text1)
        t2 = cls.normalize_text(text2)
        if not t1 or not t2:
            return False
        if t1 == t2:
            return True

        # Only allow minor single-glyph OCR difference on similar length strings
        len_diff = abs(len(t1) - len(t2))
        if len_diff > 1:
            return False

        ratio = difflib.SequenceMatcher(None, t1, t2).ratio()
        return ratio >= min_similarity

    @classmethod
    def merge_cues(
        cls,
        cues: list[dict[str, Any]],
        *,
        sample_interval: float = 0.67,
        max_gap: float | None = None,
    ) -> list[dict[str, Any]]:
        """Collapse consecutive duplicate or near-duplicate cues within adaptive max_gap."""
        if not cues:
            return []

        # Adaptive max_gap: e.g. interval 1.0s -> 1.2s; 0.67s -> 0.87s; 0.5s -> 0.7s
        effective_max_gap = (
            float(max_gap)
            if max_gap is not None
            else max(0.7, float(sample_interval or 0.67) + 0.2)
        )

        sorted_cues = sorted(cues, key=lambda c: float(c.get("start", 0.0) or 0.0))
        merged: list[dict[str, Any]] = []

        for idx, cue in enumerate(sorted_cues, start=1):
            item = dict(cue)
            item_text = str(item.get("text", "") or item.get("original_text", "") or "").strip()
            if not item_text:
                continue

            item_start = round(float(item.get("start", 0.0) or 0.0), 3)
            item_end = round(max(item_start + 0.05, float(item.get("end", item_start) or item_start)), 3)
            item["start"] = item_start
            item["end"] = item_end
            item["text"] = item_text

            cue_id = item.get("id")
            if cue_id is None:
                cue_id = idx
            item["merged_from"] = list(item.get("merged_from") or [cue_id])

            if not merged:
                merged.append(item)
                continue

            prev = merged[-1]
            prev_end = float(prev.get("end", 0.0) or 0.0)
            gap = item_start - prev_end

            # Merge if gap is within adaptive threshold and texts match
            if gap <= effective_max_gap and cls.are_cues_near_duplicate(prev.get("text", ""), item_text):
                prev["end"] = max(prev_end, item_end)
                if len(item_text) > len(str(prev.get("text", ""))):
                    prev["text"] = item_text
                prev["merged_from"].extend(item["merged_from"])
                continue

            merged.append(item)

        return merged
