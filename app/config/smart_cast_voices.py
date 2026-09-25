"""Smart Cast Voice Configuration for Multi-Speaker short drama dubbing.

Maps ranked speaker roles (lead, support) to high-quality Vietnamese TTS voices.
"""

from __future__ import annotations

SMART_CAST_VOICES: dict[str, dict[str, list[str]] | str] = {
    "male": {
        "lead": [
            "vieneu_thanhnientutin", # Nam chính: Thanh niên tự tin (VieNeu)
            "minhquang",             # Dự phòng: Minh Quang
        ],
        "support": [
            "minhquang",            # Nam phụ 1: Minh Quang (truyền cảm, rõ chữ)
            "manhdung",             # Nam phụ 2: Mạnh Dũng (trưởng thành, nam tính)
            "vietthao3886",         # Nam phụ 3: Việt Thảo (chín chắn)
            "minhkhang",            # Nam phụ 4: Minh Khang (trẻ trung)
            "chieuthanh",           # Nam phụ 5: Chiêu Thành
        ],
    },
    "female": {
        "lead": [
            "vieneu_cogaihoatbat",   # Nữ chính: Cô gái hoạt bát (VieNeu)
            "banmai",                # Dự phòng: Ban Mai
        ],
        "support": [
            "ngochuyen",            # Nữ phụ 1: Ngọc Huyền (tự nhiên, đời thường)
            "banmai",               # Nữ phụ 2: Ban Mai (dịu dàng, nhẹ nhàng)
            "maiphuong",            # Nữ phụ 3: Mai Phương (trong trẻo)
            "ngochuyennew",         # Nữ phụ 4: Ngọc Huyền New (hiện đại)
            "cuc",                  # Nữ phụ 5: Cúc
        ],
    },
    "fallback": "ngochuyen",
}


def get_smart_cast_voice(gender: str, role_rank: int) -> str:
    """Retrieve the designated voice for a given gender and role rank (1 = lead, 2+ = support)."""
    norm_gender = str(gender or "").strip().lower()
    if norm_gender not in ("male", "female"):
        norm_gender = "female"  # safe default

    gender_cfg = SMART_CAST_VOICES.get(norm_gender, {})
    if not isinstance(gender_cfg, dict):
        return str(SMART_CAST_VOICES.get("fallback", "ngochuyen"))

    leads = gender_cfg.get("lead", [])
    supports = gender_cfg.get("support", [])

    if role_rank <= 1 and leads:
        return leads[0]

    support_idx = max(0, role_rank - 2)
    if supports:
        return supports[support_idx % len(supports)]

    if leads:
        return leads[0]

    return str(SMART_CAST_VOICES.get("fallback", "ngochuyen"))
