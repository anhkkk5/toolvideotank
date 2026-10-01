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

    @classmethod
    def merge_incomplete_split_dialogues(
        cls,
        cues_list: list[dict[str, Any]],
        *,
        max_gap: float = 0.35,
        max_duration: float = 5.0,
        max_cjk_length: int = 24,
    ) -> list[dict[str, Any]]:
        """Ghép các câu phụ đề bị chia cắt dở dang (Incomplete Split Clauses) của cùng một lượt nói.

        Đảm bảo các câu như '既然这么累' + '为什么要生我呢' được hợp nhất thành một câu hoàn chỉnh,
        giúp bản dịch ngữ cảnh chính xác và lồng tiếng TTS tự nhiên, không ngắt quãng.
        """
        if not cues_list or len(cues_list) <= 1:
            return cues_list

        INCOMPLETE_PREFIXES = (
            "既然", "要不是", "如果", "要是", "假如", "哪怕", "虽然", "即使", "即便", "只要",
            "为了", "不仅", "不但", "你看", "你看给", "可是", "但是", "可你们", "但你们",
            "其实", "老师说", "她会觉得", "她一直", "每天会", "咱当父母", "做父母的", "做父母",
            "爸妈也是", "我捡些", "我让你", "我之前", "孩子有",
            "我一下子", "教育孩子", "再这么", "你今天", "这日子", "我还不是", "我俩没",
            "你这孩子", "孩子都", "而且现在", "咱得", "还有视频", "这样能", "还能", "你俩也",
            "就算", "不应该", "那不还", "无论", "哪怕是", "并且", "因此",
        )
        INCOMPLETE_SUFFIXES = (
            "说", "觉得", "认为", "想", "但是", "可是", "而且", "因为", "所以", "如果",
            "虽然", "哪怕", "为了", "只要", "既然", "不仅", "并且", "就", "还", "累",
            "但", "可", "那么", "把", "被", "给", "到", "在", "着", "去", "过",
            "神器", "追问", "思路", "知识点", "反三",
        )
        TURN_STARTERS = (
            "那还能怎么办", "那也有办法", "对不起", "抱歉", "不好意思", "我说", "你说什么", "别生气", "別生气",
            "这怎么会这样", "知道不", "怎么了", "行了", "算了", "不用", "我愿意吗", "别说了",
            "好的", "恩", "嗯", "真的吗", "不是吧", "你干嘛", "放开", "救命", "谢谢妈妈", "谢谢爸爸",
        )
        SENTENCE_FINAL_PARTICLES = ("吗", "呢", "吧", "呀", "啊", "啦", "哦", "哈", "么", "嘛", "呐")
        STANDALONE_VOCATIVES = (
            "爸爸，", "妈妈，", "小姨，", "叔叔，", "阿姨，", "老师，", "老公，", "老婆，",
            "爸爸！", "妈妈！", "小姨！", "爸爸？", "妈妈？", "小姨？",
            "爸爸!", "妈妈!", "小姨!", "爸爸?", "妈妈?", "小姨?",
        )
        CONNECTIVE_CONTINUATIONS = (
            "为什么要", "为什么", "怎么不知道", "怎么不能", "学习上", "帮不了",
            "我一下子", "早晚出问题", "这日子", "为了多挣", "你们就不用",
            "你在这", "她一直", "每天会", "你们人生", "就算过得", "那不还是",
            "不应该", "爸妈也是", "以后我们", "我们也不用", "花了我",
        )

        def is_standalone_vocative(text: str) -> bool:
            for v in STANDALONE_VOCATIVES:
                if text.startswith(v):
                    return True
            cjk = "".join(re.findall(r"[\u3400-\u9fff]", text))
            if cjk in ("爸爸", "妈妈", "小姨", "姐姐", "哥哥", "老公", "老婆", "叔叔", "阿姨"):
                return True
            return False

        merged: list[dict[str, Any]] = []
        i = 0
        while i < len(cues_list):
            curr = dict(cues_list[i])

            while i + 1 < len(cues_list):
                nxt = cues_list[i + 1]
                c_s, c_e = float(curr.get("start", 0)), float(curr.get("end", 0))
                n_s, n_e = float(nxt.get("start", 0)), float(nxt.get("end", 0))
                gap = round(n_s - c_e, 3)

                c_txt = str(curr.get("text", "") or curr.get("original_text", "")).strip()
                n_txt = str(nxt.get("text", "") or nxt.get("original_text", "")).strip()
                c_cjk = "".join(re.findall(r"[\u3400-\u9fff]", c_txt))
                n_cjk = "".join(re.findall(r"[\u3400-\u9fff]", n_txt))
                c_dur = round(c_e - c_s, 2)
                n_dur = round(n_e - n_s, 2)

                # 1. Khoảng cách thời gian liền kề: gap <= max_gap (0.35s)
                if gap > max_gap:
                    break

                # 2. Câu trước kết thúc bằng dấu chấm dứt điểm câu
                if c_txt.endswith(("。", "！", "？", "!", "?")):
                    break

                # 3. Câu trước đã đủ độ dài (>= 1.8s hoặc >= 7 chữ) VÀ kết thúc bằng trợ từ ngữ khí -> Đã trọn câu!
                if (c_dur >= 1.8 or len(c_cjk) >= 7) and any(c_cjk.endswith(p) for p in SENTENCE_FINAL_PARTICLES):
                    break

                # 4. Câu sau là từ mở đầu lượt thoại đối đáp mới -> Không ghép vào đuôi câu trước
                if any(n_cjk.startswith(trig) or n_txt.startswith(trig) for trig in TURN_STARTERS):
                    break

                # 5. Câu sau là từ hô gọi độc lập (ví dụ "妈妈" đứng riêng) -> Không ghép
                if is_standalone_vocative(n_txt):
                    break

                # 6. Ràng buộc giới tính âm học: Nếu cả 2 đều có âm học tin cậy nhưng khác giới tính -> Tuyệt đối không ghép
                c_g = str(curr.get("raw_gender") or curr.get("gender") or "unknown").lower()
                n_g = str(nxt.get("raw_gender") or nxt.get("gender") or "unknown").lower()
                c_conf = float(curr.get("raw_gender_confidence") or curr.get("confidence") or 0.0)
                n_conf = float(nxt.get("raw_gender_confidence") or nxt.get("confidence") or 0.0)
                if c_conf > 1.0:
                    c_conf /= 100.0
                if n_conf > 1.0:
                    n_conf /= 100.0

                if c_g in {"male", "female"} and n_g in {"male", "female"} and c_g != n_g and (c_conf >= 0.70 or n_conf >= 0.70):
                    break

                # 7. Giới hạn độ dài an toàn (nâng lên 5.2s và 28 CJK)
                total_cjk = len(c_cjk) + len(n_cjk)
                total_dur = round(n_e - c_s, 2)
                if total_cjk > 28 or total_dur > 5.2:
                    break

                # 8. Điều kiện gộp thông minh (Smart Clause Merging):
                # - Câu trước ngắn (< 1.5s hoặc <= 8 chữ) chưa dứt câu
                # - Hoặc câu sau là vế nối tiếp / câu trước là vế dở dang
                # - Hoặc 2 câu cực sát (gap <= 0.15s) cùng giới tính
                is_prefix = any(c_cjk.startswith(p) for p in INCOMPLETE_PREFIXES)
                is_suffix = any(c_cjk.endswith(s) for s in INCOMPLETE_SUFFIXES)
                is_short_clause = (c_dur <= 1.5 or len(c_cjk) <= 8)
                is_nxt_connective = any(n_cjk.startswith(p) for p in CONNECTIVE_CONTINUATIONS)
                is_tight_same_gender = (gap <= 0.15 and c_g == n_g and c_g in {"male", "female"})

                if not (is_prefix or is_suffix or is_short_clause or is_nxt_connective or is_tight_same_gender):
                    break

                curr["end"] = n_e
                curr["text"] = f"{c_txt} {n_txt}"
                curr["original_text"] = curr["text"]
                curr["merged_from"] = list(curr.get("merged_from", [])) + list(nxt.get("merged_from", []))
                # Ghép bản dịch nếu đã có
                c_trans = str(curr.get("translated_text", "") or "").strip()
                n_trans = str(nxt.get("translated_text", "") or "").strip()
                if c_trans and n_trans:
                    curr["translated_text"] = f"{c_trans}, {n_trans}"
                elif n_trans:
                    curr["translated_text"] = n_trans

                # Kế thừa giới tính âm học mạnh hơn nếu có
                if n_g in {"male", "female"} and n_conf > c_conf:
                    curr["raw_gender"] = n_g
                    curr["raw_gender_confidence"] = n_conf
                    curr["gender"] = n_g
                i += 1

            merged.append(curr)
            i += 1

        return merged
