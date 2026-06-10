"""
Clear the paper simulator Redis state key for the configured namespace.

Usage (from backend/):
    python -m scripts.clear_paper_state [--dry-run] [--all]

By default removes only the current v2 key.
With --all also removes the legacy paper:state and paper:prod:state (v1) keys.

Safe to run at any time. Does NOT touch:
  - market:snapshot:* keys
  - paper_trades_journal (Postgres)
  - paper_runtime_config (Postgres)
  - runtime config overrides

No broker. No live trading. No real orders. No real-money execution.
"""

import asyncio
import sys


async def main(dry_run: bool = False, remove_all: bool = False) -> None:
    from core.config import settings
    from data.redis_client import make_redis

    ns = settings.PAPER_STATE_REDIS_NAMESPACE
    keys_to_delete = [f"{ns}:state:v2"]
    if remove_all:
        keys_to_delete += [f"{ns}:state", "paper:state"]

    r = make_redis()
    try:
        for key in keys_to_delete:
            exists = await r.exists(key)
            if not exists:
                print(f"Key not found: {key!r} — skipped.")
                continue
            if dry_run:
                print(f"[dry-run] Would delete Redis key: {key!r}")
            else:
                await r.delete(key)
                print(f"Deleted Redis key: {key!r}")
    finally:
        await r.aclose()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    remove_all = "--all" in sys.argv
    asyncio.run(main(dry_run=dry_run, remove_all=remove_all))
