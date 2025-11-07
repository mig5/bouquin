import runpy
import types
import sys


def test_dunder_main_executes_without_launching_qt(monkeypatch):
    # Replace bouquin.main with a stub that records invocation and returns immediately
    calls = {"called": False}
    mod = types.SimpleNamespace(main=lambda: calls.__setitem__("called", True))
    monkeypatch.setitem(sys.modules, "bouquin.main", mod)

    # Running the module as __main__ should call mod.main() but not start a Qt loop
    runpy.run_module("bouquin.__main__", run_name="__main__")
    assert calls["called"] is True
