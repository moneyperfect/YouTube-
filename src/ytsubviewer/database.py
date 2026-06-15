"""数据库层 stub（本地模式下不使用 PostgreSQL）。

数据存储完全依赖本地 JSON 文件（job_state.json / tasks/*.json）。
此文件保留类接口用于向后兼容，但所有操作均为无操作。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Database:
    """本地模式下的数据库 stub。所有操作均为无操作。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._available = False

    @property
    def available(self) -> bool:
        return False

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def save_task(self, snapshot: dict[str, Any]) -> None:
        pass

    async def load_task(self, task_id: str) -> dict[str, Any] | None:
        return None

    async def list_tasks(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return []

    async def delete_task(self, task_id: str) -> None:
        pass

    async def save_job_state(self, work_dir: str, state: dict[str, Any]) -> None:
        pass

    async def load_job_state(self, work_dir: str) -> dict[str, Any] | None:
        return None

    async def delete_job_state(self, work_dir: str) -> None:
        pass


db: Database | None = None


def init_database(database_url: str | None = None) -> Database:
    global db
    db = Database(database_url)
    return db
