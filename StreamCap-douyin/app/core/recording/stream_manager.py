import asyncio
import os
import shutil
import subprocess
import time
from datetime import datetime
from typing import TypeVar

from ...messages import desktop_notify, message_pusher
from ...models.media.video_quality_model import VideoQuality
from ...models.recording.recording_status_model import RecordingStatus
from ...utils import utils
from ...utils.logger import logger
from ..media import ffmpeg_builders
from ..media.direct_downloader import DirectStreamDownloader
from ..platforms import platform_handlers
from ..platforms.platform_handlers import StreamData
from ..runtime.process_manager import BackgroundService

T = TypeVar("T")


class LiveStreamRecorder:
    DEFAULT_SEGMENT_TIME = "1800"
    DEFAULT_SAVE_FORMAT = "mp4"
    DEFAULT_QUALITY = VideoQuality.OD

    def __init__(self, app, recording, recording_info):
        self.app = app
        self.settings = app.settings
        self.recording = recording
        self.recording_info = recording_info
        self.subprocess_start_info = app.subprocess_start_up_info
        self.should_stop = False  # manually stopped

        self.user_config = self.settings.user_config
        self.account_config = self.settings.accounts_config
        self.platform_key = self._get_info("platform_key")
        # 优先从 cookies_config 获取，如果没有则从环境变量获取（用于抖音等平台）
        self.cookies = self.settings.cookies_config.get(self.platform_key) if self.settings.cookies_config else None
        if not self.cookies and self.platform_key == "douyin":
            self.cookies = os.getenv("DOUYIN_COOKIE", None)
            if self.cookies:
                logger.debug(f"[stream_manager] Using DOUYIN_COOKIE from environment variable for {self.platform_key}")
        if self.platform_key == "douyin" and not self.cookies:
            logger.warning(f"[stream_manager] No cookie found for douyin platform (neither from cookies_config nor DOUYIN_COOKIE env var)")

        self.platform = self._get_info("platform")
        self.live_url = self._get_info("live_url")
        self.output_dir = self._get_info("output_dir")
        self.segment_record = self._get_info("segment_record", default=False)
        self.segment_time = self._get_info("segment_time", default=self.DEFAULT_SEGMENT_TIME)
        self.quality = self._get_info("quality", default=self.DEFAULT_QUALITY)
        self.save_format = self._get_info("save_format", default=self.DEFAULT_SAVE_FORMAT).lower()
        self.proxy = self.is_use_proxy()
        self.direct_downloader = None
        self.min_valid_recording_duration = 25
        self.recording_start_time = 0
        os.makedirs(self.output_dir, exist_ok=True)
        self.app.language_manager.add_observer(self)
        self._ = {}
        self.load()

    def load(self):
        language = self.app.language_manager.language
        for key in ("recording_manager", "stream_manager"):
            self._.update(language.get(key, {}))

    def _get_info(self, key: str, default: T = None) -> T:
        return self.recording_info.get(key, default) or default

    def is_use_proxy(self):
        default_proxy_platform = self.user_config.get("default_platform_with_proxy", "")
        proxy_list = default_proxy_platform.replace("，", ",").replace(" ", "").split(",")
        if self.user_config.get("enable_proxy") and self.platform_key in proxy_list:
            self.proxy = self.user_config.get("proxy_address")
            return self.proxy

    def _get_filename(self, stream_info: StreamData) -> str:
        # New format: filename is same as directory name (年月日时 format: YYYYMMDDHHMMSS)
        # Use the timestamp stored in _get_output_dir to ensure consistency
        if hasattr(self, '_timestamp_for_filename'):
            return self._timestamp_for_filename
        
        # Fallback: generate timestamp if _get_output_dir hasn't been called yet
        now = datetime.today()
        return now.strftime("%Y%m%d%H%M%S")  # YYYYMMDDHHMMSS format

    def _get_output_dir(self, stream_info: StreamData) -> str:
        if self.recording.recording_dir and self.user_config.get("folder_name_time"):
            current_date = datetime.today().strftime("%Y-%m-%d")
            if current_date not in self.recording.recording_dir:
                self.recording.recording_dir = None

        if self.recording.recording_dir:
            return self.recording.recording_dir

        # New format: 平台/类别/roomid/年月日时/
        # Extract platform and room_id from rec_id (format: platform_room_id)
        rec_id = self.recording.rec_id
        if '_' in rec_id:
            platform, room_id = rec_id.split('_', 1)
        else:
            # Fallback: use platform from stream_info and rec_id as room_id
            platform = stream_info.platform or 'unknown'
            room_id = rec_id
        # Category from recording (可能为 None)
        category = getattr(self.recording, "category", None) or "unknown"
        
        # Format: 年月日时 (YYYYMMDDHHMMSS) - same as filename
        now = datetime.today()
        year_month_day_hour_min_sec = now.strftime("%Y%m%d%H%M%S")  # YYYYMMDDHHMMSS format
        
        # Build directory structure: 平台/类别/roomid/年月日时/
        output_dir = self.output_dir.rstrip("/").rstrip("\\")
        output_dir = os.path.join(output_dir, platform)
        output_dir = os.path.join(output_dir, category)
        output_dir = os.path.join(output_dir, room_id)
        output_dir = os.path.join(output_dir, year_month_day_hour_min_sec)
        
        # Store the timestamp for filename generation
        self._timestamp_for_filename = year_month_day_hour_min_sec
        
        os.makedirs(output_dir, exist_ok=True)
        self.recording.recording_dir = output_dir
        self.app.page.run_task(self.app.record_manager.persist_recordings)
        return output_dir

    def _get_save_path(self, filename: str, use_direct_download: bool = False) -> str:
        suffix = self.save_format
        suffix = "_%03d." + suffix if self.segment_record and not use_direct_download else "." + suffix
        save_file_path = os.path.join(self.output_dir, filename + suffix).replace(" ", "_")
        return save_file_path.replace("\\", "/")

    @staticmethod
    def _clean_and_truncate_title(title: str) -> str | None:
        if not title:
            return None
        cleaned_title = title[:30].replace("，", ",").replace(" ", "")
        return cleaned_title

    @property
    def is_flv_preferred_platform(self):
        return self.platform_key in {"douyin", "tiktok"}

    def _select_source_url(self, stream_info: StreamData):
        if (
                self.user_config.get("default_live_source") != "HLS"
                and self.is_flv_preferred_platform
        ):
            codec = utils.get_query_params(stream_info.flv_url, "codec")
            if codec and codec[0] == 'h265':
                logger.warning("FLV is not supported for h265 codec, use HLS source instead")
            else:
                return stream_info.flv_url

        return stream_info.record_url

    def _get_record_url(self, stream_info: StreamData):

        url = self._select_source_url(stream_info)

        http_record_list = ["shopee", "migu"]
        if self.user_config.get("force_https_recording") and url.startswith("http://"):
            url = url.replace("http://", "https://")

        if self.platform_key in http_record_list:
            url = url.replace("https://", "http://")
        return url

    def set_preview_url(self, stream_info: StreamData):
        self.recording.preview_url = stream_info.m3u8_url or stream_info.flv_url

    def _get_record_format(self, stream_info: StreamData):
        use_flv_record = ["shopee"]
        if stream_info.flv_url:
            if self.platform_key in use_flv_record or self.recording.flv_use_direct_download:
                self.save_format = "flv"
                self.recording.record_format = self.save_format
                self.recording.segment_record = False
                return self.save_format, True

            elif self.save_format == "flv":
                codec = utils.get_query_params(stream_info.flv_url, "codec")
                if codec and codec[0] == 'h265':
                    logger.warning("FLV is not supported for h265 codec, use TS format instead")
                    self.save_format = "ts"

        return self.save_format, False

    async def fetch_stream(self) -> StreamData:
        logger.info(f"[stream_manager] Live URL: {self.live_url}")
        logger.info(f"[stream_manager] Use Proxy: {self.proxy or None}")
        logger.debug(f"[stream_manager] Cookies for {self.platform_key}: {'Set' if self.cookies else 'Not set'}")
        self.recording.use_proxy = bool(self.proxy)

        handler = platform_handlers.get_platform_handler(
            live_url=self.live_url,
            proxy=self.proxy,
            cookies=self.cookies,
            record_quality=self.quality,
            platform=self.platform,
            username=self.account_config.get(self.platform_key, {}).get("username)"),
            password=self.account_config.get(self.platform_key, {}).get("password)"),
            account_type=self.account_config.get(self.platform_key, {}).get("account_type")
        )
        logger.info(f"[stream_manager] Handler resolved: platform_key={self.platform_key}, handler={type(handler).__name__ if handler else None}")
        
        if not handler:
            logger.error(f"[stream_manager] Handler is None for rec_id={self.recording.rec_id}, url={self.live_url}")
            self.recording.is_checking = False
            return StreamData(
                platform=self.platform,
                anchor_name=getattr(self.recording, "streamer_name", None),
                is_live=False,
                title=None,
                quality=None,
                m3u8_url=None,
                flv_url=None,
                record_url=None,
            )

        import time
        start_time = time.time()
        # 缩短超时时间到20秒，避免长时间阻塞
        timeout_seconds = 20
        logger.info(f"[stream_manager] Starting get_stream_info: rec_id={self.recording.rec_id}, url={self.live_url}, timeout={timeout_seconds}s")

        try:
            # 为防止 get_stream_info 卡死，增加超时保护
            # 如果 handler.get_stream_info 内部有同步阻塞操作，超时可能无法正常工作
            # 但至少可以防止无限等待
            stream_info = await asyncio.wait_for(
                handler.get_stream_info(self.live_url),
                timeout=timeout_seconds,
            )
            elapsed = time.time() - start_time
            logger.info(
                f"[stream_manager] get_stream_info completed in {elapsed:.2f}s: rec_id={self.recording.rec_id}, "
                f"is_live={getattr(stream_info, 'is_live', None)}, "
                f"anchor={getattr(stream_info, 'anchor_name', None)}, "
                f"has_flv={bool(getattr(stream_info, 'flv_url', None))}, "
                f"has_m3u8={bool(getattr(stream_info, 'm3u8_url', None))}"
            )
            return stream_info
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(
                f"[stream_manager] get_stream_info TIMEOUT after {elapsed:.2f}s (limit: {timeout_seconds}s): "
                f"rec_id={self.recording.rec_id}, url={self.live_url}"
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[stream_manager] get_stream_info ERROR after {elapsed:.2f}s: "
                f"rec_id={self.recording.rec_id}, url={self.live_url}, error={type(e).__name__}: {e}",
                exc_info=True,
            )
        finally:
            # 无论成功或失败，结束"检测中"状态，交由上层根据返回值判断是否继续重试
            elapsed = time.time() - start_time
            logger.debug(f"[stream_manager] get_stream_info finally block: rec_id={self.recording.rec_id}, elapsed={elapsed:.2f}s")
            self.recording.is_checking = False

        # 出现超时或错误时，返回一个 is_live=False 的占位结果，避免阻塞上层逻辑
        return StreamData(
            platform=self.platform,
            anchor_name=getattr(self.recording, "streamer_name", None),
            is_live=False,
            title=None,
            quality=None,
            m3u8_url=None,
            flv_url=None,
            record_url=None,
            new_cookies=None,
            new_token=None,
            extra=None,
        )

    async def start_recording(self, stream_info: StreamData):
        """
        Construct ffmpeg recording parameters and start recording
        """

        self.save_format, use_direct_download = self._get_record_format(stream_info)
        # Call _get_output_dir first to set timestamp, then _get_filename to use the same timestamp
        self.output_dir = self._get_output_dir(stream_info)
        filename = self._get_filename(stream_info)
        save_path = self._get_save_path(filename, use_direct_download)
        logger.info(f"Save Path: {save_path}")
        self.recording.recording_dir = os.path.dirname(save_path)
        os.makedirs(self.recording.recording_dir, exist_ok=True)
        record_url = self._get_record_url(stream_info)
        self.set_preview_url(stream_info)

        try:
            if self.recording.rec_id in self.app.record_manager.active_recorders:
                old_recorder = self.app.record_manager.active_recorders[self.recording.rec_id]
                logger.warning(
                    f"Found existing recorder instance for {self.recording.rec_id}, id: {id(old_recorder)}, stopping it"
                )
                old_recorder.request_stop()

                await asyncio.sleep(1)
            
            self.app.record_manager.active_recorders[self.recording.rec_id] = self
            logger.info(f"Saved recorder instance for {self.recording.rec_id}, id: {id(self)}")
        except Exception as e:
            logger.error(f"Failed to save recorder instance: {e}")

        if use_direct_download:
            logger.info(f"Use Direct Downloader to Download FLV Stream: {record_url}")
            headers = {}
            header_params = self.get_headers_params(record_url, self.platform_key)
            if header_params:
                key, value = header_params.split(":", 1)
                headers[key] = value

            self.direct_downloader = DirectStreamDownloader(
                record_url=record_url,
                save_path=save_path,
                headers=headers,
                proxy=self.proxy
            )

            self.app.page.run_task(
                self.start_direct_download,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                save_path,
                self.save_format,
                self.user_config.get("custom_script_command")
            )
        else:
            ffmpeg_builder = ffmpeg_builders.create_builder(
                self.save_format,
                record_url=record_url,
                proxy=self.proxy,
                segment_record=self.segment_record,
                segment_time=self.segment_time,
                full_path=save_path,
                headers=self.get_headers_params(record_url, self.platform_key)
            )
            ffmpeg_command = ffmpeg_builder.build_command()
            self.app.page.run_task(
                self.start_ffmpeg,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                ffmpeg_command,
                self.save_format,
                self.user_config.get("custom_script_command")
            )

    async def remove_active_recorder(self):
        try:
            if self.recording.rec_id in self.app.record_manager.active_recorders:
                del self.app.record_manager.active_recorders[self.recording.rec_id]
                logger.info(f"Removed recorder from active_recorders: {self.recording.rec_id}")
        except Exception as e:
            logger.error(f"Failed to remove recorder instance: {e}")

    async def recheck_live_status(self):
        if not self.should_stop:
            # not manually stopped
            recording_duration = time.time() - self.recording_start_time
            if recording_duration > self.min_valid_recording_duration:
                if self.app.recording_enabled and not self.is_flv_preferred_platform:
                    self.app.page.run_task(self.app.record_manager.check_if_live, self.recording)
            else:
                self.recording.status_info = RecordingStatus.RECORDING_ERROR

    async def start_ffmpeg(
            self,
            record_name: str,
            live_url: str,
            record_url: str,
            ffmpeg_command: list,
            save_type: str,
            script_command: str | None = None
    ) -> bool:
        """
        The child process executes ffmpeg for recording
        """

        logger.info(f"Starting ffmpeg recording - recorder id: {id(self)}, rec_id: {self.recording.rec_id}")
        self.should_stop = False

        try:
            save_file_path = ffmpeg_command[-1]

            process = await asyncio.create_subprocess_exec(
                *ffmpeg_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                startupinfo=self.subprocess_start_info
            )

            self.app.add_ffmpeg_process(process)
            self.recording.status_info = RecordingStatus.RECORDING
            self.recording.record_url = record_url
            logger.info(f"Recording in Progress: {live_url}")
            logger.log("STREAM", f"Recording Stream URL: {record_url}")
            self.recording_start_time = time.time()
            last_duration_check_time = self.recording_start_time
            duration_check_interval = 30 * 60  # 30分钟检查一次
            
            while True:
                # 每隔30分钟检查一次累计录制时长，如果超过2小时就停止录制
                current_time = time.time()
                if current_time - last_duration_check_time >= duration_check_interval:
                    try:
                        # 获取数据库中已保存的历史累计录制时长
                        total_saved_seconds = await self.app.record_manager._get_total_recording_duration_for_rec(self.recording.rec_id)
                        # 计算当前会话已录制的时长
                        current_session_duration = current_time - self.recording_start_time
                        # 总时长 = 历史累计时长 + 当前会话时长
                        total_seconds = total_saved_seconds + current_session_duration
                        
                        logger.debug(
                            f"Duration check for {self.recording.rec_id}: "
                            f"total_saved={int(total_saved_seconds)}s, "
                            f"current_session={int(current_session_duration)}s, "
                            f"total={int(total_seconds)}s"
                        )
                        
                        if total_seconds >= self.app.record_manager.max_total_recording_duration:
                            logger.info(
                                f"Recording for {self.recording.rec_id} reached max total duration "
                                f"({int(total_seconds)}s >= {self.app.record_manager.max_total_recording_duration}s), "
                                f"stopping recording"
                            )
                            self.should_stop = True
                    except Exception as e:
                        logger.debug(f"Failed to check total recording duration during recording: {e}")
                    last_duration_check_time = current_time
                
                if self.should_stop or self.recording.force_stop or not self.app.recording_enabled:
                    logger.info(f"Preparing to End Recording: {live_url}")
                    await self.remove_active_recorder()
                    self.recording.is_recording = False
                    try:
                        if os.name == "nt":
                            if process.stdin:
                                process.stdin.write(b"q")
                                await process.stdin.drain()
                                await asyncio.sleep(5)
                        else:
                            import signal
                            process.send_signal(signal.SIGINT)
                            # process.terminate()
                            await asyncio.sleep(5)

                        if process.stdin:
                            process.stdin.close()

                        await asyncio.wait_for(process.wait(), timeout=15.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"FFmpeg process did not exit gracefully, forcing termination: {live_url}")
                        process.kill()
                        await process.wait()

                    self.recording.force_stop = False
                    break

                if process.returncode is not None:
                    logger.info(f"Exit loop recording (normal 0 | abnormal 1): code={process.returncode}, {live_url}")
                    await self.remove_active_recorder()
                    self.recording.is_recording = False
                    break

                await asyncio.sleep(1)

            return_code = process.returncode
            safe_return_code = [0, 255]
            stdout, stderr = await process.communicate()
            
            if return_code not in safe_return_code and stderr:
                if not self.recording.is_recording:
                    logger.error(f"FFmpeg Stderr Output: {str(stderr.decode()).splitlines()[0]}")
                    self.recording.status_info = RecordingStatus.RECORDING_ERROR

                    try:
                        self.app.record_manager.stop_recording(self.recording)
                        await self.app.record_card_manager.update_card(self.recording)
                        self.app.page.pubsub.send_others_on_topic("update", self.recording)
                        await self.app.snack_bar.show_snack_bar(
                            record_name + " " + self._["record_stream_error"], duration=2000
                        )
                    except Exception as e:
                        logger.debug(f"Failed to update UI: {e}")

            if return_code in safe_return_code:
                self.recording.is_live = False
                if not self.recording.is_recording:
                    # 正常完成录制时，调用 stop_recording 以保存录制时长到数据库
                    # 注意：此时 is_recording 可能已经被设置为 False，但 start_time 还存在
                    if self.recording.start_time is not None:
                        self.app.record_manager.stop_recording(self.recording, manually_stopped=False)
                    
                    if self.recording.monitor_status:
                        self.recording.status_info = RecordingStatus.MONITORING
                        display_title = self.recording.title
                    else:
                        self.recording.status_info = RecordingStatus.STOPPED_MONITORING
                        display_title = self.recording.display_title

                    self.recording.live_title = None
                    if self.should_stop:
                        logger.success(f"Live recording has stopped: {record_name}")
                    else:
                        logger.success(f"Live recording completed: {record_name}")
                        self.app.page.run_task(self.end_message_push)
                    
                    try:
                        self.recording.update({"display_title": display_title})
                        self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                        self.app.page.pubsub.send_others_on_topic("update", self.recording)
                    except Exception as e:
                        logger.debug(f"Failed to update UI: {e}")

                if not self.app.recording_enabled:
                    self.recording.status_info = RecordingStatus.NOT_RECORDING_SPACE
                    self.app.page.run_task(self.stop_recording_notify)

                await self.recheck_live_status()

                if self.user_config.get("convert_to_mp4") and self.save_format == "ts":
                    if self.segment_record:
                        file_paths = utils.get_file_paths(os.path.dirname(save_file_path))
                        prefix = os.path.basename(save_file_path).rsplit("_", maxsplit=1)[0]
                        for path in file_paths:
                            if prefix in path:
                                try:
                                    self.app.page.run_task(
                                        self.converts_mp4, path, self.user_config["delete_original"]
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to convert video: {e}")
                                    await self.converts_mp4(path, self.user_config["delete_original"])
                    else:
                        try:
                            self.app.page.run_task(
                                self.converts_mp4, save_file_path, self.user_config["delete_original"]
                            )
                        except Exception as e:
                            logger.error(f"Failed to convert video: {e}")
                            await self.converts_mp4(save_file_path, self.user_config["delete_original"])

                if self.user_config.get("execute_custom_script") and script_command:
                    logger.info("Prepare a direct script in the background")
                    try:
                        self.app.page.run_task(
                            self.custom_script_execute,
                            script_command,
                            record_name,
                            save_file_path,
                            save_type,
                            self.segment_record,
                            self.user_config.get("convert_to_mp4")
                        )
                        logger.success("Successfully added script execution")
                    except Exception as e:
                        logger.error(f"Failed to execute custom script: {e}")
                        await self.custom_script_execute(
                            script_command,
                            record_name,
                            save_file_path,
                            save_type,
                            self.segment_record,
                            self.user_config.get("convert_to_mp4")
                        )

        except Exception as e:
            logger.error(f"An error occurred during the subprocess execution: {e}")
            self.recording.status_info = RecordingStatus.RECORDING_ERROR

            try:
                self.app.record_manager.stop_recording(self.recording)
                await self.app.record_card_manager.update_card(self.recording)
                self.app.page.pubsub.send_others_on_topic("update", self.recording)
                await self.app.snack_bar.show_snack_bar(
                    record_name + " " + self._["no_ffmpeg_tip"], duration=4000
                )
            except Exception as e:
                logger.debug(f"Failed to update UI: {e}")
            return False
        finally:
            self.recording.record_url = None

        return True

    async def converts_mp4(self, converts_file_path: str, is_original_delete: bool = True) -> None:
        """Asynchronous transcoding method, can be added to the background service to continue execution"""
        if not self.app.recording_enabled:
            logger.info(f"Application is closing, adding transcoding task to background service: {converts_file_path}")
            BackgroundService.get_instance().add_task(
                self.converts_mp4_sync, converts_file_path, is_original_delete
            )
            return

        # Otherwise, execute transcoding normally
        await self._do_converts_mp4(converts_file_path, is_original_delete)

    def converts_mp4_sync(self, converts_file_path: str, is_original_delete: bool = True) -> None:
        """Synchronous version of the transcoding method, used for background service"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._do_converts_mp4(converts_file_path, is_original_delete))
        finally:
            loop.close()

    async def _do_converts_mp4(self, converts_file_path: str, is_original_delete: bool = True) -> None:
        """Actual execution method for transcoding"""
        converts_success = False
        save_path = None
        try:
            converts_file_path = converts_file_path.replace("\\", "/")
            if os.path.exists(converts_file_path) and os.path.getsize(converts_file_path) > 0:
                save_path = converts_file_path.rsplit(".", maxsplit=1)[0] + ".mp4"
                ffmpeg_command = [
                    "ffmpeg",
                    "-i", converts_file_path,
                    "-c:v", "copy",
                    "-c:a", "copy",
                    "-f", "mp4",
                    save_path
                ]
                process = await asyncio.create_subprocess_exec(
                    *ffmpeg_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    startupinfo=self.subprocess_start_info
                )

                self.app.add_ffmpeg_process(process)
                task = asyncio.create_task(process.communicate())
                _, stderr = await task
                if process.returncode == 0:
                    converts_success = True
                    logger.info(f"Video transcoding completed: {save_path}")
                else:
                    logger.error(
                        f"Video transcoding failed! Error message: {stderr.decode() if stderr else 'Unknown error'}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Video transcoding failed! Error message: {e.output.decode()}")

        try:
            if converts_success:
                if is_original_delete:
                    await asyncio.sleep(1)
                    if os.path.exists(converts_file_path):
                        os.remove(converts_file_path)
                    logger.info(f"Delete Original File: {converts_file_path}")
                else:
                    converts_dir = f"{os.path.dirname(save_path)}/original"
                    os.makedirs(converts_dir, exist_ok=True)
                    shutil.move(converts_file_path, converts_dir)
                    logger.info(f"Move Transcoding Files: {converts_file_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Error occurred during conversion: {e}")
        except Exception as e:
            logger.error(f"An unknown error occurred: {e}")

    async def custom_script_execute(
            self,
            script_command: str,
            record_name: str,
            save_file_path: str,
            save_type: str,
            split_video_by_time: bool,
            converts_to_mp4: bool
    ):
        from ..runtime.process_manager import BackgroundService

        if "python" in script_command:
            params = [
                f'--record_name "{record_name}"',
                f'--save_file_path "{save_file_path}"',
                f'--save_type {save_type}',
                f'--split_video_by_time {split_video_by_time}',
                f'--converts_to_mp4 {converts_to_mp4}',
            ]
        else:
            params = [
                f'"{record_name.split(" ", maxsplit=1)[-1]}"',
                f'"{save_file_path}"',
                save_type,
                f"split_video_by_time: {split_video_by_time}",
                f"converts_to_mp4: {converts_to_mp4}"
            ]
        script_command = script_command.strip() + " " + " ".join(params)

        if not self.app.recording_enabled:
            logger.info("Application is closing, adding script execution task to background service")
            BackgroundService.get_instance().add_task(self.run_script_sync, script_command)
        else:
            self.app.page.run_task(self.run_script_async, script_command)

        logger.success("Script command execution initiated!")

    def run_script_sync(self, command: str) -> None:
        """Synchronous version of the script execution method, used for background service"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.run_script_async(command))
        finally:
            loop.close()

    async def run_script_async(self, command: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *command.split(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                startupinfo=self.subprocess_start_info,
                text=False
            )

            stdout, stderr = await process.communicate()

            if stdout:
                logger.info(stdout.splitlines()[0].decode())
            if stderr:
                logger.error(stderr.splitlines()[0].decode())

            if process.returncode != 0:
                logger.info(f"Custom Script process exited with return code {process.returncode}")

        except PermissionError:
            logger.error(
                "Script has no execution permission!, If it is a Linux environment, "
                "please first execute: chmod+x your_script.sh to grant script executable permission"
            )
        except OSError:
            logger.error("Please add `#!/bin/bash` at the beginning of your bash script file.")
        except Exception as e:
            logger.error(f"An error occurred: {e}")

    @staticmethod
    def get_headers_params(live_url, platform_key):
        live_domain = "/".join(live_url.split("/")[0:3])
        record_headers = {
            "pandalive": "origin:https://www.pandalive.co.kr",
            "winktv": "origin:https://www.winktv.co.kr",
            "popkontv": "origin:https://www.popkontv.com",
            "flextv": "origin:https://www.flextv.co.kr",
            "qiandurebo": "referer:https://qiandurebo.com",
            "17live": "referer:https://17.live/en/live/6302408",
            "lang": "referer:https://www.lang.live",
            "shopee": "origin:" + live_domain,
            "blued": "referer:https://app.blued.cn",
        }
        return record_headers.get(platform_key)

    async def start_direct_download(
            self,
            record_name: str,
            live_url: str,
            record_url: str,
            save_file_path: str,
            save_type: str,
            script_command: str | None = None
    ) -> bool:
        """
        Use the direct downloader to download the live stream
        """
        
        logger.info(f"Starting direct download - recorder id: {id(self)}, rec_id: {self.recording.rec_id}")
        self.should_stop = False
        
        try:
            await self.direct_downloader.start_download()

            self.recording.status_info = RecordingStatus.RECORDING
            self.recording.record_url = record_url
            logger.info(f"Direct Downloading: {live_url}")
            logger.log("STREAM", f"Direct Download Stream URL: {record_url}")
            self.recording_start_time = time.time()

            while True:
                if self.should_stop or self.recording.force_stop or not self.app.recording_enabled:
                    logger.info(f"Prepare to end direct download: {live_url}")
                    await self.remove_active_recorder()
                    self.recording.is_recording = False
                    await self.direct_downloader.stop_download()
                    self.recording.force_stop = False
                    break

                await asyncio.sleep(1)

                if self.direct_downloader.download_task and self.direct_downloader.download_task.done():
                    break

            await self.remove_active_recorder()
            self.recording.is_recording = False

            if not self.recording.is_recording:
                self.recording.is_live = False
                if self.recording.monitor_status:
                    self.recording.status_info = RecordingStatus.MONITORING
                    display_title = self.recording.title
                else:
                    self.recording.status_info = RecordingStatus.STOPPED_MONITORING
                    display_title = self.recording.display_title

                self.recording.live_title = None
                if self.should_stop:
                    logger.success(f"Direct Downloading Stopped: {record_name}")
                else:
                    logger.success(f"Direct Downloading Completed: {record_name}")
                    self.app.page.run_task(self.end_message_push)

                try:
                    self.recording.update({"display_title": display_title})
                    await self.app.record_card_manager.update_card(self.recording)
                    self.app.page.pubsub.send_others_on_topic("update", self.recording)
                except Exception as e:
                    logger.debug(f"Failed to update UI: {e}")

            if not self.app.recording_enabled:
                self.recording.status_info = RecordingStatus.NOT_RECORDING_SPACE
                self.app.page.run_task(self.stop_recording_notify)

            await self.recheck_live_status()

            if self.user_config.get("execute_custom_script") and script_command:
                logger.info("Prepare to execute custom script in the background")
                try:
                    self.app.page.run_task(
                        self.custom_script_execute,
                        script_command,
                        record_name,
                        save_file_path,
                        save_type,
                        False,
                        False
                    )
                    logger.success("Successfully added script execution")
                except Exception as e:
                    logger.error(f"Failed to execute custom script: {e}")
                    await self.custom_script_execute(
                        script_command,
                        record_name,
                        save_file_path,
                        save_type,
                        False,
                        False
                    )

            return True

        except Exception as e:
            logger.error(f"Error occurred during direct download: {e}")
            self.recording.status_info = RecordingStatus.RECORDING_ERROR

            try:
                self.app.record_manager.stop_recording(self.recording)
                await self.app.record_card_manager.update_card(self.recording)
                self.app.page.pubsub.send_others_on_topic("update", self.recording)
                await self.app.snack_bar.show_snack_bar(
                    record_name + " " + self._["record_stream_error"], duration=2000
                )
            except Exception as e:
                logger.debug(f"Failed to update UI: {e}")
            return False
        finally:
            self.recording.record_url = None

    async def stop_recording_notify(self):
        if desktop_notify.should_push_notification(self.app):
            desktop_notify.send_notification(
                title=self._["notify"],
                message=self.recording.streamer_name + ' | ' + self._["live_recording_stopped_message"],
                app_icon=self.app.tray_manager.icon_path
            )

    async def end_message_push(self):
        msg_manager = message_pusher.MessagePusher(self.settings)
        user_config = self.settings.user_config

        if (self.app.recording_enabled and msg_manager.should_push_message(
                self.settings, self.recording, check_manually_stopped=True, message_type='end') and
                not self.recording.notified_live_end):
            self.recording.notified_live_end = True
            push_content = self._["push_content_end"]
            end_push_message_text = user_config.get("custom_stream_end_content")
            if end_push_message_text:
                push_content = end_push_message_text

            push_at = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
            push_content = push_content.replace("[room_name]", self.recording.streamer_name).replace(
                "[time]", push_at).replace("[title]", self.recording.live_title or "None")
            msg_title = user_config.get("custom_notification_title").strip()
            msg_title = msg_title or self._["status_notify"]

            self.app.page.run_task(msg_manager.push_messages, msg_title, push_content)

    def request_stop(self):
        logger.info(f"Stop requested for recorder: {self.recording.url}, rec_id: {self.recording.rec_id}")
        logger.info(f"Recorder instance details - id: {id(self)}, recording: {self.recording.title}")
        
        old_value = self.should_stop
        self.should_stop = True
        
        logger.info(f"Set should_stop from {old_value} to {self.should_stop} for recorder: {self.recording.rec_id}")
