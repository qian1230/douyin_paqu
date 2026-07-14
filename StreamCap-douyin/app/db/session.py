from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import os
from dotenv import load_dotenv
from .base import Base  # Import Base from base.py

# Load environment variables
load_dotenv()

# Database URL (using SQLite for simplicity, can be changed to PostgreSQL/MySQL)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./streamcap.db")

# 分布式部署：节点标识
NODE_ID = os.getenv("NODE_ID", "default")
NODE_NAME = os.getenv("NODE_NAME", "默认节点")

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to False in production
    future=True,
    pool_pre_ping=True,
    pool_recycle=300,
    poolclass=NullPool
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# Dependency to get DB session
async def get_db() -> AsyncSession:
    """Dependency that provides a database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()
