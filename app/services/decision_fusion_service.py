"""Dịch vụ tổng hợp quyết định (Decision Fusion Service).

NƠI DUY NHẤT CHỊU TRÁCH NHIỆM QUYẾT ĐỊNH final_gender.
Khóa 5 nguyên tắc kiến trúc:
1. Audio confidence >= 85% -> Nguồn bằng chứng ưu tiên cao nhất, BẢO TOÀN TUYỆT ĐỐI, DeepSeek KHÔNG ĐƯỢC OVERRIDE.
2. Gender AI chỉ đọc audio, DeepSeek chỉ phân tích kịch bản và continuity.
3. Speaker Boundary Guard: Ranh giới đổi người nói (ví dụ Nữ -> Nam ở câu 4) được bảo toàn,
   không để continuity ép đổi giới tính âm học khi có bằng chứng âm học đối lập rõ rệt.
4. DeepSeek chỉ bổ trợ khi âm học yếu (< 0.85) hoặc unknown.
5. Ghi lý do chuẩn khoa học, không dùng thuật ngữ 'chuẩn 100%'.
"""

from __future__ import annotations

from typing import Any, List, Dict, Optional


class DecisionFusionService:
    """Nơi duy nhất kết hợp các nguồn bằng chứng để đưa ra final_gender."""

    ACOUSTIC_HIGH_CONFIDENCE_THRESHOLD = 0.85
    SPEAKER_BOUNDARY_GUARD_THRESHOLD = 0.65

    @classmethod
    def fuse(
        cls,
        cues: List[Dict[str, Any]],
        deepseek_genders: Optional[Dict[int, str]] = None,
        deepseek_continuity: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Quyết định final_gender cho từng câu dựa trên phân tầng ưu tiên bằng chứng."""
        if not cues:
            return []

        deepseek_map = deepseek_genders or {}
        fused: List[Dict[str, Any]] = []

        prev_final_gender = None

        for idx, cue in enumerate(cues, start=1):
            item = dict(cue)
            cid = item.get("id", idx)

            # Trường hợp phụ đề tĩnh / chữ rác bao bì / không phải lời thoại
            if item.get("skip_tts") or item.get("status") == "static_text":
                item["gender"] = "none"
                item["final_gender"] = "none"
                item["final_decision_confidence"] = 1.0
                item["decision_mode"] = "static_non_speech"
                reasons = list(item.get("gender_reason") or [])
                reasons.append("Phụ đề tĩnh / biểu tượng / không chứa giọng nói thoại")
                item["gender_reason"] = reasons
                fused.append(item)
                continue

            raw_g = str(item.get("raw_gender", "") or item.get("gender", "") or "unknown").lower().strip()
            raw_c = float(item.get("raw_gender_confidence", 0.0) or item.get("confidence", 0.0) or 0.0)
            if raw_c > 1.0:
                raw_c = raw_c / 100.0  # Chuẩn hóa về [0, 1]

            dg = str(deepseek_map.get(cid, "") or "").lower().strip()
            if dg not in {"male", "female"}:
                dg = ""

            reasons = list(item.get("gender_reason") or [])

            # NGUYÊN TẮC 1: ÂM HỌC TỰ TIN CAO (>= 85%) -> NGUỒN BẰNG CHỨNG ƯU TIÊN CAO NHẤT
            if raw_g in {"male", "female"} and raw_c >= cls.ACOUSTIC_HIGH_CONFIDENCE_THRESHOLD:
                final_g = raw_g
                final_c = raw_c
                mode = "acoustic_priority"
                reasons.append(
                    f"Mô hình âm học phân loại là {raw_g.upper()} ({raw_c*100:.1f}%) với độ tin cậy cao, ưu tiên bảo toàn kết quả âm học"
                )

            # NGUYÊN TẮC 2: SPEAKER BOUNDARY GUARD
            # Nếu câu trước có giới tính khác (ví dụ Câu 1-3 là Nữ, Câu 4 âm học là Nam)
            # và âm học câu hiện tại đạt mức đáng tin cậy (>= 50%), bảo vệ ranh giới người nói
            elif (
                raw_g in {"male", "female"}
                and raw_c >= 0.50
                and prev_final_gender in {"male", "female"}
                and raw_g != prev_final_gender
            ):
                final_g = raw_g
                final_c = raw_c
                mode = "speaker_boundary_preserved"
                reasons.append(
                    f"Phát hiện ranh giới chuyển người nói ({prev_final_gender.upper()} -> {raw_g.upper()}), bảo toàn tín hiệu âm học ({raw_c*100:.1f}%)"
                )

            # NGUYÊN TẮC 3: ĐỒNG THUẬN ÂM HỌC VỚI CÂU KẾ TIẾP (ACOUSTIC ADJACENT HARMONY)
            # Ví dụ Câu 1 âm học Nữ (57%) gối đầu/liền kề với Câu 2 âm học Nữ tự tin (99.9%)
            elif raw_g in {"male", "female"} and idx < len(cues):
                next_c = cues[idx]
                next_g = str(next_c.get("raw_gender", "")).lower().strip()
                next_conf = float(next_c.get("raw_gender_confidence", 0.0) or 0.0)
                if next_conf > 1.0:
                    next_conf /= 100.0
                cur_e = float(item.get("end", 0.0) or 0.0)
                nxt_s = float(next_c.get("start", cur_e) or cur_e)

                if next_g == raw_g and next_conf >= cls.ACOUSTIC_HIGH_CONFIDENCE_THRESHOLD and (nxt_s - cur_e) <= 1.0:
                    final_g = raw_g
                    final_c = max(raw_c, 0.85)
                    mode = "acoustic_adjacent_support"
                    reasons.append(
                        f"Âm học đồng thuận với câu kế tiếp ({raw_g.upper()} {next_conf*100:.1f}%), ưu tiên bảo toàn âm học"
                    )
                elif dg in {"male", "female"}:
                    final_g = dg
                    final_c = 0.85
                    mode = "deepseek_contextual_support"
                    reasons.append(
                        f"DeepSeek phân tích kịch bản/vai diễn ({dg.upper()}) hỗ trợ khi âm học chưa đủ tin cậy ({raw_g.upper()} {raw_c*100:.1f}%)"
                    )
                else:
                    final_g = raw_g
                    final_c = raw_c
                    mode = "acoustic_moderate"
                    reasons.append(f"Mô hình âm học phân loại là {raw_g.upper()} ({raw_c*100:.1f}%)")

            # NGUYÊN TẮC 4: ÂM HỌC YẾU HOẶC UNKNOWN -> DEEPSEEK BỔ TRỢ NGỮ CẢNH
            elif dg in {"male", "female"}:
                final_g = dg
                final_c = 0.85
                mode = "deepseek_contextual_support"
                reasons.append(
                    f"DeepSeek phân tích kịch bản/vai diễn ({dg.upper()}) hỗ trợ khi âm học chưa đủ tin cậy ({raw_g.upper()} {raw_c*100:.1f}%)"
                )

            # NGUYÊN TẮC 4: GIỮ KẾT QUẢ ÂM HỌC MỨC TRUNG BÌNH KHI KHÔNG CÓ DEEPSEEK
            elif raw_g in {"male", "female"}:
                final_g = raw_g
                final_c = raw_c
                mode = "acoustic_moderate"
                reasons.append(
                    f"Mô hình âm học phân loại là {raw_g.upper()} ({raw_c*100:.1f}%)"
                )

            else:
                final_g = "unknown"
                final_c = 0.50
                mode = "unknown"
                reasons.append("Chưa đủ bằng chứng âm học và ngữ cảnh")

            item["gender"] = final_g
            item["final_gender"] = final_g
            item["final_decision_confidence"] = final_c
            item["decision_mode"] = mode
            item["gender_reason"] = reasons

            prev_final_gender = final_g
            fused.append(item)

        return fused
