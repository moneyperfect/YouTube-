"""Automatic YouTube cookie management.

Strategy:
1. Use existing cookies.txt if fresh (< 6 hours old)
2. If Chrome is NOT running, extract cookies directly from Chrome DB
3. If Chrome IS running, prompt user to briefly close Chrome, then extract
4. After extraction, auto-relaunch Chrome
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sqlite3
import time
import ctypes
from pathlib import Path

logger = logging.getLogger(__name__)

COOKIE_MAX_AGE_HOURS = 6
_YT_URL = "https://www.youtube.com"


def _cookies_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours > COOKIE_MAX_AGE_HOURS:
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [l for l in text.splitlines() if l and not l.startswith("#")]
        return any("youtube" in l.lower() for l in lines)
    except OSError:
        return False


def _is_chrome_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=5
        )
        return "chrome.exe" in result.stdout.lower()
    except Exception:
        return False


def _find_chrome_db() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local) / "Google/Chrome/User Data/Default/Network/Cookies",
        Path(local) / "Google/Chrome/User Data/Network/Cookies",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_chrome_exe() -> str | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_decrypt(encrypted_bytes: bytes) -> bytes | None:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = DATA_BLOB(
        len(encrypted_bytes),
        ctypes.create_string_buffer(encrypted_bytes, len(encrypted_bytes)),
    )
    blob_out = DATA_BLOB()
    if crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        kernel32.LocalFree(blob_out.pbData)
        return data
    return None


def _get_chrome_key() -> bytes | None:
    try:
        local = os.environ.get("LOCALAPPDATA", "")
        state_path = Path(local) / "Google/Chrome/User Data/Local State"
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        enc_key_b64 = state["os_crypt"]["encrypted_key"]
        import base64
        enc_key = base64.b64decode(enc_key_b64)[5:]  # strip "DPAPI" prefix
        return _dpapi_decrypt(enc_key)
    except Exception as exc:
        logger.warning("Failed to get Chrome key: %s", exc)
        return None


def _decrypt_cookie(enc_value: bytes, key: bytes) -> str:
    if not enc_value:
        return ""
    if enc_value[:3] in (b"v10", b"v20"):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            nonce = enc_value[3:15]
            ct = enc_value[15:]
            return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
        except Exception:
            return ""
    decrypted = _dpapi_decrypt(enc_value)
    return decrypted.decode("utf-8") if decrypted else ""


def _extract_chrome_cookies(db_path: Path, output: Path) -> bool:
    """Read Chrome cookies DB and write Netscape format. Returns True if any cookies exported."""
    key = _get_chrome_key()
    if not key:
        logger.warning("Cannot get Chrome decryption key")
        return False

    try:
        # Copy database to temp location to avoid lock issues when Chrome is running
        import shutil
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        shutil.copy2(db_path, tmp_path)

        try:
            conn = sqlite3.connect(str(tmp_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT host_key, name, path, expires_utc, is_secure, is_httponly, encrypted_value "
                "FROM cookies WHERE host_key LIKE '%youtube%' OR host_key LIKE '%google%'"
            )
            rows = cursor.fetchall()
            conn.close()
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Cannot read Chrome DB: %s", exc)
        return False

    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(output, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# Extracted from Chrome\n")
        for host, name, path, expires, secure, httponly, enc_value in rows:
            value = _decrypt_cookie(enc_value, key)
            if not value:
                continue
            secure_str = "TRUE" if secure else "FALSE"
            httponly_str = "TRUE" if httponly else "FALSE"
            domain = host if host.startswith(".") else f".{host}"
            unix_ts = int((expires / 1000000) - 11644473600) if expires > 0 else 0
            f.write(f"{domain}\t{httponly_str}\t{path}\t{secure_str}\t{unix_ts}\t{name}\t{value}\n")
            count += 1

    logger.info("Extracted %d cookies from Chrome -> %s", count, output)
    return count > 0


def ensure_cookies(data_root: Path) -> Path | None:
    """Ensure a valid cookies.txt exists. Returns path or None if login needed."""
    cookies_path = data_root / "cookies.txt"

    # 1. Already fresh?
    if _cookies_fresh(cookies_path):
        return cookies_path

    # 2. Try to extract cookies (works even when Chrome is running)
    db_path = _find_chrome_db()
    if db_path:
        logger.info("Extracting cookies from Chrome...")
        if _extract_chrome_cookies(db_path, cookies_path):
            return cookies_path

    # 3. No Chrome database found
    return None


def extract_after_chrome_close(data_root: Path) -> Path | None:
    """Called when user confirms Chrome is closed. Extracts cookies and relaunches Chrome."""
    cookies_path = data_root / "cookies.txt"
    db_path = _find_chrome_db()
    if not db_path:
        logger.error("Chrome cookies database not found")
        return None

    success = _extract_chrome_cookies(db_path, cookies_path)

    # Auto-relaunch Chrome
    chrome_exe = _find_chrome_exe()
    if chrome_exe:
        try:
            subprocess.Popen([chrome_exe], start_new_session=True)
            logger.info("Chrome relaunched")
        except Exception as exc:
            logger.warning("Failed to relaunch Chrome: %s", exc)

    return cookies_path if success else None
