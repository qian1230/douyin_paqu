import asyncio
import threading
from collections import defaultdict
from datetime import datetime, timedelta

from ...messages import desktop_notify, message_pusher
from ...models.recording.recording_model import Recording
from ...models.recording.recording_status_model import RecordingStatus
from ...utils import utils
from ...utils.logger import logger
from ..platforms.platform_handlers import get_platform_info
from ..runtime.process_manager import BackgroundService
from ..face_detection.face_detector import FaceDetector
from app.db.session import AsyncSessionLocal, NODE_ID
from app.models.recording.scraped_room_model import ScrapedRoom, ScrapedRoomStatus
from app.db.base import RecordingLog
from sqlalchemy.future import select
from sqlalchemy import func
from .stream_manager import LiveStreamRecorder


class GlobalRecordingState:
    recordings = []
    lock = threading.Lock()


class RecordingManager:
    _sync_task_started = False

    def __init__(self, app):
        self.app = app
        self.settings = app.settings
        self.periodic_task_started = False
        self.loop_time_seconds = None
        self.face_detector = FaceDetector()
        self.sync_interval_seconds = 900  # 定期同步 DB↔recordings.json，默认15分钟（减少请求频率）
        # JSON 流程下单房间累计录制上限：2 小时（秒）
        self.max_total_recording_duration = 2 * 3600
        self.app.language_manager.add_observer(self)
        self.load_recordings()
        self._ = {}
        self.load()
        self.initialize_dynamic_state()
        max_concurrent = int(self.settings.user_config.get("platform_max_concurrent_requests", 3))
        self.platform_semaphores = defaultdict(lambda: asyncio.Semaphore(max_concurrent))
        # 限制同时开始录制的数量，避免启动时大量任务同时开始录制触发反爬
        max_concurrent_start_recordings = int(self.settings.user_config.get("max_concurrent_start_recordings", 3))
        self.start_recording_semaphore = asyncio.Semaphore(max_concurrent_start_recordings)
        self.active_recorders = {}

    @property
    def recordings(self):
        return GlobalRecordingState.recordings

    @recordings.setter
    def recordings(self, value):
        raise AttributeError("Please use add_recording/update_recording methods to modify data")

    def load(self):
        language = self.app.language_manager.language
        for key in ("recording_manager", "video_quality"):
            self._.update(language.get(key, {}))

    def load_recordings(self):
        """Load recordings from a JSON file into objects."""
        # #region agent log
        import json as json_module
        import time
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_load_recordings_start", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recordings", "message": "Starting to load recordings", "data": {}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
        # #endregion
        recordings_data = self.app.config_manager.load_recordings_config()
        # #region agent log
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_recordings_data_loaded", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recordings", "message": "Recordings data loaded from config", "data": {"type": type(recordings_data).__name__, "is_list": isinstance(recordings_data, list), "is_dict": isinstance(recordings_data, dict), "length": len(recordings_data) if hasattr(recordings_data, '__len__') else None, "current_recordings_count": len(GlobalRecordingState.recordings)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
        # #endregion
        if not GlobalRecordingState.recordings:
            try:
                if isinstance(recordings_data, list):
                    # Deduplicate by rec_id, keeping the last occurrence
                    seen_rec_ids = {}
                    deduplicated_data = []
                    for rec in recordings_data:
                        rec_id = rec.get('rec_id') if isinstance(rec, dict) else getattr(rec, 'rec_id', None)
                        if rec_id:
                            if rec_id in seen_rec_ids:
                                # Replace with newer occurrence
                                deduplicated_data[seen_rec_ids[rec_id]] = rec
                            else:
                                seen_rec_ids[rec_id] = len(deduplicated_data)
                                deduplicated_data.append(rec)
                        else:
                            deduplicated_data.append(rec)
                    
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_recordings_deduplicated", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recordings", "message": "Deduplicated recordings", "data": {"original_count": len(recordings_data), "deduplicated_count": len(deduplicated_data), "duplicates_removed": len(recordings_data) - len(deduplicated_data)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
                    # #endregion

                    # 强制将质量设为最低档（使用用户配置的最低值，默认 LD）
                    user_config = self.settings.user_config
                    target_quality = user_config.get("record_quality", "LD") or "LD"
                    # 按用户配置默认开启“分段录制”
                    segment_enabled = bool(user_config.get("segmented_recording_enabled", False))
                    segment_time = str(user_config.get("video_segment_time", "1800"))
                    recordings_list = []
                    for rec in deduplicated_data:
                        # 丢弃无 rec_id 或无 url 的无效记录，避免后续状态为空
                        rec_id = rec.get("rec_id") if isinstance(rec, dict) else getattr(rec, "rec_id", None)
                        url_val = rec.get("url") if isinstance(rec, dict) else getattr(rec, "url", None)
                        if not rec_id or not url_val:
                            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                                f.write(json_module.dumps({
                                    "id": "log_recordings_invalid_skip",
                                    "timestamp": time.time() * 1000,
                                    "location": "record_manager.py:load_recordings",
                                    "message": "Skip invalid recording without rec_id or url",
                                    "data": {"rec_id": rec_id, "url": url_val},
                                    "sessionId": "debug-session",
                                    "runId": "run1",
                                    "hypothesisId": "B"
                                }) + "\n")
                            continue
                        r_obj = Recording.from_dict(rec)
                        r_obj.quality = target_quality
                        recordings_list.append(r_obj)

                    GlobalRecordingState.recordings = recordings_list
                elif isinstance(recordings_data, dict):
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_recordings_data_is_dict", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recordings", "message": "Recordings data is dict, not list", "data": {"dict_keys": list(recordings_data.keys()) if recordings_data else []}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
                    # #endregion
                    GlobalRecordingState.recordings = []
                else:
                    GlobalRecordingState.recordings = []
            except Exception as e:
                # #region agent log
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_recordings_load_error", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recordings", "message": "Error loading recordings", "data": {"error": str(e)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
                # #endregion
                GlobalRecordingState.recordings = []
        # #region agent log
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_load_recordings_end", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recordings", "message": "Finished loading recordings", "data": {"final_count": len(self.recordings)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
        # #endregion
        logger.info(f"Live Recordings: Loaded {len(self.recordings)} items")

        # 加载完成后，强制刷新一次 UI 卡片，确保页面与内存中的 recordings 数量一致
        try:
            self.app.page.run_task(self.app.recordings.add_record_cards)
        except Exception:
            # UI 不可用时静默忽略
            pass

    def initialize_dynamic_state(self):
        """Initialize dynamic state for all recordings."""
        loop_time_seconds = self.settings.user_config.get("loop_time_seconds")
        self.loop_time_seconds = int(loop_time_seconds or 300)
        # 统一降级为用户配置的最低画质（默认 LD）
        target_quality = self.settings.user_config.get("record_quality", "LD") or "LD"
        for recording in self.recordings:
            recording.quality = target_quality
            recording.loop_time_seconds = self.loop_time_seconds
            recording.update_title(self._[recording.quality])
            recording.showed_checking_status = True

    async def add_recording(self, recording):
        # 不要在持有锁的情况下 await，避免潜在死锁 / 卡死
        import json as json_module
        import time

        with GlobalRecordingState.lock:
            # Check if recording with same rec_id already exists
            existing = self.find_recording_by_id(recording.rec_id)
            if existing:
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_add_recording_duplicate", "timestamp": time.time() * 1000, "location": "record_manager.py:add_recording", "message": "Recording with same rec_id already exists, skipping", "data": {"rec_id": recording.rec_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
                return
            GlobalRecordingState.recordings.append(recording)
            current_total = len(GlobalRecordingState.recordings)

        # 记录新增日志（在锁外，减少锁内开销）
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_add_recording_new", "timestamp": time.time() * 1000, "location": "record_manager.py:add_recording", "message": "Added new recording to memory", "data": {"rec_id": recording.rec_id, "total_after_add": current_total}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")

        # 在锁外执行持久化，避免在持有锁时 await
        await self.persist_recordings()

        # 内存中新增录制任务后，通知 UI 刷新卡片（幂等，已有卡片不会重复创建）
        try:
            self.app.page.run_task(self.app.recordings.add_record_cards)
        except Exception:
            pass

    async def remove_recording(self, recording: Recording):
        with GlobalRecordingState.lock:
            GlobalRecordingState.recordings.remove(recording)
            await self.persist_recordings()

    async def clear_all_recordings(self):
        with GlobalRecordingState.lock:
            GlobalRecordingState.recordings.clear()
            await self.persist_recordings()

    async def persist_recordings(self):
        """Persist recordings to a JSON file."""
        # #region agent log
        import json as json_module
        import time
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({
                "id": "log_persist_entry",
                "timestamp": time.time() * 1000,
                "location": "record_manager.py:persist_recordings",
                "message": "Persist recordings entry",
                "data": {"current_count": len(self.recordings)},
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "PERSIST"
            }) + "\n")
        # #endregion

        try:
            # Deduplicate before saving，同时丢弃无效记录（无 rec_id 或无 url）
            seen_rec_ids = {}
            deduplicated_recordings = []
            for rec in self.recordings:
                if not getattr(rec, "rec_id", None) or not getattr(rec, "url", None):
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({
                            "id": "log_persist_invalid_skip",
                            "timestamp": time.time() * 1000,
                            "location": "record_manager.py:persist_recordings",
                            "message": "Skip invalid recording without rec_id or url",
                            "data": {"rec_id": getattr(rec, 'rec_id', None), "url": getattr(rec, 'url', None)},
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "PERSIST"
                        }) + "\n")
                    continue
                if rec.rec_id not in seen_rec_ids:
                    seen_rec_ids[rec.rec_id] = True
                    deduplicated_recordings.append(rec)
                else:
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_persist_duplicate_removed", "timestamp": time.time() * 1000, "location": "record_manager.py:persist_recordings", "message": "Removed duplicate recording before saving", "data": {"rec_id": rec.rec_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "B"}) + "\n")
                    # #endregion
            
            # Update GlobalRecordingState with deduplicated list
            if len(deduplicated_recordings) != len(self.recordings):
                with GlobalRecordingState.lock:
                    GlobalRecordingState.recordings = deduplicated_recordings
            
            data_to_save = [rec.to_dict() for rec in deduplicated_recordings]
            await self.app.config_manager.save_recordings_config(data_to_save)
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_persist_recordings_saved", "timestamp": time.time() * 1000, "location": "record_manager.py:persist_recordings", "message": "Persisted recordings to JSON", "data": {"saved_count": len(deduplicated_recordings)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")
            # #endregion
        except Exception as e:
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({
                    "id": "log_persist_error",
                    "timestamp": time.time() * 1000,
                    "location": "record_manager.py:persist_recordings",
                    "message": "Error while persisting recordings",
                    "data": {"error": str(e)},
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "PERSIST"
                }) + "\n")
            # #endregion
            raise

    async def update_recording_card(self, recording: Recording, updated_info: dict):
        """Update an existing recording object and persist changes to a JSON file."""
        if recording:
            recording.update(updated_info)
            self.app.page.run_task(self.persist_recordings)

    @staticmethod
    async def _update_recording(
            recording: Recording, monitor_status: bool, display_title: str, status_info: str, selected: bool
    ):
        attrs_update = {
            "monitor_status": monitor_status,
            "display_title": display_title,
            "status_info": status_info,
            "selected": selected,
        }
        for attr, value in attrs_update.items():
            setattr(recording, attr, value)

    async def start_monitor_recording(self, recording: Recording, auto_save: bool = True):
        """
        Start monitoring a single recording if it is not already being monitored.
        """
        if not recording.monitor_status:
            recording.is_checking = True
            recording.is_live = False
            recording.showed_checking_status = False
            await self._update_recording(
                recording=recording,
                monitor_status=True,
                display_title=recording.title,
                status_info=RecordingStatus.STATUS_CHECKING,
                selected=False,
            )

            self.app.page.run_task(self.app.record_card_manager.update_card, recording)
            self.app.page.pubsub.send_others_on_topic("update", recording)

            self.app.page.run_task(self.check_if_live, recording)

            if auto_save:
                self.app.page.run_task(self.persist_recordings)

    async def stop_monitor_recording(self, recording: Recording, auto_save: bool = True):
        """
        Stop monitoring a single recording if it is currently being monitored.
        """
        if recording.monitor_status:
            await self._update_recording(
                recording=recording,
                monitor_status=False,
                display_title=f"[{self._['monitor_stopped']}] {recording.title}",
                status_info=RecordingStatus.STOPPED_MONITORING,
                selected=False,
            )
            self.stop_recording(recording, manually_stopped=True)
            self.app.page.run_task(self.app.record_card_manager.update_card, recording)
            self.app.page.pubsub.send_others_on_topic("update", recording)
            if auto_save:
                self.app.page.run_task(self.persist_recordings)

    async def start_monitor_recordings(self):
        """
        Start monitoring multiple recordings based on user selection or all recordings if none are selected.
        """
        selected_recordings = await self.get_selected_recordings()
        pre_start_monitor_recordings = selected_recordings if selected_recordings else self.recordings
        cards_obj = self.app.record_card_manager.cards_obj
        for recording in pre_start_monitor_recordings:
            if cards_obj[recording.rec_id]["card"].visible:
                self.app.page.run_task(self.start_monitor_recording, recording, auto_save=False)
        self.app.page.run_task(self.persist_recordings)
        logger.info(f"Batch Start Monitor Recordings: {[i.rec_id for i in pre_start_monitor_recordings]}")

    async def stop_monitor_recordings(self, selected_recordings: list[Recording | None] | None = None):
        """
        Stop monitoring multiple recordings based on user selection or all recordings if none are selected.
        """
        if not selected_recordings:
            selected_recordings = await self.get_selected_recordings()
        pre_stop_monitor_recordings = selected_recordings or self.recordings
        cards_obj = self.app.record_card_manager.cards_obj
        for recording in pre_stop_monitor_recordings:
            if cards_obj[recording.rec_id]["card"].visible:
                self.app.page.run_task(self.stop_monitor_recording, recording, auto_save=False)
        self.app.page.run_task(self.persist_recordings)
        logger.info(f"Batch Stop Monitor Recordings: {[i.rec_id for i in pre_stop_monitor_recordings]}")

    async def get_selected_recordings(self):
        return [recording for recording in self.recordings if recording.selected]

    async def remove_recordings(self, recordings: list[Recording]):
        """Remove a recording from the list and update the JSON file."""
        for recording in recordings:
            if recording in self.recordings:
                await self.remove_recording(recording)
                logger.info(f"Delete Items: {recording.rec_id}-{recording.streamer_name}")

    def find_recording_by_id(self, rec_id: str):
        """Find a recording by its ID (hash of dict representation)."""
        for rec in self.recordings:
            if rec.rec_id == rec_id:
                return rec
        return None

    async def check_all_live_status(self):
        """Check the live status of all recordings and update their display titles."""
        # #region agent log
        import json as json_module
        import time
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_check_all_live_start", "timestamp": time.time() * 1000, "location": "record_manager.py:check_all_live_status", "message": "Starting check_all_live_status", "data": {"recordings_count": len(self.recordings), "recording_enabled": self.app.recording_enabled}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
        # #endregion
        for recording in self.recordings:
            if recording.monitor_status and not recording.is_recording:
                is_exceeded = utils.is_time_interval_exceeded(recording.detection_time, recording.loop_time_seconds)
                if not recording.detection_time or is_exceeded:
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_check_if_live_triggered", "timestamp": time.time() * 1000, "location": "record_manager.py:check_all_live_status", "message": "Triggering check_if_live", "data": {"rec_id": recording.rec_id, "monitor_status": recording.monitor_status, "is_recording": recording.is_recording}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
                    # #endregion
                    self.app.page.run_task(self.check_if_live, recording)

    _periodic_task_running = False

    @classmethod
    def is_periodic_task_running(cls):
        return cls._periodic_task_running

    @classmethod
    def set_periodic_task_running(cls, value=True):
        cls._periodic_task_running = value

    async def setup_periodic_live_check(self, interval: int = 300):
        """Set up a periodic task to check live status."""

        async def periodic_check():
            logger.info("Starting periodic live check background task")
            # #region agent log
            import json as json_module
            import time
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_periodic_check_start", "timestamp": time.time() * 1000, "location": "record_manager.py:periodic_check", "message": "Periodic check task started", "data": {"interval": interval}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
            # #endregion

            first_loop = True
            while True:
                immediate_check_on_startup = self.app.settings.user_config.get("check_live_on_browser_refresh", True)
                # #region agent log
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({
                        "id": "log_periodic_check_loop",
                        "timestamp": time.time() * 1000,
                        "location": "record_manager.py:periodic_check",
                        "message": "Periodic check loop iteration",
                        "data": {
                            "immediate_check": immediate_check_on_startup,
                            "first_loop": first_loop,
                            "recording_enabled": self.app.recording_enabled,
                            "recordings_count": len(self.recordings),
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "E"
                    }) + "\n")
                # #endregion

                # 启动后：如果开启了“浏览器刷新立即检测”，首次循环不等待，直接检测；
                # 之后每次循环都先 sleep 再检测。
                if not first_loop or not immediate_check_on_startup:
                    await asyncio.sleep(interval)

                await self.check_free_space()
                if self.app.recording_enabled:
                    await self.check_all_live_status()

                first_loop = False

        if not RecordingManager.is_periodic_task_running():
            RecordingManager.set_periodic_task_running(True)
            self.periodic_task_started = True
            logger.info(f"Initializing periodic live check task with interval: {interval}s")
            asyncio.create_task(periodic_check())
            # 启动后立即同步一次 DB→recordings.json（不等待10分钟周期）
            asyncio.create_task(self.sync_recordings_with_db())
            # 启动 DB↔recordings.json 同步循环
            if not RecordingManager._sync_task_started:
                RecordingManager._sync_task_started = True
                asyncio.create_task(self._sync_recordings_loop())
        else:
            logger.info("Periodic live check task already running globally, skipping initialization")

    async def check_if_live(self, recording: Recording):
        # #region agent log
        import json as json_module
        import time
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_check_if_live_entry", "timestamp": time.time() * 1000, "location": "record_manager.py:check_if_live", "message": "check_if_live function entry", "data": {"rec_id": recording.rec_id, "url": recording.url}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "E"}) + "\n")
        # #endregion
        """Check if the live stream is available, fetch stream data and update is_live status."""

        recording.manually_stopped = False
        if recording.is_recording or recording.stopping_in_progress:
            logger.debug(f"Skip check_if_live because recording is busy: {recording.url}")
            return

        if recording.rec_id in self.active_recorders:
            logger.debug(f"Skip check_if_live because recorder is active: {recording.url}")
            return

        # JSON 流程下：先检查该房间在 RecordingLog 中的累计录制时长，超过 5 小时则不再继续录制，并标记为 RECORDED 且从列表/UI 中移除
        try:
            total_seconds = await self._get_total_recording_duration_for_rec(recording.rec_id)
            if total_seconds >= self.max_total_recording_duration:
                logger.info(
                    f"Skip recording for {recording.rec_id}: "
                    f"total recorded duration {int(total_seconds)}s >= {self.max_total_recording_duration}s"
                )
                await self._mark_room_status_in_db(recording.rec_id, ScrapedRoomStatus.RECORDED)
                # 从内存与 recordings.json 中移除，并同步移除 UI 卡片
                await self.delete_recording_cards([recording])
                # 触达上限移除后，尝试补充新任务
                asyncio.create_task(self.ensure_min_recordings())
                return
        except Exception as e:
            logger.debug(f"Failed to check total recording duration for {recording.rec_id}: {e}")
            if not recording.monitor_status:
                recording.display_title = f"[{self._['monitor_stopped']}] {recording.title}"
                recording.status_info = RecordingStatus.STOPPED_MONITORING
                recording.is_checking = False
                self.app.page.run_task(self.app.record_card_manager.update_card, recording)
                return

        recording.detection_time = datetime.now().time()
        recording.is_checking = True

        if not recording.showed_checking_status:
            recording.status_info = RecordingStatus.STATUS_CHECKING
            recording.showed_checking_status = True
            self.app.page.run_task(self.app.record_card_manager.update_card, recording)

        if recording.scheduled_recording:
            scheduled_time_range_list = await self.get_scheduled_time_range(
                recording.scheduled_start_time, recording.monitor_hours)
            recording.scheduled_time_range = scheduled_time_range_list
            in_scheduled = False
            for scheduled_time_range in scheduled_time_range_list:
                in_scheduled = utils.is_current_time_within_range(scheduled_time_range)
                if in_scheduled:
                    break

            if not in_scheduled:
                recording.status_info = RecordingStatus.NOT_IN_SCHEDULED_CHECK
                recording.is_live = False
                recording.is_checking = False
                logger.info(f"Skip Detection: {recording.url} not in scheduled check range {scheduled_time_range_list}")
                self.app.page.run_task(self.app.record_card_manager.update_card, recording)
                return

        recording.status_info = RecordingStatus.STATUS_CHECKING
        platform, platform_key = get_platform_info(recording.url)

        if platform and platform_key and (recording.platform is None or recording.platform_key is None):
            recording.platform = platform
            recording.platform_key = platform_key
            self.app.page.run_task(self.persist_recordings)

        if self.settings.user_config["language"] != "zh_CN":
            platform = platform_key

        output_dir = self.settings.get_video_save_path()
        await self.check_free_space(output_dir)
        if not self.app.recording_enabled:
            recording.is_checking = False
            recording.status_info = RecordingStatus.NOT_RECORDING_SPACE
            return
        
        # 提前获取信号量，避免并发过多导致反爬（在批量检查时尤其重要）
        semaphore = self.platform_semaphores[platform_key]
        async with semaphore:
            logger.info(f"[check_if_live] Fetch stream start: rec_id={recording.rec_id}, url={recording.url}, platform={platform_key}")
            recording_info = {
                "platform": platform,
                "platform_key": platform_key,
                "live_url": recording.url,
                "output_dir": output_dir,
                "segment_record": recording.segment_record,
                "segment_time": recording.segment_time,
                "save_format": recording.record_format,
                "quality": recording.quality,
            }

            recorder = LiveStreamRecorder(self.app, recording, recording_info)
            # 重试获取直链 2 次，间隔 60s
            stream_info = None
            for attempt in range(2):
                stream_info = await recorder.fetch_stream()
                logger.info(f"[check_if_live] Fetch stream attempt {attempt+1}/2: rec_id={recording.rec_id}, stream_info={stream_info}")
                if stream_info and stream_info.anchor_name:
                    break
                if attempt < 1:
                    await asyncio.sleep(60)

        if not stream_info or not stream_info.anchor_name:
            logger.error(f"[check_if_live] Fetch stream data failed after retries: {recording.url}")
            recording.is_checking = False
            recording.status_info = RecordingStatus.LIVE_STATUS_CHECK_ERROR
            if recording.monitor_status:
                self.app.page.run_task(self.app.record_card_manager.update_card, recording)
                self.app.page.pubsub.send_others_on_topic("update", recording)
            return
        if self.settings.user_config.get("remove_emojis"):
            stream_info.anchor_name = utils.clean_name(stream_info.anchor_name, self._["live_room"])

        if stream_info.is_live:
            # 检查当前录制数量是否已经达到上限，如果达到上限则不开始新的录制
            max_recording_count = int(self.settings.user_config.get("max_recording_count", 6))
            current_recording_count = 0
            with GlobalRecordingState.lock:
                current_recording_count = sum(
                    1 for r in self.recordings if getattr(r, "is_recording", False)
                )
            
            # 如果当前录制数量已经达到或超过上限，且当前任务还没有在录制，则不开始录制
            if current_recording_count >= max_recording_count and not recording.is_recording:
                logger.info(
                    f"Skip starting recording for {recording.rec_id}: "
                    f"current recording count ({current_recording_count}) >= max limit ({max_recording_count})"
                )
                recording.is_live = stream_info.is_live
                recording.is_checking = False
                recording.status_info = RecordingStatus.MONITORING
                self.app.page.run_task(self.app.record_card_manager.update_card, recording)
                self.app.page.pubsub.send_others_on_topic("update", recording)
                return
            
            recording.live_title = stream_info.title
            if recording.streamer_name.strip() == self._["live_room"]:
                recording.streamer_name = stream_info.anchor_name
            recording.title = f"{recording.streamer_name} - {self._[recording.quality]}"
            recording.display_title = f"[{self._['is_live']}] {recording.title}"

            if not recording.is_live:
                recording.is_live = stream_info.is_live
                recording.notified_live_start = False
                recording.notified_live_end = False

                if desktop_notify.should_push_notification(self.app):
                    desktop_notify.send_notification(
                        title=self._["notify"],
                        message=recording.streamer_name + ' | ' + self._["live_recording_started_message"],
                        app_icon=self.app.tray_manager.icon_path
                    )

            msg_manager = message_pusher.MessagePusher(self.settings)
            user_config = self.settings.user_config
            if (msg_manager.should_push_message(self.settings, recording, message_type='start')
                    and not recording.notified_live_start):
                push_content = self._["push_content"]
                begin_push_message_text = user_config.get("custom_stream_start_content")
                if begin_push_message_text:
                    push_content = begin_push_message_text

                push_at = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
                push_content = push_content.replace("[room_name]", recording.streamer_name).replace(
                    "[time]", push_at).replace("[title]", recording.live_title or "None")
                msg_title = user_config.get("custom_notification_title").strip()
                msg_title = msg_title or self._["status_notify"]

                BackgroundService.get_instance().add_task(
                    msg_manager.push_messages_sync, msg_title, push_content
                )
                recording.notified_live_start = True

            if not recording.only_notify_no_record:
                # recordings.json 入口也做首帧人脸检测，避免绕过检测直接录制
                has_faces = True
                stream_url_for_check = getattr(stream_info, "record_url", None)
                if stream_url_for_check:
                    try:
                        has_faces = await self.face_detector.check_first_frame_for_face(stream_url_for_check)
                    except Exception as e:
                        logger.debug(f"Face check failed for {recording.rec_id}: {e}")
                        has_faces = False
                else:
                    has_faces = False

                if not has_faces:
                    logger.info(f"No faces detected (recordings.json path) for {recording.rec_id}, skipping and removing")
                    recording.monitor_status = False
                    recording.status_info = RecordingStatus.NOT_RECORDING
                    with GlobalRecordingState.lock:
                        if recording in self.recordings:
                            self.recordings.remove(recording)
                    await self.persist_recordings()
                    await self._mark_room_status_in_db(recording.rec_id, ScrapedRoomStatus.SKIPPED, face_detected=False)
                    self.app.page.run_task(self.app.record_card_manager.update_card, recording)
                    self.app.page.pubsub.send_others_on_topic("update", recording)
                    # 当前房间因无人脸被移除后，尝试补充新任务
                    asyncio.create_task(self.ensure_min_recordings())
                    return

                recording.status_info = RecordingStatus.PREPARING_RECORDING
                recording.loop_time_seconds = self.loop_time_seconds
                self.start_update(recording)
                # 使用信号量限制同时开始录制的数量，避免启动时大量任务同时开始录制触发反爬
                async def start_recording_with_semaphore():
                    async with self.start_recording_semaphore:
                        await recorder.start_recording(stream_info)
                self.app.page.run_task(start_recording_with_semaphore)
            else:
                if recording.notified_live_start:
                    notify_loop_time = user_config.get("notify_loop_time")
                    recording.loop_time_seconds = int(notify_loop_time or 600)
                else:
                    recording.loop_time_seconds = self.loop_time_seconds

                recording.cumulative_duration = timedelta()
                recording.last_duration = timedelta()
                recording.status_info = RecordingStatus.LIVE_BROADCASTING

        else:
            recording.is_recording = False
            if recording.is_live:
                recording.is_live = False
                self.app.page.run_task(recorder.end_message_push)

            recording.status_info = RecordingStatus.MONITORING
            title = f"{stream_info.anchor_name or recording.streamer_name} - {self._[recording.quality]}"
            if recording.streamer_name == self._["live_room"] or \
                    f"[{self._['is_live']}]" in recording.display_title:
                recording.update(
                    {
                        "streamer_name": stream_info.anchor_name,
                        "title": title,
                        "display_title": title,
                    }
                )
                self.app.page.run_task(self.persist_recordings)

            # 当前房间不在播，仅保持监控；如果整体录制数量不足 5，则尝试从 DB 再补任务
            asyncio.create_task(self.ensure_min_recordings())

        recording.is_checking = False
        self.app.page.run_task(self.app.record_card_manager.update_card, recording)
        self.app.page.pubsub.send_others_on_topic("update", recording)
        return

    @staticmethod
    def start_update(recording: Recording):
        """Start the recording process."""
        if recording.is_live and not recording.is_recording:
            # Reset cumulative and last durations for a fresh start
            recording.update(
                {
                    "cumulative_duration": timedelta(),
                    "last_duration": timedelta(),
                    "start_time": datetime.now(),
                    "is_recording": True,
                }
            )
            logger.info(f"Started recording for {recording.title}")

    def stop_recording(self, recording: Recording, manually_stopped: bool = True):
        """Stop the recording process."""
        recording.is_live = False
        
        # 检查是否有正在进行的录制（通过 start_time 判断，因为 stream_manager 可能已经设置了 is_recording=False）
        was_recording = recording.is_recording or (recording.start_time is not None)
        
        if was_recording:
            recording.stopping_in_progress = True

            logger.info(f"Trying to stop recorder for {recording.rec_id}, title: {recording.title}")
            logger.debug(f"Active recorders: {list(self.active_recorders.keys())}")

            if recording.rec_id in self.active_recorders:
                recorder = self.active_recorders[recording.rec_id]
                logger.debug(f"Found recorder instance - id: {id(recorder)}")
                recorder.request_stop()
                logger.info(f"Requested stop for recorder: {recording.rec_id}")
            else:
                logger.warning(f"No active recorder found for {recording.rec_id}, cannot request stop")
                recording.force_stop = True
                logger.info(f"Set force_stop=True for recording: {recording.rec_id}")

            elapsed = None
            if recording.start_time is not None:
                elapsed = datetime.now() - recording.start_time
                # Add the elapsed time to the cumulative duration.
                recording.cumulative_duration += elapsed
                # Update the last recorded duration.
                recording.last_duration = recording.cumulative_duration
            recording.start_time = None
            recording.is_recording = False
            recording.manually_stopped = manually_stopped
            recording.status_info = RecordingStatus.NOT_RECORDING
            logger.info(f"Stopped recording for {recording.title}")

            self.app.page.run_task(self._reset_stopping_flag, recording)

            # JSON 流程下：异步记录本次录制时长并检查是否触达 5 小时上限，若触达则写回 DB 标记为 RECORDED 并停止后续录制
            if elapsed is not None and elapsed.total_seconds() > 0:
                elapsed_seconds = elapsed.total_seconds()
                logger.info(
                    f"Recording stopped for {recording.rec_id}, "
                    f"duration: {int(elapsed_seconds)}s, scheduling duration handler"
                )
                # 使用 asyncio.create_task 确保异步任务能正确执行
                try:
                    asyncio.create_task(
                        self._post_stop_recording_duration_handler(recording, elapsed_seconds)
                    )
                except Exception as e:
                    logger.error(f"Failed to schedule post-stop duration handler for {recording.rec_id}: {e}")

    async def _post_stop_recording_duration_handler(self, recording: Recording, elapsed_seconds: float):
        """在 JSON 流程下，停止录制后记录本次时长，并根据 5 小时上限写回 DB 状态。"""
        if elapsed_seconds <= 0:
            logger.debug(f"Skipping post-stop handler for {recording.rec_id}: elapsed_seconds <= 0")
            return
        try:
            # 计算开始时间（UTC）
            start_time_utc = datetime.utcnow() - timedelta(seconds=elapsed_seconds)
            
            # 保存本次录制时长到 RecordingLog
            await self._save_recording_duration_for_rec(recording, elapsed_seconds, start_time_utc)
            
            # 重新统计累计时长
            total_seconds = await self._get_total_recording_duration_for_rec(recording.rec_id)
            logger.info(
                f"Total recording duration for {recording.rec_id}: "
                f"{int(total_seconds)}s (this session: {int(elapsed_seconds)}s)"
            )
            
            # 检查是否触达 5 小时上限
            if total_seconds >= self.max_total_recording_duration:
                logger.info(
                    f"Recording for {recording.rec_id} reached max total duration "
                    f"({int(total_seconds)}s >= {self.max_total_recording_duration}s), "
                    f"marking as RECORDED and removing from list"
                )
                await self._mark_room_status_in_db(recording.rec_id, ScrapedRoomStatus.RECORDED)
                # 触达上限后，从 recordings.json 与 UI 中彻底移除该录制任务
                await self.delete_recording_cards([recording])
        except Exception as e:
            logger.error(f"Failed to handle post-stop duration for {recording.rec_id}: {e}", exc_info=True)

    def get_duration(self, recording: Recording):
        """Get the duration of the current recording session in a formatted string."""
        if recording.is_recording and recording.start_time is not None:
            elapsed = datetime.now() - recording.start_time
            # If recording, add the current session time.
            total_duration = recording.cumulative_duration + elapsed
            return self._["recorded"] + " " + str(total_duration).split(".")[0]
        else:
            # If stopped, show the last recorded total duration.
            total_duration = recording.last_duration
            return str(total_duration).split(".")[0]

    async def delete_recording_cards(self, recordings: list[Recording]):
        self.app.page.run_task(self.app.record_card_manager.remove_recording_card, recordings)
        self.app.page.pubsub.send_others_on_topic('delete', recordings)
        await self.remove_recordings(recordings)

        # update the filter area of the recording list page
        if hasattr(self.app, 'current_page') and hasattr(self.app.current_page, 'content_area'):
            if len(self.app.current_page.content_area.controls) > 1:
                self.app.current_page.content_area.controls[1] = self.app.current_page.create_filter_area()
                self.app.current_page.content_area.update()

    async def check_free_space(self, output_dir: str | None = None):
        disk_space_limit = float(self.settings.user_config.get("recording_space_threshold") or 0)
        output_dir = output_dir or self.settings.get_video_save_path()
        if utils.check_disk_capacity(output_dir) < disk_space_limit:
            self.app.recording_enabled = False
            logger.error(
                f"Disk space remaining is below {disk_space_limit} GB. Recording function disabled"
            )
            self.app.page.run_task(
                self.app.snack_bar.show_snack_bar,
                self._["not_disk_space_tip"],
                duration=86400,
                show_close_icon=True
            )

        else:
            self.app.recording_enabled = True

    @staticmethod
    async def get_scheduled_time_range(scheduled_start_time, monitor_hours) -> list | None:
        scheduled_time_range_list = []
        for index, start_time in enumerate(scheduled_start_time.split(',')):
            try:
                hours = str(monitor_hours).split(',')[index]
                if start_time and hours:
                    end_time = utils.add_hours_to_time(start_time, float(hours or 5))
                    scheduled_time_range = f"{start_time}~{end_time}"
                    scheduled_time_range_list.append(scheduled_time_range)
            except Exception:
                pass
        return scheduled_time_range_list

    async def ensure_min_recordings(self, min_count: int = 6):
        """
        确保当前"正在录制"的数量至少为 min_count，但不超过最大上限。
        - 仅按 is_recording 统计真实在录制的任务；
        - 如果不足，则尝试重新从 DB 拉取可录房间补充到 recordings.json。
        - 当录制数不足时，优先补足录制数量；此时不受"总监控/录制总数<=10"的限制。
          （总数>10 时会在 sync_recordings_with_db 内触发"过期监控任务"清理，但不会阻止补足到 min_count）
        - 硬性上限：同时录制的数量不能超过 max_recording_count（默认6）。
        """
        try:
            current_recording_count = 0
            with GlobalRecordingState.lock:
                current_recording_count = sum(
                    1 for r in self.recordings if getattr(r, "is_recording", False)
                )
            # 如果已经达到或超过最大上限，不再补充
            max_recording_count = int(self.settings.user_config.get("max_recording_count", 6))
            if current_recording_count >= max_recording_count:
                logger.debug(f"Current recording count ({current_recording_count}) >= max limit ({max_recording_count}), no need to add more")
                return
            # 如果已经达到目标数量，不再补充
            if current_recording_count >= min_count:
                return
            await self.sync_recordings_with_db()
        except Exception as e:
            logger.debug(f"ensure_min_recordings encountered error: {e}")

    async def _mark_room_status_in_db(self, rec_id: str, status: ScrapedRoomStatus, face_detected=None):
        """Update ScrapedRoom status/face_detected if it exists in DB."""
        try:
            platform_key, room_id = rec_id.split("_", 1)
        except ValueError:
            return

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ScrapedRoom)
                    .where(ScrapedRoom.platform == platform_key)
                    .where(ScrapedRoom.room_id == room_id)
                )
                room = result.scalars().first()
                if room:
                    room.status = status
                    if face_detected is not None:
                        room.face_detected = face_detected
                    room.updated_at = datetime.utcnow()
                    await db.commit()
        except Exception as e:
            logger.debug(f"Failed to mark room status in DB for {rec_id}: {e}")

    async def _mark_rooms_status_in_db_batch(self, rec_ids: list[str], status: ScrapedRoomStatus, face_detected=None, retry_count=3):
        """批量更新多个房间的状态，减少数据库锁定问题。"""
        if not rec_ids:
            return
        
        # 解析 rec_id 为 (platform_key, room_id) 元组
        room_keys = []
        for rec_id in rec_ids:
            try:
                platform_key, room_id = rec_id.split("_", 1)
                room_keys.append((platform_key, room_id))
            except ValueError:
                continue
        
        if not room_keys:
            return
        
        # 按平台分组，减少查询次数
        platform_rooms = {}
        for platform_key, room_id in room_keys:
            if platform_key not in platform_rooms:
                platform_rooms[platform_key] = []
            platform_rooms[platform_key].append(room_id)
        
        # 重试机制
        for attempt in range(retry_count):
            try:
                async with AsyncSessionLocal() as db:
                    updated_count = 0
                    for platform_key, room_ids in platform_rooms.items():
                        result = await db.execute(
                            select(ScrapedRoom)
                            .where(ScrapedRoom.platform == platform_key)
                            .where(ScrapedRoom.room_id.in_(room_ids))
                        )
                        rooms = result.scalars().all()
                        for room in rooms:
                            room.status = status
                            if face_detected is not None:
                                room.face_detected = face_detected
                            room.updated_at = datetime.utcnow()
                            updated_count += 1
                    
                    if updated_count > 0:
                        await db.commit()
                        logger.debug(f"Batch updated {updated_count} rooms status to {status.value}")
                    return
            except Exception as e:
                if attempt < retry_count - 1:
                    # 等待后重试，避免数据库锁定
                    await asyncio.sleep(0.1 * (attempt + 1))
                    logger.debug(f"Retry {attempt + 1}/{retry_count} batch update room status: {e}")
                else:
                    logger.debug(f"Failed to batch mark room status in DB after {retry_count} attempts: {e}")

    async def _get_total_recording_duration_for_rec(self, rec_id: str) -> float:
        """根据 rec_id 统计该房间在 RecordingLog 中的累计录制时长（秒）。"""
        try:
            platform_key, room_id = rec_id.split("_", 1)
        except ValueError:
            return 0.0

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(func.sum(RecordingLog.duration))
                    .where(RecordingLog.room_id == room_id)
                    .where(RecordingLog.platform == platform_key)
                    .where(RecordingLog.status == "completed")
                )
                total = result.scalar() or 0
                return float(total)
        except Exception as e:
            logger.debug(f"Failed to get total recording duration for {rec_id}: {e}")
            return 0.0

    async def _save_recording_duration_for_rec(
        self, recording: Recording, duration_seconds: float, start_time_utc: datetime
    ):
        """在 JSON 流程下，将一次录制时长写入 RecordingLog。"""
        if duration_seconds <= 0:
            logger.debug(f"Skipping save recording duration for {recording.rec_id}: duration <= 0")
            return
        try:
            # 优先从 recording.platform_key 获取，否则从 rec_id 解析
            platform_key = getattr(recording, "platform_key", None)
            room_id = None
            
            # 从 rec_id 解析 platform_key 和 room_id（格式：platform_room_id）
            if "_" in recording.rec_id:
                try:
                    parts = recording.rec_id.split("_", 1)
                    if len(parts) == 2:
                        parsed_platform, parsed_room_id = parts
                        if not platform_key:
                            platform_key = parsed_platform
                        if not room_id:
                            room_id = parsed_room_id
                except Exception as e:
                    logger.debug(f"Failed to parse rec_id {recording.rec_id}: {e}")

            if not (platform_key and room_id):
                logger.warning(
                    f"Cannot save recording duration for {recording.rec_id}: "
                    f"platform_key={platform_key}, room_id={room_id}"
                )
                return

            async with AsyncSessionLocal() as db:
                log = RecordingLog(
                    room_id=room_id,
                    platform=platform_key,
                    start_time=start_time_utc,
                    end_time=datetime.utcnow(),
                    duration=int(duration_seconds),
                    status="completed",
                )
                db.add(log)
                await db.commit()
                logger.info(
                    f"Saved recording log for {recording.rec_id}: "
                    f"{int(duration_seconds)}s (platform={platform_key}, room_id={room_id})"
                )
        except Exception as e:
            logger.error(f"Failed to save recording duration for {recording.rec_id}: {e}", exc_info=True)

    async def _sync_recordings_loop(self):
        """周期性同步 DB↔recordings.json：拉取可录房间到 recordings，移除已完成/无脸的."""
        logger.info(f"Starting DB↔recordings sync loop, interval={self.sync_interval_seconds}s")
        while True:
            try:
                await self.sync_recordings_with_db()
            except Exception as e:
                logger.error(f"Error in sync_recordings_with_db: {e}", exc_info=True)
            await asyncio.sleep(self.sync_interval_seconds)

    async def sync_recordings_with_db(self):
        """从 DB 加载待录房间到 recordings，并移除 DB 已标记 recorded/skipped 的任务."""
        try:
            # #region agent log
            import json as json_module
            import time
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_sync_start", "timestamp": time.time() * 1000, "location": "record_manager.py:sync_recordings_with_db", "message": "Sync start", "data": {}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")
            # #endregion
            # 仅当当前"实际录制中的数量"少于 16 时才补充任务（避免监控未录制也占用名额）
            current_recording_count = 0
            with GlobalRecordingState.lock:
                current_recording_count = sum(
                    1 for r in self.recordings if getattr(r, "is_recording", False)
                )
            # #region agent log
            import json as json_module
            import time
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_sync_monitoring_count", "timestamp": time.time() * 1000, "location": "record_manager.py:sync_recordings_with_db", "message": "Current recording count", "data": {"current_recording_count": current_recording_count}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")
            # #endregion
            
            # -------------------------
            # 规则：
            # - 第一优先级：保证正在录制的数量至少为 min_recording_count（默认16）。未达标时，不受总数<=50限制。
            # - 第二优先级：当"监控中或录制中"的总数超过 max_total_monitoring（默认50）时，清理"过期监控任务"
            #   （只清理 monitor_status=True 且 is_recording=False 且长时间未能开始录制的任务），以减少堆积。
            # - 硬性上限：同时录制的数量不能超过 max_recording_count（默认6），避免触发反爬。
            # - 总监控和录制数量不能超过10个（录制最多6个，监控最多4个）
            # -------------------------
            min_recording_count = 6
            max_recording_count = int(self.settings.user_config.get("max_recording_count", 6))
            # 录制中的数量和"仅监控"的数量分开统计：
            # - recording_count：is_recording=True（上面已算）
            # - monitoring_only_count：monitor_status=True 且 is_recording=False（只对这部分做4上限和清理，确保总数不超过10）
            max_monitoring_only = 4  # 录制最多6个，监控最多4个，总共不超过10个

            total_monitoring_count = 0
            monitoring_only_count = 0
            with GlobalRecordingState.lock:
                for r in self.recordings:
                    is_monitoring = getattr(r, "monitor_status", False)
                    is_recording = getattr(r, "is_recording", False)
                    if is_monitoring or is_recording:
                        total_monitoring_count += 1
                    if is_monitoring and not is_recording:
                        monitoring_only_count += 1

            # #region agent log
            import json as json_module
            import time
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({
                    "id": "log_sync_total_monitoring_count",
                    "timestamp": time.time() * 1000,
                    "location": "record_manager.py:sync_recordings_with_db",
                    "message": "Total monitoring/recording count",
                    "data": {
                        "total_monitoring_count": total_monitoring_count,
                        "max_monitoring_only": max_monitoring_only,
                        "monitoring_only_count": monitoring_only_count,
                        "current_recording_count": current_recording_count,
                        "min_recording_count": min_recording_count
                    },
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "SYNC"
                }) + "\n")
            # #endregion

            # 清理长时间处于错误状态或监控中但从未开始录制的任务
            # 注意：只清理"仅监控"的任务（monitor_status=True 且 is_recording=False），确保不会影响正在录制的数量
            now = datetime.now()
            stale_monitoring_threshold = timedelta(hours=1)  # 1小时未开始录制则清理
            force_cleanup_threshold = timedelta(minutes=10)  # 10分钟未开始录制则强制清理（当需要达到录制目标时）

            # 如果监控任务过多，持续清理直到 <= 50
            # 只有当"仅监控"的数量超过 50 时，才做"过期监控任务"清理
            while monitoring_only_count > max_monitoring_only:
                overflow = monitoring_only_count - max_monitoring_only
                # 如果未达到录制目标，需要清理更多任务以腾出空间
                if current_recording_count < min_recording_count:
                    needed_slots = min_recording_count - current_recording_count
                    overflow = max(overflow, needed_slots)

                # 收集所有符合条件的监控任务（不限制阈值，先收集全部）
                all_monitoring_tasks: list[tuple[Recording, datetime]] = []
                with GlobalRecordingState.lock:
                    for r in list(self.recordings):
                        # 仅考虑"仅监控"的任务
                        if not (r.monitor_status and not r.is_recording):
                            continue
                        # 允许 status_info 为 None（历史遗留数据），一并视为可清理的监控任务
                        if r.status_info not in [
                            None,
                            RecordingStatus.MONITORING,
                            RecordingStatus.RECORDING_ERROR,
                            RecordingStatus.LIVE_STATUS_CHECK_ERROR,
                            RecordingStatus.STATUS_CHECKING,
                        ]:
                            continue

                        # 计算这个任务的"监控起点时间"，越早代表越"老"。
                        start_point = None
                        try:
                            if r.start_time is not None:
                                # 有 start_time：以 start_time 为基准
                                start_point = r.start_time
                            elif hasattr(r, "detection_time") and r.detection_time:
                                # detection_time 是 time，需要结合日期
                                detection_datetime = datetime.combine(now.date(), r.detection_time)
                                if detection_datetime > now:
                                    detection_datetime = datetime.combine(
                                        (now - timedelta(days=1)).date(), r.detection_time
                                    )
                                start_point = detection_datetime
                        except Exception:
                            start_point = None

                        if start_point is None:
                            # 没有可用时间信息，当作"很老"的数据
                            start_point = now - timedelta(days=365)

                        all_monitoring_tasks.append((r, start_point))

                # 按 start_point 从最早到最新排序
                all_monitoring_tasks.sort(key=lambda x: x[1])
                
                # 如果未达到录制目标，使用更短的阈值（10分钟）来清理
                threshold = force_cleanup_threshold if current_recording_count < min_recording_count else stale_monitoring_threshold
                
                # 先筛选超过阈值的任务
                candidates = [(r, sp) for r, sp in all_monitoring_tasks if now - sp > threshold]
                
                # 如果符合条件的候选任务不足，逐步降低阈值或直接选择最老的任务
                if len(candidates) < overflow:
                    logger.info(
                        f"Only {len(candidates)} tasks exceed threshold ({threshold}), but need to clean {overflow}. "
                        f"Expanding cleanup to oldest {overflow} monitoring tasks."
                    )
                    # 直接选择最老的 overflow 个任务
                    to_cleanup_records = [r for r, _ in all_monitoring_tasks[:overflow]]
                else:
                    # 只清理超过阈值的任务，最多清理 overflow 个
                    to_cleanup_records = [r for r, _ in candidates[:overflow]]

                if len(to_cleanup_records) > 0:
                    logger.info(
                        f"Monitoring-only count ({monitoring_only_count}) > limit ({max_monitoring_only}), "
                        f"current_recording_count ({current_recording_count}) < target ({min_recording_count}), "
                        f"cleaning up {len(to_cleanup_records)} stale monitoring tasks "
                        f"(need {overflow}, found {len(candidates)} exceeding threshold, "
                        f"cleaning oldest {len(to_cleanup_records)} tasks)"
                    )
                    for r in to_cleanup_records:
                        logger.debug(f"Removing stale monitoring task: {r.rec_id}, status: {r.status_info}")
                    # 更新数据库状态
                    for r in to_cleanup_records:
                        await self._mark_room_status_in_db(r.rec_id, ScrapedRoomStatus.PENDING)
                    with GlobalRecordingState.lock:
                        for r in to_cleanup_records:
                            if r in self.recordings:
                                self.recordings.remove(r)
                    await self.persist_recordings()
                    await self.delete_recording_cards(to_cleanup_records)

                    # 清理后重新统计
                    with GlobalRecordingState.lock:
                        current_recording_count = sum(
                            1 for r in self.recordings if getattr(r, "is_recording", False)
                        )
                        monitoring_only_count = sum(
                            1 for r in self.recordings
                            if getattr(r, "monitor_status", False) and not getattr(r, "is_recording", False)
                        )
                    logger.info(
                        f"After cleanup, recording_count={current_recording_count} (target={min_recording_count}), "
                        f"monitoring_only_count={monitoring_only_count} (limit={max_monitoring_only})"
                    )
                else:
                    # 没有可清理的任务，退出循环
                    logger.info(
                        f"No more tasks to cleanup, monitoring_only_count={monitoring_only_count} (limit={max_monitoring_only})"
                    )
                    break

            # 如果已经达到或超过最大录制数量上限：不再新增任务
            if current_recording_count >= max_recording_count:
                logger.info(
                    f"Current recording count ({current_recording_count}) >= max limit ({max_recording_count}), "
                    f"no need to add more (total_monitoring_count={total_monitoring_count}, monitoring_only_limit={max_monitoring_only})"
                )
                return
            
            # 如果已经达到目标数量（16个）但未超过上限：不再新增任务（但不会因为监控数量>50去影响正在录制）
            if current_recording_count >= min_recording_count:
                logger.info(
                    f"Current recording count ({current_recording_count}) >= target ({min_recording_count}), "
                    f"no need to add more (total_monitoring_count={total_monitoring_count}, monitoring_only_limit={max_monitoring_only})"
                )
                return

            # 未达到目标数量：优先补足到目标数量，但不能超过最大上限
            # 计算需要补充的数量，但不能超过最大上限
            needed_slots = max(0, min(min_recording_count, max_recording_count) - current_recording_count)
            # 限制每次同步最多处理的任务数，避免启动时一次性处理太多任务
            # 启动时使用更严格的限制
            is_startup = (current_recording_count == 0)
            default_max_tasks = int(self.settings.user_config.get("max_tasks_per_sync", 3))
            startup_max_tasks = int(self.settings.user_config.get("startup_max_tasks_per_sync", 2))
            max_tasks_per_sync = startup_max_tasks if is_startup else default_max_tasks
            remaining_slots = min(needed_slots, max_tasks_per_sync)
            logger.info(
                f"Current recording count ({current_recording_count}) < target ({min_recording_count}), "
                f"will add up to {remaining_slots} new monitoring tasks "
                f"(limited to {max_tasks_per_sync} per sync, is_startup={is_startup} to avoid triggering anti-scraping)"
            )

            # 先定义批次大小变量，供后续使用
            # 限制每次查询的数据量，避免启动时获取太多数据导致大量同时开始录制触发反爬
            # 启动时（current_recording_count=0）使用更小的批次，后续同步使用正常批次
            default_batch_size = int(self.settings.user_config.get("db_fetch_batch_size", 10))
            startup_batch_size = int(self.settings.user_config.get("startup_fetch_batch_size", 5))
            
            # 先触发一次爬取，获取最新的开播直播间数据
            # 限制爬取数量，使其与读取数量匹配，避免数据库中积累太多未使用的数据
            # 启动时使用更小的爬取数量，后续使用正常数量
            scrape_max_rooms = startup_batch_size if is_startup else default_batch_size
            # 不再乘以1.5倍，直接使用批次大小，避免获取过多数据
            logger.info(f"Triggering scrape to get latest live rooms (max_rooms={scrape_max_rooms}, is_startup={is_startup})...")
            try:
                await self.app.recording_scheduler.scrape_all_platforms(max_rooms=scrape_max_rooms)
                logger.info("Scrape completed, will fetch newly scraped rooms from database")
            except Exception as e:
                logger.error(f"Error during scrape: {e}", exc_info=True)
                # 即使爬取失败，也继续尝试从数据库读取已有数据

            # 循环获取数据库房间，直到添加足够的任务或达到重试上限
            max_retries = 5  # 最多重试5次
            retry_count = 0
            total_added = 0
            newly_added_records: list[Recording] = []
            offset = 0  # 数据库查询偏移量
            batch_size = startup_batch_size if is_startup else default_batch_size
            logger.info(f"Using batch_size={batch_size} for DB fetch (is_startup={is_startup})")

            while remaining_slots > 0 and retry_count < max_retries:
                async with AsyncSessionLocal() as db:
                    # 拉取可录房间：pending/recording（大小写不敏感）且 face_detected 为空或为 True
                    # 分布式部署：只拉取分配给当前节点的任务，或未分配的任务
                    from sqlalchemy import or_
                    result = await db.execute(
                        select(ScrapedRoom)
                        .where(ScrapedRoom.status.in_([ScrapedRoomStatus.PENDING, ScrapedRoomStatus.RECORDING]))
                        .where(or_(ScrapedRoom.face_detected.is_(None), ScrapedRoom.face_detected.is_(True)))
                        .where(or_(
                            ScrapedRoom.assigned_node == NODE_ID,  # 分配给当前节点
                            ScrapedRoom.assigned_node.is_(None)     # 未分配的任务
                        ))
                        .order_by(ScrapedRoom.last_scraped.desc())
                        .limit(batch_size)
                        .offset(offset)
                    )
                    rooms = result.scalars().all()
                    
                    # 将未分配的任务标记为当前节点
                    for room in rooms:
                        if room.assigned_node is None:
                            room.assigned_node = NODE_ID
                    if rooms:
                        await db.commit()
                    
                    if not rooms:
                        # 没有更多房间了，退出循环
                        logger.info(f"No more rooms available in database, stopping fetch loop")
                        break
                    
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_sync_db_candidates", "timestamp": time.time() * 1000, "location": "record_manager.py:sync_recordings_with_db", "message": "DB candidates fetched", "data": {"fetched": len(rooms), "remaining_slots": remaining_slots, "offset": offset, "retry_count": retry_count}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")
                    # #endregion
                    
                    keep_ids = set()
                    added_this_batch = 0

                    # 根据用户配置决定是否默认开启分段录制
                    user_config = self.settings.user_config
                    segment_enabled = bool(user_config.get("segmented_recording_enabled", False))
                    segment_time = str(user_config.get("video_segment_time", "1800"))
                    target_quality = user_config.get("record_quality", "LD") or "LD"

                    # 添加新增房间
                    for room in rooms:
                        if remaining_slots <= 0:
                            break
                        
                        rec_id = f"{room.platform}_{room.room_id}"
                        keep_ids.add(rec_id)
                        if self.find_recording_by_id(rec_id):
                            # #region agent log
                            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                                f.write(json_module.dumps({"id": "log_sync_skip_existing", "timestamp": time.time() * 1000, "location": "record_manager.py:sync_recordings_with_db", "message": "Recording already in memory, skip", "data": {"rec_id": rec_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")
                            # #endregion
                            continue
                        
                        rec = Recording(
                            rec_id=rec_id,
                            url=room.room_url,
                            streamer_name=room.anchor_name or (room.title or room.room_id),
                            record_format="mp4",
                            quality=target_quality,
                            segment_record=segment_enabled,
                            segment_time=segment_time,
                            monitor_status=True,
                            scheduled_recording=False,
                            scheduled_start_time="",
                            monitor_hours=0,
                            recording_dir=None,
                            enabled_message_push=False,
                            only_notify_no_record=False,
                            flv_use_direct_download=False,
                            category=getattr(room, "category", None),
                        )
                        await self.add_recording(rec)
                        newly_added_records.append(rec)
                        remaining_slots -= 1
                        added_this_batch += 1
                        total_added += 1
                        # #region agent log
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({
                                "id": "log_sync_added_room",
                                "timestamp": time.time() * 1000,
                                "location": "record_manager.py:sync_recordings_with_db",
                                "message": "Added room from DB",
                                "data": {
                                    "rec_id": rec_id,
                                    "remaining_slots_after_add": remaining_slots
                                },
                                "sessionId": "debug-session",
                                "runId": "run1",
                                "hypothesisId": "SYNC"
                            }) + "\n")
                        # #endregion

                    # 如果本轮有新增，持久化并继续
                    if added_this_batch > 0:
                        await self.persist_recordings()
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"id": "log_sync_persist_after_loop", "timestamp": time.time() * 1000, "location": "record_manager.py:sync_recordings_with_db", "message": "Persist after sync loop", "data": {"added_this_batch": added_this_batch, "total_added": total_added, "saved_count": len(self.recordings)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")
                        # 重置重试计数，因为成功添加了任务
                        retry_count = 0
                        offset += batch_size
                    else:
                        # 本轮没有添加任何任务，说明获取的房间都已经存在
                        # 如果还有剩余槽位，清理一些监控任务后继续
                        if remaining_slots > 0:
                            retry_count += 1
                            logger.info(
                                f"Batch {retry_count}: No new tasks added (all rooms already exist), "
                                f"remaining_slots={remaining_slots}, will cleanup stale tasks and retry"
                            )
                            
                            # 清理一些过期的监控任务，确保腾出足够的空间
                            now = datetime.now()
                            force_cleanup_threshold = timedelta(minutes=10)
                            
                            # 收集所有符合条件的监控任务（不限制阈值，先收集全部）
                            all_monitoring_tasks: list[tuple[Recording, datetime]] = []
                            with GlobalRecordingState.lock:
                                for r in list(self.recordings):
                                    if not (r.monitor_status and not r.is_recording):
                                        continue
                                    if r.status_info not in [
                                        RecordingStatus.MONITORING,
                                        RecordingStatus.RECORDING_ERROR,
                                        RecordingStatus.LIVE_STATUS_CHECK_ERROR,
                                        RecordingStatus.STATUS_CHECKING,
                                    ]:
                                        continue
                                    start_point = None
                                    try:
                                        if r.start_time is not None:
                                            start_point = r.start_time
                                        elif hasattr(r, "detection_time") and r.detection_time:
                                            detection_datetime = datetime.combine(now.date(), r.detection_time)
                                            if detection_datetime > now:
                                                detection_datetime = datetime.combine(
                                                    (now - timedelta(days=1)).date(), r.detection_time
                                                )
                                            start_point = detection_datetime
                                    except Exception:
                                        start_point = None
                                    if start_point is None:
                                        start_point = now - timedelta(days=365)
                                    all_monitoring_tasks.append((r, start_point))

                            # 按时间排序（越早的越先清）
                            all_monitoring_tasks.sort(key=lambda x: x[1])
                            
                            # 先筛选超过阈值的任务
                            candidates = [(r, sp) for r, sp in all_monitoring_tasks if now - sp > force_cleanup_threshold]
                            
                            # 确定清理数量：至少清理 remaining_slots 个
                            cleanup_count = remaining_slots
                            if len(candidates) >= cleanup_count:
                                # 候选任务足够，清理最老的 cleanup_count 个超过阈值的任务
                                to_cleanup_records = [r for r, _ in candidates[:cleanup_count]]
                            else:
                                # 候选任务不足，扩展到清理最老的 cleanup_count 个任务（不限制阈值）
                                logger.info(
                                    f"Only {len(candidates)} tasks exceed 10min threshold, but need to clean {cleanup_count}. "
                                    f"Expanding cleanup to oldest {cleanup_count} monitoring tasks."
                                )
                                to_cleanup_records = [r for r, _ in all_monitoring_tasks[:cleanup_count]]

                            if to_cleanup_records:

                                logger.info(
                                    f"Cleaning up {len(to_cleanup_records)} stale monitoring tasks "
                                    f"(need {remaining_slots} slots, found {len(candidates)} exceeding threshold, "
                                    f"cleaning {len(to_cleanup_records)} oldest tasks) to free slots for new rooms"
                                )
                                # 更新数据库状态
                                for r in to_cleanup_records:
                                    await self._mark_room_status_in_db(r.rec_id, ScrapedRoomStatus.PENDING)
                                with GlobalRecordingState.lock:
                                    for r in to_cleanup_records:
                                        if r in self.recordings:
                                            self.recordings.remove(r)
                                await self.persist_recordings()
                                await self.delete_recording_cards(to_cleanup_records)
                                # 重置偏移量，重新从数据库开始查询
                                offset = 0
                            else:
                                # 没有可清理的任务，增加偏移量继续查询
                                offset += batch_size
                        else:
                            # 已经添加了足够的任务，退出循环
                            break

            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_sync_added", "timestamp": time.time() * 1000, "location": "record_manager.py:sync_recordings_with_db", "message": "Added recordings from DB", "data": {"total_added": total_added, "remaining_slots_after": remaining_slots, "retry_count": retry_count}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "SYNC"}) + "\n")
            # #endregion

            # 刚新增的任务，立即执行一轮开播+人脸检测，避免等待周期轮询
            # 注意：使用信号量控制并发，避免触发反爬机制
            if newly_added_records:
                try:
                    logger.info(f"Running immediate live check for {len(newly_added_records)} newly added tasks")
                    # 逐个处理，每处理一个延迟20秒，严格避免触发反爬
                    for i, recording in enumerate(newly_added_records):
                        await self.check_if_live(recording)
                        # 每个任务之间延迟20秒，避免请求过于密集触发反爬
                        if i < len(newly_added_records) - 1:
                            await asyncio.sleep(20)
                except Exception as e:
                    logger.error(f"Immediate live check after sync failed: {e}", exc_info=True)

            # 移除 DB 已标记 recorded/skipped 的房间
            async with AsyncSessionLocal() as db:
                stale_result = await db.execute(
                    select(ScrapedRoom).where(
                        ScrapedRoom.status.in_([ScrapedRoomStatus.RECORDED, ScrapedRoomStatus.SKIPPED])
                    )
                )
                stale_rooms = stale_result.scalars().all()
                stale_ids = {f"{r.platform}_{r.room_id}" for r in stale_rooms}

                to_remove = []
                with GlobalRecordingState.lock:
                    for r in list(self.recordings):
                        if getattr(r, "rec_id", None) in stale_ids:
                            to_remove.append(r)
                    for r in to_remove:
                        self.recordings.remove(r)
                if to_remove:
                    await self.persist_recordings()
        except Exception as e:
            logger.debug(f"sync_recordings_with_db encountered error: {e}")
        finally:
            try:
                self.app.page.run_task(self.app.recordings.add_record_cards)
            except Exception:
                pass

    @staticmethod
    async def _reset_stopping_flag(recording: Recording):
        recording.stopping_in_progress = False
        logger.debug(f"Reset stopping_in_progress flag for recording: {recording.rec_id}")

    async def load_recording_rooms_from_db(self):
        """Load rooms with recording status from database and add them to recordings"""
        # #region agent log
        import json as json_module
        import time
        import asyncio
        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
            f.write(json_module.dumps({"id": "log_load_db_rooms_start", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recording_rooms_from_db", "message": "Starting to load recording rooms from database", "data": {}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
        # #endregion
        
        try:
            from app.db.session import AsyncSessionLocal
            from app.models.recording.scraped_room_model import ScrapedRoom, ScrapedRoomStatus
            from sqlalchemy.future import select
            
            async with AsyncSessionLocal() as db:
                    # Only load RECORDING rooms (PENDING rooms should go through face detection first)
                    # RECORDING status means face detection has passed and recording has started
                result = await db.execute(
                    select(ScrapedRoom)
                    .where(func.lower(ScrapedRoom.status) == "recording")
                )
                recording_rooms = result.scalars().all()
                # #region agent log
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_load_db_rooms_found", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recording_rooms_from_db", "message": "Found recording rooms in database", "data": {"count": len(recording_rooms), "room_ids": [r.id for r in recording_rooms]}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
                # #endregion
                
                for room in recording_rooms:
                    rec_id = f"{room.platform}_{room.room_id}"
                    # Check if recording already exists
                    existing = self.find_recording_by_id(rec_id)
                    if not existing:
                        # #region agent log
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"id": "log_load_db_room_creating", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recording_rooms_from_db", "message": "Creating recording from database room", "data": {"room_id": room.id, "rec_id": rec_id, "platform": room.platform}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
                        # #endregion
                        rec = Recording(
                            rec_id=rec_id,
                            url=room.room_url,
                            streamer_name=room.anchor_name or (room.title or room.room_id),
                            record_format="mp4",
                            quality="OD",
                            segment_record=False,
                            segment_time="1800",
                            monitor_status=True,
                            scheduled_recording=False,
                            scheduled_start_time="",
                            monitor_hours=0,
                            recording_dir=None,
                            enabled_message_push=False,
                            only_notify_no_record=False,
                            flv_use_direct_download=False,
                        )
                        await self.add_recording(rec)
                        # #region agent log
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"id": "log_load_db_room_added", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recording_rooms_from_db", "message": "Added recording from database room", "data": {"rec_id": rec_id, "total_recordings": len(self.recordings)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
                        # #endregion
                    else:
                        # #region agent log
                        with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"id": "log_load_db_room_exists", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recording_rooms_from_db", "message": "Recording already exists, skipping", "data": {"rec_id": rec_id}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
                        # #endregion
        except Exception as e:
            # #region agent log
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"id": "log_load_db_rooms_error", "timestamp": time.time() * 1000, "location": "record_manager.py:load_recording_rooms_from_db", "message": "Error loading recording rooms from database", "data": {"error": str(e)}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "C"}) + "\n")
            # #endregion
            logger.error(f"Error loading recording rooms from database: {e}", exc_info=True)
