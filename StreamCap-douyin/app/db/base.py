from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

class BaseModel:
    """Base model with common fields and methods"""
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

class ScrapedRoom(Base, BaseModel):
    """Model for storing scraped live rooms"""
    __tablename__ = "scraped_rooms"
    
    platform = Column(String(50), nullable=False, index=True)
    room_id = Column(String(100), nullable=False, index=True)
    room_url = Column(String(500), nullable=False)
    # 直播间类别（如：文化/生活/聊天）
    category = Column(String(100))
    title = Column(String(500))
    anchor_name = Column(String(200))
    viewer_count = Column(Integer, default=0)
    cover_url = Column(String(500))
    status = Column(String(20), default='pending')  # pending, recording, recorded, skipped, error
    face_detected = Column(Boolean, default=None, nullable=True)
    last_scraped = Column(DateTime, default=datetime.utcnow)
    # 分布式部署：分配给哪个节点处理
    assigned_node = Column(String(50), nullable=True, index=True)
    
    # Add unique constraint for platform + room_id combination
    __table_args__ = (
        UniqueConstraint('platform', 'room_id', name='uq_scraped_rooms_platform_room_id'),
        {'sqlite_autoincrement': True},
    )

class RecordingLog(Base, BaseModel):
    """Model for recording logs"""
    __tablename__ = "recording_logs"
    
    room_id = Column(String(100), nullable=False, index=True)
    platform = Column(String(50), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    duration = Column(Integer)  # in seconds
    file_path = Column(String(500))
    file_size = Column(Integer)  # in bytes
    status = Column(String(20))  # started, completed, failed
    error_message = Column(String(1000))
    
    # Add foreign key relationship
    # room_id = Column(Integer, ForeignKey('scraped_rooms.id'), index=True)
    
    __table_args__ = ({
        'sqlite_autoincrement': True,
    },)

async def create_tables():
    """Create database tables if they don't exist"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    from .session import DATABASE_URL, engine
    
    # Create a new engine to avoid connection pool issues
    temp_engine = create_async_engine(DATABASE_URL)
    
    try:
        async with temp_engine.begin() as conn:
            # For SQLite, we need to enable foreign keys
            if DATABASE_URL.startswith('sqlite'):
                await conn.execute(text('PRAGMA foreign_keys = ON'))
            
            # Create all tables
            from .base import Base  # Import here to avoid circular imports
            await conn.run_sync(Base.metadata.create_all)
            
            # Add unique constraint if it doesn't exist (for existing databases)
            try:
                await conn.execute(text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_scraped_rooms_platform_room_id 
                    ON scraped_rooms(platform, room_id)
                """))
            except Exception as e:
                logger.debug(f"Unique constraint may already exist: {e}")

            # 如果旧表缺少字段，自动添加
            try:
                if DATABASE_URL.startswith('sqlite'):
                    # SQLite: 使用 PRAGMA 检查列
                    result = await conn.execute(text("PRAGMA table_info(scraped_rooms)"))
                    columns = [row[1] for row in result.fetchall()]  # row[1] 是列名
                    if "category" not in columns:
                        logger.info("Adding missing column 'category' to scraped_rooms")
                        await conn.execute(text("ALTER TABLE scraped_rooms ADD COLUMN category VARCHAR(100)"))
                    if "assigned_node" not in columns:
                        logger.info("Adding missing column 'assigned_node' to scraped_rooms")
                        await conn.execute(text("ALTER TABLE scraped_rooms ADD COLUMN assigned_node VARCHAR(50)"))
                else:
                    # PostgreSQL/MySQL: 尝试添加列（如果不存在会报错，忽略即可）
                    try:
                        await conn.execute(text("ALTER TABLE scraped_rooms ADD COLUMN IF NOT EXISTS category VARCHAR(100)"))
                        logger.info("Added column 'category' to scraped_rooms")
                    except Exception:
                        pass
                    try:
                        await conn.execute(text("ALTER TABLE scraped_rooms ADD COLUMN IF NOT EXISTS assigned_node VARCHAR(50)"))
                        logger.info("Added column 'assigned_node' to scraped_rooms")
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Failed to add columns to scraped_rooms: {e}")
            
            logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise
    finally:
        await temp_engine.dispose()
