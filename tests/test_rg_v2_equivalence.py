"""pages/Rent_Gradient_v2.py + rg_lib are the code of pages/Rent_Gradient.py, moved — not rewritten.

Every top-level definition of the single-file page must exist exactly once in the new layout with an identical AST
(``ast.dump``: docstrings and string literals included, comments and formatting excluded), except the changes listed in
INTENTIONAL_CHANGES / REMOVED / ADDED below, each with its reason. A new or edited definition therefore fails here until somebody
writes down why, which is what keeps "v2 behaves like v1" a checked statement. Offline and fast (it only reads source).

Delete the comparison tests together with pages/Rent_Gradient.py once the single-file page is retired.
"""
import ast
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OLD_PAGE = ROOT / "pages" / "Rent_Gradient.py"
NEW_PAGE = ROOT / "pages" / "Rent_Gradient_v2.py"
MODULES = sorted(p for p in (ROOT / "rg_lib").glob("*.py") if p.stem != "__init__")

needs_old_page = pytest.mark.skipif(not OLD_PAGE.exists(), reason="pages/Rent_Gradient.py was retired; the comparison is done")

# name -> why the definition differs from pages/Rent_Gradient.py
INTENTIONAL_CHANGES = {
    "_KML_FILE_PATH": "the KML file stays in pages/; the module that defines the path is one directory up (rg_lib/config.py)",
}
# name -> why a definition of the old page no longer exists
REMOVED = {
    "TIMEOUT_GITHUB_LIST": "S-1: never read (the only references are the definition and stale copies that nothing loads)",
}
# name -> why the new layout defines something the old page did not
ADDED = {
    "ROOT": "pages/Rent_Gradient_v2.py puts the repo root on sys.path so that ``import rg_lib`` works",
}


def definitions(path):
    """Top-level name -> ``ast.dump`` of the statement that defines it (functions, classes, constants)."""
    out = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        for name in names:
            assert name not in out, f"{path.name}: {name} is defined twice at top level"
            out[name] = ast.dump(node)
    return out


def new_definitions():
    found, where = {}, {}
    for path in [NEW_PAGE, *MODULES]:
        for name, dump in definitions(path).items():
            assert name not in found, f"{name} is defined in both {where[name]} and {path.name}"
            found[name], where[name] = dump, path.name
    return found


def statements(path, kind):
    return [ast.dump(n) for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, kind)]


@needs_old_page
def test_every_definition_of_the_old_page_is_in_the_new_layout_or_listed_as_removed():
    missing = sorted(set(definitions(OLD_PAGE)) - set(new_definitions()))
    assert missing == sorted(REMOVED), f"not moved: {missing}; listed as REMOVED: {sorted(REMOVED)}"


@needs_old_page
def test_moved_definitions_are_ast_identical_except_the_listed_ones():
    old, new = definitions(OLD_PAGE), new_definitions()
    changed = sorted(name for name in old if name in new and old[name] != new[name])
    assert changed == sorted(INTENTIONAL_CHANGES), (
        f"changed definitions {changed} do not match INTENTIONAL_CHANGES {sorted(INTENTIONAL_CHANGES)}: "
        "list the reason, or move the definition back verbatim")


@needs_old_page
def test_nothing_new_is_defined_except_the_listed_additions():
    added = sorted(set(new_definitions()) - set(definitions(OLD_PAGE)))
    assert added == sorted(ADDED), f"new definitions {added} do not match ADDED {sorted(ADDED)}"


@needs_old_page
def test_the_page_body_is_the_original_main_and_its_guard():
    """``main()`` (compared above as a definition), its ``__main__`` guard and the cache-folder statement are unchanged."""
    assert statements(OLD_PAGE, ast.If) == [d for d in statements(NEW_PAGE, ast.If) if "__main__" in d]
    old_exprs = [d for d in statements(OLD_PAGE, ast.Expr) if "mkdir" in d]
    new_exprs = [d for d in statements(NEW_PAGE, ast.Expr) if "mkdir" in d]
    assert old_exprs == new_exprs and len(old_exprs) == 1


@needs_old_page
def test_the_scipy_block_only_gained_fallback_names():
    old = next(n for n in ast.parse(OLD_PAGE.read_text(encoding="utf-8")).body if isinstance(n, ast.Try))
    new = next(n for n in ast.parse((ROOT / "rg_lib" / "compat.py").read_text(encoding="utf-8")).body if isinstance(n, ast.Try))
    assert [ast.dump(n) for n in new.body] == [ast.dump(n) for n in old.body]                       # the imports
    assert ast.dump(new.handlers[0].type) == ast.dump(old.handlers[0].type)                         # except Exception
    assert ast.dump(new.handlers[0].body[0]) == ast.dump(old.handlers[0].body[0])                  # HAS_SCIPY = False


def test_the_names_the_page_re_exports_are_the_defining_modules_objects():
    spec = importlib.util.spec_from_file_location("rg_v2_equivalence_page", NEW_PAGE)
    page = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = page
    try:
        spec.loader.exec_module(page)
    finally:
        sys.modules.pop(spec.name, None)
    checked = 0
    for node in ast.parse(NEW_PAGE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("rg_lib."):
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert getattr(page, alias.name) is getattr(module, alias.name), alias.name
                checked += 1
    assert checked > 80
