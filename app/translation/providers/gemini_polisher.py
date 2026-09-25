import json
import os
import re
import time

from openai import OpenAI

from ..errors import TranslationConfigError, TranslationProviderError, TranslationValidationError
from ..prompt_builder import build_translation_messages
from ..srt_utils import parse_numbered_line_items, validate_texts


_CJK_CHAR_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def validate_target_language_lines(
    source_texts: list[str], translated_texts: list[str], target_lang: str
) -> None:
    """Reject confidently untranslated CJK lines for Latin-script targets."""
    target = str(target_lang or "").strip().lower().split("-", 1)[0]
    if target not in {"vi", "en", "fr", "de", "es", "pt", "id", "ms"}:
        return
    invalid_ids = []
    for index, (source, translated) in enumerate(zip(source_texts, translated_texts), 1):
        src = str(source or "").strip()
        dst = str(translated or "").strip()
        src_cjk = len(_CJK_CHAR_RE.findall(src))
        dst_cjk = len(_CJK_CHAR_RE.findall(dst))
        normalized_src = re.sub(r"\W+", "", src, flags=re.UNICODE).lower()
        normalized_dst = re.sub(r"\W+", "", dst, flags=re.UNICODE).lower()
        unchanged_cjk = src_cjk >= 2 and normalized_src == normalized_dst
        mostly_cjk = dst_cjk >= 2 and dst_cjk >= max(2, len(dst.replace(" ", "")) // 2)
        if unchanged_cjk or mostly_cjk:
            invalid_ids.append(index)
    if invalid_ids:
        preview = ", ".join(str(value) for value in invalid_ids[:12])
        raise TranslationValidationError(
            f"Output still contains untranslated CJK text at subtitle line(s): {preview}."
        )


def parse_translation_response(text: str, expected_count: int) -> list[str]:
    """Parse JSON or numbered lines from LLM response into an exact list of translated lines."""
    cleaned_text = str(text or "").strip()
    if "```" in cleaned_text:
        cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text, flags=re.MULTILINE)
        cleaned_text = re.sub(r"\s*```$", "", cleaned_text, flags=re.MULTILINE).strip()

    # 1. First, attempt to parse as standard JSON
    try:
        data = json.loads(cleaned_text)
        if isinstance(data, dict):
            for key in ("translations", "result", "items", "data", "subtitles", "cues"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
        if isinstance(data, list) and len(data) > 0:
            results_by_id = {}
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    item_id = item.get("id", idx + 1)
                    val = (
                        item.get("vi")
                        or item.get("text")
                        or item.get("translation")
                        or item.get("translated")
                        or ""
                    )
                    try:
                        results_by_id[int(item_id)] = str(val).strip()
                    except (ValueError, TypeError):
                        results_by_id[idx + 1] = str(val).strip()
                elif isinstance(item, str):
                    results_by_id[idx + 1] = str(item).strip()
            lines = [results_by_id.get(i, "") for i in range(1, expected_count + 1)]
            if validate_texts(lines, expected_count):
                return lines
    except Exception:
        pass

    # 2. Robust Regex Rescue: extract individual JSON objects {"id": X, "vi": "Y"}
    try:
        matches = re.findall(
            r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"(?:vi|text|translation|translated)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
            cleaned_text
        )
        if matches:
            results_by_id = {}
            for m_id, m_text in matches:
                try:
                    unescaped = m_text.encode().decode('unicode_escape', 'ignore')
                except Exception:
                    unescaped = m_text
                results_by_id[int(m_id)] = unescaped.strip()
            lines = [results_by_id.get(i, "") for i in range(1, expected_count + 1)]
            if validate_texts(lines, expected_count):
                return lines
    except Exception:
        pass

    # 3. Fallback to numbered line parser (1. line, 2. line...)
    numbered_items = parse_numbered_line_items(text)
    if numbered_items:
        numbered_map = {number: line for number, line in numbered_items}
        lines = [numbered_map.get(i, "") for i in range(1, expected_count + 1)]
        if validate_texts(lines, expected_count):
            return lines

    # 4. Fallback: line-by-line split if counts match
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(raw_lines) == expected_count:
        return raw_lines

    raise TranslationValidationError(
        f"Could not parse valid translation output for {expected_count} lines from response: {text[:200]}..."
    )


class OpenAICompatiblePolisherProvider:
    """Reusable subtitle provider for OpenAI-compatible services (Gemini, DeepSeek, OpenAI, Ollama)."""

    def __init__(self, *, provider_id: str, display_name: str, env_prefix: str,
                 default_base_url: str, default_model: str = ""):
        self.provider_id = provider_id
        self.display_name = display_name
        self.api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
        self.model_name = os.getenv(f"{env_prefix}_MODEL", default_model).strip()
        self.base_url = os.getenv(f"{env_prefix}_BASE_URL", default_base_url).strip()
        if not self.api_key:
            try:
                from dotenv import load_dotenv
                _env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
                if os.path.isfile(_env):
                    load_dotenv(_env, override=False)
                    self.api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
                    self.model_name = os.getenv(f"{env_prefix}_MODEL", default_model).strip()
                    self.base_url = os.getenv(f"{env_prefix}_BASE_URL", default_base_url).strip()
            except Exception:
                pass
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model_name and self.base_url)

    def _get_client(self):
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def _build_completion_kwargs(
        self, system_msg: str, user_msg: str, max_tokens: int, timeout: int
    ) -> dict:
        is_gemini = "generativelanguage.googleapis.com" in self.base_url or "gemini" in self.model_name.lower()
        is_deepseek = "deepseek" in self.base_url.lower() or "deepseek" in self.model_name.lower()
        is_reasoning_model = is_gemini or any(
            self.model_name.lower().startswith(p) for p in ("o1", "o3", "deepseek-r1")
        )

        kwargs = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max(4096, int(max_tokens or 4096)),
            "timeout": timeout,
        }

        # Enable JSON object format if requested by prompt and supported
        if "JSON" in system_msg and not is_reasoning_model:
            kwargs["response_format"] = {"type": "json_object"}

        if is_deepseek:
            kwargs["extra_body"] = {
                "thinking": {
                    "type": "disabled"
                }
            }

        if is_gemini:
            kwargs["reasoning_effort"] = "low"
        elif is_reasoning_model:
            kwargs["reasoning_effort"] = "low"
        else:
            kwargs["temperature"] = 0.3

        return kwargs

    def polish_batch(
        self,
        *,
        source_texts: list[str],
        translated_texts: list[str] = None,
        src_lang: str,
        target_lang: str,
        style_instruction: str = "",
        previous_context: list[dict] | None = None,
        next_context: list[str] | None = None,
        speakers: list[str] | None = None,
        character_glossary: dict[str, str] | None = None,
        timeout: int = 120,
        max_retries: int = 2,
        max_tokens: int = 4096,
    ) -> tuple[list[str], list[str], str]:
        if not self.is_configured():
            raise TranslationConfigError(f"{self.display_name} is not configured. Set its API key and model in Settings.")

        system_msg, user_msg = self._build_messages(
            source_texts=source_texts,
            translated_texts=translated_texts,
            src_lang=src_lang,
            target_lang=target_lang,
            style_instruction=style_instruction,
            previous_context=previous_context,
            next_context=next_context,
            speakers=speakers,
            character_glossary=character_glossary,
        )

        client = self._get_client()
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                kwargs = self._build_completion_kwargs(
                    system_msg=system_msg,
                    user_msg=user_msg,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                try:
                    response = client.chat.completions.create(**kwargs)
                    raw_content = response.choices[0].message.content or ""
                    translated_lines = parse_translation_response(raw_content, len(source_texts))
                    if not validate_texts(translated_lines, len(source_texts)):
                        raise TranslationValidationError("The provider returned empty or missing subtitle lines.")
                    validate_target_language_lines(source_texts, translated_lines, target_lang)
                    warnings = []
                    if len(translated_lines) != len(source_texts):
                        warnings.append(
                            f"Line count mismatch: expected {len(source_texts)}, got {len(translated_lines)}"
                        )
                    return translated_lines, warnings, self.provider_id
                except TranslationValidationError as exc:
                    # Malformed/partial LLM output is transient and should use
                    # the same bounded retry policy as provider failures.
                    raise TranslationProviderError(str(exc)) from exc
                except Exception as exc:
                    raise TranslationProviderError(str(exc)) from exc
            except TranslationConfigError:
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    time.sleep(1.0)

        raise TranslationProviderError(f"{self.display_name} failed after {max_retries} attempts: {last_error}")

    def _build_messages(
        self,
        *,
        source_texts: list[str],
        translated_texts: list[str] | None,
        src_lang: str,
        target_lang: str,
        style_instruction: str = "",
        previous_context: list[dict] | None = None,
        next_context: list[str] | None = None,
        speakers: list[str] | None = None,
        character_glossary: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        return build_translation_messages(
            source_texts=source_texts,
            translated_texts=translated_texts,
            src_lang=src_lang,
            target_lang=target_lang,
            style_instruction=style_instruction,
            previous_context=previous_context,
            next_context=next_context,
            speakers=speakers,
            character_glossary=character_glossary,
        )
