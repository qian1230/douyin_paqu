import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Type
import aiohttp
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording.scraped_room_model import ScrapedRoom, ScrapedRoomStatus
from app.db.session import AsyncSessionLocal
from app.db.base import RecordingLog
from app.core.scraper.base_scraper import BaseScraper
from app.core.scraper.platforms.douyin_feed_scraper import DouyinScraper
from app.core.face_detection.face_detector import FaceDetector
from app.core.recording.record_manager import RecordingManager
from app.core.platforms.platform_handlers import get_platform_handler
from app.models.recording.recording_model import Recording

logger = logging.getLogger(__name__)

class RecordingScheduler:
    def __init__(self, recording_manager: RecordingManager):
        self.recording_manager = recording_manager
        self.face_detector = FaceDetector()
        self.scrapers: Dict[str, Type[BaseScraper]] = {
            'douyin': DouyinScraper,
            # Add other platform scrapers here
        }
        self.active_tasks = {}
        self.lock = asyncio.Lock()
        self.scraping_interval = 12 * 3600  # 12 hours
        self.max_concurrent_recordings = 3
        # 单次录制最长 2 小时，总累计录制上限同样为 2 小时
        self.recording_duration = 2 * 3600  # 2 hours in seconds
        self.max_total_recording_duration = 2 * 3600  # Maximum total recording duration per room: 2 hours
        # 只保留 recordings.json 这一条链路，不直接从 DB 执行任务
        self.use_json_tasks_only = True

    async def start(self):
        """Start the scheduler"""
        logger.info("🚀 Starting recording scheduler...")
        logger.info(f"📋 Configured scrapers: {list(self.scrapers.keys())}")
        
        try:
            # Start the background tasks
            logger.info("🔄 Starting background tasks...")
            asyncio.create_task(self._scraping_loop())
            if not self.use_json_tasks_only:
                asyncio.create_task(self._recording_loop())
            else:
                logger.info("🛑 DB->PENDING 直接录制已禁用，改由 recordings.json 任务负责")
            
            # Initial scrape
            logger.info("🔍 Running initial platform scrape...")
            await self.scrape_all_platforms()
            logger.info("✅ Initial platform scrape completed")
            
        except Exception as e:
            logger.error(f"❌ Failed to start recording scheduler: {e}", exc_info=True)
            raise

    async def _scraping_loop(self):
        """Periodically scrape for new live rooms"""
        logger.info("Starting scraping loop")
        
        while True:
            try:
                logger.debug("Starting new scraping cycle")
                await self.scrape_all_platforms()
                logger.debug("Completed scraping cycle")
            except Exception as e:
                logger.error(f"Error in scraping loop: {e}", exc_info=True)
                # Add a small delay before retrying after an error
                await asyncio.sleep(min(60, self.scraping_interval))
                continue
            
            await asyncio.sleep(self.scraping_interval)

    async def _recording_loop(self):
        """Manage recording of scraped rooms"""
        if self.use_json_tasks_only:
            # 不再直接处理 DB 的 PENDING，交给 recordings.json 同步后的监控流程
            logger.info("Recording loop skipped because use_json_tasks_only=True")
            return
        while True:
            try:
                await self.process_pending_rooms()
            except Exception as e:
                logger.error(f"Error in recording loop: {e}", exc_info=True)
            
            await asyncio.sleep(10)  # Check every 10 seconds

    async def scrape_all_platforms(self, max_rooms: int = None):
        """Scrape all configured platforms
        
        Args:
            max_rooms: 每个平台最多爬取的房间数量。如果为None，则使用配置中的默认值。
        """
        logger.info("🚀 Starting to scrape all platforms...")
        
        if not self.scrapers:
            logger.warning("⚠️ No scrapers configured!")
            return
            
        logger.debug(f"Configured scrapers: {list(self.scrapers.keys())}")
        
        # Create a session with a timeout
        timeout = aiohttp.ClientTimeout(total=60)  # 60 seconds timeout
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for platform_name, scraper_class in self.scrapers.items():
                logger.info(f"\n{'='*50}")
                logger.info(f"🔍 SCRAPING PLATFORM: {platform_name.upper()}")
                logger.info(f"{'='*50}")
                
                try:
                    # Initialize scraper with session
                    try:
                        logger.debug(f"Initializing {platform_name} scraper...")
                        scraper = scraper_class(session=session)
                        logger.debug(f"Successfully initialized {platform_name} scraper")
                    except Exception as e:
                        logger.error(f"❌ Failed to initialize {platform_name} scraper: {e}", exc_info=True)
                        continue
                    
                    # Scrape live rooms
                    try:
                        # 如果指定了max_rooms，使用指定值；否则使用默认值10
                        scrape_limit = max_rooms if max_rooms is not None else 10
                        logger.info(f"🌐 Fetching live rooms from {platform_name} (max_rooms={scrape_limit})...")
                        rooms = await scraper.scrape_live_rooms(max_rooms=scrape_limit)
                        logger.info(f"✅ Found {len(rooms)} live rooms on {platform_name}")
                        
                        if not rooms:
                            logger.warning(f"⚠️ No rooms found on {platform_name}")
                            continue
                            
                        # Log first few rooms for debugging
                        for i, room in enumerate(rooms[:3], 1):
                            logger.debug(f"Room {i}: {getattr(room, 'title', 'No title')} (ID: {getattr(room, 'room_id', 'N/A')})")
                        if len(rooms) > 3:
                            logger.debug(f"... and {len(rooms) - 3} more rooms")
                            
                        # Save to database
                        saved_count = 0
                        for room in rooms:
                            try:
                                saved = await self._save_room(room)
                                if saved:
                                    saved_count += 1
                                    logger.debug(f"💾 Saved room: {getattr(room, 'platform', 'N/A')}/{getattr(room, 'room_id', 'N/A')}")
                                else:
                                    logger.debug(f"ℹ️ Room already exists: {getattr(room, 'platform', 'N/A')}/{getattr(room, 'room_id', 'N/A')}")
                            except Exception as e:
                                room_id = getattr(room, 'room_id', 'unknown')
                                logger.error(f"❌ Error saving room {room_id}: {e}", exc_info=True)
                        
                        logger.info(f"💾 Successfully saved {saved_count}/{len(rooms)} rooms from {platform_name}")
                        
                    except asyncio.TimeoutError as te:
                        logger.error(f"⌛ Timeout while scraping {platform_name}: {te}")
                    except aiohttp.ClientError as ce:
                        logger.error(f"🌐 Network error while scraping {platform_name}: {ce}")
                    except Exception as e:
                        logger.error(f"❌ Unexpected error while scraping {platform_name}: {e}", exc_info=True)
                    
                except Exception as e:
                    logger.error(f"❌ Fatal error processing {platform_name}: {e}", exc_info=True)
                    
                logger.info(f"✅ Finished processing {platform_name}\n")
                
        logger.info("🎉 Finished scraping all platforms")

    async def _save_room(self, room: ScrapedRoom) -> bool:
        """Save a scraped room to the database if it doesn't exist"""
        # #region agent log
        import json as json_module
        import time
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_save_room_start", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:_save_room", "message": "Starting to save room", "data": {"platform": room.platform, "room_id": room.room_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
        # #endregion
        
        try:
            async with AsyncSessionLocal() as db:
                # Check if room already exists (any status)
                result = await db.execute(
                    select(ScrapedRoom)
                    .where(ScrapedRoom.platform == room.platform)
                    .where(ScrapedRoom.room_id == room.room_id)
                )
                existing = result.scalars().first()
                # #region agent log
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_save_room_check", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:_save_room", "message": "Checked for existing room", "data": {"platform": room.platform, "room_id": room.room_id, "existing_found": existing is not None, "existing_id": existing.id if existing else None, "existing_status": existing.status if existing else None}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                # #endregion
                
                if not existing:
                    try:
                        db.add(room)
                        await db.commit()
                        # #region agent log
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"id": "log_save_room_added", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:_save_room", "message": "Added new room", "data": {"platform": room.platform, "room_id": room.room_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                        # #endregion
                        logger.info(f"Added new room to record: {room.platform}/{room.room_id}")
                        return True
                    except Exception as commit_error:
                        # Handle unique constraint violation
                        await db.rollback()
                        # Try to find existing room again (may have been added by another process)
                        result = await db.execute(
                            select(ScrapedRoom)
                            .where(ScrapedRoom.platform == room.platform)
                            .where(ScrapedRoom.room_id == room.room_id)
                        )
                        existing = result.scalars().first()
                        if existing:
                            # Update existing room information
                            existing.title = room.title
                            existing.anchor_name = room.anchor_name
                            existing.viewer_count = room.viewer_count
                            existing.cover_url = room.cover_url
                            existing.last_scraped = datetime.utcnow()
                            existing.updated_at = datetime.utcnow()
                            await db.commit()
                            # #region agent log
                            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                                f.write(json_module.dumps({"id": "log_save_room_updated_after_conflict", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:_save_room", "message": "Updated existing room after unique constraint conflict", "data": {"platform": room.platform, "room_id": room.room_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                            # #endregion
                            logger.debug(f"Updated existing room after conflict: {room.platform}/{room.room_id}")
                            return False
                        else:
                            raise commit_error
                else:
                    # Update existing room information
                    existing.title = room.title
                    existing.anchor_name = room.anchor_name
                    existing.viewer_count = room.viewer_count
                    existing.cover_url = room.cover_url
                    existing.last_scraped = datetime.utcnow()
                    existing.updated_at = datetime.utcnow()
                    await db.commit()
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_save_room_updated", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:_save_room", "message": "Updated existing room", "data": {"platform": room.platform, "room_id": room.room_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                    # #endregion
                    logger.debug(f"Updated existing room: {room.platform}/{room.room_id}")
                    return False
        except Exception as e:
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_save_room_error", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:_save_room", "message": "Error saving room", "data": {"platform": room.platform, "room_id": room.room_id, "error": str(e)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
            # #endregion
            logger.error(f"Error saving room {getattr(room, 'room_id', 'unknown')}: {e}", exc_info=True)
            return False

    async def process_pending_rooms(self):
        """Process pending rooms and start recordings if possible"""
        if self.use_json_tasks_only:
            # recordings.json 任务链路已负责监控/录制，此处不直接处理 DB
            return
        # #region agent log
        import json as json_module
        import time
        import asyncio
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_process_pending_start", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Starting to process pending rooms", "data": {"active_tasks_count": len(self.active_tasks), "max_concurrent": self.max_concurrent_recordings}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "D"}) + "\n")
        # #endregion
        # Don't start new recordings if we're at capacity
        if len(self.active_tasks) >= self.max_concurrent_recordings:
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_process_pending_at_capacity", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "At capacity, skipping", "data": {}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "D"}) + "\n")
            # #endregion
            return

        try:
            async with AsyncSessionLocal() as db:
                # Get pending rooms that haven't been recorded yet (exclude RECORDED and SKIPPED)
                from sqlalchemy import or_
                result = await db.execute(
                    select(ScrapedRoom)
                    .where(ScrapedRoom.status == ScrapedRoomStatus.PENDING)
                    .where(
                        or_(
                            ScrapedRoom.face_detected.is_(None),  # Not checked yet
                            ScrapedRoom.face_detected.is_(True)   # Faces detected
                        )
                    )  # Exclude rooms skipped due to no faces (face_detected == False)
                    .order_by(ScrapedRoom.last_scraped.desc())
                    .limit(self.max_concurrent_recordings - len(self.active_tasks))
                )
                rooms = result.scalars().all()
                # #region agent log
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_process_pending_found", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Found pending rooms", "data": {"pending_count": len(rooms), "room_ids": [r.id for r in rooms]}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "D"}) + "\n")
                # #endregion

                for room in rooms:
                    if room.id in self.active_tasks:
                        # #region agent log
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"id": "log_process_pending_skip_active", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Skipping room already in active tasks", "data": {"room_id": room.id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "D"}) + "\n")
                        # #endregion
                        continue
                    # Check if room has reached maximum recording duration
                    total_duration = await self.get_total_recording_duration(room.id)
                    if total_duration >= self.max_total_recording_duration:
                        logger.info(f"Room {room.platform}/{room.room_id} has reached max duration ({total_duration}s), marking as recorded")
                        room.status = ScrapedRoomStatus.RECORDED
                        room.updated_at = datetime.utcnow()
                        await db.commit()
                        continue

                    # Face detection must be done BEFORE starting recording
                    # Check if face detection has been done
                    if room.face_detected is None:
                        # #region agent log
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"id": "log_process_pending_face_check_start", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Starting face detection for room", "data": {"room_id": room.id, "platform": room.platform, "room_id_str": room.room_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                        # #endregion
                        # Perform face detection first
                        stream_url_for_check = None
                        # 重试 2 次，间隔 60s，获取直链后再做人脸检测
                        for attempt in range(2):
                            try:
                                handler = get_platform_handler(
                                    live_url=room.room_url,
                                    proxy=None,
                                    cookies=None,
                                    record_quality="default",
                                    platform=room.platform,
                                )
                                if handler:
                                    stream_info = await handler.get_stream_info(room.room_url)
                                    if stream_info and getattr(stream_info, "is_live", False):
                                        stream_url_for_check = getattr(stream_info, "record_url", None)
                                        if stream_url_for_check:
                                            break
                            except Exception as e:
                                logger.debug(f"Failed to prefetch stream url for face check (attempt {attempt+1}): {e}")
                            if attempt < 1:
                                await asyncio.sleep(60)  # 等待 60s 再试一次

                        # Check for faces only when we have a direct stream URL
                        has_faces = True
                        if stream_url_for_check:
                            has_faces = await self.face_detector.check_first_frame_for_face(stream_url_for_check)
                            # #region agent log
                            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                                f.write(json_module.dumps({"id": "log_process_pending_face_check_result", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Face detection result", "data": {"room_id": room.id, "has_faces": has_faces}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                            # #endregion
                        else:
                            # If still no stream URL after retries, treat as no-face
                            logger.warning(f"Could not get stream URL for face check for room {room.platform}/{room.room_id}, marking as no-face")
                            has_faces = False

                        # Update face_detected status
                        room.face_detected = has_faces
                        room.updated_at = datetime.utcnow()
                        await db.commit()

                        if not has_faces:
                            logger.info(f"No faces detected in first frame of room {room.platform}/{room.room_id}, skipping and marking")
                            await self.mark_room_skipped(room.id, "No faces detected in first frame")
                            # #region agent log
                            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                                f.write(json_module.dumps({"id": "log_process_pending_face_check_skipped", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Room skipped due to no faces", "data": {"room_id": room.id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                            # #endregion
                            continue

                    # Face detection passed (face_detected == True), now mark as recording and start
                    # Mark as processing
                    room.status = ScrapedRoomStatus.RECORDING
                    room.updated_at = datetime.utcnow()
                    await db.commit()
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_process_pending_marked", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Marked room as recording", "data": {"room_id": room.id, "platform": room.platform, "room_id_str": room.room_id, "face_detected": room.face_detected}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "D"}) + "\n")
                    # #endregion

                    # Start recording task
                    task = asyncio.create_task(self.record_room(room))
                    self.active_tasks[room.id] = task
                    task.add_done_callback(lambda t, rid=room.id: self.active_tasks.pop(rid, None))
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_process_pending_task_created", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Created recording task", "data": {"room_id": room.id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "D"}) + "\n")
                    # #endregion
        except Exception as e:
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_process_pending_error", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:process_pending_rooms", "message": "Error processing pending rooms", "data": {"error": str(e)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "D"}) + "\n")
            # #endregion
            logger.error(f"Error processing pending rooms: {e}", exc_info=True)

    async def record_room(self, room: ScrapedRoom):
        """Record a single room"""
        # #region agent log
        import json as json_module
        import time
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_record_room_start", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:record_room", "message": "Starting to record room", "data": {"room_id": room.id, "platform": room.platform, "room_id_str": room.room_id, "status": room.status}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
        # #endregion
        logger.info(f"Starting recording for room: {room.platform}/{room.room_id}")
        
        try:
            # Face detection should have been done in process_pending_rooms() before calling record_room()
            # Verify that face_detected is True (should not happen if process_pending_rooms() works correctly)
            if room.face_detected is False:
                logger.warning(f"Room {room.platform}/{room.room_id} has face_detected=False, should not be recording. Skipping.")
                await self.mark_room_skipped(room.id, "Face detection failed (should not happen)")
                return
            
            # Check if room has already reached maximum recording duration (5 hours)
            total_duration = await self.get_total_recording_duration(room.id)
            if total_duration >= self.max_total_recording_duration:
                logger.info(f"Room {room.platform}/{room.room_id} has reached maximum recording duration ({total_duration}s >= {self.max_total_recording_duration}s), marking as recorded")
                await self.mark_room_recorded(room.id)
                return
            
            # Build a lightweight Recording and start via RecordingManager workflow
            user_config = self.recording_manager.settings.user_config
            segment_enabled = bool(user_config.get("segmented_recording_enabled", False))
            segment_time = str(user_config.get("video_segment_time", "1800"))

            rec = Recording(
                rec_id=f"{room.platform}_{room.room_id}",
                url=room.room_url,
                streamer_name=room.anchor_name or (room.title or room.room_id),
                record_format="mp4",
                quality=user_config.get("record_quality", "LD") or "LD",
                segment_record=segment_enabled,
                segment_time=segment_time,
                monitor_status=False,
                scheduled_recording=False,
                scheduled_start_time="",
                monitor_hours=0,
                recording_dir=None,
                enabled_message_push=False,
                only_notify_no_record=False,
                flv_use_direct_download=False,
            )

            # Register and start monitoring/recording
            # #region agent log
            import json as json_module
            import time
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_record_room_before_add", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:record_room", "message": "Before adding recording to manager", "data": {"rec_id": rec.rec_id, "current_recordings_count": len(self.recording_manager.recordings)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
            # #endregion
            await self.recording_manager.add_recording(rec)
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_record_room_after_add", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:record_room", "message": "After adding recording to manager", "data": {"rec_id": rec.rec_id, "current_recordings_count": len(self.recording_manager.recordings)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
            # #endregion
            await self.recording_manager.start_monitor_recording(rec, auto_save=False)
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_record_room_after_start", "timestamp": time.time() * 1000, "location": "recording_scheduler.py:record_room", "message": "After starting monitor recording", "data": {"rec_id": rec.rec_id, "monitor_status": rec.monitor_status}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
            # #endregion

            # Record for the specified duration or until stopped or max duration reached
            start_time = datetime.utcnow()
            total_duration_before = await self.get_total_recording_duration(room.id)
            remaining_duration = self.max_total_recording_duration - total_duration_before
            
            # Don't record longer than remaining duration
            max_recording_time = min(self.recording_duration, remaining_duration)
            
            if max_recording_time <= 0:
                logger.info(f"Room {room.platform}/{room.room_id} has no remaining recording time, marking as recorded")
                await self.mark_room_recorded(room.id)
                return
            
            while (datetime.utcnow() - start_time).total_seconds() < max_recording_time:
                await asyncio.sleep(10)
                if not await self.is_room_live(room):
                    logger.info(f"Room {room.platform}/{room.room_id} is no longer live, stopping recording")
                    break
                
                # Check if we've reached max duration (including current recording)
                elapsed_time = (datetime.utcnow() - start_time).total_seconds()
                current_total = total_duration_before + elapsed_time
                if current_total >= self.max_total_recording_duration:
                    logger.info(f"Room {room.platform}/{room.room_id} has reached maximum recording duration, stopping")
                    break

            # Stop recording gracefully
            self.recording_manager.stop_recording(rec, manually_stopped=False)
            
            # Save recording duration to database
            recording_duration = (datetime.utcnow() - start_time).total_seconds()
            await self.save_recording_duration(room.id, recording_duration, start_time)
            
            # Check if total duration reached max, if so mark as recorded
            final_total = total_duration_before + recording_duration
            if final_total >= self.max_total_recording_duration:
                await self.mark_room_recorded(room.id)
            else:
                # Mark room back to pending for next recording session
                await self.mark_room_pending(room.id)
            
        except Exception as e:
            logger.error(f"Error recording room {room.platform}/{room.room_id}: {e}", exc_info=True)
            await self.mark_room_error(room.id, str(e))
            
    async def is_room_live(self, room: ScrapedRoom) -> bool:
        """Check if a room is still live"""
        # Implement actual check based on platform API
        # This is a placeholder implementation
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(room.room_url, timeout=10) as response:
                    return response.status == 200
        except:
            return False

    async def mark_room_recorded(self, room_id: int):
        """Mark a room as successfully recorded"""
        async with AsyncSessionLocal() as db:
            room = await db.get(ScrapedRoom, room_id)
            if room:
                room.status = ScrapedRoomStatus.RECORDED
                room.updated_at = datetime.utcnow()
                await db.commit()

    async def mark_room_skipped(self, room_id: int, reason: str):
        """Mark a room as skipped (e.g., no faces detected)"""
        async with AsyncSessionLocal() as db:
            room = await db.get(ScrapedRoom, room_id)
            if room:
                room.status = ScrapedRoomStatus.SKIPPED
                room.face_detected = False  # Mark that no faces were detected
                room.updated_at = datetime.utcnow()
                await db.commit()
                logger.info(f"Marked room {room_id} as skipped: {reason}")
    
    async def mark_room_pending(self, room_id: int):
        """Mark a room as pending for next recording session"""
        async with AsyncSessionLocal() as db:
            room = await db.get(ScrapedRoom, room_id)
            if room:
                room.status = ScrapedRoomStatus.PENDING
                room.updated_at = datetime.utcnow()
                await db.commit()
    
    async def get_total_recording_duration(self, room_id: int) -> float:
        """Get total recording duration for a room in seconds"""
        async with AsyncSessionLocal() as db:
            room = await db.get(ScrapedRoom, room_id)
            if not room:
                return 0.0
            
            # Sum all completed recording durations for this room
            result = await db.execute(
                select(RecordingLog)
                .where(RecordingLog.room_id == room.room_id)
                .where(RecordingLog.platform == room.platform)
                .where(RecordingLog.status == 'completed')
            )
            logs = result.scalars().all()
            total_duration = sum(log.duration or 0 for log in logs)
            return float(total_duration)
    
    async def save_recording_duration(self, room_id: int, duration: float, start_time: datetime):
        """Save recording duration to RecordingLog"""
        async with AsyncSessionLocal() as db:
            room = await db.get(ScrapedRoom, room_id)
            if not room:
                return
            
            # Create a recording log entry
            log = RecordingLog(
                room_id=room.room_id,
                platform=room.platform,
                start_time=start_time,
                end_time=datetime.utcnow(),
                duration=int(duration),
                status='completed'
            )
            db.add(log)
            await db.commit()
            logger.debug(f"Saved recording log for room {room.platform}/{room.room_id}: {duration}s")

            # 记录全局累计时长（所有已完成录制）
            total_result = await db.execute(
                select(func.sum(RecordingLog.duration)).where(RecordingLog.status == 'completed')
            )
            total_seconds = total_result.scalar() or 0
            logger.info(f"Total recorded duration (all videos): {int(total_seconds)}s")

    async def mark_room_error(self, room_id: int, error: str):
        """Mark a room as errored"""
        async with AsyncSessionLocal() as db:
            room = await db.get(ScrapedRoom, room_id)
            if room:
                room.status = ScrapedRoomStatus.ERROR
                room.updated_at = datetime.utcnow()
                await db.commit()

    async def cleanup_stale_rooms(self):
        """Clean up stale room records"""
        async with AsyncSessionLocal() as db:
            # Mark any recording rooms older than 24 hours as completed
            result = await db.execute(
                select(ScrapedRoom)
                .where(ScrapedRoom.status == ScrapedRoomStatus.RECORDING)
                .where(ScrapedRoom.updated_at < datetime.utcnow() - timedelta(hours=24))
            )
            
            for room in result.scalars():
                room.status = ScrapedRoomStatus.RECORDED
                room.updated_at = datetime.utcnow()
            
            await db.commit()
