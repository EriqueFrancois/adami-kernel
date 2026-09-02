"""Adapter so SystemDiagnostics can getattr components like a kernel object."""

from __future__ import annotations

from typing import Any, Dict, Optional


class ComponentsKernelView:
    """Thin getattr view over the component dict used at boot."""

    def __init__(self, components: Dict[str, Any]) -> None:
        self._c = components

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._c:
            return self._c[name]
        raise AttributeError(name)

    @property
    def nerves(self) -> list:
        nr = self._c.get("nerve_registry")
        if nr is None:
            return []
        return list(getattr(nr, "nerves", []) or [])
