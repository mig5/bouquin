from importlib.resources import files
import json

_AVAILABLE = ("en", "fr")
_DEFAULT = "en"

strings = {}
translations = {}


def load_strings(current_locale: str | None = None) -> None:
    global strings, translations
    translations = {}

    # read json resources from bouquin/locales/*.json
    root = files("bouquin") / "locales"
    for loc in _AVAILABLE:
        data = (root / f"{loc}.json").read_text(encoding="utf-8")
        translations[loc] = json.loads(data)

    # Load in the system's locale if not passed in somehow from settings
    if not current_locale:
        try:
            from PySide6.QtCore import QLocale

            current_locale = QLocale.system().name().split("_")[0]
        except Exception:
            current_locale = _DEFAULT

    if current_locale not in translations:
        current_locale = _DEFAULT

    base = translations[_DEFAULT]
    cur = translations.get(current_locale, {})
    strings = {k: (cur.get(k) or base[k]) for k in base}


def translated(k: str) -> str:
    return strings.get(k, k)


_ = translated
