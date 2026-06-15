"""Base class for services."""

from __future__ import annotations

from ytsubviewer.config import Settings


class BaseService:
    """Base class for all services. Provides common initialization."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
