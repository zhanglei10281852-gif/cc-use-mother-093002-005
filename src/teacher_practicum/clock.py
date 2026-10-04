"""可控时钟。

逾期升级、确认时点等一律不直接读取系统时间，而是从该时钟取时，
便于测试与“中断恢复”场景下的确定性推进。
"""
from __future__ import annotations

from datetime import datetime, timedelta


class Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 10, 4, 9, 0, 0)

    def now(self) -> datetime:
        return self._now

    def today(self):
        return self._now.date()

    def advance(self, *, days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
        self._now += timedelta(days=days, hours=hours, minutes=minutes)
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now
