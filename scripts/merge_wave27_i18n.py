#!/usr/bin/env python3
"""Merge wave27_i18n_strings.build_wave27_blobs into locales/*/common.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from wave27_i18n_strings import build_wave27_blobs  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    en_blob, zh_blob = build_wave27_blobs()
    for loc, blob in (("en", en_blob), ("zh-Hans", zh_blob)):
        p = REPO / "src" / "adami_kernel" / "i18n" / "locales" / loc / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        overlap = set(data).intersection(blob)
        if overlap:
            raise SystemExit(f"Keys already exist in {loc}: {sorted(overlap)[:30]}")
        data.update(blob)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"merged {len(blob)} keys into {p.relative_to(REPO)}")


if __name__ == "__main__":
    main()
