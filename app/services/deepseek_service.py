"""DeepSeek Translation Service for movie/drama subtitle localization.

Implements strict JSON output, character memory persistence, sliding-window
context, validation, and bounded exponential retry policy.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

try:
    from openai import OpenAI, APIError, AuthenticationError, RateLimitError, APITimeoutError
except ImportError:
    OpenAI = None
    APIError = Exception
    AuthenticationError = Exception
    RateLimitError = Exception
    APITimeoutError = Exception

from models.subtitle_segment import SubtitleSegment


class DeepSeekTranslationError(Exception):
    """Base error for DeepSeek translation."""
    pass


class DeepSeekValidationError(DeepSeekTranslationError):
    """Validation failed for LLM response schema."""
    pass


class DeepSeekService:
    """Service to translate subtitle batches using DeepSeek API."""

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-chat"
    CONNECT_TIMEOUT = 10.0
    READ_TIMEOUT = 90.0
    MAX_RETRIES = 2
    BATCH_SIZE = 35

    def __init__(
        self,
        api_key: str = "",
        model_name: str = "",
        base_url: str = "",
    ):
        self.api_key = str(api_key or os.getenv("DEEPSEEK_API_KEY", "")).strip()
        self.model_name = str(model_name or os.getenv("DEEPSEEK_MODEL", self.DEFAULT_MODEL)).strip()
        self.base_url = str(base_url or os.getenv("DEEPSEEK_BASE_URL", self.DEFAULT_BASE_URL)).strip()
        self._client: Any = None

    def is_configured(self) -> bool:
        """Check if API key is provided."""
        return bool(self.api_key)

    def _get_client(self) -> OpenAI:
        if OpenAI is None:
            raise DeepSeekTranslationError("Thư viện 'openai' chưa được cài đặt trong môi trường Python.")
        if not self.api_key:
            raise DeepSeekTranslationError("Chưa có DEEPSEEK_API_KEY. Vui lòng cấu hình khóa API trong Cài đặt.")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.READ_TIMEOUT,
            )
        return self._client

    # -------------------------------------------------------------------------
    # Character Memory & Merge Policy
    # -------------------------------------------------------------------------
    @staticmethod
    def init_character_memory() -> dict[str, Any]:
        """Create an empty character memory structure."""
        return {
            "characters": {},     # source_name -> {"vi_name": str, "gender": str, "aliases": list, "locked": bool}
            "relationships": [],
        }

    @staticmethod
    def merge_character_updates(
        memory: dict[str, Any],
        updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Merge proposed character updates into memory following Lock Rule.
        
        Lock Rule: If source_name already exists, its vi_name and gender are locked
        and MUST NOT be overwritten. Only new aliases can be appended.
        """
        if not updates or not isinstance(updates, list):
            return memory

        characters = memory.setdefault("characters", {})
        for item in updates:
            if not isinstance(item, dict):
                continue
            src = str(item.get("source_name", "")).strip()
            vi = str(item.get("vi_name", "")).strip()
            gender = str(item.get("gender", "unknown")).lower().strip()
            if gender not in {"male", "female"}:
                gender = "unknown"
            new_aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]

            if not src or not vi:
                continue

            if src in characters:
                # Locked entry: DO NOT overwrite vi_name or gender
                existing = characters[src]
                curr_aliases = set(existing.get("aliases") or [])
                curr_aliases.update(new_aliases)
                existing["aliases"] = sorted(list(curr_aliases))
            else:
                characters[src] = {
                    "vi_name": vi,
                    "gender": gender,
                    "aliases": sorted(list(set(new_aliases))),
                    "locked": True,
                }
        return memory

    # -------------------------------------------------------------------------
    # System Prompt & Context Formatting
    # -------------------------------------------------------------------------
    def _build_system_prompt(self, memory: dict[str, Any]) -> str:
        """Construct specialized drama translation prompt with memory & rules."""
        char_list = []
        for src, info in (memory.get("characters") or {}).items():
            vi = info.get("vi_name", "")
            g = "Nam" if info.get("gender") == "male" else ("Nữ" if info.get("gender") == "female" else "")
            aliases = ", ".join(info.get("aliases") or [])
            alias_str = f" (biệt danh: {aliases})" if aliases else ""
            g_str = f" [{g}]" if g else ""
            char_list.append(f"- {src} -> {vi}{g_str}{alias_str}")

        memory_block = "\n".join(char_list) if char_list else "Chưa có danh sách nhân vật đã khóa."

        return f"""Bạn là chuyên gia dịch thuật và biên kịch kịch bản phim ảnh (Short Drama / Phim truyền hình Trung Quốc) sang tiếng Việt.
Nhiệm vụ của bạn là dịch các câu phụ đề theo thứ tự thời gian sang tiếng Việt tự nhiên, chuẩn phong cách phim ảnh, giàu cảm xúc và tuyệt đối chuẩn xác theo ngữ cảnh.

BẮT BUỘC TUÂN THỦ CÁC QUY TẮC SAU:

1. NGUYÊN TẮC XƯNG HÔ VÀ QUAN HỆ NHÂN VẬT:
   - Không suy luận quan hệ nhân vật chỉ từ giới tính. Hãy suy luận quan hệ dựa trên ngữ cảnh hội thoại, cách gọi tên/chức danh và các câu trước/sau.
   - Nếu chưa đủ bằng chứng rõ ràng về quan hệ, ưu tiên cách xưng hô trung tính và nhất quán (tôi - anh/cô, cậu - tôi...) thay vì tự ý tạo quan hệ (như anh - em yêu đương).
   - Khi đã xác định rõ vai vế (ví dụ: cấp trên - cấp dưới, vợ - chồng, mẹ - con, bạn bè thân thiết), giữ nguyên cách xưng hô đối ứng nhất quán trong toàn bộ phân cảnh.

2. QUY TẮC TÊN RIÊNG & DANH XƯNG HÁN - VIỆT (4 CẤP ĐỘ ƯU TIÊN):
   - Ưu tiên 1: Tên đã được xác định trong ngữ cảnh / phụ đề.
   - Ưu tiên 2: Sử dụng danh sách nhân vật đã khóa trong bộ nhớ (Character Memory) dưới đây. Tuyệt đối không tự ý đổi tên đã có trong bộ nhớ!
   - Ưu tiên 3: Nếu là tên Hán tự mới, chuyển sang âm Hán - Việt phù hợp (ví dụ: 小婷 -> Tiểu Đình, 林浩 -> Lâm Hạo, 顾总 -> Cố tổng). Tuyệt đối không dịch nghĩa thô.
   - Ưu tiên 4: Không tự ý thay đổi tên đã xác lập ở các câu trước. 1 nhân vật = 1 tên duy nhất trong suốt bộ phim.

BỘ NHỚ NHÂN VẬT ĐÃ KHÓA (GLOBAL CHARACTER MEMORY):
{memory_block}

3. TỪ CHỈ ĐỊNH CỰ LY (SPATIAL DEIXIS - CẤM NHẦM LẪN):
   - "这" / "这里" / "这儿" (cận chỉ - cự ly gần người nói) -> BẮT BUỘC dịch là "đây", "ở đây", "chỗ này", "này". TUYỆT ĐỐI KHÔNG dịch thành "đấy", "đó".
   - "那" / "那里" / "那儿" (viễn chỉ - cự ly xa người nói) -> dịch là "đấy", "đó", "ở đó", "kia".

4. PHÂN LOẠI CÂU RÁC / DISCLAIMER (is_noise):
   - Nếu câu là disclaimer của kịch bản Douyin/TikTok (ví dụ: "剧情需要 请勿模仿", "全剧虚构", cảnh báo an toàn) hoặc chữ rác in trên áo, thương hiệu không phải lời thoại:
     Đặt "is_noise": true và "translated_text": "".
   - Lời thoại nhân vật bình thường: Đặt "is_noise": false và "translated_text": "<nội dung dịch tiếng Việt>".

5. PHÂN VAI GIỚI TÍNH NHÂN VẬT THEO NGỮ CẢNH (BẮT BUỘC):
   - Dựa vào cốt truyện, cách xưng hô, hành động và diễn biến phim để xác định giới tính người nói:
     + "male": Nhân vật Nam nói
     + "female": Nhân vật Nữ nói
   - RẤT QUAN TRỌNG: Nếu một nhân vật nói liền mạch nhiều câu (ví dụ tỏ tình "Tiểu Đình... Chúng ta... Ở bên nhau đi" hoặc tâm sự dài), BẮT BUỘC toàn bộ các câu trong chuỗi đó phải mang cùng một giới tính!

6. ĐỊNH DẠNG ĐẦU RA (BẮT BUỘC JSON DUY NHẤT):
   Trả về DUY NHẤT một JSON Object không kèm giải thích:
   {{
     "translations": [
       {{"id": 1, "translated_text": "...", "is_noise": false, "gender": "male/female"}},
       {{"id": 2, "translated_text": "...", "is_noise": false, "gender": "male/female"}}
     ],
     "character_updates": [
       {{"source_name": "tên_tiếng_trung", "vi_name": "tên_Hán_Việt", "gender": "male/female", "aliases": []}}
     ]
   }}
   - Mọi "id" trong batch đầu vào BẮT BUỘC phải xuất hiện đầy đủ trong mảng "translations".
"""

    def _build_user_message(
        self,
        current_batch: list[SubtitleSegment],
        previous_context: list[SubtitleSegment] | None = None,
    ) -> str:
        """Format the current batch and sliding window context as JSON."""
        prev_list = []
        if previous_context:
            for s in previous_context[-8:]:
                speaker = s.speaker_label or ("Nam" if s.gender == "male" else ("Nữ" if s.gender == "female" else ""))
                prev_list.append({
                    "id": s.id,
                    "speaker": speaker,
                    "zh": s.text,
                    "vi": s.translated_text,
                })

        batch_list = []
        for s in current_batch:
            speaker = s.speaker_label or ("Nam" if s.gender == "male" else ("Nữ" if s.gender == "female" else "Không rõ"))
            batch_list.append({
                "id": s.id,
                "speaker": speaker,
                "gender": s.gender,
                "text": s.text,
            })

        payload = {
            "previous_context": prev_list,
            "current_batch": batch_list,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------------------
    # Response Parsing & Validation (6 Criteria)
    # -------------------------------------------------------------------------
    @staticmethod
    def _parse_and_validate_response(
        raw_text: str,
        expected_ids: list[int],
    ) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
        """Parse LLM response and strictly validate the 6 criteria.
        
        Returns:
            (translations_by_id, character_updates)
        """
        cleaned = raw_text.strip()
        if "```" in cleaned:
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        try:
            data = json.loads(cleaned)
        except Exception as exc:
            raise DeepSeekValidationError(f"Không thể giải mã JSON từ kết quả DeepSeek: {exc}") from exc

        if not isinstance(data, dict):
            raise DeepSeekValidationError("Kết quả DeepSeek không phải là một JSON Object.")

        translations = data.get("translations")
        if not isinstance(translations, list):
            raise DeepSeekValidationError("JSON thiếu trường 'translations' dạng mảng.")

        # Criteria 1: Count & duplicate check
        found_ids = set()
        result_map: dict[int, dict[str, Any]] = {}
        for item in translations:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            try:
                iid = int(item_id)
            except (ValueError, TypeError):
                continue

            if iid in found_ids:
                raise DeepSeekValidationError(f"Phát hiện ID bị trùng lặp trong kết quả: ID {iid}")
            found_ids.add(iid)

            is_noise = bool(item.get("is_noise", False))
            trans_text = str(item.get("translated_text", "") or "").strip()
            g_raw = str(item.get("gender", "") or "").lower().strip()
            item_gender = "male" if g_raw in {"male", "nam"} else ("female" if g_raw in {"female", "nu", "nữ"} else "")

            # Criteria 5: translated_text cannot be empty if not noise
            if not is_noise and not trans_text:
                raise DeepSeekValidationError(f"Câu ID {iid} không phải rác nhưng bản dịch bị rỗng.")

            result_map[iid] = {
                "translated_text": trans_text,
                "is_noise": is_noise,
                "gender": item_gender,
            }

        # Criteria 2 & 3: Missing IDs
        missing = [expected_id for expected_id in expected_ids if expected_id not in found_ids]
        if missing:
            raise DeepSeekValidationError(f"DeepSeek bỏ sót các câu ID: {missing[:5]}{'...' if len(missing) > 5 else ''}")

        # Criteria 4: Unexpected extra IDs
        expected_set = set(expected_ids)
        extra = [fid for fid in found_ids if fid not in expected_set]
        if extra:
            raise DeepSeekValidationError(f"DeepSeek trả về ID lạ không thuộc batch: {extra[:5]}")

        char_updates = data.get("character_updates", [])
        if not isinstance(char_updates, list):
            char_updates = []

        return result_map, char_updates

    # -------------------------------------------------------------------------
    # Core Translation with Bounded Retry Policy
    # -------------------------------------------------------------------------
    def translate_batch(
        self,
        batch: list[SubtitleSegment],
        memory: dict[str, Any],
        previous_context: list[SubtitleSegment] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Translate a single batch with exponential backoff retry.
        
        Returns:
            (batch_results, updated_memory)
        """
        if not batch:
            return [], memory

        expected_ids = [s.id for s in batch]
        system_prompt = self._build_system_prompt(memory)
        user_message = self._build_user_message(batch, previous_context)

        client = self._get_client()
        last_error = ""

        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": "disabled"}},
                    temperature=0.3,
                )

                raw_content = response.choices[0].message.content or ""
                result_map, char_updates = self._parse_and_validate_response(raw_content, expected_ids)

                # Merge character updates safely
                updated_memory = self.merge_character_updates(memory, char_updates)

                # Format results preserving original order
                formatted_results = []
                for s in batch:
                    info = result_map.get(s.id, {"translated_text": "", "is_noise": False})
                    is_noise = info["is_noise"]
                    trans_text = info["translated_text"]

                    # Spatial deixis normalization check
                    trans_text = self._post_process_spatial_deixis(s.text, trans_text)

                    formatted_results.append({
                        "id": s.id,
                        "translated_text": trans_text,
                        "is_noise": is_noise,
                        "gender": info.get("gender", ""),
                        "translation_source": "deepseek",
                        "translation_status": "noise" if is_noise else "translated",
                    })

                return formatted_results, updated_memory

            except (AuthenticationError,) as auth_err:
                # Fail Fast: Wrong API key or Unauthorized
                raise DeepSeekTranslationError(f"Khóa DeepSeek API không hợp lệ hoặc hết hạn: {auth_err}") from auth_err

            except (APITimeoutError, RateLimitError, APIError, DeepSeekValidationError) as recoverable_err:
                last_error = str(recoverable_err)
                if attempt <= self.MAX_RETRIES:
                    backoff = 1.0 if attempt == 1 else 3.0
                    time.sleep(backoff)
                    continue
                break

            except Exception as unk_err:
                last_error = str(unk_err)
                if attempt <= self.MAX_RETRIES:
                    time.sleep(1.5)
                    continue
                break

        raise DeepSeekTranslationError(
            f"Dịch batch ({len(batch)} câu, ID {expected_ids[0]}-{expected_ids[-1]}) thất bại sau {self.MAX_RETRIES + 1} lần thử: {last_error}"
        )

    # -------------------------------------------------------------------------
    # Spatial Deixis Helper
    # -------------------------------------------------------------------------
    @staticmethod
    def _post_process_spatial_deixis(source_text: str, target_text: str) -> str:
        """Guarantee that '这/这里' is not mistranslated into 'đấy/đó'."""
        if not source_text or not target_text:
            return target_text

        # Near deixis in source: 这, 这里, 这儿
        has_near = bool(re.search(r"[这這]", source_text))
        has_far = bool(re.search(r"[那]", source_text))

        result = target_text
        if has_near and not has_far:
            # Replace common incorrect far deixis patterns with near deixis
            result = re.sub(r"\bngồi đấy\b", "ngồi đây", result, flags=re.IGNORECASE)
            result = re.sub(r"\bngồi đó\b", "ngồi đây", result, flags=re.IGNORECASE)
            result = re.sub(r"\bqua đấy\b", "qua đây", result, flags=re.IGNORECASE)
            result = re.sub(r"\bở đấy\b", "ở đây", result, flags=re.IGNORECASE)
            result = re.sub(r"\bchỗ đấy\b", "chỗ này", result, flags=re.IGNORECASE)
            result = re.sub(r"\bchỗ đó\b", "chỗ này", result, flags=re.IGNORECASE)

        return result
