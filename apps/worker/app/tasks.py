import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app

DATABASE_URL = os.getenv("DATABASE_URL_SYNC", "postgresql://agenthub:agenthub@postgres:5432/agenthub")


def get_sync_session() -> Session:
    engine = create_engine(DATABASE_URL)
    return sessionmaker(bind=engine)()


@celery_app.task(name="app.tasks.expire_sessions")
def expire_sessions():
    """Find and expire sessions past their TTL."""
    from app.models_sync import RentalSession, SessionStatus

    session = get_sync_session()
    try:
        now = datetime.now(UTC)
        result = session.execute(
            select(RentalSession).where(
                RentalSession.status == SessionStatus.ACTIVE,
                RentalSession.expires_at < now,
            )
        )
        expired_count = 0
        for rental_session in result.scalars():
            rental_session.status = SessionStatus.EXPIRED
            expired_count += 1
        session.commit()
        return {"expired": expired_count}
    except Exception as e:
        session.rollback()
        return {"error": str(e), "expired": 0}
    finally:
        session.close()
