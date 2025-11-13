from bouquin import strings


def test_load_strings_uses_system_locale_and_fallback():
    # pass a bogus locale to trigger fallback-to-default
    strings.load_strings("zz")
    assert strings._("next")  # key exists in base translations
