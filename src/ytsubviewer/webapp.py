"""FastAPI web application for YTSubViewer."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ytsubviewer.auth import AuthMiddleware, generate_session_token
from ytsubviewer.background_jobs import BackgroundGenerationManager, TaskSnapshot
from ytsubviewer.config import (
    APP_VERSION,
    Settings,
    decrypt_value,
    save_user_settings,
    settings as app_settings,
)
from ytsubviewer.creator_profiles import CreatorProfileStore
from ytsubviewer.i18n import load_translations
from ytsubviewer.job_state import artifacts_from_state, load_job_state
from ytsubviewer.license import LicenseManager
from ytsubviewer.models import TranslationControlConfig
from ytsubviewer.pipeline import SubtitlePipeline
from ytsubviewer.providers import ModelProvider, get_provider
from ytsubviewer.rate_limit import RateLimitMiddleware
from ytsubviewer.routes.helpers import (
    build_controls,
    load_state_for_task,
    load_state_for_work_dir,
    resolve_control_texts,
    resolve_download_path,
    strategy_text,
    validate_youtube_url,
)
from ytsubviewer.routes.serializers import (
    serialize_creator_profiles,
    serialize_current_job,
    serialize_history,
    serialize_job,
    serialize_metadata,
    serialize_performance_modes,
    serialize_profile,
    serialize_providers,
    serialize_settings,
    serialize_state,
    serialize_style_presets,
    state_from_artifacts,
)
from ytsubviewer.runtime import inspect_environment
from ytsubviewer.services.translate import DeepSeekTranslator
from ytsubviewer.services.youtube import YouTubeLoginRequired
from ytsubviewer.update_service import UpdateService

logger = logging.getLogger(__name__)


# ── Payload models ──


class SettingsPayload(BaseModel):
    api_key: str = ""
    provider_name: str = ""
    model_name: str = ""
    base_url: str = ""
    provider_api_keys: dict[str, str] = {}


class AnalyzePayload(BaseModel):
    url: str
    style_preset: str = "default"
    glossary_text: str = ""
    protected_terms_text: str = ""
    performance_mode: str = "balanced"
    use_creator_defaults: bool = True


class BatchPayload(BaseModel):
    urls_text: str
    style_preset: str = "default"
    glossary_text: str = ""
    protected_terms_text: str = ""
    performance_mode: str = "balanced"
    use_creator_defaults: bool = True


class OpenPlayerPayload(BaseModel):
    work_dir: str
    bilingual: bool = False


class ExportPayload(BaseModel):
    work_dir: str
    bilingual: bool = False
    preview: bool = False
    performance_mode: str = "balanced"


class CueUpdatePayload(BaseModel):
    cue_id: int
    target_text: str = ""


class CueLockPayload(BaseModel):
    cue_id: int
    locked: bool = True


class BulkReplacePayload(BaseModel):
    source_text: str
    target_text: str


class CreatorProfilePayload(BaseModel):
    url: str
    style_preset: str = "default"
    glossary_text: str = ""
    protected_terms_text: str = ""


class LicensePayload(BaseModel):
    license_key: str = ""


class TestProviderPayload(BaseModel):
    provider_name: str
    api_key: str = ""
    model_name: str = ""
    base_url: str = ""


# ── App factory ──


def create_web_app(
    *,
    app_runtime_settings: Settings | None = None,
    pipeline: SubtitlePipeline | None = None,
    generation_manager: BackgroundGenerationManager | None = None,
) -> FastAPI:
    runtime_settings = app_runtime_settings or app_settings
    runtime_pipeline = pipeline or SubtitlePipeline(runtime_settings)
    runtime_generation_manager = generation_manager or BackgroundGenerationManager(
        runtime_settings, runtime_pipeline
    )
    runtime_generation_manager.bind_pipeline(runtime_pipeline)

    session_token = generate_session_token()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    runtime: dict[str, Any] = {
        "settings": runtime_settings,
        "pipeline": runtime_pipeline,
        "generation_manager": runtime_generation_manager,
        "creator_profiles": CreatorProfileStore(runtime_settings),
        "license_manager": LicenseManager(runtime_settings),
        "update_service": UpdateService(runtime_settings),
        "session_token": session_token,
    }

    web_root = _resolve_web_root(runtime_settings)
    app = FastAPI(title="YTSubViewer", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)
    app.add_middleware(AuthMiddleware, token=session_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=web_root), name="static")

    # ── System routes ──

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web_root / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        current_settings = runtime["settings"]
        return {
            "version": APP_VERSION,
            "settings": serialize_settings(current_settings),
            "environment": inspect_environment(current_settings),
            "style_presets": serialize_style_presets(),
            "performance_modes": serialize_performance_modes(),
            "job": serialize_current_job(runtime),
            "history": serialize_history(runtime),
            "license": runtime["license_manager"].status(),
            "update": runtime["update_service"].status(),
            "creator_profiles": serialize_creator_profiles(runtime),
            "session_token": runtime["session_token"],
            "providers": serialize_providers(current_settings),
            "available_languages": [
                {"code": "zh", "label": "中文"},
                {"code": "en", "label": "English"},
            ],
        }

    # ── Settings routes ──

    @app.post("/api/settings")
    def save_settings(payload: SettingsPayload) -> dict[str, Any]:
        save_user_settings(
            deepseek_api_key=payload.api_key or None,
            provider_name=payload.provider_name or None,
            model_name=payload.model_name or None,
            base_url=payload.base_url or None,
            provider_api_keys=payload.provider_api_keys or None,
        )
        _reload_runtime(runtime)
        current_settings = runtime["settings"]
        return {
            "settings": serialize_settings(current_settings),
            "environment": inspect_environment(current_settings),
            "style_presets": serialize_style_presets(),
            "performance_modes": serialize_performance_modes(),
            "job": serialize_current_job(runtime),
            "history": serialize_history(runtime),
            "license": runtime["license_manager"].status(),
            "update": runtime["update_service"].status(),
            "creator_profiles": serialize_creator_profiles(runtime),
            "providers": serialize_providers(current_settings),
        }

    @app.post("/api/settings/test")
    def test_provider(payload: TestProviderPayload) -> dict[str, Any]:
        provider = get_provider(payload.provider_name)
        model = payload.model_name or (provider.models[0] if provider and provider.models else "")

        api_key = payload.api_key
        custom_base_url = ""
        if not api_key:
            try:
                config_path = runtime["settings"].config_path
                if config_path.exists():
                    _user = json.loads(config_path.read_text(encoding="utf-8")) or {}
                    custom_base_url = _user.get("custom_base_url", "")
                    enc = _user.get(f"api_key_{payload.provider_name}", "") or _user.get(
                        "deepseek_api_key_encrypted", ""
                    )
                    if enc:
                        api_key = decrypt_value(enc)
            except Exception:
                pass
        if not api_key and provider:
            api_key = provider.resolve_api_key()

        base_url = payload.base_url or custom_base_url or (provider.base_url if provider else "")

        if not base_url:
            return {"success": False, "message": "请填写 API 地址。"}
        if not api_key and (not provider or provider.name != "ollama"):
            return {"success": False, "message": "请先输入 API Key。"}

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key or "ollama", base_url=base_url, timeout=15)
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            return {"success": True, "message": f"连接成功，模型 {model} 可用。"}
        except Exception as exc:
            return {"success": False, "message": f"连接失败：{exc}"}

    # ── YouTube routes ──

    @app.post("/api/youtube-login")
    def youtube_login() -> dict[str, Any]:
        from ytsubviewer.services.cookie_manager import _find_chrome_db, ensure_cookies

        result = ensure_cookies(runtime["settings"].data_root)
        if result:
            return {"success": True, "message": "Cookies 获取成功！"}
        if not _find_chrome_db():
            return {"success": False, "message": "未找到 Chrome 浏览器数据。请确认已安装 Chrome 并登录过 YouTube。"}
        return {"success": False, "message": "Cookies 提取失败，请重试。"}

    @app.post("/api/youtube-extract")
    def youtube_extract() -> dict[str, Any]:
        return youtube_login()

    # ── Job routes ──

    @app.post("/api/analyze")
    def analyze(payload: AnalyzePayload) -> dict[str, Any]:
        url = payload.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="请输入 YouTube 链接。")
        validate_youtube_url(url)

        current_pipeline: SubtitlePipeline = runtime["pipeline"]
        try:
            metadata = current_pipeline.analyze(url)
        except YouTubeLoginRequired:
            raise HTTPException(
                status_code=428, detail="YouTube 需要登录验证，请先点击「登录 YouTube」按钮完成登录。"
            )
        profile = runtime["creator_profiles"].get_for_metadata(metadata)
        resolved = resolve_control_texts(payload, profile)
        controls = build_controls(
            resolved["style_preset"],
            resolved["glossary_text"],
            resolved["protected_terms_text"],
        )
        existing_artifacts = current_pipeline.find_existing_artifacts(metadata)
        state = state_from_artifacts(current_pipeline, existing_artifacts, controls) if existing_artifacts else None
        controls_match = bool(state and current_pipeline._controls_match_state(state, controls))

        return {
            "metadata": serialize_metadata(metadata),
            "strategy_text": strategy_text(
                metadata.manual_english_subtitle_lang,
                metadata.automatic_english_subtitle_lang,
            ),
            "profile": serialize_profile(profile),
            "resolved_controls": resolved,
            "has_existing_result": state is not None,
            "controls_match": controls_match,
            "state": serialize_state(current_pipeline, state) if state else None,
        }

    @app.post("/api/generate")
    async def generate(payload: AnalyzePayload) -> dict[str, Any]:
        url = payload.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="请输入 YouTube 链接。")
        validate_youtube_url(url)
        if not runtime["settings"].deepseek_api_key:
            raise HTTPException(status_code=400, detail="请先保存 DeepSeek API Key。")

        current_pipeline: SubtitlePipeline = runtime["pipeline"]
        try:
            metadata = current_pipeline.analyze(url)
        except YouTubeLoginRequired:
            raise HTTPException(
                status_code=428, detail="YouTube 需要登录验证，请先点击「登录 YouTube」按钮完成登录。"
            )
        profile = runtime["creator_profiles"].get_for_metadata(metadata)
        resolved = resolve_control_texts(payload, profile)
        controls = build_controls(
            resolved["style_preset"],
            resolved["glossary_text"],
            resolved["protected_terms_text"],
        )
        snapshot = runtime["generation_manager"].start_generation(
            url=url,
            metadata=metadata,
            strategy_text=strategy_text(
                metadata.manual_english_subtitle_lang,
                metadata.automatic_english_subtitle_lang,
            ),
            controls=controls,
            glossary_text=resolved["glossary_text"],
            protected_terms_text=resolved["protected_terms_text"],
            performance_mode=payload.performance_mode,
        )
        return {"job": serialize_job(runtime, snapshot)}

    @app.post("/api/batch")
    async def batch_generate(payload: BatchPayload) -> dict[str, Any]:
        urls = [line.strip() for line in payload.urls_text.replace("\r", "\n").split("\n") if line.strip()]
        if not urls:
            raise HTTPException(status_code=400, detail="请至少输入一个 YouTube 链接。")
        for url in urls:
            validate_youtube_url(url)
        queued: list[dict[str, Any]] = []
        batch_id = Path(os.urandom(8).hex()).name
        for url in urls:
            metadata = runtime["pipeline"].analyze(url)
            profile = runtime["creator_profiles"].get_for_metadata(metadata)
            resolved = resolve_control_texts(payload, profile)
            controls = build_controls(
                resolved["style_preset"],
                resolved["glossary_text"],
                resolved["protected_terms_text"],
            )
            snapshot = runtime["generation_manager"].start_generation(
                url=url,
                metadata=metadata,
                strategy_text=strategy_text(
                    metadata.manual_english_subtitle_lang,
                    metadata.automatic_english_subtitle_lang,
                ),
                controls=controls,
                glossary_text=resolved["glossary_text"],
                protected_terms_text=resolved["protected_terms_text"],
                performance_mode=payload.performance_mode,
                batch_id=batch_id,
            )
            queued.append(serialize_job(runtime, snapshot))
        return {"jobs": queued, "history": serialize_history(runtime)}

    @app.get("/api/job/current")
    def current_job() -> dict[str, Any]:
        return {"job": serialize_current_job(runtime)}

    @app.get("/api/job/history")
    def job_history() -> dict[str, Any]:
        return {"jobs": serialize_history(runtime)}

    @app.get("/api/job/{task_id}")
    def job_detail(task_id: str) -> dict[str, Any]:
        snapshot = runtime["generation_manager"].get_task(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return {"job": serialize_job(runtime, snapshot)}

    @app.post("/api/job/{task_id}/cancel")
    async def cancel_job(task_id: str) -> dict[str, Any]:
        snapshot = runtime["generation_manager"].cancel_task(task_id)
        return {"job": serialize_job(runtime, snapshot), "history": serialize_history(runtime)}

    @app.post("/api/job/{task_id}/retry")
    async def retry_job(task_id: str) -> dict[str, Any]:
        snapshot = runtime["generation_manager"].retry_task(task_id)
        return {"job": serialize_job(runtime, snapshot), "history": serialize_history(runtime)}

    # ── Export routes ──

    @app.post("/api/export")
    async def export_video(payload: ExportPayload) -> dict[str, Any]:
        state = load_state_for_work_dir(Path(payload.work_dir))
        snapshot = runtime["generation_manager"].start_export(
            state=state,
            bilingual=payload.bilingual,
            preview=payload.preview,
            performance_mode=payload.performance_mode,
        )
        return {"job": serialize_job(runtime, snapshot)}

    @app.get("/api/export/{task_id}")
    def export_detail(task_id: str) -> dict[str, Any]:
        snapshot = runtime["generation_manager"].get_task(task_id)
        if snapshot is None or snapshot.kind != "export":
            raise HTTPException(status_code=404, detail="导出任务不存在。")
        return {"job": serialize_job(runtime, snapshot)}

    # ── Editor routes ──

    @app.get("/api/job/{task_id}/quality")
    def quality_report(task_id: str) -> dict[str, Any]:
        state = load_state_for_task(runtime, task_id)
        quality = dict(state.get("quality_report") or {})
        return {
            "quality_report": quality,
            "quality_report_path": str(state.get("quality_report_path", "") or ""),
        }

    @app.get("/api/job/{task_id}/editor")
    def editor_document(task_id: str, issues_only: bool = False, query: str = "") -> dict[str, Any]:
        state = load_state_for_task(runtime, task_id)
        return runtime["pipeline"].get_editor_payload(state, issues_only=issues_only, query=query)

    @app.post("/api/job/{task_id}/cue/update")
    def update_cue(task_id: str, payload: CueUpdatePayload) -> dict[str, Any]:
        state = load_state_for_task(runtime, task_id)
        artifacts = runtime["pipeline"].update_cue_translation(state, payload.cue_id, payload.target_text)
        return {
            "state": serialize_state(runtime["pipeline"], load_job_state(artifacts.work_dir)),
            "editor": runtime["pipeline"].get_editor_payload(load_job_state(artifacts.work_dir) or {}),
        }

    @app.post("/api/job/{task_id}/cue/retranslate")
    def retranslate_cue(task_id: str, payload: CueUpdatePayload) -> dict[str, Any]:
        state = load_state_for_task(runtime, task_id)
        artifacts = runtime["pipeline"].retranslate_cue(state, payload.cue_id)
        return {
            "state": serialize_state(runtime["pipeline"], load_job_state(artifacts.work_dir)),
            "editor": runtime["pipeline"].get_editor_payload(load_job_state(artifacts.work_dir) or {}),
        }

    @app.post("/api/job/{task_id}/cue/lock")
    def lock_cue(task_id: str, payload: CueLockPayload) -> dict[str, Any]:
        state = load_state_for_task(runtime, task_id)
        artifacts = runtime["pipeline"].set_cue_lock(state, payload.cue_id, payload.locked)
        return {
            "state": serialize_state(runtime["pipeline"], load_job_state(artifacts.work_dir)),
            "editor": runtime["pipeline"].get_editor_payload(load_job_state(artifacts.work_dir) or {}),
        }

    @app.post("/api/job/{task_id}/cue/bulk-replace")
    def bulk_replace(task_id: str, payload: BulkReplacePayload) -> dict[str, Any]:
        state = load_state_for_task(runtime, task_id)
        artifacts = runtime["pipeline"].bulk_replace_term(state, payload.source_text, payload.target_text)
        refreshed = load_job_state(artifacts.work_dir) or state
        return {
            "state": serialize_state(runtime["pipeline"], refreshed),
            "editor": runtime["pipeline"].get_editor_payload(refreshed),
        }

    @app.post("/api/open-player")
    def open_player(payload: OpenPlayerPayload) -> dict[str, Any]:
        work_dir = Path(payload.work_dir.strip())
        state = load_job_state(work_dir)
        if not state:
            raise HTTPException(status_code=404, detail="当前任务结果不存在，请先生成字幕。")
        artifacts = artifacts_from_state(state)
        if artifacts is None:
            raise HTTPException(status_code=400, detail="当前任务还没有可播放的结果。")

        current_pipeline: SubtitlePipeline = runtime["pipeline"]
        video_path, subtitle_path = current_pipeline.prepare_player_paths(artifacts, bilingual=payload.bilingual)
        message = current_pipeline.player.open_with_subtitle(video_path, subtitle_path)
        return {"message": message}

    @app.post("/api/creator-profile/save")
    def save_creator_profile(payload: CreatorProfilePayload) -> dict[str, Any]:
        url = payload.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="请输入 YouTube 链接。")
        metadata = runtime["pipeline"].analyze(url)
        profile = runtime["creator_profiles"].save_for_metadata(
            metadata,
            style_preset=payload.style_preset,
            glossary_text=payload.glossary_text,
            protected_terms_text=payload.protected_terms_text,
        )
        return {"profile": serialize_profile(profile), "profiles": serialize_creator_profiles(runtime)}

    # ── License routes ──

    @app.get("/api/license/status")
    def license_status() -> dict[str, Any]:
        return runtime["license_manager"].status()

    @app.post("/api/license/activate")
    def activate_license(payload: LicensePayload) -> dict[str, Any]:
        return runtime["license_manager"].activate(payload.license_key)

    @app.post("/api/license/deactivate")
    def deactivate_license() -> dict[str, Any]:
        return runtime["license_manager"].deactivate()

    @app.post("/api/license/verify")
    async def verify_license(payload: LicensePayload) -> dict[str, Any]:
        return await runtime["license_manager"].verify_remote(payload.license_key)

    # ── File routes ──

    @app.get("/api/file")
    def download_file(path: str) -> FileResponse:
        resolved = resolve_download_path(runtime["settings"], path)
        return FileResponse(resolved, filename=resolved.name)

    return app


# ── Internal helpers ──


def _resolve_web_root(current_settings: Settings) -> Path:
    candidates = [
        current_settings.resource_root / "src" / "ytsubviewer" / "web",
        Path(__file__).resolve().parent / "web",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Web frontend assets are missing.")


def _reload_runtime(runtime: dict[str, Any]) -> None:
    current_settings = Settings.load()
    runtime["settings"] = current_settings
    runtime["pipeline"] = SubtitlePipeline(current_settings)
    generation_manager: BackgroundGenerationManager = runtime["generation_manager"]
    generation_manager.settings = current_settings
    generation_manager.runtime_dir = current_settings.data_root / ".runtime"
    generation_manager.runtime_dir.mkdir(parents=True, exist_ok=True)
    generation_manager.tasks_dir = generation_manager.runtime_dir / "tasks"
    generation_manager.tasks_dir.mkdir(parents=True, exist_ok=True)
    generation_manager.current_snapshot_path = generation_manager.runtime_dir / "current_generation_job.json"
    generation_manager.bind_pipeline(runtime["pipeline"])
    runtime["creator_profiles"] = CreatorProfileStore(current_settings)
    runtime["license_manager"] = LicenseManager(current_settings)
    runtime["update_service"] = UpdateService(current_settings)

    from ytsubviewer.providers import get_default_provider

    provider = get_provider(current_settings.provider_name) or get_default_provider()
    stored_key = ""
    custom_base_url = ""
    try:
        if current_settings.config_path.exists():
            _user = json.loads(current_settings.config_path.read_text(encoding="utf-8")) or {}
            enc = _user.get(f"api_key_{provider.name}", "") or _user.get("deepseek_api_key_encrypted", "")
            if enc:
                stored_key = decrypt_value(enc)
            custom_base_url = str(_user.get("custom_base_url", "")).strip()
    except Exception:
        pass
    if not stored_key:
        stored_key = current_settings.deepseek_api_key or ""
    if stored_key:
        provider.api_key = stored_key
    if custom_base_url:
        provider = ModelProvider(
            name=provider.name,
            label=provider.label,
            base_url=custom_base_url,
            models=provider.models,
            api_key_env=provider.api_key_env,
            api_key=provider.api_key,
        )
    runtime["pipeline"].translator.provider = provider
