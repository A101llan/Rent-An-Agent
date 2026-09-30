"""Read-only: list usage_records rows for a session from the dev AgentHub DB.

  python scripts\\check_cloud_usage.py <session_id>

Uses apps/api settings (its .env) for the DB URL; never prints the URL.
"""

import asyncio
import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2] / "api"
os.chdir(API_DIR)
sys.path.insert(0, str(API_DIR))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402


async def main(session_id: str) -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "select id, metric_type, quantity, unit, execution_id, recorded_at "
                "from usage_records where session_id = :sid order by recorded_at"
            ),
            {"sid": session_id},
        )
        n = 0
        for r in rows:
            n += 1
            print(f"{r.id}  {r.metric_type:<14} {float(r.quantity):>8g} {r.unit:<6} exec={r.execution_id} at={r.recorded_at.isoformat()}")
        print(f"usage_records for session {session_id}: {n}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
