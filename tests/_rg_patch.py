"""Test helper: patch a module-level name of a Rent_Gradient page wherever the page re-exports it.

``pages/Rent_Gradient.py`` is a single script, so ``monkeypatch.setattr(page, "CACHE_DIR", ...)`` reaches every function
that reads ``CACHE_DIR``. ``pages/Rent_Gradient_v2.py`` is a thin page over the ``rg_lib`` package: the functions read the
name from the module that defines them, so the patch must be applied there too. This helper patches the page and every
``rg_lib`` module that holds the very same object (identity, not name), so the same test runs against either page:

    python -m pytest tests                                              # pages/Rent_Gradient.py
    RENT_GRADIENT_PAGE=pages/Rent_Gradient_v2.py python -m pytest tests # pages/Rent_Gradient_v2.py

On the single-file page there is no ``rg_lib`` module in ``sys.modules`` holding the object, so it is a plain ``setattr``.
"""
import sys


def patch_everywhere(monkeypatch, page, name, value):
    original = getattr(page, name)
    holders = [page] + [m for n, m in list(sys.modules.items())
                        if m is not None and n.startswith("rg_lib.") and getattr(m, name, None) is original]
    for target in holders:
        monkeypatch.setattr(target, name, value)
