"""Session — config + cache bundle (.zip) export/import, local and from GitHub.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import hashlib
import io
import json
import os
import requests
import time
import zipfile
from typing import Any, Dict, Optional, Tuple

from .config import BUNDLE_VERSION, CACHE_FORMAT_VERSION, CONFIG_SCHEMA_VERSION, GITHUB_BUNDLE_URL, MAX_CACHE_ENTRY_BYTES, TIMEOUT_GITHUB_DOWNLOAD
from .osm import export_cache_as_zip, import_cache_from_zip
from .state import StateManager


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _build_bundle_manifest() -> Dict[str, Any]:
    return {
        "bundle_version": BUNDLE_VERSION,
        "app_name": "Rent_Gradient",
        "app_version": "streamlit-monolith",
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "cache_format_version": CACHE_FORMAT_VERSION,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform_info": {"python": os.sys.version.split()[0], "os": os.name},
        "import_policy": {"mode": "fallback"},
    }


def export_bundle_zip() -> bytes:
    """Export all-in-one bundle.zip with separated config + cache files."""
    config_bytes = StateManager.export_config().encode("utf-8")
    cache_bytes = export_cache_as_zip() or b""
    manifest = _build_bundle_manifest()
    manifest["cache_present"] = bool(cache_bytes)
    manifest["integrity_checksums"] = {
        "config/config.json": _sha256_bytes(config_bytes),
        "cache/cache.zip": _sha256_bytes(cache_bytes),
    }
    manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    checksums = [
        f"{_sha256_bytes(manifest_bytes)}  manifest.json",
        f"{_sha256_bytes(config_bytes)}  config/config.json",
        f"{_sha256_bytes(cache_bytes)}  cache/cache.zip",
    ]
    checksum_bytes = ("\n".join(checksums) + "\n").encode("utf-8")
    readme_bytes = (
        "Rent_Gradient bundle.zip\n"
        "- manifest.json: compatibility & policy\n"
        "- config/config.json: user settings + precomputed results\n"
        "- cache/cache.zip: OSM graph cache archive\n"
    ).encode("utf-8")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("config/config.json", config_bytes)
        zf.writestr("cache/cache.zip", cache_bytes)
        zf.writestr("checksums.sha256", checksum_bytes)
        zf.writestr("README.txt", readme_bytes)
    return out.getvalue()


def import_bundle_zip(bundle_bytes: bytes) -> Dict[str, Any]:
    """Import bundle.zip with validation and fallback policy."""
    result = {"success": False, "config_loaded": False, "cache_loaded": False, "warnings": [], "errors": []}
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
            required = {"manifest.json", "config/config.json", "cache/cache.zip", "checksums.sha256"}
            names = set(zf.namelist())
            missing = required - names
            if missing:
                result["errors"].append(f"ไฟล์ไม่ครบใน bundle: {', '.join(sorted(missing))}")
                return result

            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("bundle_version") != BUNDLE_VERSION:
                result["errors"].append("bundle_version ไม่รองรับ")
                return result
            if manifest.get("config_schema_version") != CONFIG_SCHEMA_VERSION:
                result["errors"].append("config schema ไม่เข้ากัน")
                return result

            config_bytes = zf.read("config/config.json")
            cache_bytes = zf.read("cache/cache.zip")
            if len(cache_bytes) > MAX_CACHE_ENTRY_BYTES:
                result["warnings"].append("cache ใหญ่เกินกำหนด ระบบจะโหลดเฉพาะ config")
                cache_bytes = b""

            declared = manifest.get("integrity_checksums", {})
            if declared.get("config/config.json") != _sha256_bytes(config_bytes):
                result["errors"].append("checksum config ไม่ถูกต้อง")
                return result
            if declared.get("cache/cache.zip") != _sha256_bytes(cache_bytes if cache_bytes else b""):
                result["warnings"].append("checksum cache ไม่ถูกต้อง โหลดเฉพาะ config")
                cache_bytes = b""

            StateManager.import_config(json.loads(config_bytes.decode("utf-8")))
            result["config_loaded"] = True
            if cache_bytes:
                cache_result = import_cache_from_zip(cache_bytes)
                if cache_result.get("success"):
                    result["cache_loaded"] = True
                else:
                    result["warnings"].append("cache ใช้งานไม่ได้ โหลดเฉพาะ config")
            result["success"] = result["config_loaded"]
    except Exception as e:
        result["errors"].append(f"นำเข้า bundle ล้มเหลว: {str(e)}")
    return result


def download_github_bundle() -> Tuple[Optional[bytes], Optional[str]]:
    """Download fixed-source bundle ZIP from GitHub."""
    try:
        response = requests.get(GITHUB_BUNDLE_URL, timeout=TIMEOUT_GITHUB_DOWNLOAD)
        response.raise_for_status()
        return response.content, None
    except requests.RequestException as e:
        return None, f"ดาวน์โหลด Bundle จาก GitHub ไม่สำเร็จ: {str(e)}"
