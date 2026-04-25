## Purpose

`observability/` contains cross-cutting observability utilities (shims and bridges). These modules are designed to be safe to import across the codebase and to degrade gracefully when optional dependencies are missing.

## Key files

- `agl_compat.py`: Agent Lightning compatibility layer (single-point capability detection, noop fallback).
- `__init__.py`: package marker.

