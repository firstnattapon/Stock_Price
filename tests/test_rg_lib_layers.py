"""rg_lib has one rule: a module imports only from modules listed *above* it (see rg_lib/__init__.py).

The order below is the contract. It keeps the numbers (core, engines, I/O) free of streamlit and ``st.session_state``,
and keeps the dependency graph a DAG, so a layer can be read and tested without the layers above it. Offline, no imports
of the modules themselves — the check reads the source.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "rg_lib"

# lowest layer first
ORDER = ["compat", "config", "geo",                       # core
         "rent", "vision", "roads",                       # pure engines
         "osm", "network", "evidence",                    # I/O
         "state", "bundle",                               # session
         "controllers",
         "ui_map", "ui_sidebar", "ui_panels"]             # UI
NO_STREAMLIT = ORDER[:ORDER.index("state")]               # everything below the session layer


def _tree(module):
    return ast.parse((PKG / f"{module}.py").read_text(encoding="utf-8"))


def test_every_module_is_listed_in_the_order():
    on_disk = {p.stem for p in PKG.glob("*.py")} - {"__init__"}
    assert on_disk == set(ORDER), "add new rg_lib modules to ORDER (and to the table in rg_lib/__init__.py)"


@pytest.mark.parametrize("module", ORDER)
def test_module_imports_only_from_lower_layers(module):
    rank = {name: i for i, name in enumerate(ORDER)}
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            target = node.module
            assert target in rank, f"{module}: imports unknown rg_lib module {target!r}"
            assert rank[target] < rank[module], f"{module} imports {target}, which is not below it"
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert not (node.module or "").startswith(("rg_lib", "pages")), f"{module}: use a relative import below it"
        elif isinstance(node, ast.Import):
            assert not any(a.name.startswith(("rg_lib", "pages")) for a in node.names), module


@pytest.mark.parametrize("module", NO_STREAMLIT)
def test_numbers_and_io_layers_do_not_touch_streamlit(module):
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] in ("streamlit", "streamlit_folium") for a in node.names), module
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in ("streamlit", "streamlit_folium"), module
        elif isinstance(node, ast.Name):
            assert node.id not in ("st", "StateManager"), f"{module}: uses {node.id} at line {node.lineno}"
        elif isinstance(node, ast.Attribute):
            assert node.attr != "session_state", f"{module}: reads session_state at line {node.lineno}"


def test_the_page_imports_the_library_and_nothing_from_pages():
    tree = ast.parse((ROOT / "pages" / "Rent_Gradient_v2.py").read_text(encoding="utf-8"))
    modules = [n.module for n in tree.body if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("rg_lib")]
    assert modules, "the page should import from rg_lib"
    assert all(m.split(".")[1] in ORDER for m in modules)


def test_rg_lib_still_imports_when_scipy_is_missing():
    """pages/Rent_Gradient.py treats SciPy as an optional accelerator (HAS_SCIPY); the modules must keep importing."""
    code = (
        "import importlib, sys\n"
        "sys.modules['scipy'] = None\n"                      # `import scipy...` now raises ImportError
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "compat = importlib.import_module('rg_lib.compat')\n"
        "assert compat.HAS_SCIPY is False and compat.ndi is None and compat.csgraph_dijkstra is None\n"
        f"for name in {ORDER!r}:\n"
        "    importlib.import_module('rg_lib.' + name)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
