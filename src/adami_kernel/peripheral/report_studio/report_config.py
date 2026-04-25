from __future__ import annotations

from datetime import time
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ReportType = Literal["daily", "weekly", "monthly"]


class ReportSchedule(BaseModel):
    """
    Minimal schedule spec (phase 1):
    - time: local time in timezone (HH:MM)
    - weekday: for weekly reports (0=Mon..6=Sun), optional
    - day_of_month: for monthly reports (1..28/30/31), optional
    """

    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    publish_time_hhmm: str = Field(default="09:00", min_length=4, max_length=5)
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)

    @field_validator("publish_time_hhmm")
    @classmethod
    def _validate_hhmm(cls, v: str) -> str:
        s = (v or "").strip()
        if len(s) != 5 or s[2] != ":":
            raise ValueError("publish_time_hhmm must be HH:MM")
        hh = int(s[0:2])
        mm = int(s[3:5])
        time(hour=hh, minute=mm)  # validates range
        return s


class ReportSections(BaseModel):
    # fixed blocks (always enabled; only allow tuning top_n later)
    system_updates_top_n: int = Field(default=3, ge=1, le=10)
    world_news_top_n: int = Field(default=5, ge=1, le=20)
    ai_progress_top_n: int = Field(default=5, ge=1, le=20)
    market_moves_top_n: int = Field(default=5, ge=1, le=20)

    # optional blocks toggles
    general_news: bool = False
    sports: bool = False
    politics: bool = False
    military: bool = False
    tech_news: bool = False


class ReportConfig(BaseModel):
    version: str = Field(default="1.0", min_length=1, max_length=16)
    report_type: ReportType
    enabled: bool = True
    schedule: ReportSchedule = Field(default_factory=ReportSchedule)
    sections: ReportSections = Field(default_factory=ReportSections)
    write_to: Literal["Inbox", "Resources"] = "Inbox"
    note_prefix: str = Field(default="report", min_length=1, max_length=32)
