import asyncio
from app.db.session import engine
from app.models import Base

async def init_db():
    async with engine.begin() as conn:
        print("Creating all tables in the database...")
        await conn.run_sync(Base.metadata.create_all)
        print("Done!")

if __name__ == "__main__":
    asyncio.run(init_db())
