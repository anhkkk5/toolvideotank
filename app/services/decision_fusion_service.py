"""Dịch vụ tổng hợp quyết định Đa phương thức (Bayesian Multi-Modal Decision Fusion).

NƠI DUY NHẤT CHỊU TRÁCH NHIỆM QUYẾT ĐỊNH final_gender.
Áp dụng cơ chế Bayesian Evidence Fusion (Tổng hợp Bằng chứng Xác suất Bayes)
kết hợp 5 nguồn tín hiệu độc lập:
1. Vocative Bayesian Soft-Weights (Trọng số xác suất từ vựng xưng hô đối ứng tiếng Trung)
2. 3D-Speaker Voiceprint Clustering (Gom cụm vector âm sắc ERes2Net)
3. DeepSeek Macro-Contextual Reasoning (Suy luận ngữ cảnh kịch bản phim của LLM)
4. Physical Acoustic Model Evidence (Mô hình âm học vật lý ECAPA-TDNN / AST)
5. Temporal Dialogue Continuity & Sandwich Smoothing (Đồng thuận chuỗi thoại liên tục)
"""

from __future__ import annotations

import re
from typing import Any, List, Dict, Optional, Tuple


class DecisionFusionService:
    """Nơi duy nhất kết hợp các nguồn bằng chứng xác suất Bayes để đưa ra final_gender."""

    ACOUSTIC_HIGH_CONFIDENCE_THRESHOLD = 0.68
    SPEAKER_BOUNDARY_GUARD_THRESHOLD = 0.55

    @classmethod
    def detect_vocative_gender(cls, zh_text: str, vi_text: str) -> Tuple[Optional[str], float, Optional[str]]:
        """Xác định trọng số ưu tiên xác suất (Bayesian Soft-weight) từ đại từ xưng hô đối ứng tiếng Trung."""
        zh = str(zh_text or "").strip()
        vi = str(vi_text or "").strip().lower()

        # 1. Từ vựng ưu tiên mạnh của NGƯỜI NÓI LÀ NAM (Gọi vợ / Chồng xưng anh nhận lỗi / Bố nói với con 'Bố và mẹ'):
        zh_male_exact = [
            "老婆", "老婆大人", "哎老婆", "媳妇", "媳妇儿", "太太", "内人", "爱妻", "老婆子", "都怪我不会说话", "哎呀我错了",
            "我和你妈", "我跟你妈", "我同你妈", "我与你妈", "我和你妈妈", "我跟你妈妈", "对得起我和你妈", "对得起你妈和我",
            "我和你母亲", "听你妈的", "听你妈妈的", "你妈不容易", "你妈妈不容易", "爸爸我"
        ]
        for trig in zh_male_exact:
            if trig in zh:
                return "male", 0.45, f"Xưng hô Nam / Gọi vợ / Bố nói với con ('{trig}')"

        vi_male_exact = [
            "vợ yêu", "vợ ơi", "vợ à", "ơ vợ", "bà xã", "vợ của anh",
            "anh sai rồi", "anh xin lỗi vợ", "đều tại anh không biết ăn nói",
            "ba và mẹ", "bố với mẹ", "ba với mẹ", "bố và mẹ", "cha và mẹ", "cha với mẹ",
            "ba của con và mẹ", "bố của con và mẹ", "ba uống bao nhiêu", "bố uống bao nhiêu"
        ]
        for trig in vi_male_exact:
            if trig in vi:
                return "male", 0.45, f"Bản dịch tiếng Việt xưng hô Nam ('{trig}')"

        # 2. Từ vựng ưu tiên mạnh của NGƯỜI NÓI LÀ NỮ (Gọi chồng / Vợ xưng em / Mẹ nói với con 'Mẹ và ba'):
        zh_female_exact = [
            "老公", "老公大人", "哎老公", "相公", "当家的", "先生",
            "我和你爸", "我跟你爸", "我同你爸", "我与你爸", "我和你爸爸", "我跟你爸爸", "对得起我和你爸", "对得起你爸和我",
            "我和你父亲", "听你爸的", "听你爸爸的", "你爸不容易", "你爸爸不容易", "妈妈我"
        ]
        for trig in zh_female_exact:
            if trig in zh:
                return "female", 0.45, f"Xưng hô Nữ / Gọi chồng / Mẹ nói với con ('{trig}')"

        vi_female_exact = [
            "chồng yêu", "chồng ơi", "chồng à", "ơ chồng", "ông xã", "chồng của em",
            "mẹ và ba", "mẹ với ba", "mẹ và bố", "mẹ với bố", "mẹ của con và ba", "mẹ của con và bố",
            "có lỗi với mẹ và ba", "xứng với mẹ và ba", "xứng đáng với mẹ và ba",
            "có lỗi với mẹ và bố", "xứng với mẹ và bố", "xứng đáng với mẹ và bố"
        ]
        for trig in vi_female_exact:
            if trig in vi:
                return "female", 0.45, f"Bản dịch tiếng Việt xưng hô Nữ ('{trig}')"

        return None, 0.0, None

    @classmethod
    def is_moral_summary_quote(cls, zh_text: str, vi_text: str) -> bool:
        """Phát hiện phụ đề trích dẫn triết lý, danh ngôn đúc kết bài học ở cuối phim."""
        zh = str(zh_text or "").strip()
        vi = str(vi_text or "").strip()

        quote_markers = [
            "相处之道", "才是夫妻", "夫妻最好的相处之道", "必修课", "换位思考",
            "有效沟通", "注意措辞 才是夫妻"
        ]
        is_quoted = (
            (zh.startswith("“") and zh.endswith("”"))
            or (zh.startswith('"') and zh.endswith('"'))
            or (vi.startswith("“") and vi.endswith("”"))
            or (vi.startswith('"') and vi.endswith('"'))
        )
        if is_quoted and any(m in zh for m in quote_markers):
            return True
        if any(m in zh for m in ["才是夫妻最好的相处之道", "才是夫妻"]):
            return True
        return False

    @classmethod
    def fuse(
        cls,
        cues: List[Dict[str, Any]],
        deepseek_genders: Optional[Dict[int, str]] = None,
        deepseek_continuity: Optional[List[Dict[str, Any]]] = None,
        llm_genders: Optional[Dict[int, str]] = None,
        llm_continuity: Optional[List[Dict[str, Any]]] = None,
        llm_provider_name: str = "LLM AI",
    ) -> List[Dict[str, Any]]:
        """Tổng hợp bằng chứng xác suất Bayes (Bayesian Evidence Fusion) để quyết định final_gender.
        
        Hỗ trợ đa mô hình ngôn ngữ lớn (Gemini, ChatGPT, DeepSeek, Ollama).
        """
        if not cues:
            return []

        llm_map = llm_genders if llm_genders is not None else (deepseek_genders or {})
        llm_cont = llm_continuity if llm_continuity is not None else (deepseek_continuity or [])
        fused: List[Dict[str, Any]] = []

        # Xây dựng danh sách liên kết chuỗi từ LLM (Gemini/ChatGPT/DeepSeek/Ollama)
        linked_pairs = set()
        if llm_cont:
            for grp in llm_cont:
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

            zh_text = str(item.get("text", "") or item.get("original_text", "")).strip()
            vi_text = str(item.get("translated_text", "")).strip()

            # -----------------------------------------------------------------
            # 1. BỎ QUA PHỤ ĐỀ TĨNH / CHỮ RÁC / TRÍCH DẪN TRIẾT LÝ CUỐI PHIM
            # -----------------------------------------------------------------
            if item.get("skip_tts") or item.get("status") == "static_text":
                item["gender"] = "none"
                item["final_gender"] = "none"
                item["final_decision_confidence"] = 1.0
                item["decision_mode"] = "static_non_speech"
                reasons = list(item.get("gender_reason") or [])
                reasons.append("Phụ đề tĩnh / biểu tượng / không chứa giọng nói thoại")
                item["gender_reason"] = reasons
                fused.append(item)
                prev_final_gender = None
                prev_cid = cid
                continue

            if cls.is_moral_summary_quote(zh_text, vi_text):
                item["gender"] = "unknown"
                item["final_gender"] = "unknown"
                item["final_decision_confidence"] = 1.0
                item["decision_mode"] = "moral_quote"
                reasons = list(item.get("gender_reason") or [])
                reasons.append("Phụ đề trích dẫn triết lý/danh ngôn đúc kết cuối phim (không thuộc vai thoại nhân vật)")
                item["gender_reason"] = reasons
                fused.append(item)
                prev_final_gender = None
                prev_cid = cid
                continue

            # -----------------------------------------------------------------
            # 2. KHỞI TẠO TỔNG HỢP BẰNG CHỨNG XÁC SUẤT (BAYESIAN EVIDENCE ACCUMULATION)
            # -----------------------------------------------------------------
            evidence = {"female": 0.0, "male": 0.0}
            reasons = list(item.get("gender_reason") or [])

            # BẰNG CHỨNG 1: VOCATIVE BAYESIAN SOFT-WEIGHTS
            voc_g, voc_boost, voc_reason = cls.detect_vocative_gender(zh_text, vi_text)
            if voc_g in {"male", "female"}:
                evidence[voc_g] += voc_boost
                reasons.append(f"Ngữ nghĩa xưng hô đối ứng: {voc_reason} (+{voc_boost:.2f} {voc_g})")

            # BẰNG CHỨNG 2: 3D-SPEAKER VOICEPRINT CLUSTER EVIDENCE (ERes2Net Voiceprint)
            cl_id = str(item.get("cluster_id") or item.get("voice_cluster") or "").strip()
            cl_f_ratio = float(item.get("cluster_female_ratio", 0.5) or 0.5)
            cl_m_ratio = float(item.get("cluster_male_ratio", 0.5) or 0.5)
            # Nếu cụm âm sắc có độ áp đảo cao (>= 75%), tăng trọng số cụm lên 0.45
            is_strong_cluster = abs(cl_f_ratio - cl_m_ratio) >= 0.50
            W_CLUSTER = 0.45 if is_strong_cluster else 0.35
            evidence["female"] += cl_f_ratio * W_CLUSTER
            evidence["male"] += cl_m_ratio * W_CLUSTER
            if cl_id and abs(cl_f_ratio - cl_m_ratio) >= 0.15:
                fav = "female" if cl_f_ratio > cl_m_ratio else "male"
                fav_pct = max(cl_f_ratio, cl_m_ratio) * 100.0
                reasons.append(f"Cụm âm sắc 3D-Speaker ({cl_id}): Nghiêng về {fav.upper()} ({fav_pct:.1f}%)")

            # BẰNG CHỨNG 3: LLM MACRO-CONTEXTUAL REASONING (Gemini / ChatGPT / DeepSeek / Ollama)
            lg = str(llm_map.get(cid, "") or item.get("llm_gender", "") or item.get("deepseek_gender", "") or "").lower().strip()
            W_LLM = 0.40
            if lg in {"male", "female"}:
                evidence[lg] += W_LLM
                reasons.append(f"{llm_provider_name} suy luận ngữ cảnh kịch bản: {lg.upper()} (+{W_LLM:.2f})")

            # BẰNG CHỨNG 4: PHYSICAL ACOUSTIC MODEL (ECAPA-TDNN / AST) - ACOUSTIC NOISE GATE
            raw_g = str(item.get("raw_gender", "") or item.get("gender", "") or "unknown").lower().strip()
            raw_c = float(item.get("raw_gender_confidence", 0.0) or item.get("confidence", 0.0) or 0.0)
            if raw_c > 1.0:
                raw_c = raw_c / 100.0

            W_ACOUSTIC = 0.35
            if raw_g in {"male", "female"}:
                # Ngưỡng tin cậy âm học: Dưới 0.65 (đoán mò 50-60%) được coi là nhiễu,
                # triệt tiêu trọng số để không phá hỏng phán đoán của Cụm âm sắc ERes2Net và Kịch bản!
                if raw_c >= 0.65:
                    ac_score = raw_c * W_ACOUSTIC
                    evidence[raw_g] += ac_score
                    reasons.append(f"Âm học vật lý sóng âm: {raw_g.upper()} ({raw_c*100:.1f}%, +{ac_score:.2f})")
                else:
                    ac_score = max(0.01, (raw_c - 0.50) * 0.10)
                    evidence[raw_g] += ac_score
                    reasons.append(f"Âm học vật lý không chắc chắn ({raw_c*100:.1f}%, suy giảm trọng số còn +{ac_score:.2f})")

            # BẰNG CHỨNG 5: DIALOGUE CONTINUITY & SANDWICH SMOOTHING
            dur = float(item.get("end", 0.0)) - float(item.get("start", 0.0))
            is_turn = bool(item.get("is_turn_taking", False))
            if not is_turn:
                TURN_TAKING_TRIGGERS = (
                    "对不起", "抱歉", "不好意思", "我错了", "我不是", "我没有", "我不太懂", "我不知道",
                    "不要", "凭什么", "为什么", "算了", "行了", "别说了", "没关系", "怎么了",
                    "好的", "恩", "嗯", "真的吗", "不是吧", "你干嘛", "你别", "放开", "救命",
                    "我？", "我?", "怎么可能", "不是吧"
                )
                if any(trig in zh_text for trig in TURN_TAKING_TRIGGERS):
                    is_turn = True

            is_sandwich = False
            sandwich_target = None
            if idx > 1 and idx < len(cues):
                nxt_cue = cues[idx]
                nxt_start = float(nxt_cue.get("start", 0.0) or 0.0)
                curr_end = float(item.get("end", 0.0) or 0.0)
                curr_start = float(item.get("start", 0.0) or 0.0)
                prev_cue = cues[idx - 2]
                prev_end = float(prev_cue.get("end", 0.0) or 0.0)
                gap_p = max(0.0, curr_start - prev_end)
                gap_n = max(0.0, nxt_start - curr_end)
                nxt_raw_g = str(nxt_cue.get("raw_gender") or nxt_cue.get("gender") or "").lower()
                nxt_raw_c = float(nxt_cue.get("raw_gender_confidence") or nxt_cue.get("confidence") or 0.0)
                if nxt_raw_c > 1.0:
                    nxt_raw_c /= 100.0

                if (
                    prev_final_gender in {"male", "female"}
                    and nxt_raw_g == prev_final_gender
                    and nxt_raw_c >= 0.65
                    and gap_p <= 0.60
                    and gap_n <= 0.60
                    and not is_turn
                ):
                    is_sandwich = True
                    sandwich_target = prev_final_gender

            if is_sandwich and sandwich_target:
                evidence[sandwich_target] += 0.25
                reasons.append(f"Sandwich continuity: Đồng thuận chuỗi thoại liên tục của {sandwich_target.upper()} (+0.25)")
            else:
                cont_g = item.get("continuation_gender")
                if cont_g in {"male", "female"} and not is_turn:
                    evidence[cont_g] += 0.15
                    reasons.append(f"Quán tính lời thoại: Tiếp nối cùng lượt thoại của {cont_g.upper()} (+0.15)")

            # -----------------------------------------------------------------
            # 3. QUYẾT ĐỊNH XÁC SUẤT HẬU NGHIỆM (POSTERIOR DECISION)
            # -----------------------------------------------------------------
            total_ev = evidence["female"] + evidence["male"] + 1e-6
            prob_female = evidence["female"] / total_ev
            prob_male = evidence["male"] / total_ev

            if prob_female >= 0.53:
                final_g = "female"
                final_c = round(prob_female, 3)
                mode = "bayesian_evidence_fusion"
            elif prob_male >= 0.53:
                final_g = "male"
                final_c = round(prob_male, 3)
                mode = "bayesian_evidence_fusion"
            else:
                # Trường hợp bằng điểm (Tie-break): Phân xử bằng âm học có độ tin cậy hoặc DeepSeek
                if raw_g in {"male", "female"} and raw_c >= 0.70:
                    final_g = raw_g
                    final_c = round(raw_c, 3)
                    mode = "acoustic_tiebreak"
                    reasons.append("Phân xử hòa điểm: Ưu tiên âm học vật lý đáng tin cậy")
                elif dg in {"male", "female"}:
                    final_g = dg
                    final_c = 0.60
                    mode = "deepseek_tiebreak"
                    reasons.append("Phân xử hòa điểm: Ưu tiên DeepSeek ngữ cảnh kịch bản")
                else:
                    final_g = "unknown"
                    final_c = 0.50
                    mode = "uncertain"

            conf_display = round(final_c * 100.0 if final_c <= 1.0 else final_c, 1)

            item["gender"] = final_g
            item["final_gender"] = final_g
            item["final_decision_confidence"] = conf_display
            item["confidence"] = conf_display
            item["decision_mode"] = mode
            item["gender_reason"] = reasons

            prev_final_gender = final_g
            prev_cid = cid
            fused.append(item)

        return fused
