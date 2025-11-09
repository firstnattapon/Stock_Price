# log_graph_streamlit_app.py
# Streamlit port of "LogarithmicGraph" (React → Python)
# Schema version: 1.2.0
# Notes:
# - Preserves math, toggles, auto-rollover β logic, import/export JSON, and GitHub raw loader.
# - Uses matplotlib (one figure per tab) to avoid extra deps; Streamlit handles display.
# - Colors aim to mirror the React version but may differ slightly due to matplotlib styles.

import streamlit as st
import math
import json
import datetime as dt
import io
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
import requests
import numpy as np
import matplotlib.pyplot as plt

APP_SCHEMA_VERSION = "1.2.0"

# ---------------- Math helpers ----------------
def H(z: float) -> int:
    return 1 if z >= 0 else 0

def safe_log(arg: float) -> Optional[float]:
    try:
        if arg > 0:
            return math.log(arg)
        return None
    except Exception:
        return None

def piecewise_delta(x: float, thr: float, below: float, above: float) -> float:
    return below + H(x - thr) * (above - below)

def scale_or_none(v: Optional[float], s: float) -> Optional[float]:
    return None if v is None else v * s

def add_bias_or_none(v: Optional[float], b: float) -> Optional[float]:
    return None if v is None else v + b

def sum_or_none(values: List[Optional[float]], actives: List[bool]) -> Optional[float]:
    # If any active value is None, result is None
    for v, a in zip(values, actives):
        if a and v is None:
            return None
    s = 0.0
    for v, a in zip(values, actives):
        if a and v is not None:
            s += v
    return s

def subtract_or_none(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

# ---------------- Types ----------------
@dataclass
class Toggles:
    showY1: bool = True
    showY2: bool = False
    showY3: bool = False
    showY4: bool = False
    showY5: bool = False
    showY6: bool = True
    showY7: bool = True
    showY8: bool = True
    showY9: bool = True
    showY10: bool = False
    showY11: bool = False

@dataclass
class Params:
    # y1_y5
    x0_1: float = 7.0
    constant1: float = 1500.0
    b1: float = 0.0
    b1Base: float = 0.0
    autoRolloverB1: bool = False
    b1_add_option: float = 0.0
    # y2_y4
    x0_2: float = 10.0
    constant2: float = 1500.0
    b2: float = 0.0
    b2Base: float = 0.0
    autoRolloverB2: bool = False
    b2_add_option: float = 0.0
    # y6_y7_ref
    anchorY6: float = 7.0
    refConst: float = 1500.0
    # y8_call
    callContracts: int = 100
    premiumCall: float = 2.6
    # y9_put
    putContracts: int = 100
    premiumPut: float = 2.6
    # y10_long
    longEntryPrice: float = 7.0
    longShares: int = 100
    # y11_short
    shortEntryPrice: float = 10.0
    shortShares: int = 100
    # global
    delta1: float = 0.2
    delta2: float = 1.0
    includePremium: bool = True
    biasMode: str = "real"  # 'real' | 'add_option'
    # chart
    x1Range: Tuple[float, float] = (3.0, 17.0)

@dataclass
class ExportConfig:
    version: str
    exported_at: str
    params: Dict[str, Any]
    toggles: Dict[str, Any]

# ---------------- GitHub helpers ----------------
def normalize_ref(ref: str) -> str:
    return ref.replace("refs/heads/", "")

def to_raw_from_blob(url: str) -> Optional[str]:
    try:
        from urllib.parse import urlparse
        u = urlparse(url)
        if u.netloc != "github.com":
            return None
        seg = [s for s in u.path.split("/") if s]
        if "blob" in seg:
            i = seg.index("blob")
            if len(seg) > i + 2:
                owner, repo, ref = seg[0], seg[1], seg[i + 1]
                path = "/".join(seg[i + 2:])
                return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    except Exception:
        pass
    return None

def parse_github_input(inp: str) -> Optional[Dict[str, str]]:
    # Supports:
    # - owner/repo/path@branch
    # - raw.githubusercontent.com URL
    # - github.com blob URL (auto-convert to raw)
    # - api.github.com/repos/{owner}/{repo}/contents/{path}?ref=branch
    try:
        if inp.startswith("http://") or inp.startswith("https://"):
            if "raw.githubusercontent.com" in inp:
                return {"raw": inp}
            if "github.com" in inp:
                raw_try = to_raw_from_blob(inp)
                if raw_try:
                    return {"raw": raw_try}
                # maybe it's a repo/tree; let browse use API later
                return {"browse": inp}
            if "api.github.com" in inp:
                return {"api": inp}
            return {"raw": inp}
        # owner/repo/path@branch
        left, _, at = inp.partition("@")
        ref = normalize_ref(at) if at else "master"
        parts = [s for s in left.split("/") if s]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            path = "/".join(parts[2:])
            if path.endswith(".json"):
                raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
                return {"raw": raw}
            else:
                # directory browse case
                api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
                return {"api": api}
    except Exception:
        return None
    return None

def list_github_jsons(api_url: str) -> List[Dict[str, str]]:
    # returns [{"name":..., "download_url":...}, ...] if directory
    headers = {"Accept": "application/vnd.github+json"}
    r = requests.get(api_url, headers=headers, timeout=15)
    if not r.ok:
        raise RuntimeError(f"GitHub API {r.status_code}: {r.text[:180]}")
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError("Not a directory listing")
    out = []
    for x in data:
        if isinstance(x, dict) and x.get("type") == "file" and str(x.get("name","")).lower().endswith(".json"):
            url = x.get("download_url")
            if not url:
                # Fallback to constructing raw
                url = f"https://raw.githubusercontent.com/{x.get('repository','')}/{x.get('path','')}"
            out.append({"name": x.get("name","config.json"), "download_url": url})
    return out

def fetch_json(url: str) -> Dict[str, Any]:
    r = requests.get(url, timeout=20)
    if not r.ok:
        raise RuntimeError(f"Fetch failed: {r.status_code} {r.text[:120]}")
    return r.json()

# ---------------- State helpers ----------------
def ensure_state():
    if "params" not in st.session_state:
        st.session_state.params = Params()
    if "toggles" not in st.session_state:
        st.session_state.toggles = Toggles()
    if "prev_auto_b1" not in st.session_state:
        st.session_state.prev_auto_b1 = st.session_state.params.autoRolloverB1
    if "prev_auto_b2" not in st.session_state:
        st.session_state.prev_auto_b2 = st.session_state.params.autoRolloverB2

def build_config_dict() -> ExportConfig:
    p = asdict(st.session_state.params)
    t = asdict(st.session_state.toggles)
    return ExportConfig(
        version=APP_SCHEMA_VERSION,
        exported_at=dt.datetime.utcnow().isoformat() + "Z",
        params=p,
        toggles=t
    )

def apply_config(raw: Dict[str, Any]):
    version = str(raw.get("version", "0"))
    if version not in {APP_SCHEMA_VERSION, "1.1.1", "1.1.0"}:
        st.warning(f"Config version {version} != app {APP_SCHEMA_VERSION}. จะพยายาม import แบบอ่อนโยน")

    p = raw.get("params", {})
    t = raw.get("toggles", {})

    # Coerce/Clamp
    def num(key, default, lo=None, hi=None):
        v = p.get(key, default)
        try:
            v = float(v)
        except Exception:
            v = default
        if lo is not None and hi is not None:
            v = clamp(v, lo, hi)
        return v

    def intval(key, default, lo=None, hi=None):
        v = p.get(key, default)
        try:
            v = int(round(float(v)))
        except Exception:
            v = default
        if lo is not None and hi is not None:
            v = max(lo, min(hi, v))
        return v

    def boolv(key, default):
        v = p.get(key, default)
        return bool(v) if isinstance(v, bool) else bool(v)

    # ranges
    X0_MIN, X0_MAX = 0.1, 50.0
    DELTA_MIN, DELTA_MAX = 0.01, 2.0
    C_MIN, C_MAX = 100.0, 10000.0
    B_MIN, B_MAX = -5000.0, 5000.0
    X_RANGE_MIN, X_RANGE_MAX = 0.1, 50.0
    CONTRACTS_MAX = 10000
    PREMIUM_MAX = 1000.0
    PRICE_MIN, PRICE_MAX = 0.0, 50.0
    SHARES_MIN, SHARES_MAX = 0, 10_000_000

    new_params = Params(
        x0_1 = clamp(num("x0_1", st.session_state.params.x0_1), X0_MIN, X0_MAX),
        constant1 = clamp(num("constant1", st.session_state.params.constant1), C_MIN, C_MAX),
        b1 = clamp(num("b1", st.session_state.params.b1), B_MIN, B_MAX),
        b1Base = num("b1Base", st.session_state.params.b1Base),
        autoRolloverB1 = bool(p.get("autoRolloverB1", st.session_state.params.autoRolloverB1)),
        b1_add_option = clamp(num("b1_add_option", st.session_state.params.b1_add_option), B_MIN, B_MAX),
        x0_2 = clamp(num("x0_2", st.session_state.params.x0_2), X0_MIN, X0_MAX),
        constant2 = clamp(num("constant2", st.session_state.params.constant2), C_MIN, C_MAX),
        b2 = clamp(num("b2", st.session_state.params.b2), B_MIN, B_MAX),
        b2Base = num("b2Base", st.session_state.params.b2Base),
        autoRolloverB2 = bool(p.get("autoRolloverB2", st.session_state.params.autoRolloverB2)),
        b2_add_option = clamp(num("b2_add_option", st.session_state.params.b2_add_option), B_MIN, B_MAX),
        anchorY6 = clamp(num("anchorY6", st.session_state.params.anchorY6), X0_MIN, X0_MAX),
        refConst = clamp(num("refConst", st.session_state.params.refConst), C_MIN, C_MAX),
        callContracts = intval("callContracts", st.session_state.params.callContracts, 0, CONTRACTS_MAX),
        premiumCall = clamp(num("premiumCall", st.session_state.params.premiumCall), 0.0, PREMIUM_MAX),
        putContracts = intval("putContracts", st.session_state.params.putContracts, 0, CONTRACTS_MAX),
        premiumPut = clamp(num("premiumPut", st.session_state.params.premiumPut), 0.0, PREMIUM_MAX),
        longEntryPrice = clamp(num("longEntryPrice", st.session_state.params.longEntryPrice), PRICE_MIN, PRICE_MAX),
        longShares = intval("longShares", st.session_state.params.longShares, SHARES_MIN, SHARES_MAX),
        shortEntryPrice = clamp(num("shortEntryPrice", st.session_state.params.shortEntryPrice), PRICE_MIN, PRICE_MAX),
        shortShares = intval("shortShares", st.session_state.params.shortShares, SHARES_MIN, SHARES_MAX),
        delta1 = clamp(num("delta1", st.session_state.params.delta1), DELTA_MIN, DELTA_MAX),
        delta2 = clamp(num("delta2", st.session_state.params.delta2), DELTA_MIN, DELTA_MAX),
        includePremium = bool(p.get("includePremium", st.session_state.params.includePremium)),
        biasMode = p.get("biasMode", st.session_state.params.biasMode) if p.get("biasMode", st.session_state.params.biasMode) in {"real","add_option"} else st.session_state.params.biasMode,
        x1Range = tuple(p.get("x1Range", st.session_state.params.x1Range)) if isinstance(p.get("x1Range", None), (list,tuple)) and len(p.get("x1Range"))==2 else st.session_state.params.x1Range,
    )

    st.session_state.params = new_params

    # Toggles
    nt = Toggles(
        showY1 = bool(t.get("showY1", st.session_state.toggles.showY1)),
        showY2 = bool(t.get("showY2", st.session_state.toggles.showY2)),
        showY3 = bool(t.get("showY3", st.session_state.toggles.showY3)),
        showY4 = bool(t.get("showY4", st.session_state.toggles.showY4)),
        showY5 = bool(t.get("showY5", st.session_state.toggles.showY5)),
        showY6 = bool(t.get("showY6", st.session_state.toggles.showY6)),
        showY7 = bool(t.get("showY7", st.session_state.toggles.showY7)),
        showY8 = bool(t.get("showY8", st.session_state.toggles.showY8)),
        showY9 = bool(t.get("showY9", st.session_state.toggles.showY9)),
        showY10 = bool(t.get("showY10", st.session_state.toggles.showY10)),
        showY11 = bool(t.get("showY11", st.session_state.toggles.showY11)),
    )
    st.session_state.toggles = nt

def apply_auto_rollover_if_needed():
    p = st.session_state.params
    # Detect rising edge of auto toggles -> set base to current b
    if p.autoRolloverB1 and not st.session_state.prev_auto_b1:
        st.session_state.params = Params(**{**asdict(p), "b1Base": p.b1})
    if p.autoRolloverB2 and not st.session_state.prev_auto_b2:
        st.session_state.params = Params(**{**asdict(st.session_state.params), "b2Base": p.b2})
    st.session_state.prev_auto_b1 = p.autoRolloverB1
    st.session_state.prev_auto_b2 = p.autoRolloverB2

    # Recompute b1, b2 if autos are on
    p = st.session_state.params  # refresh
    if p.autoRolloverB1 and p.x0_1 > 0 and p.x0_2 > 0:
        lnTerm = math.log(p.x0_2 / p.x0_1)
        calc = p.b1Base + (p.refConst - p.constant1) * lnTerm
        if math.isfinite(calc):
            st.session_state.params = Params(**{**asdict(st.session_state.params), "b1": calc})
    p = st.session_state.params
    if p.autoRolloverB2 and p.x0_1 > 0 and p.x0_2 > 0:
        lnTerm = math.log(p.x0_1 / p.x0_2)
        calc = p.b2Base + (p.refConst - p.constant2) * lnTerm
        if math.isfinite(calc):
            st.session_state.params = Params(**{**asdict(st.session_state.params), "b2": calc})

# ---------------- Core calculations ----------------
def effective_bias(b_real: float, b_add: float, mode: str) -> float:
    return b_real if mode == "real" else b_add

def generate_comparison_data(p: Params, t: Toggles) -> List[Dict[str, Optional[float]]]:
    pts = []
    steps = 100
    step = (p.x1Range[1] - p.x1Range[0]) / steps
    b1_eff = effective_bias(p.b1, p.b1_add_option, p.biasMode)
    b2_eff = effective_bias(p.b2, p.b2_add_option, p.biasMode)

    for i in range(steps + 1):
        x1 = p.x1Range[0] + i * step

        ln1 = safe_log(x1 / p.x0_1)
        ln2 = safe_log(2 - x1 / p.x0_2)

        y1_raw = None if ln1 is None else p.constant1 * ln1
        y2_raw = None if ln2 is None else p.constant2 * ln2

        y1_d1 = add_bias_or_none(scale_or_none(y1_raw, p.delta1), b1_eff)
        y1_d2 = add_bias_or_none(scale_or_none(y1_raw, p.delta2), b1_eff)
        y2_d1 = add_bias_or_none(scale_or_none(y2_raw, p.delta1), b2_eff)
        y2_d2 = add_bias_or_none(scale_or_none(y2_raw, p.delta2), b2_eff)

        d_y4 = piecewise_delta(x1, p.x0_2, p.delta2, p.delta1)
        y4_piece = add_bias_or_none(scale_or_none(y2_raw, d_y4), b2_eff)

        d_y5 = piecewise_delta(x1, p.x0_1, p.delta1, p.delta2)
        y5_piece = add_bias_or_none(scale_or_none(y1_raw, d_y5), b1_eff)

        ln6 = safe_log(x1 / p.anchorY6)
        y6_raw = None if ln6 is None else p.refConst * ln6
        ln7 = safe_log(2 - x1 / p.anchorY6)
        y7_raw = None if ln7 is None else p.refConst * ln7

        y6_ref_d1 = scale_or_none(y6_raw, p.delta1)
        y6_ref_d2 = scale_or_none(y6_raw, p.delta2)
        y7_ref_d1 = scale_or_none(y7_raw, p.delta1)
        y7_ref_d2 = scale_or_none(y7_raw, p.delta2)

        premCallCost = p.callContracts * p.premiumCall if p.includePremium else 0.0
        premPutCost = p.putContracts * p.premiumPut if p.includePremium else 0.0
        y8_call_intrinsic = max(0.0, x1 - p.x0_1) * p.callContracts - premCallCost
        y9_put_intrinsic = max(0.0, p.x0_2 - x1) * p.putContracts - premPutCost

        y10_long_pl = (x1 - p.longEntryPrice) * p.longShares
        y11_short_pl = (p.shortEntryPrice - x1) * p.shortShares

        actives_d1 = [t.showY1, t.showY2, t.showY4, t.showY5, t.showY8, t.showY9, t.showY10, t.showY11]
        vals_d1 = [y1_d1, y2_d1, y4_piece, y5_piece, y8_call_intrinsic, y9_put_intrinsic, y10_long_pl, y11_short_pl]
        y3_d1 = sum_or_none(vals_d1, actives_d1)

        actives_d2 = [t.showY1, t.showY2, t.showY4, t.showY5, t.showY8, t.showY9, t.showY10, t.showY11]
        vals_d2 = [y1_d2, y2_d2, y4_piece, y5_piece, y8_call_intrinsic, y9_put_intrinsic, y10_long_pl, y11_short_pl]
        y3_d2 = sum_or_none(vals_d2, actives_d2)

        y_overlay_d2 = subtract_or_none(y3_d2, y6_ref_d2)

        pts.append({
            "x1": x1,
            "y1_delta1": y1_d1, "y1_delta2": y1_d2,
            "y2_delta1": y2_d1, "y2_delta2": y2_d2,
            "y4_piece": y4_piece, "y5_piece": y5_piece,
            "y3_delta1": y3_d1, "y3_delta2": y3_d2,
            "y6_ref_delta1": y6_ref_d1, "y6_ref_delta2": y6_ref_d2,
            "y7_ref_delta1": y7_ref_d1, "y7_ref_delta2": y7_ref_d2,
            "y8_call_intrinsic": y8_call_intrinsic, "y9_put_intrinsic": y9_put_intrinsic,
            "y10_long_pl": y10_long_pl, "y11_short_pl": y11_short_pl,
            "y_overlay_d2": y_overlay_d2,
        })
    return pts

def zero_crossings(values: List[Optional[float]], xs: List[float]) -> List[float]:
    # Linear interpolation for zero crossings on y3_delta2
    zs = []
    for i in range(1, len(values)):
        a = values[i-1]
        b = values[i]
        if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)):
            continue
        if a == 0:
            zs.append(xs[i-1]); continue
        if b == 0:
            zs.append(xs[i]); continue
        if (a < 0 and b > 0) or (a > 0 and b < 0):
            x0 = xs[i-1] + (0 - a) * (xs[i] - xs[i-1]) / (b - a)
            if math.isfinite(x0):
                zs.append(x0)
    return zs

# ---------------- Plot helpers (matplotlib, one figure per tab) ----------------
def plot_lines(x, series: Dict[str, List[Optional[float]]], title: str, y_auto_zero=False, markers: List[float]=None, ref_dots: Dict[str, float]=None):
    fig, ax = plt.subplots(figsize=(9.5, 5.8))
    for name, y in series.items():
        # Filter Nones: plot as NaN
        y_np = np.array([np.nan if v is None else v for v in y], dtype=float)
        ax.plot(x, y_np, label=name, linewidth=2.2)

    # Reference dots / vertical markers at y=0
    if ref_dots:
        for label, xv in ref_dots.items():
            ax.scatter([xv], [0], s=60, marker='o', label=label)

    if markers:
        ax.scatter(markers, [0]*len(markers), s=70, marker='o', label="zero", alpha=0.8)

    ax.grid(True, linestyle="--", alpha=0.35)
    ax.set_xlabel("x₁")
    ax.set_ylabel("y")
    if y_auto_zero:
        ymin, ymax = np.nanmin([np.nanmin(np.array(v, dtype=float)) for v in series.values()]), np.nanmax([np.nanmax(np.array(v, dtype=float)) for v in series.values()])
        ymin = min(0, ymin)
        ymax = max(0, ymax)
        ax.set_ylim([ymin, ymax])
    ax.legend()
    st.pyplot(fig, clear_figure=True)

# ---------------- UI ----------------
def main():
    st.set_page_config(page_title="เปรียบเทียบกราฟ (Streamlit)", layout="wide")
    ensure_state()
    p: Params = st.session_state.params
    t: Toggles = st.session_state.toggles

    st.title("เปรียบเทียบกราฟ (รองรับ β): + Intrinsic + P/L Long–Short — Streamlit Edition")

    # Import / Export
    with st.container():
        c1, c2, c3 = st.columns([2,1,1])
        with c1:
            st.markdown(f"**Schema:** v{APP_SCHEMA_VERSION}")
            uploaded = st.file_uploader("Import .json", type=["json"])
            if uploaded is not None:
                try:
                    raw = json.load(uploaded)
                    apply_config(raw)
                    st.success("นำเข้า config สำเร็จ")
                except Exception as e:
                    st.error(f"นำเข้าไม่สำเร็จ: {e}")
        with c2:
            cfg = build_config_dict()
            st.download_button(
                "Export .json",
                data=json.dumps(asdict(cfg), indent=2).encode("utf-8"),
                file_name=f"log_graph_config_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )
        with c3:
            st.write("โหลดจาก GitHub (raw/blob/tree / owner/repo/path@branch)")
            gh_input = st.text_input("GitHub input", value="firstnattapon/streamlit-example-1/exotic_payoff@master")
            gh_cols = st.columns(3)
            with gh_cols[0]:
                if st.button("Load JSON"):
                    try:
                        parsed = parse_github_input(gh_input)
                        if not parsed or "raw" not in parsed:
                            st.warning("อ่าน GitHub input ไม่ได้ หรือไม่ใช่ไฟล์ .json โดยตรง")
                        else:
                            data = fetch_json(parsed["raw"])
                            apply_config(data)
                            st.success("โหลด config จาก GitHub สำเร็จ")
                    except Exception as e:
                        st.error(f"โหลดจาก GitHub ล้มเหลว: {e}")
            with gh_cols[1]:
                if st.button("Browse Dir"):
                    try:
                        parsed = parse_github_input(gh_input)
                        api = None
                        if parsed and "api" in parsed:
                            api = parsed["api"]
                        elif parsed and "browse" in parsed:
                            # best effort to convert repo/tree into API (not perfect)
                            from urllib.parse import urlparse
                            u = urlparse(parsed["browse"])
                            # try to infer owner/repo/ref/path
                            seg = [s for s in u.path.split("/") if s]
                            if "tree" in seg:
                                i = seg.index("tree")
                                owner, repo, ref = seg[0], seg[1], seg[i+1]
                                path = "/".join(seg[i+2:])
                                api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
                            else:
                                owner, repo = seg[0], seg[1]
                                api = f"https://api.github.com/repos/{owner}/{repo}/contents/?ref=master"
                        if not api:
                            st.warning("สร้าง API URL ไม่สำเร็จ")
                        else:
                            items = list_github_jsons(api)
                            if not items:
                                st.info("ไม่พบไฟล์ .json ในโฟลเดอร์นี้")
                            else:
                                st.session_state._gh_items = items
                                st.success(f"พบ .json {len(items)} ไฟล์")
                    except Exception as e:
                        st.error(f"เรียกรายการโฟลเดอร์ล้มเหลว: {e}")
            with gh_cols[2]:
                if st.button("Load Selected"):
                    try:
                        items = st.session_state.get("_gh_items", [])
                        if not items:
                            st.warning("ยังไม่มีรายการให้เลือก (กด Browse Dir ก่อน)")
                        else:
                            names = [x["name"] for x in items]
                            sel = st.selectbox("เลือกไฟล์", names, key="_gh_sel", index=0)
                            url = next((x["download_url"] for x in items if x["name"] == sel), None)
                            if not url:
                                st.warning("ไม่พบ URL ของไฟล์")
                            else:
                                data = fetch_json(url)
                                apply_config(data)
                                st.success("โหลด config (รายการที่เลือก) สำเร็จ")
                    except Exception as e:
                        st.error(f"โหลดรายการที่เลือกไม่สำเร็จ: {e}")

    # Bias mode and control buttons
    with st.container():
        a, b, c, d, e = st.columns(5)
        with a:
            new_mode = st.radio("Bias (β) Mode", options=["real","add_option"], index=0 if p.biasMode=="real" else 1, horizontal=True)
            if new_mode != p.biasMode:
                st.session_state.params = Params(**{**asdict(p), "biasMode": new_mode})
                p = st.session_state.params
        with b:
            if st.button("เปิดทั้งหมด"):
                st.session_state.toggles = Toggles(**{k: True for k in asdict(t).keys()})
                t = st.session_state.toggles
        with c:
            if st.button("ปิดทั้งหมด"):
                st.session_state.toggles = Toggles(**{k: False for k in asdict(t).keys()})
                t = st.session_state.toggles
        with d:
            if st.button("Net เท่านั้น"):
                zeros = {k: False for k in asdict(t).keys()}
                zeros["showY3"] = True
                st.session_state.toggles = Toggles(**zeros)
                t = st.session_state.toggles
        with e:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("รีเซ็ต β = 0"):
                    st.session_state.params = Params(**{**asdict(p), "b1":0.0, "b2":0.0, "b1Base":0.0, "b2Base":0.0, "b1_add_option":0.0, "b2_add_option":0.0})
                    p = st.session_state.params
            with col2:
                if st.button("เดโม β"):
                    st.session_state.params = Params(**{**asdict(p), "b1":-1000.0, "b2":1000.0, "b1Base":-1000.0, "b2Base":1000.0, "b1_add_option":-1000.0, "b2_add_option":1000.0})
                    p = st.session_state.params

    # Parameter panels
    st.markdown("---")
    st.subheader("พาเนลพารามิเตอร์")

    # Real mode inputs (y1/y5, y2/y4)
    disabled_real = (p.biasMode != "real")
    cols = st.columns(3)
    with cols[0]:
        st.number_input("x₀₁ (threshold y₁/y₅)", min_value=0.1, max_value=50.0, step=0.01, value=float(p.x0_1), key="x01",
                        disabled=disabled_real)
        st.number_input("ค่าคงที่ y1/y5", min_value=100.0, max_value=10000.0, step=1.0, value=float(p.constant1), key="c1",
                        disabled=disabled_real)
        st.number_input("b₁ (bias y₁/y₅)", min_value=-5000.0, max_value=5000.0, step=1.0, value=float(p.b1), key="b1",
                        disabled=disabled_real)
    with cols[1]:
        st.number_input("x₀₂ (threshold y₂/y₄)", min_value=0.1, max_value=50.0, step=0.01, value=float(p.x0_2), key="x02",
                        disabled=disabled_real)
        st.number_input("ค่าคงที่ y2/y4", min_value=100.0, max_value=10000.0, step=1.0, value=float(p.constant2), key="c2",
                        disabled=disabled_real)
        st.number_input("b₂ (bias y₂/y₄)", min_value=-5000.0, max_value=5000.0, step=1.0, value=float(p.b2), key="b2",
                        disabled=disabled_real)
    with cols[2]:
        pass

    # Sync back changed real params
    if not disabled_real:
        st.session_state.params = Params(**{**asdict(st.session_state.params),
                                            "x0_1": float(st.session_state.x01),
                                            "constant1": float(st.session_state.c1),
                                            "b1": float(st.session_state.b1),
                                            "x0_2": float(st.session_state.x02),
                                            "constant2": float(st.session_state.c2),
                                            "b2": float(st.session_state.b2)})
        p = st.session_state.params

    # Add option bias inputs
    disabled_add = (p.biasMode != "add_option")
    cols = st.columns(2)
    with cols[0]:
        st.number_input("b₁ (bias add_option)", min_value=-5000.0, max_value=5000.0, step=1.0, value=float(p.b1_add_option), key="b1a",
                        disabled=disabled_add)
    with cols[1]:
        st.number_input("b₂ (bias add_option)", min_value=-5000.0, max_value=5000.0, step=1.0, value=float(p.b2_add_option), key="b2a",
                        disabled=disabled_add)
    if not disabled_add:
        st.session_state.params = Params(**{**asdict(p),
                                            "b1_add_option": float(st.session_state.b1a),
                                            "b2_add_option": float(st.session_state.b2a)})
        p = st.session_state.params

    # Reference (y6/y7)
    cols = st.columns(3)
    with cols[0]:
        st.number_input("Anchor (threshold y₆/y₇)", min_value=0.1, max_value=50.0, step=0.01, value=float(p.anchorY6), key="anch")
    with cols[1]:
        st.number_input("ค่าคงที่ Baseline (y₆/y₇)", min_value=100.0, max_value=10000.0, step=1.0, value=float(p.refConst), key="rc")
    with cols[2]:
        pass
    st.session_state.params = Params(**{**asdict(p), "anchorY6": float(st.session_state.anch), "refConst": float(st.session_state.rc)})
    p = st.session_state.params

    # Global deltas
    cols = st.columns(2)
    with cols[0]:
        st.number_input("Delta 1 (δ₁)", min_value=0.01, max_value=2.0, step=0.01, value=float(p.delta1), key="d1")
    with cols[1]:
        st.number_input("Delta 2 (δ₂)", min_value=0.01, max_value=2.0, step=0.01, value=float(p.delta2), key="d2")
    st.session_state.params = Params(**{**asdict(p), "delta1": float(st.session_state.d1), "delta2": float(st.session_state.d2)})
    p = st.session_state.params

    # X range
    st.markdown("**ช่วงแกน x₁**")
    cols = st.columns(2)
    with cols[0]:
        xmin = st.number_input("x₁ min", min_value=0.1, max_value=49.9, step=0.1, value=float(p.x1Range[0]), key="xmin")
    with cols[1]:
        xmax = st.number_input("x₁ max", min_value=xmin+0.1, max_value=50.0, step=0.1, value=float(p.x1Range[1]), key="xmax")
    st.session_state.params = Params(**{**asdict(p), "x1Range": (float(xmin), float(xmax))})
    p = st.session_state.params

    # Auto roll-over
    st.markdown("**Auto roll-over β**")
    cols = st.columns(2)
    with cols[0]:
        auto_b1 = st.toggle("Auto roll-over β (สำหรับ y₁ + y₅)", value=p.autoRolloverB1)
        st.write(f"Anchor P* = x₀₂ (ปัจจุบัน: {p.x0_2:.2f})")
        st.caption("สูตร: b₁ = b₁(base) + (refConst − constant1) × ln(x₀₂/x₀₁)")
    with cols[1]:
        auto_b2 = st.toggle("Auto roll-over β (สำหรับ y₂ + y₄)", value=p.autoRolloverB2)
        st.write(f"Anchor P* = x₀₁ (ปัจจุบัน: {p.x0_1:.2f})")
        st.caption("สูตร: b₂ = b₂(base) + (refConst − constant2) × ln(x₀₁/x₀₂)")

    st.session_state.params = Params(**{**asdict(p), "autoRolloverB1": bool(auto_b1), "autoRolloverB2": bool(auto_b2)})
    p = st.session_state.params

    # Include premium
    st.markdown("**Include premium in P/L**")
    inc = st.toggle("รวมต้นทุนพรีเมียม", value=p.includePremium)
    st.session_state.params = Params(**{**asdict(p), "includePremium": bool(inc)})
    p = st.session_state.params

    cols = st.columns(2)
    with cols[0]:
        st.number_input("contracts_call (y₈)", min_value=0, max_value=10000, step=1, value=int(p.callContracts), key="cc")
        st.number_input("premium_call", min_value=0.0, max_value=1000.0, step=0.01, value=float(p.premiumCall), key="pc")
    with cols[1]:
        st.number_input("contracts_put (y₉)", min_value=0, max_value=10000, step=1, value=int(p.putContracts), key="cp")
        st.number_input("premium_put", min_value=0.0, max_value=1000.0, step=0.01, value=float(p.premiumPut), key="pp")
    st.session_state.params = Params(**{**asdict(p),
                                        "callContracts": int(st.session_state.cc),
                                        "premiumCall": float(st.session_state.pc),
                                        "putContracts": int(st.session_state.cp),
                                        "premiumPut": float(st.session_state.pp)})
    p = st.session_state.params

    # Long/Short
    st.markdown("**P/L (Long / Short)**")
    cols = st.columns(2)
    with cols[0]:
        st.number_input("Long (y₁₀): ราคาเข้าซื้อ", min_value=0.0, max_value=50.0, step=0.01, value=float(p.longEntryPrice), key="lep")
        st.number_input("Long (y₁₀): จำนวนหุ้น", min_value=0, max_value=1_000_000, step=1, value=int(p.longShares), key="ls")
    with cols[1]:
        st.number_input("Short (y₁₁): ราคาเปิดชอร์ต", min_value=0.0, max_value=50.0, step=0.01, value=float(p.shortEntryPrice), key="sep")
        st.number_input("Short (y₁₁): จำนวนหุ้น", min_value=0, max_value=1_000_000, step=1, value=int(p.shortShares), key="ss")
    st.session_state.params = Params(**{**asdict(p),
                                        "longEntryPrice": float(st.session_state.lep),
                                        "longShares": int(st.session_state.ls),
                                        "shortEntryPrice": float(st.session_state.sep),
                                        "shortShares": int(st.session_state.ss)})
    p = st.session_state.params

    # Toggles group
    st.markdown("**เลือกเส้นที่จะโชว์**")
    tg_cols = st.columns(6)
    keys = list(asdict(t).keys())
    vals = [getattr(t, k) for k in keys]
    for i, k in enumerate(keys):
        with tg_cols[i % 6]:
            v = st.checkbox(k, value=bool(vals[i]), key=f"_tg_{k}")
            setattr(st.session_state.toggles, k, bool(v))
    t = st.session_state.toggles

    # Auto-rollover apply
    apply_auto_rollover_if_needed()
    p = st.session_state.params

    # Deriveds
    be_call = p.x0_1 + (p.premiumCall if p.includePremium else 0.0)
    be_put = p.x0_2 - (p.premiumPut if p.includePremium else 0.0)

    # Sync effects: longEntryPrice <- x0_1; shortEntryPrice <- x0_2 (as in React)
    st.session_state.params = Params(**{**asdict(p), "longEntryPrice": p.x0_1, "shortEntryPrice": p.x0_2})
    p = st.session_state.params

    # Compute series
    comp = generate_comparison_data(p, t)
    x = [d["x1"] for d in comp]

    # Tabs
    tabs = st.tabs(["เปรียบเทียบทั้งหมด", "Net เท่านั้น", "Delta_Log_Overlay", "Dynamic_Log_Overlay", f"δ = {p.delta1:.2f}", f"δ = {p.delta2:.2f}"])

    # 1) Comparison
    with tabs[0]:
        st.markdown("ครบชุด: y₁..y₅, Net, Benchmarks, y₈(call), y₉(put), y₁₀(Long), y₁₁(Short) + BE")
        series = {}
        if t.showY1:
            series[f"y₁ (δ={p.delta1:.2f})"] = [d["y1_delta1"] for d in comp]
            series[f"y₁ (δ={p.delta2:.2f})"] = [d["y1_delta2"] for d in comp]
        if t.showY2:
            series[f"y₂ (δ={p.delta1:.2f})"] = [d["y2_delta1"] for d in comp]
            series[f"y₂ (δ={p.delta2:.2f})"] = [d["y2_delta2"] for d in comp]
        if t.showY4:
            series["y₄ (piecewise δ, x₀₂, +b₂)"] = [d["y4_piece"] for d in comp]
        if t.showY5:
            series["y₅ (piecewise δ, x₀₁ — δ สลับ, +b₁)"] = [d["y5_piece"] for d in comp]
        if t.showY3:
            series["Net (δ₁ base)"] = [d["y3_delta1"] for d in comp]
            series["Net (δ₂ base)"] = [d["y3_delta2"] for d in comp]
        if t.showY6:
            series["y₆ (Ref y₁, δ₂)"] = [d["y6_ref_delta2"] for d in comp]
        if t.showY7:
            series["y₇ (Ref y₂, δ₂)"] = [d["y7_ref_delta2"] for d in comp]
        if t.showY8:
            series["y₈ (Call Intrinsic)"] = [d["y8_call_intrinsic"] for d in comp]
        if t.showY9:
            series["y₉ (Put Intrinsic)"] = [d["y9_put_intrinsic"] for d in comp]
        if t.showY10:
            series["y₁₀ (P/L Long)"] = [d["y10_long_pl"] for d in comp]
        if t.showY11:
            series["y₁₁ (P/L Short)"] = [d["y11_short_pl"] for d in comp]

        ref_dots = {}
        if (t.showY1 or t.showY5 or t.showY8):
            ref_dots["x₀₁"] = p.x0_1
        if t.showY6:
            ref_dots["Anchor"] = p.anchorY6
        if (t.showY2 or t.showY4 or t.showY7 or t.showY9):
            ref_dots["x₀₂"] = p.x0_2
        if t.showY10:
            ref_dots["BE₁₀"] = p.longEntryPrice
        if t.showY11:
            ref_dots["BE₁₁"] = p.shortEntryPrice
        if p.includePremium and t.showY8:
            ref_dots["BE₈"] = be_call
        if p.includePremium and t.showY9:
            ref_dots["BE₉"] = be_put

        plot_lines(x, series, "Comparison", y_auto_zero=True, ref_dots=ref_dots)

    # 2) Net only
    with tabs[1]:
        series = {}
        if t.showY3:
            series["Net (δ₁ base)"] = [d["y3_delta1"] for d in comp]
            series["Net (δ₂ base)"] = [d["y3_delta2"] for d in comp]
        if t.showY6:
            series["Benchmark (y₆, δ₂)"] = [d["y6_ref_delta2"] for d in comp]
        ref = {"Anchor": p.anchorY6} if t.showY6 else None
        plot_lines(x, series, "Net + Benchmark", y_auto_zero=True, ref_dots=ref)

    # 3) Overlay
    with tabs[2]:
        series = {"Delta Log Overlay": [d["y_overlay_d2"] for d in comp]}
        plot_lines(x, series, "Delta Log Overlay", y_auto_zero=False)

    # 4) Dynamic Overlay (Net vs 0) + zero crossings
    with tabs[3]:
        y_net = [d["y3_delta2"] for d in comp]
        zs = zero_crossings(y_net, x)
        series = {"Dynamic Log Overlay (Net vs 0)": y_net}
        plot_lines(x, series, "Dynamic Log Overlay", y_auto_zero=False, markers=zs)

    # 5) δ1 Tab
    with tabs[4]:
        series = {}
        if t.showY1: series["y₁"] = [d["y1_delta1"] for d in comp]
        if t.showY2: series["y₂ (δ₁)"] = [d["y2_delta1"] for d in comp]
        if t.showY4: series["y₄ (piecewise δ, x₀₂, +b₂)"] = [d["y4_piece"] for d in comp]
        if t.showY5: series["y₅ (piecewise δ, x₀₁ — δ สลับ, +b₁)"] = [d["y5_piece"] for d in comp]
        if t.showY6: series["y₆ (Ref y₁, δ₁)"] = [d["y6_ref_delta1"] for d in comp]
        if t.showY7: series["y₇ (Ref y₂, δ₁)"] = [d["y7_ref_delta1"] for d in comp]
        if t.showY3: series["y₃ (Net)"] = [d["y3_delta1"] for d in comp]
        if t.showY8: series["y₈ (Call Intrinsic)"] = [d["y8_call_intrinsic"] for d in comp]
        if t.showY9: series["y₉ (Put Intrinsic)"] = [d["y9_put_intrinsic"] for d in comp]
        if t.showY10: series["y₁₀ (P/L Long)"] = [d["y10_long_pl"] for d in comp]
        if t.showY11: series["y₁₁ (P/L Short)"] = [d["y11_short_pl"] for d in comp]
        plot_lines(x, series, f"δ = {p.delta1:.2f}", y_auto_zero=True,
                   ref_dots={"BE₁₀": p.longEntryPrice, "BE₁₁": p.shortEntryPrice} if (t.showY10 or t.showY11) else None)

    # 6) δ2 Tab
    with tabs[5]:
        series = {}
        if t.showY1: series["y₁"] = [d["y1_delta2"] for d in comp]
        if t.showY2: series["y₂ (เดิม, δ₂)"] = [d["y2_delta2"] for d in comp]
        if t.showY4: series["y₄ (piecewise δ, x₀₂, +b₂)"] = [d["y4_piece"] for d in comp]
        if t.showY5: series["y₅ (piecewise δ, x₀₁ — δ สลับ, +b₁)"] = [d["y5_piece"] for d in comp]
        if t.showY6: series["y₆ (Ref y₁, δ₂)"] = [d["y6_ref_delta2"] for d in comp]
        if t.showY7: series["y₇ (Ref y₂, δ₂)"] = [d["y7_ref_delta2"] for d in comp]
        if t.showY3: series["y₃ (Net)"] = [d["y3_delta2"] for d in comp]
        if t.showY8: series["y₈ (Call Intrinsic)"] = [d["y8_call_intrinsic"] for d in comp]
        if t.showY9: series["y₉ (Put Intrinsic)"] = [d["y9_put_intrinsic"] for d in comp]
        if t.showY10: series["y₁₀ (P/L Long)"] = [d["y10_long_pl"] for d in comp]
        if t.showY11: series["y₁₁ (P/L Short)"] = [d["y11_short_pl"] for d in comp]
        plot_lines(x, series, f"δ = {p.delta2:.2f}", y_auto_zero=True,
                   ref_dots={"BE₁₀": p.longEntryPrice, "BE₁₁": p.shortEntryPrice} if (t.showY10 or t.showY11) else None)

    st.markdown("---")
    st.caption("หมายเหตุ: y₁₀,y₁₁ จะถูกนับรวมใน Net ก็ต่อเมื่อเปิด Active เท่านั้น (toggle ด้านบน)")

if __name__ == "__main__":
    main()
