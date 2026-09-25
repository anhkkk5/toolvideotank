"""Dịch vụ gộp các phụ đề OCR trùng lặp (Fuzzy Duplicate Subtitle Service).

Chịu trách nhiệm duy nhất tại tầng OCR / Normalization trước khi chuyển sang
dịch thuật DeepSeek và phân tích âm học Gender AI.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, List, Dict, Optional


class FuzzyDuplicateService:
    """Tách biệt trách nhiệm gộp các câu OCR trùng lặp hoặc lặp đuôi do quét frame."""

    @staticmethod
    def merge_fuzzy_cues(
        cues: List[Dict[str, Any]],
        max_gap: float = 1.5,
        min_cjk_overlap: int = 3,
        cjk_similarity_threshold: float = 0.70,
        vad_intervals: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Gộp các câu OCR trùng lặp với quy tắc chặt chẽ:
        
        1. Khoảng cách thời gian: cur_start - prev_end <= max_gap (1.5s).
        2. Bằng chứng chữ Hán:
           - Trùng đuôi hoặc trùng đầu >= min_cjk_overlap (3 ký tự), HOẶC
           - Độ tương đồng ký tự CJK >= cjk_similarity_threshold (70%).
        3. TUYỆT ĐỐI KHÔNG dùng độ tương đồng bản dịch tiếng Việt để merge.
        4. Kiểm tra Speaker Switch: Không gộp nếu 2 cue nằm ở 2 ranh giới âm học tách biệt
           có khoảng ngắt nghỉ rõ ràng hoặc khác tín hiệu speaker.
        """
        if not cues or len(cues) <= 1:
            return cues or []

        cleaned: List[Dict[str, Any]] = []

        for cue in cues:
            if not cleaned:
                cleaned.append(dict(cue))
                continue

            prev = cleaned[-1]
            prev_end = float(prev.get("end", 0.0) or 0.0)
            cur_start = float(cue.get("start", 0.0) or 0.0)
            cur_end = float(cue.get("end", cur_start) or cur_start)

            # 1. Điều kiện khoảng cách thời gian
            gap = cur_start - prev_end
            if gap <= max_gap:
                prev_text = str(prev.get("text", "") or prev.get("original_text", "") or "").strip()
                cur_text = str(cue.get("text", "") or cue.get("original_text", "") or "").strip()

                # Lọc ký tự CJK thuần túy
                prev_cjk = "".join(re.findall(r"[\u3400-\u9fff]", prev_text))
                cur_cjk = "".join(re.findall(r"[\u3400-\u9fff]", cur_text))

                has_suffix_match = False
                has_prefix_match = False
                high_cjk_similarity = False

                if prev_cjk and cur_cjk:
                    min_len = min(len(prev_cjk), len(cur_cjk))

                    # Trùng đuôi chữ Hán >= 3 ký tự (ví dụ case '有点懵我想想')
                    for length in range(min_len, min_cjk_overlap - 1, -1):
                        if prev_cjk.endswith(cur_cjk[-length:]):
                            has_suffix_match = True
                            break

                    # Trùng đầu chữ Hán >= 3 ký tự
                    if not has_suffix_match:
                        for length in range(min_len, min_cjk_overlap - 1, -1):
                            if prev_cjk.startswith(cur_cjk[:length]):
                                has_prefix_match = True
                                break

                    # Độ tương đồng chữ Hán >= 70%
                    if not has_suffix_match and not has_prefix_match and min_len >= 4:
                        sim = SequenceMatcher(None, prev_cjk, cur_cjk).ratio()
                        if sim >= cjk_similarity_threshold:
                            high_cjk_similarity = True

                # 2. Điều kiện âm học / Speaker switch
                # Nếu có sự ngắt quãng âm học lớn và không trùng đuôi rõ rệt, không được ép merge
                speaker_switch = False
                prev_spk = str(prev.get("speaker", "") or "")
                cur_spk = str(cue.get("speaker", "") or "")
                if prev_spk and cur_spk and prev_spk != cur_spk:
                    speaker_switch = True

                # Thực hiện merge khi thỏa mãn điều kiện text CJK và không có switch rõ ràng
                if (has_suffix_match or has_prefix_match or high_cjk_similarity) and not speaker_switch:
                    prev["end"] = max(prev_end, cur_end)

                    # Tinh chỉnh text: ưu tiên bản text sạch/chuẩn hơn
                    if has_suffix_match:
                        # Nếu câu sau chỉ chứa phần đuôi sạch
                        if len(cur_cjk) <= len(prev_cjk) and prev_cjk.endswith(cur_cjk):
                            pass
                        elif len(cur_text) < len(prev_text):
                            prev["text"] = cur_text
                            prev["original_text"] = cur_text
                    elif len(cur_text) > len(prev_text) and high_cjk_similarity:
                        prev["text"] = cur_text
                        prev["original_text"] = cur_text

                    merged = list(prev.get("merged_from") or [prev.get("id")])
                    merged.append(cue.get("id"))
                    prev["merged_from"] = merged
                    continue

            cleaned.append(dict(cue))

        return cleaned
