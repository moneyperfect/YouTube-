"""
从 Chrome 浏览器导出 YouTube cookies 供 yt-dlp 使用。
运行方式：双击运行 或 python 导出YouTubeCookies.py

注意：Chrome 运行时会锁定 cookies 数据库。
如果导出失败，请先关闭 Chrome 浏览器（包括后台进程），然后重新运行此脚本。
"""
import ctypes
import sqlite3
import json
import os
import shutil
import tempfile
import base64
import time
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_decrypt(encrypted_bytes: bytes) -> bytes | None:
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


def get_chrome_aes_key() -> bytes:
    local = os.environ.get("LOCALAPPDATA", "")
    local_state_path = Path(local) / "Google/Chrome/User Data/Local State"
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)
    encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
    encrypted_key = base64.b64decode(encrypted_key_b64)[5:]
    return dpapi_decrypt(encrypted_key)


def decrypt_cookie_value(encrypted_value: bytes, key: bytes) -> str:
    if not encrypted_value:
        return ""
    if encrypted_value[:3] in (b"v10", b"v20"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(key)
        try:
            return aesgcm.decrypt(encrypted_value[3:], None).decode("utf-8")
        except Exception:
            return ""
    decrypted = dpapi_decrypt(encrypted_value)
    return decrypted.decode("utf-8") if decrypted else ""


def try_copy_cookie_db(cookie_db: Path) -> str | None:
    """Try to copy the cookie DB. Returns temp path if successful, None if locked."""
    tmp_db = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(cookie_db, tmp_db)
        return tmp_db
    except PermissionError:
        if os.path.exists(tmp_db):
            os.unlink(tmp_db)
        return None


def main():
    print("=" * 50)
    print("  YouTube Cookies 导出工具")
    print("=" * 50)
    print()

    # Find Chrome cookie database
    local = os.environ.get("LOCALAPPDATA", "")
    cookie_db = Path(local) / "Google/Chrome/User Data/Default/Network/Cookies"
    if not cookie_db.exists():
        cookie_db = Path(local) / "Google/Chrome/User Data/Network/Cookies"
    if not cookie_db.exists():
        print("[错误] 未找到 Chrome cookies 数据库")
        print("请确认已安装 Chrome 浏览器。")
        input("\n按回车退出...")
        return

    print(f"Chrome cookies: {cookie_db}")

    try:
        aes_key = get_chrome_aes_key()
        print("解密密钥: OK")
    except Exception as e:
        print(f"[错误] 获取解密密钥失败: {e}")
        input("\n按回车退出...")
        return

    # Try to copy the DB (Chrome locks it when running)
    print()
    tmp_db = try_copy_cookie_db(cookie_db)
    if tmp_db is None:
        print("[提示] Chrome 正在运行，cookies 数据库被锁定。")
        print()
        print("请执行以下操作之一：")
        print("  1. 关闭所有 Chrome 窗口（包括后台进程），然后按回车重试")
        print("  2. 或者在 Chrome 中安装扩展「Get cookies.txt LOCALLY」")
        print("     打开 youtube.com -> 点击扩展图标 -> Export")
        print(f"     保存到: D:\\YTSubViewerData\\cookies.txt")
        print()

        for attempt in range(3):
            input(f"按回车重试 (剩余 {3 - attempt} 次)...")
            tmp_db = try_copy_cookie_db(cookie_db)
            if tmp_db:
                print("复制成功!")
                break
            print("Chrome 仍在运行，请先关闭 Chrome...")

        if tmp_db is None:
            print("\n[失败] 无法读取 cookies。请关闭 Chrome 后重新运行此脚本。")
            input("\n按回车退出...")
            return

    try:
        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT host_key, name, path, expires_utc, is_secure, is_httponly, encrypted_value
            FROM cookies
            WHERE host_key LIKE '%youtube%' OR host_key LIKE '%google%'
            """
        )
        rows = cursor.fetchall()
        conn.close()
    finally:
        if os.path.exists(tmp_db):
            os.unlink(tmp_db)

    print(f"找到 {len(rows)} 条 YouTube/Google cookies")

    # Write Netscape format
    output_path = Path("D:/YTSubViewerData/cookies.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for host, name, path, expires, secure, httponly, enc_value in rows:
            value = decrypt_cookie_value(enc_value, aes_key)
            if not value:
                continue
            secure_str = "TRUE" if secure else "FALSE"
            httponly_str = "TRUE" if httponly else "FALSE"
            domain = host if host.startswith(".") else f".{host}"
            unix_ts = int((expires / 1000000) - 11644473600) if expires > 0 else 0
            f.write(f"{domain}\t{httponly_str}\t{path}\t{secure_str}\t{unix_ts}\t{name}\t{value}\n")
            count += 1

    print()
    print(f"已导出 {count} 条有效 cookies")
    print(f"保存到: {output_path}")
    print()
    print("现在可以运行 YTSubViewer 了！")
    input("\n按回车退出...")


if __name__ == "__main__":
    main()
