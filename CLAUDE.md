# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

YTSubViewer 是一个 Windows 本地优先的 YouTube 长视频字幕本地化工具（英文 → 中文简体/日语/韩语）。支持本地单机模式和 Docker 分布式部署。用户粘贴 YouTube 链接后，自动下载、转写、翻译并输出双语字幕和硬字幕视频。

## 启动与开发命令

```bash
# 激活虚拟环境
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器（自动选端口并打开浏览器）
python app.py

# 或使用 PowerShell 脚本
.\start.ps1

# 运行全部测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_subtitle_processing.py -v

# 带覆盖率
pytest tests/ -v --cov=src/ytsubviewer --cov-report=term-missing

# 语法检查
python -m compileall app.py src tests

# 构建便携版（PyInstaller）
.\build_portable.ps1

# 构建安装器（Inno Setup 6）
.\build_installer.ps1

# Docker 部署（需要 Redis + PostgreSQL）
docker compose up -d
```

## 架构概览

### 目录结构

```
src/ytsubviewer/
├── config/              # 配置模块
│   ├── __init__.py      # 导出接口
│   ├── settings.py      # Settings dataclass
│   └── crypto.py        # 加密/解密工具
├── routes/              # API 路由
│   ├── __init__.py
│   ├── serializers.py   # 序列化函数
│   └── helpers.py       # 辅助函数
├── services/            # 服务层
│   ├── base.py          # 基类
│   ├── youtube.py       # YouTube 服务
│   ├── translate.py     # 翻译服务
│   ├── transcribe.py    # 转写服务
│   ├── export.py        # 导出服务
│   └── player.py        # 播放器服务
├── web/                 # 前端资源
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── modules/         # JS 模块（参考）
│   └── components/      # CSS 组件
├── webapp.py            # FastAPI 应用
├── pipeline.py          # 翻译流程编排
├── background_jobs.py   # 后台任务管理
└── models.py            # 数据模型
```

### 双模式运行架构

项目支持两种运行模式，通过环境变量自动切换：

**本地模式（默认）**：`BackgroundGenerationManager` 使用 `threading` 做单机后台任务队列，任务状态持久化在 `{data_root}/.runtime/tasks/*.json`。

**分布式模式**：设置 `REDIS_URL` 后，自动切换到 Celery 任务队列。`celery_app.py` 中的 Celery worker 通过 Redis broker 接收任务。设置 `DATABASE_URL`（PostgreSQL）后，任务状态额外同步到数据库（`database.py` 中的 SQLAlchemy async 层）。

### 入口与服务层

- `app.py` — 应用入口，启动 uvicorn 服务器并自动打开浏览器
- `src/ytsubviewer/webapp.py` — FastAPI Web API，所有前端交互的后端接口
- `src/ytsubviewer/web/` — 前端静态资源（原生 HTML/JS/CSS，无框架）
- `src/ytsubviewer/ui.py` — 遗留 Gradio UI（挂载在 `/legacy` 路径）

### 核心处理流程

`pipeline.py` 中的 `SubtitlePipeline` 是整个翻译流程的编排器，使用 Generator 模式 (`generate_events`) 逐步产出 `PipelineEvent`：

1. **分析** — `YouTubeService.extract_metadata()` 通过 yt-dlp 获取视频元数据
2. **下载** — `YouTubeService.download_video()` 下载视频到 `workspace/jobs/{video_id}_{slug}/`
3. **字幕来源** — 优先级：人工英文字幕 > YouTube 自动字幕 > 本地 Whisper 转写
4. **翻译** — `DeepSeekTranslator` 通过 OpenAI 兼容 API 调用 LLM 批量翻译字幕段
5. **后处理** — 断句优化、双语字幕生成、质量报告
6. **导出** — `VideoExportService` 使用 ffmpeg 将 ASS 字幕烧录进视频

### 翻译系统

`services/translate.py` 中的 `DeepSeekTranslator` 是翻译核心：
- 通过 `providers.py` 中的 `ModelProvider` 注册表支持多 LLM 后端（DeepSeek、OpenAI、通义千问、Moonshot、Ollama 本地）
- 使用 OpenAI 兼容 API 协议，所有 provider 共享同一套调用逻辑
- 支持 4 种翻译风格预设（default/creator/conference/technical）
- 翻译后自动检测低质量结果（保留英文过多）并触发自动重译
- 支持术语表、保护词、批量并行翻译

### 后台任务系统

`background_jobs.py` 中的 `BackgroundGenerationManager` 统一管理两种模式：
- 本地模式：threading 并发，最多 `max_concurrent_tasks` 个线程
- Celery 模式：通过 `_submit_celery_generation` / `_submit_celery_export` 提交到 Redis
- 任务状态双向同步：本地 JSON 文件 + 可选的 PostgreSQL 数据库
- 应用重启后自动恢复 pending 任务

### 数据模型

`models.py` 中的关键数据结构：
- `SubtitleCue` — 单条字幕（id, start, end, source_text, target_text）
- `VideoMetadata` — 视频元数据（video_id, title, duration, 字幕可用性）
- `JobArtifacts` — 任务产出物路径集合（视频、字幕、质量报告等）
- `TranslationControlConfig` — 翻译控制配置（风格预设、术语表、保护词）

### 配置体系

`config.py` 中的 `Settings` dataclass 管理所有配置，优先级：
1. 环境变量 / `.env` 文件
2. 用户设置文件（`%LOCALAPPDATA%/YTSubViewer/settings.json`）
3. 默认值

外部工具路径（ffmpeg, mpv）自动从 `.tools/` 目录搜索。API Key 使用 Fernet 对称加密存储（密钥派生自机器指纹）。

### 服务层 (`services/`)

所有服务继承自 `BaseService`，统一接收 `Settings` 参数：

- `base.py` — 服务基类
- `youtube.py` — yt-dlp 封装，视频/字幕下载，自动处理 Cookie 认证和 bot 检测
- `cookie_manager.py` — 从 Chrome 浏览器提取 YouTube Cookies，处理 Chrome 运行时锁定
- `transcribe.py` — faster-whisper 本地转写，自动处理 CUDA DLL 路径
- `translate.py` — OpenAI 兼容 API 翻译，支持术语表、风格预设、批量并行、质量自检与自动重译
- `export.py` — ffmpeg 字幕烧录导出
- `player.py` — mpv 播放器启动（带字幕）

### 字幕处理

`subtitle_processing.py` 负责：
- VTT/SRT 解析与写入
- ASS 字幕生成（支持中文和双语模式，使用 Microsoft YaHei 字体）
- 字幕分段合并（`split_source_cues`，按 90 字符分割长行）
- 翻译后断句优化（`polish_translated_cues`，按 `target_line_width` 和 `max_subtitle_lines` 控制）

### 前端架构

`src/ytsubviewer/web/` 目录包含原生 HTML/JS/CSS 前端：
- `index.html` — 单页应用，使用 Lucide Icons（禁止 Emoji）
- `app.js` — 前端逻辑，通过 `/api/bootstrap` 初始化，轮询任务状态
- `styles.css` — 样式表，遵循 Warm & Organic 色彩体系
- `i18n/` — 国际化文件（zh.json, en.json）

前端通过 `session_token` 进行 API 认证，所有非公开接口需要 `Authorization: Bearer {token}` 头。

### 认证与安全

- `auth.py` — 基于本地 token 的 API 认证中间件
- `rate_limit.py` — 内存速率限制器（默认 60 请求/分钟）
- `license.py` — 授权管理（试用期 14 天，支持离线宽限期）

### 创作者配置系统

`creator_profiles.py` 中的 `CreatorProfileStore` 管理频道/创作者级配置：
- 按 channel_id 自动关联翻译风格、术语表、保护词
- 配置持久化在 `{data_root}/creator_profiles.json`

### 国际化

`i18n.py` 提供后端 i18n 支持：
- 翻译文件位于 `src/ytsubviewer/web/i18n/`
- 前端通过 `i18n.js` 实现界面翻译
- 支持中文和英文

## 关键外部依赖

- `yt-dlp` — YouTube 视频/字幕下载
- `ffmpeg` — 音频抽取、字幕烧录、视频导出（位于 `.tools/ffmpeg-8.1/`）
- `mpv` — 本地视频播放器（位于 `.tools/mpv-20260307/`）
- `faster-whisper` — 本地语音转写（自动下载模型，首次使用较慢）
- `openai` — OpenAI 兼容 API 客户端（用于调用 DeepSeek 等翻译服务）
- `celery[redis]` — 分布式任务队列（可选，Docker 部署时使用）
- `sqlalchemy[asyncpg]` — 异步数据库层（可选，Docker 部署时使用）

## 环境变量

参考 `.env.example`。核心变量：
- `DEEPSEEK_API_KEY` — DeepSeek 翻译 API 密钥（本地模式必须）
- `WHISPER_MODEL` / `WHISPER_FALLBACK_MODEL` — 转写模型选择
- `YTSUBVIEWER_DATA_ROOT` — 数据存储根目录（默认 `D:\YTSubViewerData`）
- `PREFER_AUTOMATIC_SUBTITLES` — 是否优先使用 YouTube 自动字幕
- `REDIS_URL` — Redis 连接地址（设置后启用 Celery 分布式模式）
- `DATABASE_URL` — PostgreSQL 连接地址（设置后启用数据库持久化）
- `YTSUBVIEWER_LICENSE_SECRET` — 授权验证密钥（可选）

## 工作目录结构

每个翻译任务在 `workspace/jobs/{video_id}_{title_slug}/` 下生成：
- `job_state.json` — 完整任务状态（含源字幕、翻译字幕的 JSON 序列化）
- `video.*` — 下载的视频文件
- `source*.vtt` / `source.auto*.vtt` — YouTube 字幕文件
- `{title}.zh-CN.srt` — 中文字幕
- `{title}.zh-CN.ass` — 中文 ASS 字幕
- `{title}.bilingual.ass` — 双语 ASS 字幕
- `{title}.quality-report.md` — 翻译质量报告

## 性能模式

三种模式（`fast` / `balanced` / `quality`）控制转写模型、翻译并行数和导出编码参数，在 `pipeline.py` 的 `_performance_profile()` 中定义。

## 测试

```bash
# 运行全部测试
python -m unittest discover -s tests -v

# 运行单个测试文件
python -m unittest tests.test_config -v

# 带覆盖率
pytest tests/ -v --cov=src/ytsubviewer --cov-report=term-missing
```

测试文件位于 `tests/` 目录，使用 `unittest` 框架。测试通过 `httpx.AsyncClient` 测试 FastAPI 端点。

当前测试覆盖：
- `test_config.py` — 配置模块测试
- `test_webapp.py` — API 端点测试
- `test_subtitle_processing.py` — 字幕处理测试
- 其他功能测试

## 构建与部署

### 便携版构建

```powershell
.\build_portable.ps1
```

构建完成后，可交付目录为 `dist\YTSubViewer`，其中包含 `YTSubViewer.exe`。

### 安装器构建

```powershell
.\build_installer.ps1
```

前提：已安装 Inno Setup 6，能找到 `ISCC.exe`。安装器脚本位于 `installer\YTSubViewer.iss`。

### Docker 部署

```bash
docker compose up -d
```

Docker 镜像基于 `python:3.12-slim`，包含 ffmpeg。数据卷挂载在 `/data`。

## 图标规范

使用 Lucide Icons，禁止 Emoji。如需在前端新增图标元素，安装 `lucide` 并使用。

## 修改验证流程

修改后执行以下黑盒验证：
1. `python app.py` → 终端显示 uvicorn 启动日志，浏览器自动打开，无报错
2. 粘贴一个 YouTube 链接 → 元数据正确解析（标题、时长、字幕可用性）
3. 点击开始翻译 → 任务进入后台队列 → 进度实时更新 → 最终生成双语字幕文件
4. 导出视频 → ASS 字幕正确烧录，播放验证字幕与画面同步
