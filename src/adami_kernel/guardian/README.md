## Purpose

`guardian/` provides system safety rails:

- timeouts / circuit breakers (Immunity system)
- RBAC checks
- rate limiting / resource limiting
- sensitive filtering and TLS helpers

## Key files

- `immunity.py`: `ImmunitySystem` timeout wrapper (pain/fuse semantics).
- `rbac.py`, `rbac_initializer.py`: role-based access control.
- `limiter.py`: rate limiting primitives.
- `sensitive_filter.py`: sensitive content filtering.
- `tls.py`: TLS helpers.

