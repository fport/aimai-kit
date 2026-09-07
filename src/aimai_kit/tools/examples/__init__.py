"""A realistic five-tool example built on a local SQLite database.

Deliberately not an integration with a real service: OAuth, webhooks and
queues would teach nothing about tool design and everything about that
particular vendor. What matters here is the SHAPE — one side-effecting tool
that requires approval, four read-only ones, and descriptions that say when
NOT to use each tool.
"""

from .orders import build_registry, seed_database

__all__ = ["build_registry", "seed_database"]
