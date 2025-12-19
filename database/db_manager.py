from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import event
from sqlalchemy.engine import Engine
from config import DB_URL
from .models import Base
from utils.logger import setup_logger
from asyncio import current_task

logger = setup_logger("db_manager")


class DatabaseManager:
    def __init__(self, db_url=DB_URL):
        self.engine = create_async_engine(
            db_url, echo=False, connect_args={"check_same_thread": False}
        )

        # Enable WAL Mode for SQLite concurrency (Async style)
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        self.AsyncSessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    async def init_db(self):
        """Creates tables if they don't exist"""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables initialized successfully.")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise

    def get_session(self) -> AsyncSession:
        return self.AsyncSessionLocal()


# Global Instance
db = DatabaseManager()
