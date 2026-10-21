"""Core — optional SciPy/numpy accelerator (``HAS_SCIPY``); importing this module never fails.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


# scipy เป็น optional accelerator สำหรับ closeness (fallback เป็น networkx ถ้าไม่มี)
try:
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components as csgraph_components
    from scipy.sparse.csgraph import dijkstra as csgraph_dijkstra
    from scipy import ndimage as ndi
    HAS_SCIPY: bool = True
except Exception:
    HAS_SCIPY = False
    # the other modules import these names from here: keep them importable; the code that needs them is
    # guarded by HAS_SCIPY exactly as in pages/Rent_Gradient.py (numpy stays bound if it imported before SciPy failed)
    csr_matrix = csgraph_components = csgraph_dijkstra = ndi = None
    np = globals().get("np")
