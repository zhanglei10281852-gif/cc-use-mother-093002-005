"""可控制时钟：逾期升级与汇总都依赖它，测试与演练可注入手动时钟。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        ...


class SystemClock:
    """真实时钟。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock:
    """手动时钟：只能显式推进，用于可控地触发逾期升级。"""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        self._current = start

    def now(self) -> datetime:
        return self._current

    def advance(self, **kwargs) -> datetime:
        self._current = self._current + timedelta(**kwargs)
        return self._current

    def set_now(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        self._current = moment
