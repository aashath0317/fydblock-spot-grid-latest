from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.engine import Engine
from config import DB_URL
from .models import Base
from utils.logger import setup_logger

logger = setup_logger("db_manager")


class DatabaseManager:
    def __init__(self, db_url=DB_URL):
        self.engine = create_engine(
            db_url, echo=False, connect_args={"check_same_thread": False}
        )

        # Enable WAL Mode for SQLite concurrency
        event.listen(self.engine, "connect", self._enable_wal)

        self.SessionLocal = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        )

    def _enable_wal(self, dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    def init_db(self):
        """Creates tables if they don't exist"""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables initialized successfully.")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise

    def get_session(self):
        return self.SessionLocal()


# Global Instance
db = DatabaseManager()
