from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint
from enum import Enum

class ScrapedRoomStatus(str, Enum):
    PENDING = "pending"
    RECORDING = "recording"
    RECORDED = "recorded"
    SKIPPED = "skipped"
    ERROR = "error"

class ScrapedRoom(SQLModel, table=True):
    __tablename__ = "scraped_rooms"
    __table_args__ = (
        UniqueConstraint('platform', 'room_id', name='uq_scraped_rooms_platform_room_id'),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str
    room_id: str
    room_url: str
    # 直播间类别（如：文化/生活/聊天），用于后续分类存储与分析
    category: Optional[str] = None
    title: Optional[str] = None
    anchor_name: Optional[str] = None
    viewer_count: Optional[int] = None
    cover_url: Optional[str] = None
    status: ScrapedRoomStatus = Field(default=ScrapedRoomStatus.PENDING)
    is_active: bool = Field(default=True)
    face_detected: Optional[bool] = None
    last_scraped: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
