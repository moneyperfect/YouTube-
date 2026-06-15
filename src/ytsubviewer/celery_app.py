"""Celery 应用配置（本地模式下不使用）。

此文件保留用于向后兼容，实际任务执行通过 background_jobs.py 的 threading 模式完成。
"""

from __future__ import annotations

app = None
