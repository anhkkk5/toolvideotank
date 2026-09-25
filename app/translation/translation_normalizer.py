import re


def normalize_spatial_deixis(source_text: str, translated_text: str) -> str:
    """Correct spatial deixis mismatches (e.g. confusing 'here' [đây] with 'there' [đấy/đó])."""
    if not source_text or not translated_text:
        return translated_text

    src = str(source_text).strip()
    res = str(translated_text)

    # Check for near deixis (这 / 这里 / 这儿)
    has_near_deixis = bool(re.search(r"[这這](?:里|儿|兒|边|邊)?", src))
    has_sit_near = bool(re.search(r"坐[这這]|坐到[这這]|坐在[这這]", src))
    has_come_near = bool(re.search(r"来[这這]|來[这這]|过来|過來|到[这這]|走过来", src))
    has_stand_near = bool(re.search(r"站[这這]|站到[这這]", src))
    has_look_near = bool(re.search(r"看[这這]", src))

    if has_sit_near:
        # "ngồi đấy", "ngồi đó" -> "ngồi đây"
        res = re.sub(r"\b([Nn]gồi)\s+(?:đấy|đó|kia)\b", r"\1 đây", res)

    if has_come_near:
        # "lại đấy", "qua đấy", "đến đấy" -> "... đây"
        res = re.sub(r"\b([Ll]ại|[Qq]ua|[Đđ]ến|[Tt]ới)\s+(?:đấy|đó)\b", r"\1 đây", res)

    if has_stand_near:
        # "đứng đấy", "đứng đó" -> "đứng đây"
        res = re.sub(r"\b([Đđ]ứng)\s+(?:đấy|đó)\b", r"\1 đây", res)

    if has_look_near:
        res = re.sub(r"\b([Nn]hìn)\s+(?:đấy|đó)\b", r"\1 đây", res)

    # General near deixis correction if the source strictly says "ở đây / chỗ này"
    if re.search(r"[在到][这這][里儿兒]", src):
        res = re.sub(r"\bở\s+(?:đấy|đó)\b", "ở đây", res)
        res = re.sub(r"\bchỗ\s+(?:đấy|đó)\b", "chỗ này", res)

    return res


def normalize_character_names(translated_text: str, glossary: dict[str, str]) -> str:
    """Ensure character names match the unified glossary across all lines."""
    if not translated_text or not glossary:
        return translated_text

    res = translated_text
    # Check known variants or typos if needed
    for zh_name, vi_name in glossary.items():
        if not vi_name:
            continue
        # If the target contains a known deformed translation of this name, replace it
        # E.g. "Tiểu Mĩ" -> "Tiểu Mỹ"
        if "Mỹ" in vi_name:
            res = re.sub(r"\bTiểu\s+Mĩ\b", vi_name, res)
            res = re.sub(r"\bMỹ\s+nhỏ\b", vi_name, res)

    return res


def post_process_translation(
    source_text: str,
    translated_text: str,
    glossary: dict[str, str] | None = None,
) -> str:
    """Combined normalization pipeline for AI subtitle translations."""
    res = normalize_spatial_deixis(source_text, translated_text)
    if glossary:
        res = normalize_character_names(res, glossary)
    return res


# Common Chinese short drama character patterns to auto-harvest
_CHARACTER_PATTERNS = [
    r"(小[A-Za-z\u4e00-\u9fa5])",
    r"(老[A-Za-z\u4e00-\u9fa5])",
    r"([\u4e00-\u9fa5]{1,2}(?:总|少|哥|姐|叔|伯|姑|姨|助理|秘书|医生|老师|律师|总裁|董事长))",
]


def harvest_character_entities(
    source_texts: list[str],
    translated_texts: list[str],
    current_glossary: dict[str, str] | None = None,
) -> dict[str, str]:
    """Inspect source and translated lines to discover and register character names dynamically."""
    glossary = dict(current_glossary or {})

    # Common known honorific mappings
    title_suffix_map = {
        "总": "tổng",
        "少": "thiếu",
        "哥": "ca",
        "姐": "tỷ",
    }

    for src, trans in zip(source_texts, translated_texts):
        src_str = str(src or "").strip()
        trans_str = str(trans or "").strip()
        if not src_str or not trans_str:
            continue

        # Check for Little X (小X) -> Tiểu X
        xiao_matches = re.findall(r"小([\u4e00-\u9fa5])", src_str)
        for ch in xiao_matches:
            zh_key = f"小{ch}"
            if zh_key not in glossary:
                # Look for "Tiểu [A-ZÀ-Ỹ][a-zà-ỹ]*" in translation
                m = re.search(r"\b(Tiểu\s+[A-ZÀ-Ỹ][a-zà-ỹ]*)\b", trans_str)
                if m:
                    glossary[zh_key] = m.group(1).strip()

        # Check for X Tổng (X总) -> X tổng
        zong_matches = re.findall(r"([\u4e00-\u9fa5]{1,2})总", src_str)
        for ch in zong_matches:
            zh_key = f"{ch}总"
            if zh_key not in glossary:
                m = re.search(r"\b([A-ZÀ-Ỹ][a-zà-ỹ]*\s+[Tt]ổng)\b", trans_str)
                if m:
                    glossary[zh_key] = m.group(1).strip()

        # Check for X Thiếu (X少) -> X thiếu / Cậu X
        shao_matches = re.findall(r"([\u4e00-\u9fa5]{1,2})少", src_str)
        for ch in shao_matches:
            zh_key = f"{ch}少"
            if zh_key not in glossary:
                m = re.search(r"\b([A-ZÀ-Ỹ][a-zà-ỹ]*\s+[Tt]hiếu)\b", trans_str)
                if m:
                    glossary[zh_key] = m.group(1).strip()

    return glossary
