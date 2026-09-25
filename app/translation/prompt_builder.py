from __future__ import annotations

import json
from .prompt_loader import render_prompt


def build_translation_messages(
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
    """Build the system/user message pair from editable Markdown templates."""
    style_value = str(style_instruction or "").strip()
    style_clause = f" Style: {style_value}" if style_value else ""
    lowered_style = style_value.lower()
    dubbing_mode = "[mode=dubbing_rewrite]" in lowered_style
    ocr_capture_mode = "[mode=ocr_capture]" in lowered_style
    is_direct = not translated_texts

    # Use specialized short drama translation with sliding window context for direct translation
    is_cjk = str(src_lang or "").lower().startswith(("zh", "chi", "auto"))
    if is_direct and (is_cjk or previous_context or next_context or character_glossary) and not ocr_capture_mode:
        prompt_key = "short_drama_translation"
        payload: dict = {}
        if character_glossary:
            payload["character_glossary"] = character_glossary
        if previous_context:
            payload["previous_context"] = [
                {
                    **({"speaker": str(c.get("speaker")).strip()} if c.get("speaker") else {}),
                    "source": str(c.get("source") or c.get("zh") or "").strip(),
                    "translated": str(c.get("translated") or c.get("vi") or "").strip(),
                }
                for c in previous_context
                if c.get("source") or c.get("zh")
            ]
        payload["to_translate"] = [
            {
                "id": index + 1,
                **({"speaker": str(speakers[index]).strip()} if speakers and index < len(speakers) and str(speakers[index]).strip() else {}),
                "text": str(text or "").strip(),
            }
            for index, text in enumerate(source_texts)
        ]
        if next_context:
            payload["next_context"] = [
                {"text": str(text or "").strip()}
                for text in next_context
                if str(text or "").strip()
            ]
        user_message = json.dumps(payload, ensure_ascii=False, indent=2)
    elif is_direct and ocr_capture_mode:
        prompt_key = "ocr_translation"
        lines = [
            f"{index + 1}. <OCR_TEXT>{' '.join(str(text or '').splitlines())}</OCR_TEXT>"
            for index, text in enumerate(source_texts)
        ]
        user_message = "\n".join(lines)
    elif is_direct:
        prompt_key = "subtitle_translation"
        lines = [f"{index + 1}. {text}" for index, text in enumerate(source_texts)]
        user_message = "\n".join(lines)
    else:
        prompt_key = "dubbing_rewrite" if dubbing_mode else "subtitle_refinement"
        lines = [
            f"{index + 1}. {source} ||| {draft}"
            for index, (source, draft) in enumerate(zip(source_texts, translated_texts or []))
        ]
        user_message = "\n".join(lines)

    values = {
        "source_lang": str(src_lang or "auto"),
        "target_lang": str(target_lang or "vi"),
        "style_clause": style_clause,
    }
    system_message = render_prompt(f"{prompt_key}.system.md", **values)
    return system_message, user_message
