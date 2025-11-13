from importlib.resources import files
import json

# Get list of locales
root = files("bouquin") / "locales"
_AVAILABLE = tuple(
    entry.stem
    for entry in root.iterdir()
    if entry.is_file() and entry.suffix == ".json"
)

_DEFAULT = "en"

strings = {}
translations = {}


def load_strings(current_locale: str) -> None:
    global strings, translations
    translations = {}

    # read in the locales json
    for loc in _AVAILABLE:
        data = (root / f"{loc}.json").read_text(encoding="utf-8")
        translations[loc] = json.loads(data)

    if current_locale not in translations:
        current_locale = _DEFAULT

    base = translations[_DEFAULT]
    cur = translations.get(current_locale, {})
    strings = {k: (cur.get(k) or base[k]) for k in base}


def translated(k: str) -> str:
    return strings.get(k, k)


_ = translated
