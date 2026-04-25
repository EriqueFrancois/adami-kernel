from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.peripheral.report_studio.report_config import ReportConfig, ReportType


class ReportConfigStoreError(RuntimeError):
    pass


def _ensure_under_root(root: Path, path: Path) -> Path:
    r = root.resolve()
    p = path.resolve()
    try:
        p.relative_to(r)
    except ValueError as e:
        raise ReportConfigStoreError(f"path escapes brain root: {p}") from e
    return p


def _configs_dir(root: Path) -> Path:
    d = root / "System" / "working-memory" / "report_configs"
    return _ensure_under_root(root, d)


def _config_path(root: Path, report_type: ReportType) -> Path:
    return _ensure_under_root(root, _configs_dir(root) / f"{report_type}.json")


def default_config(report_type: ReportType) -> ReportConfig:
    cfg = ReportConfig(report_type=report_type)
    if report_type == "weekly":
        cfg.schedule.weekday = 0  # Monday
    if report_type == "monthly":
        cfg.schedule.day_of_month = 1
    return cfg


class ReportConfigStore:
    """
    SecondBrain-backed report config store.

    Files:
      {brain_root}/System/working-memory/report_configs/{daily|weekly|monthly}.json
    """

    def __init__(self, second_brain: Optional[SecondBrainManager] = None) -> None:
        self.sb = second_brain or SecondBrainManager()
        self.root = Path(self.sb.root).resolve()

    def ensure_defaults(self) -> None:
        d = _configs_dir(self.root)
        d.mkdir(parents=True, exist_ok=True)
        for t in ("daily", "weekly", "monthly"):
            p = _config_path(self.root, t)  # type: ignore[arg-type]
            if not p.is_file():
                cfg = default_config(t)  # type: ignore[arg-type]
                p.write_text(
                    cfg.model_dump_json(indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )

    def list_configs(self) -> List[Dict[str, str]]:
        self.ensure_defaults()
        out: List[Dict[str, str]] = []
        for t in ("daily", "weekly", "monthly"):
            p = _config_path(self.root, t)  # type: ignore[arg-type]
            if p.is_file():
                out.append({"report_type": t, "path": str(p)})
        return out

    def load(self, report_type: ReportType) -> ReportConfig:
        self.ensure_defaults()
        p = _config_path(self.root, report_type)
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        return ReportConfig.model_validate(data)

    def save(self, cfg: ReportConfig) -> Path:
        self.ensure_defaults()
        p = _config_path(self.root, cfg.report_type)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(cfg.model_dump_json(indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(p))
        return p

    def patch(self, report_type: ReportType, updates: Dict) -> ReportConfig:
        cfg = self.load(report_type)
        merged = cfg.model_dump()
        # shallow merge for phase 1; nested keys supported via dicts for schedule/sections
        for k, v in (updates or {}).items():
            if k in ("schedule", "sections") and isinstance(v, dict):
                merged[k] = {**(merged.get(k) or {}), **v}
            else:
                merged[k] = v
        new_cfg = ReportConfig.model_validate(merged)
        self.save(new_cfg)
        return new_cfg
