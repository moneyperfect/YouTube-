"""Helper functions for API routes."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ytsubviewer.config import Settings
from ytsubviewer.models import TranslationControlConfig


YOUTUBE_URL_RE = re.compile(
    r"^https?://(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
)


def validate_youtube_url(url: str) -> None:
    if not YOUTUBE_URL_RE.match(url):
        raise HTTPException(status_code=400, detail=f"无效的 YouTube 链接：{url}")


def build_controls(style_preset: str, glossary_text: str, protected_terms_text: str) -> TranslationControlConfig:
    temp_settings = Settings(
        translation_style_preset=(style_preset or "default").strip() or "default",
        translation_glossary_json=glossary_text.strip(),
        translation_protected_terms_json=protected_terms_text.strip(),
    )
    return temp_settings.translation_controls()


def strategy_text(manual_lang: str | None, automatic_lang: str | None) -> str:
    if manual_lang:
        return f"优先使用人工英文字幕：{manual_lang}"
    if automatic_lang:
        return f"未检测到人工英文字幕，将优先使用 YouTube 自动英文字幕：{automatic_lang}"
    return "未检测到英文字幕，将回退到本地转写。"


def resolve_download_path(current_settings: Settings, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在。")

    resolved = path.resolve()
    allowed_roots = [
        current_settings.data_root.resolve(),
        current_settings.project_root.resolve(),
        current_settings.config_dir.resolve(),
    ]
    if not any(_is_within_root(resolved, root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="不允许访问这个文件。")
    return resolved


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath([str(path), str(root)])
    except ValueError:
        return False
    return common.lower() == str(root).lower()


def resolve_control_texts(payload, profile) -> dict[str, str]:
    style_preset = (payload.style_preset or "default").strip() or "default"
    glossary_text = payload.glossary_text
    protected_terms_text = payload.protected_terms_text
    if getattr(payload, "use_creator_defaults", True) and profile is not None:
        if style_preset == "default" and profile.style_preset:
            style_preset = profile.style_preset
        if not glossary_text.strip() and profile.glossary_text:
            glossary_text = profile.glossary_text
        if not protected_terms_text.strip() and profile.protected_terms_text:
            protected_terms_text = profile.protected_terms_text
    return {
        "style_preset": style_preset,
        "glossary_text": glossary_text,
        "protected_terms_text": protected_terms_text,
    }


def load_state_for_work_dir(work_dir: Path) -> dict[str, Any]:
    from ytsubviewer.job_state import load_job_state
    state = load_job_state(work_dir)
    if not state:
        raise HTTPException(status_code=404, detail="当前任务缺少可用状态，请先生成字幕。")
    return state


def load_state_for_task(runtime: dict[str, Any], task_id: str) -> dict[str, Any]:
    from ytsubviewer.job_state import load_job_state
    snapshot = runtime["generation_manager"].get_task(task_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    if not snapshot.work_dir:
        raise HTTPException(status_code=400, detail="当前任务还没有可编辑结果。")
    state = load_job_state(Path(snapshot.work_dir))
    if not state:
        raise HTTPException(status_code=404, detail="当前任务缺少可编辑状态。")
    return state
