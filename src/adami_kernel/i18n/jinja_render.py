"""Render packaged Jinja templates (long structured snippets; not UI locale catalogs)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


@lru_cache(maxsize=1)
def _template_env() -> Environment:
    root = Path(__file__).resolve().parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_i18n_template(rel_path: str, **kwargs: Any) -> str:
    """Load ``templates/<rel_path>`` relative to this package."""
    return _template_env().get_template(rel_path).render(**kwargs)
