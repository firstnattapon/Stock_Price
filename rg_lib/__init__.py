"""Rent Gradient — the layered library behind pages/Rent_Gradient_v2.py.

pages/Rent_Gradient.py is one 6,000-line script and stays untouched as the reference. Its definitions are cut
verbatim into the modules below, and there is a single rule: a module imports only from modules listed *above* it.

    compat  config  geo                  core            constants, optional SciPy, geometry
    rent  vision  roads                  pure engines    numbers in, numbers out (no streamlit, no I/O)
    osm  network  evidence               I/O             OSM / WMS fetch and the disk cache (no streamlit)
    state  bundle                        session         StateManager (st.session_state) and the config/cache bundle
    controllers                          controllers     perform_* handlers, @st.cache_data wrappers, KML, map clicks
    ui_map  ui_sidebar  ui_panels        UI              everything that draws

tests/test_rg_lib_layers.py enforces the rule; tests/test_rg_v2_equivalence.py proves the moved code is the old code.
"""
