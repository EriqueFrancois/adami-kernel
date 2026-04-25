## Purpose

`market/` owns “skill market” ingestion and recommendation.
It provides mechanisms to find, rank, and import skills (e.g., via GitHub) and to present them to the system.

## Key files

- `skill_market.py`: skill catalog, ranking, and market operations.
- `github_hunter.py`: GitHub discovery (Tier-1 graceful degrade behavior).
- `recommender.py`: recommendation logic.
- `melter.py`: “melting”/templating utilities for skill packaging.

