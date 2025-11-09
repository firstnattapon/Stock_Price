import streamlit as st
import pandas as pd
import numpy as np
import math
import json
import requests
import datetime
import altair as alt
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------
# 1. Constants and Schema
# ---------------------------------------------------------------------
APP_SCHEMA_VERSION = '1.2.0'

# Parameter Limits
X0_MIN, X0_MAX = 0.1, 50.0
DELTA_MIN, DELTA_MAX = 0.01, 2.0
C_MIN, C_MAX = 100, 10000
B_MIN, B_MAX = -5000, 5000
X_RANGE_MIN, X_RANGE_MAX = 0.1, 50.0
CONTRACTS_MAX = 10000
PREMIUM_MAX = 1000
PRICE_MIN, PRICE_MAX = 0.0, 50.0
SHARES_MIN, SHARES_MAX = 0, 10_000_000

# ---------------------------------------------------------------------
# 2. Initial State
# ---------------------------------------------------------------------

# This is the Python equivalent of the 'initialState' object
initial_state = {
    'params': {
        'y1_y5': {'x0_1': 7.0, 'constant1': 1500, 'b1': 0, 'b1Base': 0, 'autoRolloverB1': False, 'b1_add_option': 0},
        'y2_y4': {'x0_2': 10.0, 'constant2': 1500, 'b2': 0, 'b2Base': 0, 'autoRolloverB2': False, 'b2_add_option': 0},
        'y6_y7_ref': {'anchorY6': 7.0, 'refConst': 1500},
        'y8_call': {'callContracts': 100, 'premiumCall': 2.6},
        'y9_put': {'putContracts': 100, 'premiumPut': 2.6},
        'y10_long': {'longEntryPrice': 7.0, 'longShares': 100},
        'y11_short': {'shortEntryPrice': 10.0, 'shortShares': 100},
        'global': {'delta1': 0.2, 'delta2': 1.0, 'includePremium': True, 'biasMode': 'real'},
        'chart': {'x1Range': [3.0, 17.0]},
    },
    'toggles': {
        'showY1': True,
        'showY2': False,
        'showY3': False,
        'showY4': False,
        'showY5': False,
        'showY6': True,
        'showY7': True,
        'showY8': True,
        'showY9': True,
        'showY10': False,
        'showY11': False,
    }
}

# Function to initialize session_state
def initialize_state():
    if 'params' not in st.session_state:
        st.session_state.update(initial_state)

# ---------------------------------------------------------------------
# 3. Math Helpers (Ported from JS)
# ---------------------------------------------------------------------

def H(z: float) -> int:
    """Heaviside step function"""
    return 1 if z >= 0 else 0

def safe_log(arg: float) -> float | None:
    """Safe logarithm, returns None for non-positive input"""
    if arg > 0:
        try:
            return math.log(arg)
        except (ValueError, TypeError):
            return None
    return None

def piecewise_delta(x: float, thr: float, below: float, above: float) -> float:
    return below + H(x - thr) * (above - below)

def scale_or_null(v: float | None, s: float) -> float | None:
    return None if v is None else v * s

def add_bias_or_null(v: float | None, b: float) -> float | None:
    return None if v is None else v + b

def sum_or_null(values: list[float | None], actives: list[bool]) -> float | None:
    total = 0.0
    for i, v in enumerate(values):
        if actives[i]:
            if v is None:
                return None  # If any active value is null, result is null
            total += v
    return total

def subtract_or_null(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b

def clamp(x, lo, hi):
    return max(lo, min(x, hi))

def coerce_num(v, default):
    try:
        num = float(v)
        if math.isfinite(num):
            return num
    except (ValueError, TypeError):
        pass
    return default

def coerce_bool(v, default):
    return v if isinstance(v, bool) else default

def is_tuple2(v):
    return isinstance(v, (list, tuple)) and len(v) == 2 and \
           isinstance(v[0], (int, float)) and isinstance(v[1], (int, float))


# ---------------------------------------------------------------------
# 4. State Callbacks (Ported from appReducer and useEffect)
# ---------------------------------------------------------------------

def calculate_auto_rollover():
    """Ported from CALCULATE_AUTO_ROLLOVER and useEffect"""
    s = st.session_state.params
    
    # Logic for auto-rollover b1
    if s['y1_y5']['autoRolloverB1'] and s['y1_y5']['x0_1'] > 0 and s['y2_y4']['x0_2'] > 0:
        try:
            ln_term = math.log(s['y2_y4']['x0_2'] / s['y1_y5']['x0_1'])
            calc_b1 = s['y1_y5']['b1Base'] + (s['y6_y7_ref']['refConst'] - s['y1_y5']['constant1']) * ln_term
            if math.isfinite(calc_b1):
                s['y1_y5']['b1'] = calc_b1
        except Exception:
            pass # Keep previous value if math error

    # Logic for auto-rollover b2
    if s['y2_y4']['autoRolloverB2'] and s['y1_y5']['x0_1'] > 0 and s['y2_y4']['x0_2'] > 0:
        try:
            ln_term = math.log(s['y1_y5']['x0_1'] / s['y2_y4']['x0_2'])
            calc_b2 = s['y2_y4']['b2Base'] + (s['y6_y7_ref']['refConst'] - s['y2_y4']['constant2']) * ln_term
            if math.isfinite(calc_b2):
                s['y2_y4']['b2'] = calc_b2
        except Exception:
            pass # Keep previous value if math error

def sync_x0_1():
    """Ported from useEffect [y1_y5.x0_1]"""
    # Sync long entry price
    st.session_state.params['y10_long']['longEntryPrice'] = st.session_state.params['y1_y5']['x0_1']
    # Trigger auto-rollover calculation
    calculate_auto_rollover()

def sync_x0_2():
    """Ported from useEffect [y2_y4.x0_2]"""
    # Sync short entry price
    st.session_state.params['y11_short']['shortEntryPrice'] = st.session_state.params['y2_y4']['x0_2']
    # Trigger auto-rollover calculation
    calculate_auto_rollover()

def toggle_autoroll_b1(new_value):
    """Ported from SET_PARAM logic for autoRolloverB1"""
    st.session_state.params['y1_y5']['autoRolloverB1'] = new_value
    if new_value:
        # Toggling ON: Set base to current b1
        st.session_state.params['y1_y5']['b1Base'] = st.session_state.params['y1_y5']['b1']
    calculate_auto_rollover()

def toggle_autoroll_b2(new_value):
    """Ported from SET_PARAM logic for autoRolloverB2"""
    st.session_state.params['y2_y4']['autoRolloverB2'] = new_value
    if new_value:
        # Toggling ON: Set base to current b2
        st.session_state.params['y2_y4']['b2Base'] = st.session_state.params['y2_y4']['b2']
    calculate_auto_rollover()

def set_manual_b1(new_value):
    """Ported from SET_PARAM logic for b1"""
    st.session_state.params['y1_y5']['b1'] = new_value
    if not st.session_state.params['y1_y5']['autoRolloverB1']:
        # Manual b1 change: Update base
        st.session_state.params['y1_y5']['b1Base'] = new_value

def set_manual_b2(new_value):
    """Ported from SET_PARAM logic for b2"""
    st.session_state.params['y2_y4']['b2'] = new_value
    if not st.session_state.params['y2_y4']['autoRolloverB2']:
        # Manual b2 change: Update base
        st.session_state.params['y2_y4']['b2Base'] = new_value

# --- Callbacks for buttons ---
def set_all_toggles(value: bool):
    """Ported from SET_ALL_TOGGLES"""
    for key in st.session_state.toggles:
        st.session_state.toggles[key] = value

def set_net_only():
    """Ported from SET_NET_ONLY"""
    set_all_toggles(False)
    st.session_state.toggles['showY3'] = True

def set_bias(b1: float, b2: float):
    """Ported from SET_BIAS"""
    s = st.session_state.params
    s['y1_y5']['b1'] = b1
    s['y1_y5']['b1Base'] = b1
    s['y1_y5']['b1_add_option'] = b1
    s['y2_y4']['b2'] = b2
    s['y2_y4']['b2Base'] = b2
    s['y2_y4']['b2_add_option'] = b2

def reset_chart_range():
    """Ported from RESET_CHART_RANGE"""
    st.session_state.params['chart']['x1Range'] = [3.0, 17.0]


# ---------------------------------------------------------------------
# 5. Config Import/Export & GitHub (Ported)
# ---------------------------------------------------------------------

def build_config() -> dict:
    """Builds the exportable config dict from session_state"""
    s = st.session_state
    return {
        'version': APP_SCHEMA_VERSION,
        'exported_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'params': {
            'x0_1': s.params['y1_y5']['x0_1'],
            'constant1': s.params['y1_y5']['constant1'],
            'b1': s.params['y1_y5']['b1'],
            'b1Base': s.params['y1_y5']['b1Base'],
            'autoRolloverB1': s.params['y1_y5']['autoRolloverB1'],
            'b1_add_option': s.params['y1_y5']['b1_add_option'],
            'x0_2': s.params['y2_y4']['x0_2'],
            'constant2': s.params['y2_y4']['constant2'],
            'b2': s.params['y2_y4']['b2'],
            'b2Base': s.params['y2_y4']['b2Base'],
            'autoRolloverB2': s.params['y2_y4']['autoRolloverB2'],
            'b2_add_option': s.params['y2_y4']['b2_add_option'],
            'anchorY6': s.params['y6_y7_ref']['anchorY6'],
            'refConst': s.params['y6_y7_ref']['refConst'],
            'callContracts': s.params['y8_call']['callContracts'],
            'premiumCall': s.params['y8_call']['premiumCall'],
            'putContracts': s.params['y9_put']['putContracts'],
            'premiumPut': s.params['y9_put']['premiumPut'],
            'longEntryPrice': s.params['y10_long']['longEntryPrice'],
            'longShares': s.params['y10_long']['longShares'],
            'shortEntryPrice': s.params['y11_short']['shortEntryPrice'],
            'shortShares': s.params['y11_short']['shortShares'],
            'delta1': s.params['global']['delta1'],
            'delta2': s.params['global']['delta2'],
            'includePremium': s.params['global']['includePremium'],
            'biasMode': s.params['global']['biasMode'],
            'x1Range': s.params['chart']['x1Range'],
        },
        'toggles': s.toggles,
    }

def apply_config(raw: dict):
    """Ported from APPLY_CONFIG and applyConfig (JS)"""
    s = st.session_state
    p = raw.get('params', {})
    t = raw.get('toggles', {})
    
    # Coerce and clamp chart range
    nx1Range = s.params['chart']['x1Range']
    if is_tuple2(p.get('x1Range')):
        a = clamp(coerce_num(p['x1Range'][0], s.params['chart']['x1Range'][0]), X_RANGE_MIN, X_RANGE_MAX)
        b = clamp(coerce_num(p['x1Range'][1], s.params['chart']['x1Range'][1]), X_RANGE_MIN, X_RANGE_MAX)
        lo, hi = min(a, b), max(a, b)
        nx1Range = [max(lo, X_RANGE_MIN), max(hi, lo + 0.1)]

    # Apply params
    s.params['y1_y5']['x0_1'] = clamp(coerce_num(p.get('x0_1'), s.params['y1_y5']['x0_1']), X0_MIN, X0_MAX)
    s.params['y2_y4']['x0_2'] = clamp(coerce_num(p.get('x0_2'), s.params['y2_y4']['x0_2']), X0_MIN, X0_MAX)
    s.params['y6_y7_ref']['anchorY6'] = clamp(coerce_num(p.get('anchorY6'), s.params['y6_y7_ref']['anchorY6']), X0_MIN, X0_MAX)
    s.params['chart']['x1Range'] = nx1Range
    s.params['global']['delta1'] = clamp(coerce_num(p.get('delta1'), s.params['global']['delta1']), DELTA_MIN, DELTA_MAX)
    s.params['global']['delta2'] = clamp(coerce_num(p.get('delta2'), s.params['global']['delta2']), DELTA_MIN, DELTA_MAX)
    s.params['y1_y5']['constant1'] = clamp(coerce_num(p.get('constant1'), s.params['y1_y5']['constant1']), C_MIN, C_MAX)
    s.params['y2_y4']['constant2'] = clamp(coerce_num(p.get('constant2'), s.params['y2_y4']['constant2']), C_MIN, C_MAX)
    s.params['y6_y7_ref']['refConst'] = clamp(coerce_num(p.get('refConst'), s.params['y6_y7_ref']['refConst']), C_MIN, C_MAX)
    s.params['y1_y5']['b1'] = clamp(coerce_num(p.get('b1'), s.params['y1_y5']['b1']), B_MIN, B_MAX)
    s.params['y2_y4']['b2'] = clamp(coerce_num(p.get('b2'), s.params['y2_y4']['b2']), B_MIN, B_MAX)
    s.params['y1_y5']['b1Base'] = coerce_num(p.get('b1Base'), s.params['y1_y5']['b1Base'])
    s.params['y2_y4']['b2Base'] = coerce_num(p.get('b2Base'), s.params['y2_y4']['b2Base'])
    s.params['y1_y5']['b1_add_option'] = clamp(coerce_num(p.get('b1_add_option'), s.params['y1_y5']['b1_add_option']), B_MIN, B_MAX)
    s.params['y2_y4']['b2_add_option'] = clamp(coerce_num(p.get('b2_add_option'), s.params['y2_y4']['b2_add_option']), B_MIN, B_MAX)
    s.params['global']['biasMode'] = p.get('biasMode', s.params['global']['biasMode']) if p.get('biasMode') in ['real', 'add_option'] else s.params['global']['biasMode']
    s.params['y1_y5']['autoRolloverB1'] = coerce_bool(p.get('autoRolloverB1'), s.params['y1_y5']['autoRolloverB1'])
    s.params['y2_y4']['autoRolloverB2'] = coerce_bool(p.get('autoRolloverB2'), s.params['y2_y4']['autoRolloverB2'])
    s.params['global']['includePremium'] = coerce_bool(p.get('includePremium'), s.params['global']['includePremium'])
    s.params['y8_call']['callContracts'] = clamp(round(coerce_num(p.get('callContracts'), s.params['y8_call']['callContracts'])), 0, CONTRACTS_MAX)
    s.params['y9_put']['putContracts'] = clamp(round(coerce_num(p.get('putContracts'), s.params['y9_put']['putContracts'])), 0, CONTRACTS_MAX)
    s.params['y8_call']['premiumCall'] = clamp(coerce_num(p.get('premiumCall'), s.params['y8_call']['premiumCall']), 0, PREMIUM_MAX)
    s.params['y9_put']['premiumPut'] = clamp(coerce_num(p.get('premiumPut'), s.params['y9_put']['premiumPut']), 0, PREMIUM_MAX)
    s.params['y10_long']['longEntryPrice'] = clamp(coerce_num(p.get('longEntryPrice'), s.params['y10_long']['longEntryPrice']), PRICE_MIN, PRICE_MAX)
    s.params['y10_long']['longShares'] = clamp(round(coerce_num(p.get('longShares'), s.params['y10_long']['longShares'])), SHARES_MIN, SHARES_MAX)
    s.params['y11_short']['shortEntryPrice'] = clamp(coerce_num(p.get('shortEntryPrice'), s.params['y11_short']['shortEntryPrice']), PRICE_MIN, PRICE_MAX)
    s.params['y11_short']['shortShares'] = clamp(round(coerce_num(p.get('shortShares'), s.params['y11_short']['shortShares'])), SHARES_MIN, SHARES_MAX)
    
    # Apply toggles
    for key in s.toggles:
        s.toggles[key] = coerce_bool(t.get(key), s.toggles[key])

    st.toast("นำเข้า config สำเร็จ", icon="✅")


def handle_import_file(uploaded_file):
    if uploaded_file is not None:
        try:
            raw_data = json.load(uploaded_file)
            apply_config(raw_data)
        except Exception as e:
            st.error(f"นำเข้าไม่สำเร็จ: ไฟล์ไม่ใช่ JSON ตามรูปแบบ ({e})")

# --- GitHub Helpers (Ported) ---
def normalize_ref(ref: str) -> str:
    return ref.replace('refs/heads/', '')

def parse_github_input(input_str: str) -> dict | None:
    try:
        if not input_str.startswith(('http://', 'https://')):
            at_parts = input_str.split('@')
            left, ref = at_parts[0], normalize_ref(at_parts[1]) if len(at_parts) > 1 else 'master'
            parts = [p for p in left.split('/') if p]
            if len(parts) >= 2:
                path = '/'.join(parts[2:])
                return {'owner': parts[0], 'repo': parts[1], 'ref': ref, 'path': path, 'isFileGuess': path.endswith('.json')}
            return None

        u = urlparse(input_str)
        seg = [s for s in u.path.split('/') if s]
        
        if u.hostname == 'raw.githubusercontent.com' and len(seg) >= 4:
            path = '/'.join(seg[3:])
            return {'owner': seg[0], 'repo': seg[1], 'ref': normalize_ref(seg[2]), 'path': path, 'isFileGuess': path.endswith('.json')}
        
        if u.hostname == 'api.github.com':
            try:
                i = seg.index('repos')
                j = seg.index('contents')
                if i >= 0 and j > i and len(seg) > j + 1:
                    owner, repo = seg[i + 1], seg[i + 2]
                    path = '/'.join(seg[j + 1:])
                    ref = normalize_ref(parse_qs(u.query).get('ref', ['master'])[0])
                    return {'owner': owner, 'repo': repo, 'ref': ref, 'path': path, 'isFileGuess': path.endswith('.json')}
            except ValueError:
                pass
        
        if u.hostname == 'github.com':
            try:
                i = seg.index('blob') # Check for blob URLs
                if i >= 0 and len(seg) > i + 2:
                    owner, repo, ref = seg[0], seg[1], seg[i + 1]
                    path = '/'.join(seg[i + 2:])
                    raw_url = f"https.raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
                    return parse_github_input(raw_url)
            except ValueError:
                pass
            try:
                i = seg.index('tree') # Check for tree URLs
                if i >= 0 and len(seg) > i + 1:
                    path = '/'.join(seg[i + 2:])
                    return {'owner': seg[0], 'repo': seg[1], 'ref': normalize_ref(seg[i + 1]), 'path': path, 'isFileGuess': False}
            except ValueError:
                pass
            if len(seg) >= 2: # Guess repo
                return {'owner': seg[0], 'repo': seg[1], 'ref': 'master', 'path': '', 'isFileGuess': False}

        return None
    except Exception:
        return None

def build_api_url(g: dict) -> str:
    return f"https://api.github.com/repos/{g['owner']}/{g['repo']}/contents/{g.get('path', '')}?ref={g['ref']}"

def build_raw_url(g: dict) -> str:
    return f"https.raw.githubusercontent.com/{g['owner']}/{g['repo']}/{g['ref']}/{g['path']}"

@st.cache_data(ttl=60) # Cache directory listing for 1 minute
def list_github_jsons(g: dict) -> list[dict]:
    api_url = build_api_url(g)
    try:
        r = requests.get(api_url, headers={'Accept': 'application/vnd.github+json'})
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise ValueError('Not a directory listing')
        
        results = []
        for item in data:
            if item.get('type') == 'file' and item.get('name', '').endswith('.json'):
                raw_url = item.get('download_url', 
                           f"https.raw.githubusercontent.com/{g['owner']}/{g['repo']}/{g['ref']}/{g.get('path', '')}/{item['name']}".replace('//', '/'))
                results.append({'name': item['name'], 'rawUrl': raw_url})
        return results
    except Exception as e:
        st.error(f"GitHub API Error: {e}")
        return []

@st.cache_data(ttl=60) # Cache file content for 1 minute
def load_github_json(raw_url: str) -> dict:
    try:
        r = requests.get(raw_url)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"GitHub Fetch Error: {e}")
        return {}


# ---------------------------------------------------------------------
# 6. Core Data Generation (Ported from generateComparisonData)
# ---------------------------------------------------------------------

@st.cache_data
def generate_comparison_data(params, toggles, effective_b1, effective_b2):
    """
    Core calculation function.
    Reads state, returns a wide DataFrame.
    Wrapped with @st.cache_data for performance.
    """
    p = params
    t = toggles
    x_min, x_max = p['chart']['x1Range']
    steps = 100
    
    # Create x1 array
    x1_values = np.linspace(x_min, x_max, steps + 1)
    
    # Prepare data storage
    data = {'x1': x1_values}

    # Vectorize calculations using NumPy where possible
    x0_1 = p['y1_y5']['x0_1']
    x0_2 = p['y2_y4']['x0_2']
    anchorY6 = p['y6_y7_ref']['anchorY6']
    
    with np.errstate(divide='ignore', invalid='ignore'): # Ignore log(0) warnings
        ln1_values = np.log(x1_values / x0_1)
        ln2_values = np.log(2 - x1_values / x0_2)
        ln6_values = np.log(x1_values / anchorY6)
        ln7_values = np.log(2 - x1_values / anchorY6)
    
    # Replace -inf/nan with None (via np.nan which pandas handles)
    ln1_values[~np.isfinite(ln1_values)] = np.nan
    ln2_values[~np.isfinite(ln2_values)] = np.nan
    ln6_values[~np.isfinite(ln6_values)] = np.nan
    ln7_values[~np.isfinite(ln7_values)] = np.nan

    # Calculate y1, y2, y6, y7 raw
    y1_raw = ln1_values * p['y1_y5']['constant1']
    y2_raw = ln2_values * p['y2_y4']['constant2']
    y6_raw = ln6_values * p['y6_y7_ref']['refConst']
    y7_raw = ln7_values * p['y6_y7_ref']['refConst']

    # --- Deltas and Biases ---
    delta1, delta2 = p['global']['delta1'], p['global']['delta2']
    
    data['y1_delta1'] = y1_raw * delta1 + effective_b1
    data['y1_delta2'] = y1_raw * delta2 + effective_b1
    data['y2_delta1'] = y2_raw * delta1 + effective_b2
    data['y2_delta2'] = y2_raw * delta2 + effective_b2

    # --- Piecewise (y4, y5) ---
    d_y4 = np.where(x1_values >= x0_2, delta1, delta2)
    data['y4_piece'] = y2_raw * d_y4 + effective_b2
    
    d_y5 = np.where(x1_values >= x0_1, delta2, delta1)
    data['y5_piece'] = y1_raw * d_y5 + effective_b1

    # --- Reference (y6, y7) ---
    data['y6_ref_delta1'] = y6_raw * delta1
    data['y6_ref_delta2'] = y6_raw * delta2
    data['y7_ref_delta1'] = y7_raw * delta1
    data['y7_ref_delta2'] = y7_raw * delta2

    # --- Intrinsic & P/L (y8, y9, y10, y11) ---
    prem_call_cost = (p['y8_call']['callContracts'] * p['y8_call']['premiumCall']) if p['global']['includePremium'] else 0
    prem_put_cost = (p['y9_put']['putContracts'] * p['y9_put']['premiumPut']) if p['global']['includePremium'] else 0
    
    data['y8_call_intrinsic'] = np.maximum(0, x1_values - x0_1) * p['y8_call']['callContracts'] - prem_call_cost
    data['y9_put_intrinsic'] = np.maximum(0, x0_2 - x1_values) * p['y9_put']['putContracts'] - prem_put_cost
    
    data['y10_long_pl'] = (x1_values - p['y10_long']['longEntryPrice']) * p['y10_long']['longShares']
    data['y11_short_pl'] = (p['y11_short']['shortEntryPrice'] - x1_values) * p['y11_short']['shortShares']

    # --- Net (y3) ---
    # Convert np.nan back to None for sum_or_null logic if needed, or handle with np
    df = pd.DataFrame(data)
    
    actives_d1 = [t['showY1'], t['showY2'], t['showY4'], t['showY5'], t['showY8'], t['showY9'], t['showY10'], t['showY11']]
    cols_d1 = ['y1_delta1', 'y2_delta1', 'y4_piece', 'y5_piece', 'y8_call_intrinsic', 'y9_put_intrinsic', 'y10_long_pl', 'y11_short_pl']
    active_cols_d1 = [col for i, col in enumerate(cols_d1) if actives_d1[i]]
    
    actives_d2 = [t['showY1'], t['showY2'], t['showY4'], t['showY5'], t['showY8'], t['showY9'], t['showY10'], t['showY11']]
    cols_d2 = ['y1_delta2', 'y2_delta2', 'y4_piece', 'y5_piece', 'y8_call_intrinsic', 'y9_put_intrinsic', 'y10_long_pl', 'y11_short_pl']
    active_cols_d2 = [col for i, col in enumerate(cols_d2) if actives_d2[i]]

    # Summing active columns. .sum() handles np.nan by default (treats as 0 unless all are nan)
    # We must check if any active col has nan, if so, the sum is nan
    df['y3_delta1'] = df[active_cols_d1].sum(axis=1)
    df.loc[df[active_cols_d1].isnull().any(axis=1), 'y3_delta1'] = np.nan
    
    df['y3_delta2'] = df[active_cols_d2].sum(axis=1)
    df.loc[df[active_cols_d2].isnull().any(axis=1), 'y3_delta2'] = np.nan

    # --- Overlay ---
    df['y_overlay_d2'] = df['y3_delta2'] - df['y6_ref_delta2']

    # Replace all np.nan with None so Altair handles gaps correctly
    return df.where(pd.notna(df), None)

@st.cache_data
def find_zero_crossings(comparison_data: pd.DataFrame) -> list[float]:
    """Finds x-intercepts for y3_delta2 using linear interpolation"""
    xs = []
    y_values = comparison_data['y3_delta2'].values
    x_values = comparison_data['x1'].values
    
    for i in range(1, len(y_values)):
        a = y_values[i-1]
        b = y_values[i]
        
        if a is None or b is None or not math.isfinite(a) or not math.isfinite(b):
            continue
        
        if a == 0:
            xs.append(x_values[i-1])
            continue
        if b == 0:
            xs.append(x_values[i])
            continue
        
        # Sign change
        if (a < 0 and b > 0) or (a > 0 and b < 0):
            # Linear interpolation: x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            # Here y = 0
            try:
                x0 = x_values[i-1] + (0 - a) * (x_values[i] - x_values[i-1]) / (b - a)
                if math.isfinite(x0):
                    xs.append(x0)
            except ZeroDivisionError:
                pass
                
    return xs


# ---------------------------------------------------------------------
# 7. Charting Function (Altair)
# ---------------------------------------------------------------------

def plot_chart(df: pd.DataFrame, lines_config: dict, dots_config: list, y_domain_auto: bool = False):
    """
    Generates an Altair chart based on the provided data and configs.
    
    :param df: Wide DataFrame with data
    :param lines_config: Dict of {'col_name': {'color': '#hex', 'dash': [int, int] | None, 'width': int, 'name': 'str'}}
    :param dots_config: List of {'x': float, 'label': 'str', 'color': '#hex'}
    :param y_domain_auto: If True, use Altair's auto domain. If False, ensure 0 is included.
    """
    
    # Filter only lines we need to plot
    lines_to_plot = list(lines_config.keys())
    if not lines_to_plot:
        st.warning("ไม่มีเส้นกราฟให้แสดงผล (กรุณาเปิด Toggle ที่ Sidebar)")
        return

    # Melt data from wide to long format
    df_melted = df.melt('x1', 
                        value_vars=[col for col in lines_to_plot if col in df.columns], 
                        var_name='line_name', 
                        value_name='y_value')
    
    # Map display names, colors, etc. from config
    df_melted['color'] = df_melted['line_name'].map(lambda x: lines_config[x]['color'])
    df_melted['dash'] = df_melted['line_name'].map(lambda x: lines_config[x].get('dash', None))
    df_melted['width'] = df_melted['line_name'].map(lambda x: lines_config[x].get('width', 2))
    df_melted['name'] = df_melted['line_name'].map(lambda x: lines_config[x]['name'])

    # Y-axis domain
    if y_domain_auto:
        y_scale = alt.Y('y_value', title='y', axis=alt.Axis(format=',.0f'))
    else:
        # Calculate domain, ensuring 0 is included
        min_y = df_melted['y_value'].min()
        max_y = df_melted['y_value'].max()
        if pd.isna(min_y): min_y = -1
        if pd.isna(max_y): max_y = 1
        domain = [min(min_y, 0), max(max_y, 0)]
        y_scale = alt.Y('y_value', title='y', scale=alt.Scale(domain=domain, clamp=True), axis=alt.Axis(format=',.0f'))

    # Base chart
    base = alt.Chart(df_melted).encode(
        x=alt.X('x1', title='x₁', scale=alt.Scale(domain=st.session_state.params['chart']['x1Range'], clamp=True)),
        y=y_scale,
        color=alt.Color('name', title='Legend', scale=alt.Scale(
            domain=[v['name'] for v in lines_config.values()],
            range=[v['color'] for v in lines_config.values()]
        )),
        strokeDash=alt.StrokeDash('dash', legend=None),
        strokeWidth=alt.StrokeWidth('width', legend=None),
        tooltip=[
            alt.Tooltip('x1', format=',.2f'),
            alt.Tooltip('name', title='Line'),
            alt.Tooltip('y_value', title='Value', format=',.0f')
        ]
    ).properties(
        height=450
    )
    
    # Create line layer
    lines = base.mark_line(interpolate='monotone').transform_filter(
        alt.datum.y_value != None # Handle gaps
    )
    
    # Create ReferenceDot layer
    chart_layers = [lines]
    if dots_config:
        dots_df = pd.DataFrame(dots_config)
        # Add a 'y' column with value 0 for plotting on x-axis
        dots_df['y'] = 0 
        
        dots_base = alt.Chart(dots_df).encode(
            x='x',
            y='y',
            color=alt.Color('color', scale=None),
            tooltip=[
                alt.Tooltip('x', format=',.2f'),
                'label'
            ]
        )
        
        dots = dots_base.mark_point(size=100, filled=True, opacity=0.8, stroke='color', strokeWidth=2)
        text = dots_base.mark_text(align='center', dy=-10).encode(text='label')
        
        chart_layers.append(dots)
        chart_layers.append(text)

    # Combine layers and make interactive
    final_chart = alt.layer(*chart_layers).interactive()
    
    st.altair_chart(final_chart, use_container_width=True)


# ---------------------------------------------------------------------
# 8. UI Helpers (Replicating InputSlider)
# ---------------------------------------------------------------------

def ui_input_slider(label: str, group: str, key: str, min_val: float, max_val: float, step: float, help: str = None, on_change_callback = None, format:str = "%.2f"):
    """
    Custom Streamlit widget to replicate the JS InputSlider.
    Uses st.columns to place a number_input and slider together.
    State is managed via session_state keys and callbacks.
    """
    
    # Function to sync state from widget to session_state
    def _update_state():
        widget_key = f"widget_{group}_{key}"
        if widget_key in st.session_state:
            new_val = st.session_state[widget_key]
            # Clamp value just in case number_input bypasses slider limits
            new_val = clamp(new_val, min_val, max_val)
            st.session_state.params[group][key] = new_val
            
            # Run any extra callbacks (like for x0_1 or auto-rollover)
            if on_change_callback:
                on_change_callback(new_val)

    # Get current value from session_state
    current_val = st.session_state.params[group][key]

    # Layout: Label + Number Input
    cols = st.columns([0.7, 0.3])
    with cols[0]:
        st.text(label)
    with cols[1]:
        st.number_input(
            label,
            min_value=min_val,
            max_value=max_val,
            value=current_val,
            step=step,
            key=f"widget_{group}_{key}", # This key triggers the callback
            on_change=_update_state,
            label_visibility="collapsed",
            format=format
        )
    
    # Slider below
    st.slider(
        label,
        min_value=min_val,
        max_value=max_val,
        value=current_val,
        step=step,
        key=f"widget_{group}_{key}", # Use the SAME key
        on_change=_update_state,
        label_visibility="collapsed",
        help=help,
        format=format
    )

def ui_param_slider(label, group, key, min_val, max_val, step, format="%.2f", on_change=None, help=None):
    """A simpler slider that just updates the state"""
    
    def _update():
        new_val = st.session_state[f"widget_{group}_{key}"]
        st.session_state.params[group][key] = new_val
        if on_change:
            on_change() # e.g., calculate_auto_rollover
            
    st.slider(
        label,
        min_value=min_val,
        max_value=max_val,
        value=st.session_state.params[group][key],
        step=step,
        key=f"widget_{group}_{key}",
        on_change=_update,
        format=format,
        help=help
    )

def ui_param_number_input(label, group, key, min_val, max_val, step, format="%.2f", on_change=None, help=None, is_int=False):
    """A number input that just updates the state"""
    
    def _update():
        new_val = st.session_state[f"widget_{group}_{key}"]
        if is_int: new_val = int(new_val)
        st.session_state.params[group][key] = new_val
        if on_change:
            on_change(new_val) # e.g., set_manual_b1
            
    st.number_input(
        label,
        min_value=min_val,
        max_value=max_val,
        value=st.session_state.params[group][key],
        step=step,
        key=f"widget_{group}_{key}",
        on_change=_update,
        format=format,
        help=help
    )

def ui_param_toggle(label, group, key, on_change=None):
    """A toggle that just updates the state"""
    
    def _update():
        new_val = st.session_state[f"widget_{group}_{key}"]
        st.session_state.params[group][key] = new_val
        if on_change:
            on_change(new_val) # e.g., toggle_autoroll_b1
            
    st.toggle(
        label,
        value=st.session_state.params[group][key],
        key=f"widget_{group}_{key}",
        on_change=_update
    )


# ---------------------------------------------------------------------
# 9. Main Application
# ---------------------------------------------------------------------
def run_app():
    
    # --- Page Config ---
    st.set_page_config(
        page_title="Logarithmic Graph Comparator",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # --- Initialize State ---
    initialize_state()
    
    # --- Main Title ---
    st.title("เปรียบเทียบกราฟ (รองรับ β): + Intrinsic + P/L Long–Short")

    # --- Sidebar (All Controls) ---
    with st.sidebar:
        st.header("⚙️ แผงควบคุม")
        
        # --- Import / Export ---
        with st.expander("Import / Export Config"):
            uploaded_file = st.file_uploader(
                "Import .json", 
                type="json",
                on_change=handle_import_file,
                args=(st.session_state.get('file_uploader_key'),) # Hack to use on_change
            )
            
            # Re-assign key to clear widget after processing
            if uploaded_file: st.session_state.file_uploader_key = str(np.random.rand())
            
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"log_graph_config_{ts}.json"
            
            st.download_button(
                label="Export .json",
                data=json.dumps(build_config(), indent=2),
                file_name=fname,
                mime="application/json"
            )
            st.caption(f"schema v{APP_SCHEMA_VERSION}")

        # --- GitHub Loader ---
        with st.expander("Load from GitHub"):
            gh_input = st.text_input("Owner/Repo/Path@Branch หรือ URL", value="firstnattapon/streamlit-example-1/exotic_payoff@master", key="gh_input")
            
            gh_parsed = parse_github_input(st.session_state.gh_input)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Load JSON File", use_container_width=True):
                    if gh_parsed and gh_parsed['isFileGuess']:
                        raw_url = build_raw_url(gh_parsed)
                        data = load_github_json(raw_url)
                        if data: apply_config(data)
                    else:
                        st.error("Input ไม่ได้ชี้ไปที่ไฟล์ .json")
            
            with col2:
                if st.button("Browse Dir", use_container_width=True):
                    if gh_parsed:
                        if gh_parsed['isFileGuess']: # User pointed to a file, get parent dir
                            gh_parsed['path'] = '/'.join(gh_parsed['path'].split('/')[:-1])
                        
                        st.session_state.gh_list = list_github_jsons(gh_parsed)
                        if not st.session_state.gh_list:
                            st.warning("ไม่พบไฟล์ .json ในโฟลเดอร์นี้")
                    else:
                        st.error("Input ไม่ถูกต้อง")

            if 'gh_list' in st.session_state and st.session_state.gh_list:
                file_list = st.session_state.gh_list
                selected_file = st.selectbox(
                    "Select file:",
                    options=file_list,
                    format_func=lambda x: x['name'],
                    key='gh_selected_file'
                )
                if st.button("Load Selected", use_container_width=True):
                    data = load_github_json(selected_file['rawUrl'])
                    if data: apply_config(data)

        # --- Chart Toggles ---
        with st.expander("Chart Toggles (y₁-y₁₁)", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.button("เปิดทั้งหมด", on_click=set_all_toggles, args=(True,), use_container_width=True)
            with c2:
                st.button("ปิดทั้งหมด", on_click=set_all_toggles, args=(False,), use_container_width=True)
            with c3:
                st.button("Net เท่านั้น", on_click=set_net_only, use_container_width=True)
            
            st.divider()
            
            t = st.session_state.toggles
            c1, c2 = st.columns(2)
            with c1:
                t['showY1'] = st.toggle("y₁ (Log)", value=t['showY1'])
                t['showY2'] = st.toggle("y₂ (Log-Rev)", value=t['showY2'])
                t['showY4'] = st.toggle("y₄ (Piecewise y₂)", value=t['showY4'])
                t['showY5'] = st.toggle("y₅ (Piecewise y₁)", value=t['showY5'])
                t['showY8'] = st.toggle("y₈ (Call Intrinsic)", value=t['showY8'])
                t['showY10'] = st.toggle("y₁₀ (P/L Long)", value=t['showY10'])
            with c2:
                t['showY3'] = st.toggle("y₃ (Net)", value=t['showY3'])
                t['showY6'] = st.toggle("y₆ (Ref y₁)", value=t['showY6'])
                t['showY7'] = st.toggle("y₇ (Ref y₂)", value=t['showY7'])
                t['showY9'] = st.toggle("y₉ (Put Intrinsic)", value=t['showY9'])
                t['showY11'] = st.toggle("y₁₁ (P/L Short)", value=t['showY11'])
        
        # --- Control Buttons ---
        with st.expander("Preset Controls"):
            c1, c2 = st.columns(2)
            with c1:
                st.button("รีเซ็ต β = 0", on_click=set_bias, args=(0, 0), use_container_width=True, help="รีเซ็ต β ทั้งโหมด 'real' และ 'add_option'")
            with c2:
                st.button("เดโม β", on_click=set_bias, args=(-1000, 1000), use_container_width=True, help="ตั้ง b1=-1000, b2=1000 ทั้งสองโหมด")

        # --- Main Control Tabs ---
        st.header("Parameters")
        
        ctrl_t1, ctrl_t2, ctrl_t3, ctrl_t4 = st.tabs([
            "Global", "y₁/y₅ • y₂/y₄", "y₆/y₇ (Ref)", "Options • P/L"
        ])

        with ctrl_t1: # Global
            p = st.session_state.params
            p['global']['biasMode'] = st.radio(
                "Bias (β) Mode",
                options=['real', 'add_option'],
                format_func=lambda x: "Real (Calculated)" if x == 'real' else "Add Option",
                index=0 if p['global']['biasMode'] == 'real' else 1,
                horizontal=True
            )
            ui_param_slider("Delta 1 (δ₁)", 'global', 'delta1', DELTA_MIN, DELTA_MAX, 0.01)
            ui_param_slider("Delta 2 (δ₂)", 'global', 'delta2', DELTA_MIN, DELTA_MAX, 0.01)
            
            st.divider()
            st.button("รีเซ็ตช่วงแกน X", on_click=reset_chart_range, use_container_width=True)
            c1, c2 = st.columns(2)
            with c1:
                ui_param_number_input("x₁ min", 'chart', 'x1Range', X_RANGE_MIN, X_RANGE_MAX - 0.1, 0.1, key="x1Min_input")
            with c2:
                ui_param_number_input("x₁ max", 'chart', 'x1Range', X_RANGE_MIN + 0.1, X_RANGE_MAX, 0.1, key="x1Max_input")


        with ctrl_t2: # y1/y5, y2/y4
            is_real_mode = st.session_state.params['global']['biasMode'] == 'real'
            
            with st.container(border=True):
                st.subheader("y₁ / y₅ (Log)")
                ui_param_number_input("x₀₁ (threshold y₁/y₅)", 'y1_y5', 'x0_1', X0_MIN, X0_MAX, 0.01, on_change=lambda _: sync_x0_1())
                ui_param_number_input("ค่าคงที่ y₁/y₅", 'y1_y5', 'constant1', C_MIN, C_MAX, 1, format="%d", on_change=lambda _: calculate_auto_rollover())
                
                with st.container(border=True, height=200):
                    st.markdown("**Real Mode (β)**")
                    with st.columns(2):
                        ui_param_toggle("Auto roll-over β", 'y1_y5', 'autoRolloverB1', on_change=toggle_autoroll_b1)
                    ui_param_number_input("b₁ (bias y₁/y₅)", 'y1_y5', 'b1', B_MIN, B_MAX, 1, format="%d", on_change=set_manual_b1)
                    st.caption(f"b₁ base: {st.session_state.params['y1_y5']['b1Base']:.0f}")

                with st.container(border=True, height=150):
                    st.markdown("**Add Option Mode (β)**")
                    ui_param_number_input("b₁ (bias add_option)", 'y1_y5', 'b1_add_option', B_MIN, B_MAX, 1, format="%d")
            
            with st.container(border=True):
                st.subheader("y₂ / y₄ (Log-Rev)")
                ui_param_number_input("x₀₂ (threshold y₂/y₄)", 'y2_y4', 'x0_2', X0_MIN, X0_MAX, 0.01, on_change=lambda _: sync_x0_2())
                ui_param_number_input("ค่าคงที่ y₂/y₄", 'y2_y4', 'constant2', C_MIN, C_MAX, 1, format="%d", on_change=lambda _: calculate_auto_rollover())

                with st.container(border=True, height=200):
                    st.markdown("**Real Mode (β)**")
                    with st.columns(2):
                        ui_param_toggle("Auto roll-over β", 'y2_y4', 'autoRolloverB2', on_change=toggle_autoroll_b2)
                    ui_param_number_input("b₂ (bias y₂/y₄)", 'y2_y4', 'b2', B_MIN, B_MAX, 1, format="%d", on_change=set_manual_b2)
                    st.caption(f"b₂ base: {st.session_state.params['y2_y4']['b2Base']:.0f}")
                
                with st.container(border=True, height=150):
                    st.markdown("**Add Option Mode (β)**")
                    ui_param_number_input("b₂ (bias add_option)", 'y2_y4', 'b2_add_option', B_MIN, B_MAX, 1, format="%d")

        with ctrl_t3: # y6/y7 (Ref)
            st.subheader("y₆ / y₇ (Benchmark)")
            ui_param_number_input("Anchor (threshold y₆/y₇)", 'y6_y7_ref', 'anchorY6', X0_MIN, X0_MAX, 0.01)
            ui_param_number_input("ค่าคงที่ Baseline (y₆/y₇)", 'y6_y7_ref', 'refConst', C_MIN, C_MAX, 1, format="%d", on_change=lambda _: calculate_auto_rollover())

        with ctrl_t4: # Options / PL
            st.subheader("Options (y₈, y₉)")
            ui_param_toggle("Include premium in P/L", 'global', 'includePremium')
            
            with st.container(border=True):
                st.markdown("**y₈ (Call)**")
                ui_param_number_input("contracts_call", 'y8_call', 'callContracts', 0, CONTRACTS_MAX, 1, format="%d", is_int=True)
                ui_param_number_input("premium_call", 'y8_call', 'premiumCall', 0, PREMIUM_MAX, 0.01)
                
            with st.container(border=True):
                st.markdown("**y₉ (Put)**")
                ui_param_number_input("contracts_put", 'y9_put', 'putContracts', 0, CONTRACTS_MAX, 1, format="%d", is_int=True)
                ui_param_number_input("premium_put", 'y9_put', 'premiumPut', 0, PREMIUM_MAX, 0.01)
            
            st.subheader("P/L (y₁₀, y₁₁)")
            with st.container(border=True):
                st.markdown("**y₁₀ (Long)**")
                ui_param_number_input("Long: ราคาเข้าซื้อ", 'y10_long', 'longEntryPrice', PRICE_MIN, PRICE_MAX, 0.01)
                ui_param_number_input("Long: จำนวนหุ้น", 'y10_long', 'longShares', SHARES_MIN, SHARES_MAX, 1, format="%d", is_int=True)

            with st.container(border=True):
                st.markdown("**y₁₁ (Short)**")
                ui_param_number_input("Short: ราคาเปิดชอร์ต", 'y11_short', 'shortEntryPrice', PRICE_MIN, PRICE_MAX, 0.01)
                ui_param_number_input("Short: จำนวนหุ้น", 'y11_short', 'shortShares', SHARES_MIN, SHARES_MAX, 1, format="%d", is_int=True)

    # ---------------------------------------------------------------------
    # 10. Main Page (Charts)
    # ---------------------------------------------------------------------
    
    # --- Preparations ---
    s = st.session_state
    
    # Calculate effective bias
    effective_b1 = s.params['y1_y5']['b1'] if s.params['global']['biasMode'] == 'real' else s.params['y1_y5']['b1_add_option']
    effective_b2 = s.params['y2_y4']['b2'] if s.params['global']['biasMode'] == 'real' else s.params['y2_y4']['b2_add_option']
    
    # Generate data (cached)
    comparison_data = generate_comparison_data(s.params, s.toggles, effective_b1, effective_b2)
    
    # --- Define Chart Configs ---
    d1 = s.params['global']['delta1']
    d2 = s.params['global']['delta2']
    
    # Config for 'เปรียบเทียบทั้งหมด'
    lines_comp = {
        'y1_delta1': {'color': '#06b6d4', 'dash': [5, 5], 'width': 2, 'name': f'y₁ (δ={d1:.2f})'},
        'y1_delta2': {'color': '#22d3ee', 'width': 3, 'name': f'y₁ (δ={d2:.2f})'},
        'y2_delta1': {'color': '#fbbf24', 'dash': [5, 5], 'width': 2, 'name': f'y₂ (δ={d1:.2f})'},
        'y2_delta2': {'color': '#fde047', 'width': 3, 'name': f'y₂ (δ={d2:.2f})'},
        'y4_piece': {'color': '#a3e635', 'width': 3, 'name': 'y₄ (piecewise δ, x₀₂)'},
        'y5_piece': {'color': '#10b981', 'width': 3, 'name': 'y₅ (piecewise δ, x₀₁)'},
        'y3_delta1': {'color': '#ec4899', 'dash': [5, 5], 'width': 2.5, 'name': 'Net (δ₁ base)'},
        'y3_delta2': {'color': '#f472b6', 'width': 3.5, 'name': 'Net (δ₂ base)'},
        'y6_ref_delta2': {'color': '#94a3b8', 'dash': [6, 4], 'width': 2.5, 'name': 'y₆ (Ref y₁, δ₂)'},
        'y7_ref_delta2': {'color': '#c084fc', 'dash': [6, 4], 'width': 2.5, 'name': 'y₇ (Ref y₂, δ₂)'},
        'y8_call_intrinsic': {'color': '#ef4444', 'width': 3, 'name': 'y₈ (Call Intrinsic)'},
        'y9_put_intrinsic': {'color': '#22c55e', 'width': 3, 'name': 'y₉ (Put Intrinsic)'},
        'y10_long_pl': {'color': '#60a5fa', 'width': 3, 'name': 'y₁₀ (P/L Long)'},
        'y11_short_pl': {'color': '#fb923c', 'width': 3, 'name': 'y₁₁ (P/L Short)'},
    }
    # Filter only active lines
    active_lines_comp = {k: v for k, v in lines_comp.items() if s.toggles[f'show{k.split("_")[0][1:]}']}

    # Calculate Break-Even points
    be_call = s.params['y1_y5']['x0_1'] + (s.params['y8_call']['premiumCall'] if s.params['global']['includePremium'] else 0)
    be_put = s.params['y2_y4']['x0_2'] - (s.params['y9_put']['premiumPut'] if s.params['global']['includePremium'] else 0)

    # Config for 'เปรียบเทียบทั้งหมด' dots
    dots_comp = [
        {'x': s.params['y1_y5']['x0_1'], 'label': 'x₀₁', 'color': '#06b6d4'},
        {'x': s.params['y2_y4']['x0_2'], 'label': 'x₀₂', 'color': '#fbbf24'},
        {'x': s.params['y6_y7_ref']['anchorY6'], 'label': 'Anchor', 'color': '#94a3b8'},
        {'x': s.params['y10_long']['longEntryPrice'], 'label': 'BE₁₀', 'color': '#60a5fa'},
        {'x': s.params['y11_short']['shortEntryPrice'], 'label': 'BE₁₁', 'color': '#fb923c'},
        {'x': be_call, 'label': 'BE₈', 'color': '#ef4444'},
        {'x': be_put, 'label': 'BE₉', 'color': '#22c55e'},
    ]
    # Filter only active dots
    active_dots_comp = [
        dots_comp[0] if s.toggles['showY1'] or s.toggles['showY5'] or s.toggles['showY8'] else None,
        dots_comp[1] if s.toggles['showY2'] or s.toggles['showY4'] or s.toggles['showY7'] or s.toggles['showY9'] else None,
        dots_comp[2] if s.toggles['showY6'] else None,
        dots_comp[3] if s.toggles['showY10'] else None,
        dots_comp[4] if s.toggles['showY11'] else None,
        dots_comp[5] if s.toggles['showY8'] and s.params['global']['includePremium'] else None,
        dots_comp[6] if s.toggles['showY9'] and s.params['global']['includePremium'] else None,
    ]
    active_dots_comp = [d for d in active_dots_comp if d is not None]

    # --- Render Tabs ---
    tab_comp, tab_net, tab_overlay, tab_dyn_overlay, tab_d1, tab_d2 = st.tabs([
        "เปรียบเทียบทั้งหมด", 
        "Net เท่านั้น", 
        "Delta_Log_Overlay", 
        "Dynamic_Log_Overlay", 
        f"δ = {d1:.2f}", 
        f"δ = {d2:.2f}"
    ])
    
    with tab_comp:
        st.subheader("ครบชุด: y₁..y₅, Net, Benchmarks, y₈(call), y₉(put), y₁₀(Long), y₁₁(Short) + BE")
        plot_chart(comparison_data, active_lines_comp, active_dots_comp)

    with tab_net:
        st.subheader("Net (y₃) + Benchmark (y₆)")
        lines_net = {k: v for k, v in lines_comp.items() if k in ['y3_delta1', 'y3_delta2', 'y6_ref_delta2']}
        dots_net = [dots_comp[2]] if s.toggles['showY6'] else []
        plot_chart(comparison_data, lines_net, dots_net)

    with tab_overlay:
        st.subheader("Delta Log Overlay: Net (y₃) - Benchmark (y₆)")
        lines_overlay = {
            'y_overlay_d2': {'color': '#ea580c', 'width': 3.5, 'name': 'Delta Log Overlay (y₃ - y₆)'}
        }
        plot_chart(comparison_data, lines_overlay, [], y_domain_auto=True)
    
    with tab_dyn_overlay:
        st.subheader("Dynamic Log Overlay: Net (y₃) vs Baseline 0")
        lines_dyn = {
            'y3_delta2': {'color': '#f472b6', 'width': 3.5, 'name': 'Dynamic Log Overlay (Net vs 0)'}
        }
        
        # Get zero crossings (cached)
        zero_crossings = find_zero_crossings(comparison_data)
        dots_dyn = [{'x': x, 'label': '0', 'color': '#f472b6'} for x in zero_crossings]
        
        plot_chart(comparison_data, lines_dyn, dots_dyn, y_domain_auto=True)

    with tab_d1:
        st.subheader(f"กราฟด้วย δ = {d1:.2f}")
        # Create a new config dict for delta 1 only
        lines_d1_config = {
            'y1_delta1': lines_comp['y1_delta1'],
            'y2_delta1': lines_comp['y2_delta1'],
            'y4_piece': lines_comp['y4_piece'],
            'y5_piece': lines_comp['y5_piece'],
            'y3_delta1': lines_comp['y3_delta1'],
            'y6_ref_delta1': {'color': '#94a3b8', 'dash': [6, 4], 'width': 2.5, 'name': f'y₆ (Ref y₁, δ₁)'},
            'y7_ref_delta1': {'color': '#c084fc', 'dash': [6, 4], 'width': 2.5, 'name': f'y₇ (Ref y₂, δ₁)'},
            'y8_call_intrinsic': lines_comp['y8_call_intrinsic'],
            'y9_put_intrinsic': lines_comp['y9_put_intrinsic'],
            'y10_long_pl': lines_comp['y10_long_pl'],
            'y11_short_pl': lines_comp['y11_short_pl'],
        }
        active_lines_d1 = {k: v for k, v in lines_d1_config.items() if s.toggles[f'show{k.split("_")[0][1:]}']}
        dots_d1 = [d for d in dots_comp if d['label'] in ['BE₁₀', 'BE₁₁']] # Only show P/L BE dots
        active_dots_d1 = [
            dots_d1[0] if s.toggles['showY10'] else None,
            dots_d1[1] if s.toggles['showY11'] else None,
        ]
        active_dots_d1 = [d for d in active_dots_d1 if d is not None]
        
        plot_chart(comparison_data, active_lines_d1, active_dots_d1)

    with tab_d2:
        st.subheader(f"กราฟด้วย δ = {d2:.2f}")
        # Create a new config dict for delta 2 only
        lines_d2_config = {
            'y1_delta2': lines_comp['y1_delta2'],
            'y2_delta2': lines_comp['y2_delta2'],
            'y4_piece': lines_comp['y4_piece'],
            'y5_piece': lines_comp['y5_piece'],
            'y3_delta2': lines_comp['y3_delta2'],
            'y6_ref_delta2': lines_comp['y6_ref_delta2'],
            'y7_ref_delta2': lines_comp['y7_ref_delta2'],
            'y8_call_intrinsic': lines_comp['y8_call_intrinsic'],
            'y9_put_intrinsic': lines_comp['y9_put_intrinsic'],
            'y10_long_pl': lines_comp['y10_long_pl'],
            'y11_short_pl': lines_comp['y11_short_pl'],
        }
        active_lines_d2 = {k: v for k, v in lines_d2_config.items() if s.toggles[f'show{k.split("_")[0][1:]}']}
        dots_d2 = [d for d in dots_comp if d['label'] in ['BE₁₀', 'BE₁₁']] # Only show P/L BE dots
        active_dots_d2 = [
            dots_d2[0] if s.toggles['showY10'] else None,
            dots_d2[1] if s.toggles['showY11'] else None,
        ]
        active_dots_d2 = [d for d in active_dots_d2 if d is not None]
        
        plot_chart(comparison_data, active_lines_d2, active_dots_d2)

# --- Entry point ---
if __name__ == "__main__":
    run_app()
