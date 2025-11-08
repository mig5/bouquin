import importlib


def test_main_module_has_main():
    m = importlib.import_module("bouquin.main")
    assert hasattr(m, "main")


def test_dunder_main_imports_main():
    m = importlib.import_module("bouquin.__main__")
    assert hasattr(m, "main")
