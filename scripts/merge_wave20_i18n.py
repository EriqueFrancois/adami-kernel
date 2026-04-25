#!/usr/bin/env python3
"""Merge wave20_i18n_strings into src/adami_kernel/i18n/locales/*/common.json."""

from __future__ import annotations

import json
from pathlib import Path

from wave20_i18n_strings import WAVE20_EN, WAVE20_ZH

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    for loc, blob in (("en", WAVE20_EN), ("zh-Hans", WAVE20_ZH)):
        p = REPO / "src" / "adami_kernel" / "i18n" / "locales" / loc / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        overlap = set(data).intersection(blob)
        if overlap:
            raise SystemExit(f"Keys already exist in {loc}: {sorted(overlap)[:20]}...")
        data.update(blob)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"merged {len(blob)} keys into {p.relative_to(REPO)}")


if __name__ == "__main__":
    main()
