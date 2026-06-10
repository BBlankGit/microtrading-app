"""
Clear the paper simulator Redis state key for the configured namespace.

Usage (from backend/):
    python -m scripts.clear_paper_state [--dry-run]

Safe to run at any time. Only deletes the paper state key for the configured
namespace (PAPER_STATE_REDIS_NAMESPACE, default paper:prod). Does NOT touch:
  - market:snapshot:* keys
  - paper_trades_journal (Postgres)
  - paper_runtime_config (Postgres)
  - runtime config overrides

No broker. No live trading. No real orders. No real-money execution.
"""

import asyncio
import sys


async def main(dry_run: bool = False) -> None:
    from core.config import settings
    from data.redis_client import make_redis

    key = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state"

    r = make_redis()
    try:
        exists = await r.exists(key)
        if not exists:
            print(f"Key not found: {key!r} — nothing to delete.")
            return

        if dry_run:
            print(f"[dry-run] Would delete Redis key: {key!r}")
            return

        await r.delete(key)
        print(f"Deleted Redis key: {key!r}")
    finally:
        await r.aclose()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry_run))
