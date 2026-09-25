"""Dịch vụ tổng hợp quyết định (Decision Fusion Service).

NƠI DUY NHẤT CHỊU TRÁCH NHIỆM QUYẾT ĐỊNH final_gender.
Khóa 5 nguyên tắc kiến trúc phổ quát (Universal Multi-Modal Architecture):
1. Quán tính lời thoại (Continuation Inertia): Câu ngắn nối tiếp cùng lượt nói của nhân vật trước
   được bảo toàn tuyệt đối, ngăn tiếng nhạc nền/tiếng thở trong audio ngắn bóp méo vai diễn.
2. Mốc âm học tự tin cao (Acoustic Anchors >= 88%): Bằng chứng vật lý hàng đầu từ giọng người thật.
3. Speaker Boundary Guard: Ranh giới đổi người nói (A-B-A) được bảo vệ khi có tín hiệu đối lập.
4. DeepSeek Contextual Cast: Khi âm học chưa đạt ngưỡng chắc chắn (< 88%) hoặc bị nhiễu BGM (như câu 4),
   DeepSeek dựa trên kịch bản đối thoại và các mốc âm học đã biết để suy luận vai chuẩn xác.
5. Tuyệt đối KHÔNG sử dụng từ khóa hardcode của riêng bất kỳ video nào.
"""

from __future__ import annotations

from typing import Any, List, Dict, Optional


class DecisionFusionService:
    """Nơi duy nhất kết hợp các nguồn bằng chứng để đưa ra final_gender."""

    ACOUSTIC_HIGH_CONFIDENCE_THRESHOLD = 0.88
    SPEAKER_BOUNDARY_GUARD_THRESHOLD = 0.50

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

        # Xây dựng danh sách các cặp (prev_id, curr_id) thuộc cùng một nhóm liên tục của DeepSeek:
        linked_pairs = set()
        if deepseek_continuity:
            for grp in deepseek_continuity:
                grp_ids = grp.get("ids", [])
                for i in range(len(grp_ids) - 1):
                    p_id, c_id = grp_ids[i], grp_ids[i + 1]
                    linked_pairs.add((p_id, c_id))
                    linked_pairs.add((str(p_id), str(c_id)))

        prev_final_gender = None
        prev_cid = None

        for idx, cue in enumerate(cues, start=1):
            item = dict(cue)
            cid = item.get("id", idx)

            # 1. Trường hợp phụ đề tĩnh / chữ rác bao bì / không phải lời thoại
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

            dur = float(item.get("end", 0.0)) - float(item.get("start", 0.0))

            dg = str(deepseek_map.get(cid, "") or "").lower().strip()
            if dg not in {"male", "female"}:
                dg = ""

            reasons = list(item.get("gender_reason") or [])
            is_same_speaker_linked = ((prev_cid, cid) in linked_pairs) or ((str(prev_cid), str(cid)) in linked_pairs)
            cont_g = item.get("continuation_gender")

            # NGUYÊN TẮC 1: QUÁN TÍNH NỐI TIẾP VỚI CÂU TRƯỚC (CONTINUATION INERTIA)
            # Áp dụng khi câu này là câu ngắn tiếp nối cùng lượt nói của nhân vật trước
            if cont_g in {"male", "female"}:
                final_g = cont_g
                final_c = 0.95
                mode = "continuation_inertia"
                reasons.append(
                    f"Quán tính lời thoại: Tiếp nối cùng lượt nói của nhân vật {final_g.upper()}"
                )
            elif is_same_speaker_linked and prev_final_gender in {"male", "female"} and dur < 1.3:
                final_g = prev_final_gender
                final_c = 0.95
                mode = "continuation_inertia"
                reasons.append(
                    f"Quán tính lời thoại: Tiếp nối cùng nhân vật {prev_final_gender.upper()} từ câu trước"
                )

            # NGUYÊN TẮC 2: MỐC ÂM HỌC TỰ TIN CAO (>= 88%)
            # Nếu âm học đạt độ tin cậy rất cao (>= 88%), đây là bằng chứng vật lý hàng đầu
            elif raw_g in {"male", "female"} and raw_c >= cls.ACOUSTIC_HIGH_CONFIDENCE_THRESHOLD:
                final_g = raw_g
                final_c = raw_c
                mode = "acoustic_priority"
                reasons.append(
                    f"Mô hình âm học phân loại là {raw_g.upper()} ({raw_c*100:.1f}%) với độ tin cậy cao, ưu tiên bảo toàn âm học"
                )

            # NGUYÊN TẮC 3: SPEAKER BOUNDARY GUARD
            # Khi chuyển từ Nữ sang Nam hoặc ngược lại với tín hiệu âm học rõ ràng
            elif (
                raw_g in {"male", "female"}
                and raw_c >= cls.SPEAKER_BOUNDARY_GUARD_THRESHOLD
                and prev_final_gender in {"male", "female"}
                and raw_g != prev_final_gender
                and (not dg or dg == raw_g)
            ):
                final_g = raw_g
                final_c = raw_c
                mode = "speaker_boundary_preserved"
                reasons.append(
                    f"Phát hiện ranh giới chuyển người nói ({prev_final_gender.upper()} -> {raw_g.upper()}), bảo toàn tín hiệu âm học ({raw_c*100:.1f}%)"
                )

            # NGUYÊN TẮC 4: DEEPSEEK PHÂN VAI NGỮ CẢNH CHO ÂM HỌC CHƯA ĐỦ MẠNH (< 88%) HOẶC UNKNOWN
            elif dg in {"male", "female"}:
                final_g = dg
                final_c = 0.88
                mode = "deepseek_contextual_support"
                reasons.append(
                    f"DeepSeek phân tích kịch bản/vai diễn ({dg.upper()}) giải quyết câu đối đáp khi âm thanh chưa đủ chắc chắn (< 88%)"
                )

            # NGUYÊN TẮC 5: GIỮ KẾT QUẢ ÂM HỌC NẾU CÓ
            elif raw_g in {"male", "female"}:
                final_g = raw_g
                final_c = raw_c
                mode = "acoustic_moderate"
                reasons.append(f"Mô hình âm học phân loại là {raw_g.upper()} ({raw_c*100:.1f}%)")

            else:
                final_g = "unknown"
                final_c = 0.50
                mode = "unknown"
                reasons.append("Không đủ dữ liệu xác định giới tính")

            item["gender"] = final_g
            item["final_gender"] = final_g
            item["final_decision_confidence"] = final_c
            item["confidence"] = final_c
            item["decision_mode"] = mode
            item["gender_reason"] = reasons

            prev_final_gender = final_g
            prev_cid = cid
            fused.append(item)

        return fused
