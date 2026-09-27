"""Pure Yahoo -> NBA player matching. No network access; see sources.py for fetching."""
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# Letters that NFKD does not decompose into base letter + combining mark.
EXTRA_LETTERS = str.maketrans({"ø": "o", "ł": "l", "đ": "d", "æ": "ae", "ß": "ss", "ı": "i"})
DROP_CHARS = str.maketrans("", "", ".'’,")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().translate(EXTRA_LETTERS).translate(DROP_CHARS).replace("-", " ")
    return " ".join(w for w in text.split() if w not in SUFFIXES)
