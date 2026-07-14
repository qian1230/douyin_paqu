#!/usr/bin/env python3
"""
抖音直播录制脚本 - 完整版：新增直播间库/热度时序库/弹幕库
扩展数据库：live_rooms、popularity_logs、danmaku_logs
支持分类别录制、人脸过滤、热度时序采集、弹幕同步抓取
用法: python record_category.py 娱乐
       python record_category.py 二次元
       python record_category.py 文化
"""
import subprocess
import threading
import sys
import asyncio
import aiohttp
import os
import sys
import subprocess
import cv2
import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from douyin_danmaku import DouyinDanmaku
# ===================== 环境配置 =====================
ffmpeg_dir = r"C:\Users\PC013\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin"
os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ["PATH"]

subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("✅ ffmpeg 已就绪")
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 业务导入
from app.core.scraper.platforms.douyin_feed_scraper import DouyinScraper
from app.core.platforms.platform_handlers.douyin_worker import fetch_douyin_stream
from app.models.recording.scraped_room_model import ScrapedRoom, ScrapedRoomStatus

# ===================== 全局常量 =====================
CATEGORY_PARTITION = {
    "娱乐": 202,
    "知识": 203,
    "电商": 106,
    "二次元": 104,
    "游戏": 103,
    "运动": 108,
    "舞蹈": 105,
    "音乐": 102,
    "聊天": 203,
    "生活": 107,
    "文化": 210,
}

MAX_RECORDING = 20
RECORD_DURATION = 600
CHECK_INTERVAL = 150
TASK_DELAY = 20
FACE_DETECTION = False
VIDEO_SAVE_PATH = Path(r"D:\zhibo-video\douyin")
DB_PATH = Path("streamcap.db")
MAX_EMPTY_RESULTS = 3
BAN_WAIT_TIME = 1800
DANMU_SAVE_ROOT = VIDEO_SAVE_PATH / "danmu_csv"
DANMU_SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# ===================== 数据库初始化函数 =====================
def init_db():
    """程序启动自动创建全部数据表"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 1. 直播间基础信息表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS live_rooms(
        room_id TEXT PRIMARY KEY,
        category TEXT,
        anchor_name TEXT,
        title TEXT,
        first_crawl_time TEXT
    );
    ''')

    # 2. 热度时序日志表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS popularity_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT,
        timestamp TEXT,
        viewer_count INTEGER DEFAULT 0,
        like_count INTEGER DEFAULT 0,
        share_count INTEGER DEFAULT 0,
        gift_count INTEGER DEFAULT 0
    );
    ''')

    # 3. 弹幕日志表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS danmaku_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT,
        timestamp TEXT,
        user_name TEXT,
        content TEXT
    );
    ''')

    # 原有录制日志表（保留兼容）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS recording_logs (
        room_id TEXT,
        platform TEXT,
        start_time TEXT,
        end_time TEXT,
        duration INTEGER,
        file_path TEXT,
        status TEXT
    );
    ''')
    conn.commit()
    conn.close()
    print("✅ 数据库表初始化完成")

# ===================== 主录制类 =====================
class CategoryRecorder:
    def __init__(self, category):
        self.category = category
        self.partition_id = CATEGORY_PARTITION.get(category)
        if not self.partition_id:
            raise ValueError(f"未知类别: {category}")

        self.recording_tasks = {}
        self.waiting_list = []
        self.consecutive_empty = 0

        self.stats = {
            'checked': 0, 'found_live': 0, 'recorded': 0,
            'face_passed': 0, 'face_failed': 0, 'failed': 0,
            'fixed': 0, 'ban_detected': 0
        }

        self.category_path = VIDEO_SAVE_PATH / category
        self.category_path.mkdir(parents=True, exist_ok=True)

        self.log("=" * 60)
        self.log(f"🚀 抖音录制服务启动 - 类别: {category} (ID:{self.partition_id})")
        self.log("=" * 60)
        self.log(f"视频保存路径: {self.category_path}")
        self.log("弹幕CSV根目录: {DANMU_SAVE_ROOT}")
        self.log("=" * 60)


    def log(self, msg, level="INFO", end="\n"):
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] [{self.category}] [{level}] {msg}", end=end)

    def launch_danmu_task(self, room_id: str, csv_save_path: str):
        """独立线程启动弹幕抓取子进程"""
        danmu_main = r"D:\pycharm\Project\DouyinLiveWebFetcher-main\DouyinLiveWebFetcher-main\main.py"
        cmd = [
            sys.executable,
            danmu_main,
            room_id,
            csv_save_path
        ]
        self.log(f"【DEBUG】弹幕启动命令: {cmd}")
        # 移除管道拦截，允许弹出控制台窗口，直接看弹幕脚本报错
        subprocess.Popen(
            cmd,
            # creationflags=subprocess.CREATE_NO_WINDOW, 注释掉，弹出黑窗口看日志
            # stdout=subprocess.PIPE,
            # stderr=subprocess.PIPE
        )
        #self.log(f"✅ 同步启动外部弹幕抓取 room_id:{room_id}，弹幕文件：{csv_save_path}")
    # ---------------- 新增：存储直播间基础信息 ----------------
    def save_room_info(self, room: ScrapedRoom):
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO live_rooms
        (room_id, category, anchor_name, title, first_crawl_time)
        VALUES (?,?,?,?,?)
        """, (
            room.room_id,
            self.category,
            room.anchor_name,
            room.title,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()

    # ---------------- 新增：实时写入热度时序数据 ----------------
    def save_popularity(self, room):

        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        cursor.execute("""
                       INSERT INTO popularity_logs
                       (room_id,
                        timestamp,
                        viewer_count,
                        like_count,
                        share_count,
                        gift_count)
                       VALUES (?, ?, ?, ?, ?, ?)
                       """,
                       (
                           room.room_id,
                           datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           room.viewer_count,
                           0,
                           0,
                           0
                       ))

        conn.commit()
        conn.close()
    # ---------------- 新增：单条弹幕入库 ----------------
    def save_danmaku(self, room_id: str, user_name: str, content: str):
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO danmaku_logs
        (room_id, timestamp, user_name, content)
        VALUES (?,?,?,?)
        """, (
            room_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user_name,
            content
        ))
        conn.commit()
        conn.close()

    def log_recording(self, room_id, file_path, duration, status="completed"):
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO recording_logs 
                (room_id, platform, start_time, end_time, duration, file_path, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                room_id,
                "douyin",
                (datetime.now() - timedelta(seconds=duration)).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                duration,
                str(file_path),
                status
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            self.log(f"录制日志入库失败: {e}", "ERROR")

    async def detect_face(self, stream_url):
        if not FACE_DETECTION:
            return True
        try:
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                return False
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            faces_detected = 0
            for _ in range(8):
                ret, frame = cap.read()
                if not ret:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(50, 50))
                if len(faces) > 0:
                    faces_detected += 1
            cap.release()
            return faces_detected >= 2
        except Exception:
            return False

    async def crawl_live_rooms(self):
        self.log("=" * 60)
        self.log("🔄 开始爬取分区直播间列表")
        self.log("=" * 60)
        base_url = "https://live.douyin.com/webcast/web/partition/detail/room/v2/"
        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "enter_from": "page_refresh",
            "cookie_enabled": "true",
            "screen_width": "801",
            "screen_height": "858",
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "browser_version": "142.0.0.0",
            "count": "15",
            "offset": "0",
            "partition": str(self.partition_id),
            "partition_type": "4",
            "req_from": "2",
        }
        from urllib.parse import urlencode
        from app.core.scraper.platforms.douyin_abogus import get_a_bogus
        bogus = get_a_bogus(params)
        if bogus:
            params["a_bogus"] = bogus
        url = f"{base_url}?{urlencode(params)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv("DOUYIN_COOKIE", ""),
            "Referer": "https://live.douyin.com/",
        }
        rooms = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30) as resp:
                    if resp.status != 200:
                        self.log(f"❌ 分区接口请求失败 HTTP {resp.status}", "ERROR")
                        return rooms
                    data = await resp.json()
                    inner_data = data.get("data", {})
                    items = inner_data.get("data", [])
                    for item in items:
                        room_data = item.get("room", {})
                        owner = item.get("owner") or room_data.get("owner") or {}
                        slug = str(item.get("web_rid") or room_data.get("id_str") or room_data.get("id") or "").strip()
                        if not slug:
                            continue
                        new_room = ScrapedRoom(
                            platform="douyin",
                            room_id=str(slug),
                            room_url=f"https://live.douyin.com/{slug}",
                            title=room_data.get("title", ""),
                            anchor_name=owner.get("nickname", ""),
                            viewer_count=room_data.get("user_count", 0),
                            status=ScrapedRoomStatus.PENDING,
                            category=self.category,
                        )
                        rooms.append(new_room)
                        # 新增：爬取到直播间立刻入库基础信息
                        self.save_room_info(new_room)
                    self.log(f"✅ 爬取到 {len(rooms)} 个直播间，已入库基础信息")
                    return rooms
        except Exception as e:
            self.log(f"爬取直播间列表异常: {e}", "ERROR")
            return rooms

    async def check_room_live(self, room):
        try:
            result = await fetch_douyin_stream(
                url=room.room_url,
                proxy=None,
                cookies=os.getenv("DOUYIN_COOKIE"),
                quality="ld"
            )
            if result and result.get('is_live'):
                # 新增：检测到直播，立刻写入当前热度数据
                self.save_popularity(room)
                return {
                    'is_live': True,
                    'anchor': result.get('anchor_name'),
                    'title': result.get('title'),
                    'stream_url': result.get('record_url'),
                    'room': room,
                    'stream_meta': result  # 完整热度元数据透传
                }
            return {'is_live': False}
        except Exception as e:
            self.log(f"直播间{room.room_id}检测异常: {e}", "ERROR")
            return {'is_live': False}

    def get_video_path(self, room):
        now = datetime.now()
        date_str = now.strftime("%Y%m%d_%H%M%S")
        video_dir = self.category_path / room.room_id / date_str
        video_dir.mkdir(parents=True, exist_ok=True)
        return video_dir / f"{date_str}.mp4"

    async def fix_video(self, video_path):
        import shutil
        disk_usage = shutil.disk_usage(video_path.parent)
        free_gb = disk_usage.free / (1024 ** 3)
        if free_gb < 10:
            self.log(f"⚠️ 磁盘剩余不足10GB，跳过视频修复", "WARNING")
            return
        fixed_path = video_path.with_suffix('.tmp.mp4')
        try:
            if fixed_path.exists():
                fixed_path.unlink()
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', str(video_path), '-c', 'copy',
                '-movflags', '+faststart', '-y', str(fixed_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=300)
            except asyncio.TimeoutError:
                process.kill()
                self.log("⏰ 视频修复超时", "WARNING")
                fixed_path.unlink(missing_ok=True)
                return
            if process.returncode == 0 and fixed_path.exists():
                video_path.unlink(missing_ok=True)
                fixed_path.rename(video_path)
                self.stats['fixed'] += 1
                self.log(f"✅ 视频修复完成")
            else:
                self.log(f"⚠️ 视频修复失败 退出码:{process.returncode}", "WARNING")
                fixed_path.unlink(missing_ok=True)
        except Exception as e:
            self.log(f"❌ 视频修复异常:{e}", "ERROR")
            try:
                fixed_path.unlink(missing_ok=True)
            except Exception:
                pass

    # ---------------- 预留：异步弹幕监听协程（可对接ws弹幕接口） ----------------
    async def danmu_listener_task(self, room_id, room_url, save_csv_path):
        """
        录制期间后台持续监听弹幕，解析后：
        1. 写入本地csv 方便Lab2批量读取
        2. 调用 self.save_danmaku() 存入sqlite danmaku_logs表
        """
        self.log(f"📝 启动弹幕监听任务 room:{room_id}")
        # ========== 此处填入抖音websocket弹幕连接、解析逻辑 ==========
        # while True:
        #     raw_msg = await websocket.recv()
        #     danmu_data = parse_douyin_danmu(raw_msg)
        #     self.save_danmaku(room_id, danmu_data["nick"], danmu_data["text"])
        #     写入csv
        # ==========================================================
        await asyncio.Event().wait()  # 占位，待实现ws逻辑

    async def start_recording(self, room, stream_info):
        if len(self.recording_tasks) >= MAX_RECORDING:
            if len(self.waiting_list) < MAX_RECORDING:
                self.waiting_list.append({
                    'room': room,
                    'stream_info': stream_info,
                    'detected_time': datetime.now()
                })
                self.log(f"   ⏳ 录制达上限，加入等待队列 ({len(self.waiting_list)}/{MAX_RECORDING})")
            else:
                self.log(f"   ⚠️ 等待队列已满，丢弃直播间", "WARNING")
            return False

        video_path = self.get_video_path(room)
        danmu_csv = video_path.parent / f"danmu_{room.room_id}.csv"

        # 仅启动一次弹幕子进程，消除重复日志、文件抢占冲突
        threading.Thread(
            target=self.launch_danmu_task,
            args=(room.room_id, str(danmu_csv)),
            daemon=True
        ).start()
        self.log(f"✅ 同步启动外部弹幕抓取 room_id:{room.room_id}，弹幕文件：{danmu_csv}")
        import time
        time.sleep(0.3)
        # ffmpeg录制命令
        cmd = [
            'ffmpeg', '-i', stream_info['stream_url'],
            '-t', str(RECORD_DURATION),
            '-c', 'copy', '-bsf:a', 'aac_adtstoasc', '-y',
            str(video_path)
        ]
        self.log(f"\n🎬 开始录制: {room.anchor_name}")
        self.log(f"   标题: {stream_info['title']}")
        self.log(f"   视频路径: {video_path}")
        self.log(f"   弹幕存储csv: {danmu_csv}")

        try:
            ffmpeg_proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )

            self.recording_tasks[room.room_id] = {
                'ffmpeg_proc': ffmpeg_proc,
                'danmu_task': None,
                'room': room,
                'video_path': video_path,
                'danmu_csv': danmu_csv,
                'start_time': datetime.now()
            }
            self.stats['recorded'] += 1
            self.log(f"   ✅ 录制中 | 并发录制:{len(self.recording_tasks)} | 等待队列:{len(self.waiting_list)}")
            return True
        except Exception as e:
            self.log(f"❌ 启动录制失败:{e}", "ERROR")
            return False
    async def check_waiting_list(self):
        if not self.waiting_list:
            return
        while self.waiting_list and len(self.recording_tasks) < MAX_RECORDING:
            next_task = self.waiting_list.pop(0)
            self.log(f"\n🔄 有空位，取出队列直播间，剩余队列:{len(self.waiting_list)}")
            await self.start_recording(next_task['room'], next_task['stream_info'])

    async def monitor_recordings(self):
        finished_room_ids = []
        for room_id, task_info in self.recording_tasks.items():
            if task_info['ffmpeg_proc'].returncode is not None:
                finished_room_ids.append(room_id)
                try:
                    if task_info['video_path'].exists():
                        duration_sec = int((datetime.now() - task_info['start_time']).total_seconds())
                        self.log(f"\n✅ 录制完成 主播:{task_info['room'].anchor_name} 时长:{duration_sec}s")
                        self.log_recording(room_id, task_info['video_path'], duration_sec)
                        # 内置弹幕协程已废弃，非空才取消
                        if task_info['danmu_task'] is not None:
                            task_info['danmu_task'].cancel()
                        # 执行视频修复
                        try:
                            await self.fix_video(task_info['video_path'])
                        except Exception as e:
                            self.log(f"视频修复异常:{e}", "ERROR")
                    else:
                        self.log(f"\n⚠️ 录制进程结束，但视频文件不存在", "WARNING")
                except PermissionError:
                    self.log(f"⚠️ 文件被占用，暂不移除任务，下轮重试", "WARNING")
                    finished_room_ids.remove(room_id)
                    continue
                except Exception as e:
                    self.log(f"❌ 录制文件检查异常:{e}", "ERROR")
        # 清理已完成任务
        for rid in finished_room_ids:
            del self.recording_tasks[rid]
        # 有空位立刻补队列
        if finished_room_ids:
            await self.check_waiting_list()

    async def run_once(self):
        await self.monitor_recordings()
        if len(self.waiting_list) >= MAX_RECORDING:
            self.log(f"⏸️ 等待队列已满，暂停本轮爬取", "INFO")
            return
        rooms = await self.crawl_live_rooms()
        if not rooms:
            self.consecutive_empty += 1
            if self.consecutive_empty >= MAX_EMPTY_RESULTS:
                self.log(f"🚨 连续无直播间，疑似风控，休眠30分钟", "WARNING")
                await asyncio.sleep(BAN_WAIT_TIME)
                self.consecutive_empty = 0
            return
        self.consecutive_empty = 0
        self.log(f"\n🔍 开始检测直播间状态 | 当前录制:{len(self.recording_tasks)} | 队列:{len(self.waiting_list)}")
        for idx, room in enumerate(rooms):
            if len(self.waiting_list) >= MAX_RECORDING:
                self.log(f"⏸️ 队列已满，终止本轮检测")
                break
            await self.monitor_recordings()
            self.stats['checked'] += 1
            self.log(f"   检测 {idx+1}/{len(rooms)} 主播:{room.anchor_name}")
            await asyncio.sleep(random.uniform(1, TASK_DELAY))
            live_res = await self.check_room_live(room)
            if live_res['is_live']:
                self.log(f"   🔴 正在直播")
                self.stats['found_live'] += 1
                if FACE_DETECTION:
                    face_ok = await self.detect_face(live_res['stream_url'])
                    if not face_ok:
                        self.stats['face_failed'] += 1
                        self.log(f"   ❌ 人脸检测不通过，跳过录制")
                        continue
                    self.stats['face_passed'] += 1
                    self.log(f"   ✅ 人脸校验通过，启动录制")
                await self.start_recording(room, live_res)
            else:
                self.log(f"   ⚪ 未开播")
        # 本轮统计输出
        self.log("\n" + "=" * 60)
        self.log("📊 本轮运行统计")
        self.log("=" * 60)
        self.log(f"检测直播间总数: {self.stats['checked']}")
        self.log(f"有效直播房间: {self.stats['found_live']}")
        self.log(f"人脸校验通过: {self.stats['face_passed']} | 人脸校验失败: {self.stats['face_failed']}")
        self.log(f"累计成功录制: {self.stats['recorded']}")
        self.log(f"并发录制任务: {len(self.recording_tasks)} | 等待队列: {len(self.waiting_list)}")
        self.log("=" * 60)

    async def run_forever(self):
        while True:
            try:
                await self.run_once()
                self.log(f"\n⏰ 休眠 {CHECK_INTERVAL//60} 分钟后重新检测分区")
                await asyncio.sleep(CHECK_INTERVAL)
            except KeyboardInterrupt:
                self.log("🛑 用户终止程序，退出循环")
                break

def main():
    # 程序启动先初始化全部数据表
    init_db()
    if len(sys.argv) < 2:
        print("使用方式：python record_category.py 类别名")
        print(f"支持类别列表: {list(CATEGORY_PARTITION.keys())}")
        return
    category_input = sys.argv[1]
    if category_input not in CATEGORY_PARTITION:
        print(f"错误：不存在类别「{category_input}」")
        print(f"合法类别: {list(CATEGORY_PARTITION.keys())}")
        return
    recorder = CategoryRecorder(category_input)
    asyncio.run(recorder.run_forever())

if __name__ == "__main__":
    main()