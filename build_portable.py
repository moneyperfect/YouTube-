"""
YTSubViewer 便携版构建脚本

自动下载 Embeddable Python、安装依赖、打包项目为完全独立的绿色版。

用法:
    python build_portable.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────

PYTHON_VERSION = "3.11.9"
PYTHON_PLATFORM = "win-amd64"
PYTHON_ZIP_NAME = f"python-{PYTHON_VERSION}-{PYTHON_PLATFORM}.zip"
PYTHON_DOWNLOAD_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP_NAME}"
)

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "dist" / "YTSubViewer"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
PYTHON_DIR = RUNTIME_DIR / "python"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def log(tag: str, message: str) -> None:
    print(f"  [{tag}] {message}")


def log_step(step: int, total: int, message: str) -> None:
    print(f"\n{'='*60}")
    print(f"  步骤 {step}/{total}: {message}")
    print(f"{'='*60}")


def download_file(url: str, dest: Path) -> None:
    log("下载", url)
    log("  目标", str(dest))

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(100, downloaded * 100 // total_size)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            print(f"\r  下载中: {percent}% ({mb_done:.1f}/{mb_total:.1f} MB)", end="", flush=True)

    urllib.request.urlretrieve(url, str(dest), reporthook=_progress)
    print()
    log("完成", f"{dest.stat().st_size / (1024*1024):.1f} MB")


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    log("解压", f"{zip_path.name} -> {dest_dir}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    log("完成", f"解压了 {len(list(dest_dir.rglob('*')))} 个文件")


def run_cmd(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        log("错误", f"命令失败: {' '.join(cmd)}")
        if result.stdout.strip():
            log("stdout", result.stdout.strip()[-500:])
        if result.stderr.strip():
            log("stderr", result.stderr.strip()[-500:])
        raise RuntimeError(f"命令执行失败 (exit {result.returncode})")
    return result


def safe_copytree(src: Path, dst: Path, *, ignore_names: set[str] | None = None) -> int:
    ignore = ignore_names or set()
    count = 0
    if not src.exists():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in ignore or item.name.startswith("."):
            continue
        dest = dst / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
            count += 1
        else:
            shutil.copy2(item, dest)
            count += 1
    return count


def ensure_pip_embedded(python_exe: Path) -> None:
    """在 Embeddable Python 中引导 pip。"""
    # 引导 pip（会安装到 python_dir/Lib/site-packages/）
    log("引导", "运行 ensurepip 安装 pip...")
    run_cmd([str(python_exe), "-m", "ensurepip", "--default-pip"])

    # 升级 pip
    log("升级", "升级 pip 到最新版本...")
    run_cmd([str(python_exe), "-m", "pip", "install", "--upgrade", "pip", "--no-warn-script-location"])

    log("完成", "pip 已就绪")


def install_requirements(python_exe: Path, requirements: Path) -> None:
    """使用 pip 安装依赖到 site-packages。"""
    log("安装", f"安装依赖: {requirements.name}")
    run_cmd([
        str(python_exe), "-m", "pip", "install",
        "-r", str(requirements),
        "--no-warn-script-location",
        "--disable-pip-version-check",
    ])


def create_pth_file(python_dir: Path) -> None:
    """在 Embeddable Python 中创建/修改 ._pth 文件以启用 site-packages。

    Embeddable Python 默认的 ._pth 文件中 `import site` 是被注释掉的，
    需要取消注释才能让 Python 读取 Lib/site-packages/ 下安装的包。
    """
    pth_candidates = list(python_dir.glob("python*._pth"))
    if not pth_candidates:
        # 没有找到 ._pth 文件，创建一个
        short_ver = PYTHON_VERSION.replace(".", "")[:2]
        pth_file = python_dir / f"python{short_ver}._pth"
        pth_file.write_text(
            f"python{short_ver}.zip\n"
            ".\n"
            "Lib\n"
            "Lib/site-packages\n"
            "import site\n",
            encoding="utf-8",
        )
        log("创建", f"._pth 文件: {pth_file.name}")
        return

    for pth_file in pth_candidates:
        content = pth_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        modified = False

        # 取消注释 import site（Embeddable Python 默认注释掉此行）
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == "#import site" or stripped == "# import site":
                new_lines.append("import site")
                modified = True
            else:
                new_lines.append(line)
        if not modified:
            # 检查是否已经有未注释的 import site
            if not any(line.strip() == "import site" for line in new_lines):
                new_lines.append("import site")
                modified = True

        # 确保有 Lib/site-packages 路径
        if "site-packages" not in "\n".join(new_lines):
            # 在 import site 之前插入 Lib/site-packages
            final_lines = []
            for line in new_lines:
                if line.strip() == "import site":
                    final_lines.append("Lib/site-packages")
                final_lines.append(line)
            new_lines = final_lines
            modified = True

        if modified:
            pth_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            log("修改", f"._pth 文件: {pth_file.name} (已启用 site-packages)")
        else:
            log("跳过", f"._pth 文件: {pth_file.name} (已正确配置)")


def write_launcher_bat(output_dir: Path) -> None:
    """生成启动脚本。"""
    bat = output_dir / "启动YTSubViewer.bat"
    bat.write_text(
        "@echo off\n"
        "chcp 65001 >nul 2>&1\n"
        "title YTSubViewer\n"
        "cd /d \"%~dp0\"\n"
        "\n"
        "set \"PYTHONDONTWRITEBYTECODE=1\"\n"
        "set \"PYTHONPATH=%~dp0src\"\n"
        "set \"PATH=%~dp0runtime\\python;%~dp0.tools\\ffmpeg\\bin;%~dp0.tools\\mpv;%PATH%\"\n"
        "set \"YTSUBVIEWER_DATA_ROOT=%~dp0workspace\"\n"
        "set \"HF_HOME=%~dp0workspace\\.cache\\huggingface\"\n"
        "set \"HF_HUB_OFFLINE=1\"\n"
        "set \"YTSUBVIEWER_RESOURCE_ROOT=%~dp0\"\n"
        "\n"
        "if not exist \"%~dp0workspace\" mkdir \"%~dp0workspace\"\n"
        "if not exist \"%~dp0workspace\\.cache\" mkdir \"%~dp0workspace\\.cache\"\n"
        "\n"
        "echo.\n"
        "echo   YTSubViewer - YouTube 字幕翻译工作台\n"
        "echo   正在启动，请稍候...\n"
        "echo.\n"
        "\n"
        "\"%~dp0runtime\\python\\python.exe\" \"%~dp0app.py\" %*\n"
        "\n"
        "if errorlevel 1 (\n"
        "    echo.\n"
        "    echo   应用异常退出，请检查日志。\n"
        "    pause\n"
        ")\n",
        encoding="utf-8",
    )
    log("生成", "启动YTSubViewer.bat")


def write_launcher_vbs(output_dir: Path) -> None:
    """生成无窗口启动器（隐藏命令行黑框）。"""
    vbs = output_dir / "启动YTSubViewer(后台).vbs"
    vbs.write_text(
        'Set WshShell = CreateObject("WScript.Shell")\n'
        'WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject")'
        '.GetParentFolderName(WScript.ScriptFullName)\n'
        'WshShell.Run "cmd /c 启动YTSubViewer.bat", 0, False\n',
        encoding="utf-8",
    )
    log("生成", "启动YTSubViewer(后台).vbs (无窗口启动)")


def write_readme(output_dir: Path) -> None:
    """生成使用说明。"""
    readme = output_dir / "使用说明.txt"
    readme.write_text(
        "YTSubViewer - YouTube 字幕翻译工作台 (便携版)\n"
        "===============================================\n"
        "\n"
        "启动方式:\n"
        "  双击「启动YTSubViewer.bat」启动（显示命令行窗口）\n"
        "  或双击「启动YTSubViewer(后台).vbs」启动（无窗口）\n"
        "\n"
        "首次使用:\n"
        "  1. 启动后浏览器会自动打开\n"
        "  2. 如提示激活，请输入激活码\n"
        "  3. 在「应用设置」中填写 DeepSeek API Key\n"
        "  4. 粘贴 YouTube 链接，点击「生成字幕」\n"
        "\n"
        "目录说明:\n"
        "  runtime/      - Python 运行时和依赖库（勿删）\n"
        "  src/          - 应用源码（勿删）\n"
        "  workspace/    - 所有任务数据和配置（可备份）\n"
        "  .tools/       - ffmpeg 和 mpv 工具（如存在）\n"
        "  .env          - 环境变量配置（可选）\n"
        "\n"
        "便携特性:\n"
        "  - 无需安装 Python，运行时已内置\n"
        "  - 无需安装 ffmpeg/mpv，工具已内嵌（如 .tools 目录存在）\n"
        "  - 所有数据存储在 workspace/ 目录，跟随应用走\n"
        "  - 整个文件夹拷到任意 Windows 电脑即可使用\n"
        "\n"
        "环境变量（可在 .env 文件中配置）:\n"
        "  DEEPSEEK_API_KEY     - DeepSeek API 密钥\n"
        "  WHISPER_MODEL        - Whisper 转写模型名称\n"
        "  HF_HUB_OFFLINE       - 设为 1 禁止联网下载模型\n"
        "\n"
        "官方网站: https://github.com/your-org/YTSubViewer\n",
        encoding="utf-8",
    )
    log("生成", "使用说明.txt")


def create_dotenv_template(output_dir: Path) -> None:
    """在构建目录创建 .env 模板（如果不存在）。"""
    env_path = output_dir / ".env.example"
    if not env_path.exists():
        env_path.write_text(
            "DEEPSEEK_API_KEY=your_key_here\n"
            "WHISPER_MODEL=distil-large-v3\n"
            "HF_HUB_OFFLINE=1\n",
            encoding="utf-8",
        )


def get_dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> None:
    start_time = time.time()
    total_steps = 5

    print()
    print("=" * 60)
    print("  YTSubViewer 便携版构建工具")
    print(f"  Python {PYTHON_VERSION} | {PYTHON_PLATFORM}")
    print(f"  项目目录: {PROJECT_ROOT}")
    print(f"  输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    # ── 步骤 1: 准备输出目录 ──────────────────────────────────────────────────
    log_step(1, total_steps, "准备输出目录")

    if OUTPUT_DIR.exists():
        log("清理", f"删除已有目录: {OUTPUT_DIR}")
        shutil.rmtree(OUTPUT_DIR)

    for d in [OUTPUT_DIR, RUNTIME_DIR, PIP_DIR, PYTHON_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    log("完成", "目录结构已创建")

    # ── 步骤 2: 下载并解压 Embeddable Python ──────────────────────────────────
    log_step(2, total_steps, "下载 Embeddable Python")

    zip_path = PROJECT_ROOT / ".tmp" / PYTHON_ZIP_NAME
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    if zip_path.exists() and zip_path.stat().st_size > 1024:
        log("复用", f"已有缓存: {zip_path.name}")
    else:
        download_file(PYTHON_DOWNLOAD_URL, zip_path)

    extract_zip(zip_path, PYTHON_DIR)

    # 验证 python.exe 存在
    python_exe = PYTHON_DIR / "python.exe"
    if not python_exe.exists():
        raise FileNotFoundError(f"python.exe 未找到: {python_exe}")
    log("验证", f"python.exe 就绪: {python_exe}")

    # ── 步骤 3: 配置 pip 并安装依赖 ───────────────────────────────────────────
    log_step(3, total_steps, "配置 pip 并安装项目依赖")

    # 创建 ._pth 文件启用 site-packages
    create_pth_file(PYTHON_DIR)

    # 引导 pip
    ensure_pip_embedded(python_exe)

    # 安装项目依赖
    if REQUIREMENTS_FILE.exists():
        install_requirements(python_exe, REQUIREMENTS_FILE)
    else:
        log("警告", f"未找到 {REQUIREMENTS_FILE.name}，跳过依赖安装")

    # ── 步骤 4: 迁移项目组件 ──────────────────────────────────────────────────
    log_step(4, total_steps, "迁移项目组件")

    # 复制核心文件
    for filename in ["app.py", "requirements.txt", "sitecustomize.py"]:
        src = PROJECT_ROOT / filename
        if src.exists():
            shutil.copy2(src, OUTPUT_DIR / filename)
            log("复制", filename)

    # 复制 src 目录
    src_count = safe_copytree(
        PROJECT_ROOT / "src",
        OUTPUT_DIR / "src",
        ignore_names={"__pycache__", ".pytest_cache", "*.egg-info"},
    )
    log("复制", f"src/ ({src_count} 项)")

    # 复制 .tools 目录（如果存在）
    tools_src = PROJECT_ROOT / ".tools"
    if tools_src.exists():
        tools_count = safe_copytree(tools_src, OUTPUT_DIR / ".tools")
        log("复制", f".tools/ ({tools_count} 项)")
    else:
        log("跳过", ".tools/ 目录不存在，便携版需自行放置 ffmpeg/mpv")

    # 复制 models 目录（如果存在）
    models_src = PROJECT_ROOT / "models"
    if models_src.exists():
        models_count = safe_copytree(models_src, OUTPUT_DIR / "models")
        log("复制", f"models/ ({models_count} 项)")
    else:
        log("跳过", "models/ 目录不存在，Whisper 模型需运行时下载")

    # 创建 workspace 目录
    workspace = OUTPUT_DIR / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".cache").mkdir(parents=True, exist_ok=True)
    log("创建", "workspace/ 数据目录")

    # 创建 .env 模板
    create_dotenv_template(OUTPUT_DIR)

    # ── 步骤 5: 生成启动器 ───────────────────────────────────────────────────
    log_step(5, total_steps, "生成启动器")

    write_launcher_bat(OUTPUT_DIR)
    write_launcher_vbs(OUTPUT_DIR)
    write_readme(OUTPUT_DIR)

    # ── 完成 ──────────────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    output_size = get_dir_size(OUTPUT_DIR)

    print()
    print("=" * 60)
    print("  构建完成!")
    print(f"  输出目录: {OUTPUT_DIR}")
    print(f"  总大小:   {output_size / (1024*1024):.1f} MB")
    print(f"  耗时:     {elapsed:.1f} 秒")
    print()
    print("  启动方式:")
    print("    双击 dist\\YTSubViewer\\启动YTSubViewer.bat")
    print("    或双击 dist\\YTSubViewer\\启动YTSubViewer(后台).vbs (无窗口)")
    print("=" * 60)
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n构建已取消。")
        sys.exit(1)
    except Exception as exc:
        print(f"\n构建失败: {exc}")
        sys.exit(1)
