from bouquin import strings


def test_load_strings_uses_system_locale_and_fallback():
    # pass a bogus locale to trigger fallback-to-default
    strings.load_strings("zz")
    assert strings._("next")  # key exists in base translations


def test_load_strings_french():
    strings.load_strings("fr")
    assert strings._("today") == "Aujourd'hui"  # translation exists in French


def test_load_strings_italian():
    strings.load_strings("it")
    assert strings._("today") == "Oggi"  # translation exists in Italian
