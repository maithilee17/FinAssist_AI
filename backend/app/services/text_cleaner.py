"""Conservative text normalization for extracted financial content."""

import re
import unicodedata

_INVISIBLE_CHARACTERS = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_PROSE_SPACES = re.compile(r"[ \f\v]+")
_EXCESS_BLANK_LINES = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")
_TABLE_SPACING = re.compile(r"\S {2,}\S")


def clean_extracted_text(text: str) -> str:
    """Normalize layout noise without altering financial punctuation or symbols."""

    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ")
    normalized = _INVISIBLE_CHARACTERS.sub("", normalized)

    lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            lines.append("")
            continue
        if "\t" in line or _TABLE_SPACING.search(line):
            lines.append(line.replace("\t", "    ").strip())
        else:
            lines.append(_PROSE_SPACES.sub(" ", line.strip()))

    cleaned = "\n".join(lines)
    cleaned = _EXCESS_BLANK_LINES.sub("\n\n", cleaned)
    return cleaned.strip()
