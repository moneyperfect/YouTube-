# YTSubViewer 重构计划

## 目标
将代码库从 MVP 状态重构为可维护、可扩展的产品级代码。

## 重构原则
1. **渐进式重构** — 每次只改一个模块，保持功能正常
2. **测试先行** — 每个重构步骤后运行测试
3. **向后兼容** — 不破坏现有 API 和用户数据
4. **文档同步** — 重构后更新 CLAUDE.md

---

## Phase 1: 清理遗留代码（1天）

### Task 1.1: 删除遗留 Gradio UI
- **文件**: `src/ytsubviewer/ui.py` (1678行)
- **操作**: 删除文件
- **修改**: `src/ytsubviewer/webapp.py` — 移除 `/legacy` 路由挂载
- **验证**: 
  - `python app.py` 启动正常
  - `/legacy` 返回 404
  - 所有测试通过

### Task 1.2: 清理旧版启动脚本
- **文件**: `start.ps1`, `启动.bat`, `安装依赖.bat`, `导出Cookies.bat`
- **操作**: 删除过时的批处理文件
- **保留**: `start.ps1`（更新为新版命令）
- **验证**: `.\start.ps1` 能正常启动

---

## Phase 2: 后端模块化（3天）

### Task 2.1: 拆分 webapp.py 为路由模块
**当前**: `webapp.py` (948行，30个端点)

**目标结构**:
```
src/ytsubviewer/
├── webapp.py          # 主应用工厂
├── routes/
│   ├── __init__.py
│   ├── settings.py    # /api/settings/* (2个端点)
│   ├── jobs.py        # /api/job/* (8个端点)
│   ├── youtube.py     # /api/youtube-* (2个端点)
│   ├── export.py      # /api/export/* (2个端点)
│   ├── editor.py      # /api/job/*/cue/* (4个端点)
│   ├── license.py     # /api/license/* (4个端点)
│   ├── profile.py     # /api/creator-profile/* (1个端点)
│   └── system.py      # /, /api/health, /api/bootstrap, /api/file (4个端点)
```

**操作**:
1. 创建 `routes/` 目录
2. 每个路由文件使用 `APIRouter`
3. 在 `webapp.py` 中注册所有路由
4. 保持 `create_web_app()` 接口不变

**验证**:
- 所有 30 个端点正常响应
- 前端功能不受影响
- 所有测试通过

### Task 2.2: 配置系统重构
**当前**: `config.py` (447行) + `providers.py` (64行)

**目标**:
```
src/ytsubviewer/
├── config/
│   ├── __init__.py    # 导出 Settings, settings
│   ├── settings.py    # Settings dataclass
│   ├── providers.py   # Provider 注册表
│   └── crypto.py      # 加密/解密工具
```

**操作**:
1. 创建 `config/` 目录
2. 拆分 `config.py` 为 `settings.py` + `crypto.py`
3. 移动 `providers.py` 到 `config/`
4. 更新所有导入路径

**验证**:
- `Settings.load()` 正常工作
- `get_provider()` 正常工作
- 所有测试通过

### Task 2.3: 服务层接口标准化
**当前**: 各服务类接口不一致

**目标**: 统一服务接口
```python
class BaseService:
    def __init__(self, settings: Settings): ...
    
class YouTubeService(BaseService):
    def extract_metadata(self, url: str) -> VideoMetadata: ...
    def download_video(self, url: str, work_dir: Path) -> Path: ...
    # ...

class TranslateService(BaseService):
    def translate_cues(self, cues: list[SubtitleCue]) -> list[SubtitleCue]: ...
    # ...
```

**操作**:
1. 创建 `base.py` 定义 `BaseService`
2. 修改所有服务继承 `BaseService`
3. 统一错误处理模式

**验证**:
- 所有服务正常工作
- 所有测试通过

---

## Phase 3: 前端模块化（2天）

### Task 3.1: JavaScript 模块化
**当前**: `app.js` (1199行，单文件)

**目标结构**:
```
src/ytsubviewer/web/
├── app.js           # 主入口
├── modules/
│   ├── api.js       # API 请求封装
│   ├── state.js     # 全局状态管理
│   ├── router.js    # 前端路由
│   ├── settings.js  # 设置页面逻辑
│   ├── workbench.js # 工作台逻辑
│   ├── history.js   # 历史页面逻辑
│   ├── editor.js    # 编辑器逻辑
│   ├── i18n.js      # 国际化
│   └── utils.js     # 工具函数
```

**操作**:
1. 创建 `modules/` 目录
2. 按功能拆分代码
3. 使用 ES6 模块 (import/export)
4. 更新 HTML 引用

**验证**:
- 所有页面功能正常
- 导航切换正常
- 配置保存/加载正常

### Task 3.2: CSS 组件化
**当前**: `styles.css` (1030行，单文件)

**目标结构**:
```
src/ytsubviewer/web/
├── styles.css       # 主样式 + CSS 变量
├── components/
│   ├── sidebar.css  # 侧边栏样式
│   ├── forms.css    # 表单样式
│   ├── buttons.css  # 按钮样式
│   ├── cards.css    # 卡片样式
│   ├── editor.css   # 编辑器样式
│   └── overlay.css  # 弹窗样式
```

**操作**:
1. 创建 `components/` 目录
2. 按组件拆分样式
3. 在 `styles.css` 中 `@import` 所有组件
4. 保持 CSS 变量在主文件中

**验证**:
- 所有样式正常显示
- 响应式设计正常

---

## Phase 4: 测试覆盖（2天）

### Task 4.1: 单元测试补充
**当前**: 57 个测试，覆盖率不足

**目标**: 核心模块 80%+ 覆盖率

**补充测试**:
- `test_routes.py` — API 端点测试
- `test_config.py` — 配置加载测试
- `test_services.py` — 服务层测试（mock 外部调用）

**验证**:
- `pytest tests/ -v --cov=src/ytsubviewer --cov-report=term-missing`
- 覆盖率 ≥ 80%

### Task 4.2: 集成测试
**目标**: 端到端流程测试

**测试用例**:
1. 完整翻译流程（从 URL 到字幕文件）
2. 配置保存/加载流程
3. 任务取消/重试流程

**验证**:
- 集成测试全部通过

---

## Phase 5: 文档和部署（1天）

### Task 5.1: 更新文档
- 更新 `CLAUDE.md` — 新的目录结构
- 更新 `README.md` — 安装和使用说明
- 添加 `CONTRIBUTING.md` — 开发指南

### Task 5.2: 部署配置优化
- 更新 `Dockerfile` — 优化镜像大小
- 更新 `docker-compose.yml` — 添加健康检查
- 添加 `.dockerignore`

---

## 执行顺序

```
Phase 1 (清理) → Phase 2 (后端) → Phase 3 (前端) → Phase 4 (测试) → Phase 5 (文档)
     ↓                ↓                ↓                ↓                ↓
   1天              3天              2天              2天              1天
                                                   总计: 9天
```

## 质量保证

每个 Task 完成后：
1. 运行 `python -m compileall` 检查语法
2. 运行 `pytest tests/ -v` 确认测试通过
3. 手动测试关键功能
4. 更新相关文档

## 风险控制

1. **功能回归** — 每个 Phase 完成后进行完整功能测试
2. **数据兼容** — 确保用户配置和任务数据不受影响
3. **回滚机制** — 每个 Task 使用独立 commit，便于回滚

---

## 开始执行？

确认后我将从 Phase 1 开始执行。
