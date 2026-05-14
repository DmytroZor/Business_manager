from __future__ import annotations

from secrets import randbelow


TRANSLITERATION_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "h",
    "ґ": "g",
    "д": "d",
    "е": "e",
    "є": "ye",
    "ж": "zh",
    "з": "z",
    "и": "y",
    "і": "i",
    "ї": "yi",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ь": "",
    "ю": "yu",
    "я": "ya",
}

UNIT_CODE_MAP = {
    "кг": "KG",
    "kg": "KG",
    "г": "GR",
    "гр": "GR",
    "g": "GR",
    "шт": "PCS",
    "pcs": "PCS",
    "piece": "PCS",
    "уп": "PK",
    "упаковка": "PK",
    "pack": "PK",
}


def _transliterate(text: str | None) -> str:
    if not text:
        return ""
    translated: list[str] = []
    for char in text.lower():
        if char in TRANSLITERATION_MAP:
            translated.append(TRANSLITERATION_MAP[char])
        elif char.isascii() and char.isalnum():
            translated.append(char.lower())
        elif char in {" ", "-", "_", "/"}:
            translated.append(" ")
    return "".join(translated)


def _build_name_code(name: str | None) -> str:
    transliterated = _transliterate(name)
    words = [word for word in transliterated.split() if word]
    if not words:
        return "SEA"
    if len(words) >= 2:
        combined = "".join(word[:2] for word in words[:2])
    else:
        combined = words[0][:4]
    normalized = "".join(char for char in combined.upper() if char.isalnum())
    return (normalized or "SEA")[:4].ljust(4, "X")


def _build_unit_code(unit: str | None) -> str:
    normalized = (unit or "").strip().lower()
    if normalized in UNIT_CODE_MAP:
        return UNIT_CODE_MAP[normalized]
    fallback = "".join(char for char in _transliterate(normalized).upper() if char.isalnum())
    return (fallback or "GEN")[:3].ljust(3, "X")


def generate_sku(*, name: str | None = None, unit: str | None = None) -> str:
    """Generate a readable SKU with a searchable 4-digit suffix."""

    name_code = _build_name_code(name)
    unit_code = _build_unit_code(unit)
    suffix = f"{randbelow(10000):04d}"
    return f"{name_code}-{unit_code}-{suffix}"
