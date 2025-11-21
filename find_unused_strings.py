#!/usr/bin/env python3

import ast
import json
from pathlib import Path
from typing import Dict, Set


BASE_DIR = Path(__file__).resolve().parent / "bouquin"
LOCALES_DIR = BASE_DIR / "locales"

DEFAULT_LOCALE = "en"


def load_json_keys(locale: str = DEFAULT_LOCALE) -> Set[str]:
    """Load all keys from the given locale JSON file."""
    path = LOCALES_DIR / f"{locale}.json"
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return set(data.keys())


class KeyParamFinder(ast.NodeVisitor):
    """
    First pass:
    For each function/method, figure out which parameters are later passed
    into _(), translated(), or strings._().

    Example: in your _prompt_name, it discovers that title_key and label_key
    are translation-key parameters.
    """

    def __init__(self) -> None:
        # func_name -> {"param_positions": {param: arg_index}, "key_param_positions": set[arg_index]}
        self.func_info: Dict[str, dict] = {}
        self.current_func_name_stack: list[str] = []
        self.current_param_positions_stack: list[Dict[str, int]] = []
        self.current_class_stack: list[str] = []

    # Track when we're inside a class so we can treat "self" specially
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.current_class_stack.append(node.name)
        self.generic_visit(node)
        self.current_class_stack.pop()

    def _enter_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        funcname = node.name
        params = [arg.arg for arg in node.args.args]

        # If we're inside a class and there is at least one param,
        # assume the first one is "self"/"cls" and is implicit at call sites.
        is_method = bool(self.current_class_stack) and len(params) > 0

        param_positions: Dict[str, int] = {}
        for i, name in enumerate(params):
            if is_method and i == 0:
                # skip self/cls; it doesn't correspond to an explicit arg in calls like self.method(...)
                continue
            call_index = i - 1 if is_method else i
            param_positions[name] = call_index

        self.current_func_name_stack.append(funcname)
        self.current_param_positions_stack.append(param_positions)

        self.func_info.setdefault(funcname, {
            "param_positions": param_positions,
            "key_param_positions": set(),
        })
        # If the function name is reused, last definition wins
        self.func_info[funcname]["param_positions"] = param_positions

    def _exit_function(self) -> None:
        self.current_func_name_stack.pop()
        self.current_param_positions_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_function(node)
        self.generic_visit(node)
        self._exit_function()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_function(node)
        self.generic_visit(node)
        self._exit_function()

    def visit_Call(self, node: ast.Call) -> None:
        # Only care about calls *inside* functions
        if not self.current_func_name_stack:
            return self.generic_visit(node)

        func = node.func
        func_name: str | None = None

        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            # e.g. strings._(...)
            func_name = f"{func.value.id}.{func.attr}"

        # Is this a translation call?
        if func_name in {"_", "translated", "strings._"}:
            cur_name = self.current_func_name_stack[-1]
            param_positions = self.current_param_positions_stack[-1]

            # Positional first arg
            if node.args:
                first = node.args[0]
                if isinstance(first, ast.Name):
                    pname = first.id
                    if pname in param_positions:
                        idx = param_positions[pname]
                        self.func_info[cur_name]["key_param_positions"].add(idx)

            # Keyword args, e.g. strings._(key=title_key)
            for kw in node.keywords or []:
                if isinstance(kw.value, ast.Name):
                    pname = kw.value.id
                    if pname in param_positions:
                        idx = param_positions[pname]
                        self.func_info[cur_name]["key_param_positions"].add(idx)

        self.generic_visit(node)


class UsedKeyCollector(ast.NodeVisitor):
    """
    Second pass:
    - Collect string literals passed directly to _()/translated()/strings._()
    - Collect string literals passed into parameters that we know are
      "translation-key parameters" of wrapper functions/methods.
    """

    def __init__(self, func_info: Dict[str, dict]) -> None:
        self.func_info = func_info
        self.used_keys: Set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        def full_name(f: ast.expr) -> str | None:
            if isinstance(f, ast.Name):
                return f.id
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                return f"{f.value.id}.{f.attr}"
            return None

        func_full = full_name(func)

        # 1) Direct translation calls like _("key") or strings._("key")
        if func_full in {"_", "translated", "strings._"}:
            if node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    self.used_keys.add(first.value)
            for kw in node.keywords or []:
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    self.used_keys.add(kw.value.value)

        # 2) Wrapper calls: functions whose params we know are translation-key params
        called_base_name: str | None = None
        if isinstance(func, ast.Name):
            called_base_name = func.id
        elif isinstance(func, ast.Attribute):
            called_base_name = func.attr  # e.g. self._prompt_name -> "_prompt_name"

        if called_base_name in self.func_info:
            info = self.func_info[called_base_name]
            param_positions: Dict[str, int] = info["param_positions"]
            key_positions: Set[int] = info["key_param_positions"]

            # positional args
            for idx, arg in enumerate(node.args):
                if idx in key_positions and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self.used_keys.add(arg.value)

            # keyword args
            for kw in node.keywords or []:
                if kw.arg is None:
                    continue  # **kwargs, ignore
                param_name = kw.arg
                if param_name in param_positions:
                    idx = param_positions[param_name]
                    if idx in key_positions:
                        val = kw.value
                        if isinstance(val, ast.Constant) and isinstance(val.value, str):
                            self.used_keys.add(val.value)

        self.generic_visit(node)


def collect_used_keys() -> Set[str]:
    """Parse all .py files and collect all translation keys used."""
    trees: list[ast.AST] = []

    # Read and parse all Python files in this folder
    for path in BASE_DIR.glob("*.py"):
        # Optionally skip this script itself
        if path.name == Path(__file__).name:
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        trees.append(tree)

    # First pass: find which parameters are translation-key params
    finder = KeyParamFinder()
    for tree in trees:
        finder.visit(tree)

    # Second pass: collect string literals passed to those parameters
    collector = UsedKeyCollector(finder.func_info)
    for tree in trees:
        collector.visit(tree)

    return collector.used_keys


def main() -> None:
    json_keys = load_json_keys()
    used_keys = collect_used_keys()

    unused_keys = sorted(json_keys - used_keys)
    missing_in_json = sorted(used_keys - json_keys)

    print("=== Unused keys in JSON (present in locales but never used in code) ===")
    if unused_keys:
        for k in unused_keys:
            print("  ", k)
    else:
        print("  (none)")

    print("\n=== Keys used in code but missing from JSON ===")
    if missing_in_json:
        for k in missing_in_json:
            print("  ", k)
    else:
        print("  (none)")


if __name__ == "__main__":
    main()

