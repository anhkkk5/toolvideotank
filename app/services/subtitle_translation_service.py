"""Dedicated service for translating subtitle cues into Vietnamese or target language."""

from __future__ import annotations

import os
from typing import Any, Callable

from models.subtitle_segment import SubtitleSegment
from services.deepseek_service import DeepSeekService, DeepSeekTranslationError


class SubtitleTranslationService:
    """Translate subtitle cue texts into target language with DeepSeek support."""

    def __init__(self, deepseek_service: DeepSeekService | None = None):
        self.deepseek = deepseek_service or DeepSeekService()

    def translate_with_deepseek(
        self,
        cues: list[dict[str, Any] | SubtitleSegment],
        *,
        overwrite_manual: bool = False,
        progress: Callable[[str, int, int], None] | None = None,
        row_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Translate segments using DeepSeek with character memory and batching.
        
        Args:
            cues: List of cue dicts or SubtitleSegment instances.
            overwrite_manual: If False, preserves any manual edits already made by the user.
            progress: Progress callback(message, current_item, total_items).
            row_callback: Real-time per-row callback(updated_row_dict).

        Returns:
            (updated_cues_list, final_character_memory)
        """
        if not cues:
            return [], self.deepseek.init_character_memory()

        notify = progress or (lambda _msg, _cur, _tot: None)
        row_notify = row_callback or (lambda _row: None)

        # 1. Convert input to SubtitleSegment objects
        segments: list[SubtitleSegment] = []
        for idx, item in enumerate(cues, start=1):
            if isinstance(item, SubtitleSegment):
                segments.append(item)
            elif isinstance(item, dict):
                segments.append(SubtitleSegment.from_dict(item, default_id=idx))
            else:
                continue

        total_segments = len(segments)
        character_memory = self.deepseek.init_character_memory()

        # 2. Determine which items need translation
        items_to_translate: list[SubtitleSegment] = []
        for s in segments:
            if not overwrite_manual and s.translation_edited and s.translated_text:
                # Keep manual edit, don't re-translate
                s.translation_source = "manual"
                s.translation_status = "manual"
            else:
                items_to_translate.append(s)

        if not items_to_translate:
            notify("Tất cả các câu đã được chỉnh sửa thủ công và được giữ nguyên.", total_segments, total_segments)
            return [s.to_dict() for s in segments], character_memory

        notify(f"Bắt đầu dịch {len(items_to_translate)} câu bằng DeepSeek…", 0, len(items_to_translate))

        # 3. Batch processing
        batch_size = self.deepseek.BATCH_SIZE
        translated_map: dict[int, dict[str, Any]] = {}
        history_context: list[SubtitleSegment] = []

        total_to_trans = len(items_to_translate)
        processed_count = 0

        for batch_start in range(0, total_to_trans, batch_size):
            batch = items_to_translate[batch_start : batch_start + batch_size]
            b_num = (batch_start // batch_size) + 1
            total_batches = (total_to_trans + batch_size - 1) // batch_size

            notify(
                f"Đang dịch lượt {b_num}/{total_batches} ({len(batch)} câu, ID {batch[0].id}-{batch[-1].id})…",
                processed_count,
                total_to_trans,
            )

            # Perform translation for current batch
            batch_results, character_memory = self.deepseek.translate_batch(
                batch=batch,
                memory=character_memory,
                previous_context=history_context,
            )

            # Store results & notify row callback
            for res_item in batch_results:
                item_id = res_item["id"]
                translated_map[item_id] = res_item

            # Build sliding context for next batch
            for seg in batch:
                res_info = translated_map.get(seg.id)
                if res_info:
                    seg.translated_text = res_info["translated_text"]
                    seg.is_noise = res_info["is_noise"]
                    if res_info.get("gender"):
                        seg.gender = res_info["gender"]
                    seg.translation_source = "deepseek"
                    seg.translation_edited = False
                    seg.translation_status = res_info["translation_status"]
                    history_context.append(seg)
                    row_notify(seg.to_dict())

            processed_count += len(batch)
            notify(
                f"Hoàn tất lượt {b_num}/{total_batches} ({processed_count}/{total_to_trans} câu)",
                processed_count,
                total_to_trans,
            )

        # 4. Assemble final list preserving original input order
        final_list = []
        for s in segments:
            if s.id in translated_map:
                res = translated_map[s.id]
                s.translated_text = res["translated_text"]
                s.is_noise = res["is_noise"]
                if res.get("gender"):
                    s.gender = res["gender"]
                s.translation_source = "deepseek"
                s.translation_edited = False
                s.translation_status = res["translation_status"]
                if s.is_noise or not s.translated_text:
                    s.skip_tts = True
            final_list.append(s.to_dict())

        notify("Dịch hoàn tất toàn bộ phụ đề!", total_segments, total_segments)
        return final_list, character_memory

    def translate_cues(
        self,
        cues: list[dict[str, Any]],
        *,
        src_lang: str = "auto",
        target_lang: str = "vi",
        enable_polish: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Legacy method retained for backward compatibility."""
        if not cues:
            return []

        notify = progress or (lambda _message: None)
        notify("Đang dịch nghĩa phụ đề sang tiếng Việt…")

        translated_cues = [dict(c) for c in cues]
        try:
            from translator import translate_segments

            trans_inputs = [
                {
                    "start": float(c.get("start", 0.0) or 0.0),
                    "end": max(float(c.get("start", 0.0) or 0.0) + 0.1, float(c.get("end", 0.0) or 0.0)),
                    "text": str(c.get("text", "") or c.get("original_text", "") or "").strip(),
                }
                for c in translated_cues
            ]
            translated = translate_segments(
                trans_inputs,
                src_lang=src_lang,
                target_lang=target_lang,
                enable_polish=enable_polish,
            )
            for cue, trans in zip(translated_cues, translated):
                cue["translated_text"] = str(trans.get("text", "") or "").strip()
        except Exception as exc:
            print(f"[Subtitle Translation] Translation skipped: {exc}")
            for cue in translated_cues:
                cue.setdefault("translated_text", "")

        return translated_cues
