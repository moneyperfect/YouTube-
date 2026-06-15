"""Serialization helpers for API responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ytsubviewer.background_jobs import GenerationJobSnapshot, TaskSnapshot
from ytsubviewer.config import Settings, decrypt_value
from ytsubviewer.job_state import artifacts_from_state, load_job_state
from ytsubviewer.models import JobArtifacts
from ytsubviewer.pipeline import SubtitlePipeline
from ytsubviewer.providers import get_builtin_providers
from ytsubviewer.services.translate import DeepSeekTranslator
from ytsubviewer.utils import format_duration, format_eta


def serialize_style_presets() -> list[dict[str, str]]:
    presets = DeepSeekTranslator.available_style_presets()
    return [
        {
            "name": preset.name,
            "label": preset.label,
            "description": preset.description,
        }
        for preset in presets.values()
    ]


def serialize_performance_modes() -> list[dict[str, str]]:
    return [
        {
            "name": "fast",
            "label": "Fast",
            "description": "优先速度，适合快速预览和短视频批量处理。",
        },
        {
            "name": "balanced",
            "label": "Balanced",
            "description": "默认模式，平衡速度、稳定性和导出质量。",
        },
        {
            "name": "quality",
            "label": "Quality",
            "description": "优先质量，适合正式交付前的最终成品。",
        },
    ]


def serialize_settings(current_settings: Settings) -> dict[str, Any]:
    custom_base_url = ""
    try:
        if current_settings.config_path.exists():
            _user = json.loads(current_settings.config_path.read_text(encoding="utf-8")) or {}
            custom_base_url = str(_user.get("custom_base_url", "")).strip()
    except Exception:
        pass
    return {
        "api_key_ready": bool(current_settings.deepseek_api_key),
        "data_root": str(current_settings.data_root),
        "config_path": str(current_settings.config_path),
        "prefer_automatic_subtitles": current_settings.prefer_automatic_subtitles,
        "update_feed_url": current_settings.update_feed_url,
        "max_concurrent_tasks": current_settings.max_concurrent_tasks,
        "target_language": current_settings.target_language,
        "provider_name": current_settings.provider_name,
        "model_name": current_settings.model_name,
        "custom_base_url": custom_base_url,
    }


def serialize_providers(current_settings: Settings) -> list[dict[str, Any]]:
    providers = get_builtin_providers()
    result = []
    for p in providers:
        stored_key = ""
        user_settings = {}
        try:
            config_path = current_settings.config_path
            if config_path.exists():
                user_settings = json.loads(config_path.read_text(encoding="utf-8")) or {}
            encrypted = user_settings.get(f"api_key_{p.name}", "")
            if encrypted:
                stored_key = decrypt_value(encrypted)
        except Exception:
            pass

        if not stored_key and p.name == "deepseek":
            try:
                legacy_enc = user_settings.get("deepseek_api_key_encrypted", "")
                if legacy_enc:
                    stored_key = decrypt_value(legacy_enc)
            except Exception:
                pass
        api_key = stored_key or p.resolve_api_key() or (current_settings.deepseek_api_key if p.name == "deepseek" else "")
        has_key = bool(api_key) or p.name == "ollama"
        effective_base_url = p.base_url
        if p.name == current_settings.provider_name:
            custom_url = user_settings.get("custom_base_url", "")
            if custom_url:
                effective_base_url = custom_url
        result.append({
            "name": p.name,
            "label": p.label,
            "base_url": effective_base_url,
            "models": p.models,
            "has_key": has_key,
            "is_current": p.name == current_settings.provider_name,
        })
    return result


def serialize_current_job(runtime: dict[str, Any]) -> dict[str, Any] | None:
    active = runtime["generation_manager"].get_active_task()
    if active is not None:
        return serialize_job(runtime, active)
    snapshot = runtime["generation_manager"].get_current_snapshot()
    if snapshot is None:
        return None
    return serialize_job(runtime, snapshot)


def serialize_history(runtime: dict[str, Any], *, limit: int = 30) -> list[dict[str, Any]]:
    tasks = runtime["generation_manager"].list_tasks(limit=limit)
    return [serialize_job(runtime, task) for task in tasks]


def serialize_job(runtime: dict[str, Any], snapshot: GenerationJobSnapshot | TaskSnapshot) -> dict[str, Any]:
    current_pipeline: SubtitlePipeline = runtime["pipeline"]
    state = _state_from_snapshot(snapshot)
    return {
        "job_id": snapshot.task_id,
        "kind": snapshot.kind,
        "status": snapshot.status,
        "stage": snapshot.stage,
        "progress": snapshot.progress,
        "progress_percent": max(1, round(snapshot.progress * 100)) if snapshot.status in {"running", "pending"} else 100,
        "title": snapshot.title,
        "duration_seconds": snapshot.duration_seconds,
        "duration_text": format_duration(snapshot.duration_seconds),
        "strategy_text": snapshot.strategy_text,
        "thumbnail_url": snapshot.thumbnail_url,
        "work_dir": snapshot.work_dir,
        "logs": list(snapshot.log_lines),
        "error": snapshot.error,
        "performance_mode": snapshot.performance_mode,
        "bilingual": snapshot.bilingual,
        "preview": snapshot.preview,
        "current_step": snapshot.current_step,
        "total_steps": snapshot.total_steps,
        "completed_items": snapshot.completed_items,
        "total_items": snapshot.total_items,
        "eta_text": format_eta(snapshot.eta_seconds),
        "can_retry": snapshot.status in {"failed", "completed", "cancelled"},
        "can_cancel": snapshot.status in {"pending", "running"},
        "state": serialize_state(current_pipeline, state) if state else None,
    }


def _state_from_snapshot(snapshot: GenerationJobSnapshot | TaskSnapshot) -> dict[str, Any] | None:
    if not snapshot.work_dir:
        return None
    return load_job_state(Path(snapshot.work_dir))


def serialize_state(current_pipeline: SubtitlePipeline, state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state:
        return None
    artifacts = artifacts_from_state(state)
    if artifacts is not None:
        artifacts = current_pipeline.ensure_subtitle_artifacts(artifacts)
        artifacts = current_pipeline.ensure_quality_report(artifacts)
        state = load_job_state(artifacts.work_dir) or state

    return {
        "status": str(state.get("status", "")).strip() or "idle",
        "video_id": state.get("video_id", ""),
        "title": state.get("title", ""),
        "duration_seconds": int(state["duration_seconds"]) if state.get("duration_seconds") else None,
        "duration_text": format_duration(int(state["duration_seconds"])) if state.get("duration_seconds") else "",
        "source_kind": state.get("source_kind", ""),
        "work_dir": state.get("work_dir", ""),
        "downloads": serialize_downloads(state),
        "quality_report_path": state.get("quality_report_path", ""),
        "quality_report": dict(state.get("quality_report") or {}),
    }


def serialize_downloads(state: dict[str, Any]) -> dict[str, dict[str, str]]:
    files = {
        "video": state.get("video_path", ""),
        "subtitle": state.get("chinese_subtitle_path", ""),
        "chinese_ass": state.get("chinese_ass_path", ""),
        "bilingual_ass": state.get("bilingual_ass_path", ""),
        "quality_report": state.get("quality_report_path", ""),
        "burned_chinese_video": state.get("burned_chinese_video_path", ""),
        "burned_bilingual_video": state.get("burned_bilingual_video_path", ""),
    }
    payload: dict[str, dict[str, str]] = {}
    for key, raw_path in files.items():
        path_text = str(raw_path or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if not path.exists():
            continue
        payload[key] = {
            "path": str(path),
            "name": path.name,
            "url": f"/api/file?path={quote(str(path))}",
        }
    return payload


def serialize_metadata(metadata) -> dict[str, Any]:
    return {
        "video_id": metadata.video_id,
        "title": metadata.title,
        "duration_seconds": metadata.duration_seconds,
        "duration_text": format_duration(metadata.duration_seconds),
        "thumbnail_url": metadata.thumbnail_url,
        "channel_id": metadata.channel_id,
        "channel_name": metadata.channel_name,
        "uploader": metadata.uploader,
    }


def serialize_profile(profile) -> dict[str, Any] | None:
    if profile is None:
        return None
    return profile.to_dict()


def serialize_creator_profiles(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in runtime["creator_profiles"].list_profiles()]


def state_from_artifacts(
    current_pipeline: SubtitlePipeline,
    artifacts: JobArtifacts | None,
    controls,
) -> dict[str, Any] | None:
    if artifacts is None:
        return None
    artifacts = current_pipeline.ensure_subtitle_artifacts(artifacts)
    artifacts = current_pipeline.ensure_quality_report(artifacts)
    state = load_job_state(artifacts.work_dir) or artifacts.to_state()
    state["translation_controls"] = state.get("translation_controls") or controls.to_dict()
    return state
