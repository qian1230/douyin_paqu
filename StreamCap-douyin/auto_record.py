
#!/usr/bin/env python3
"""
抖音直播自动录制脚本 - 完整功能版
专为唇语识别任务设计，包含人脸检测、去重、时长控制等功能
目标分区：娱乐、知识、电商
人脸检测：检测前8帧，连续3帧中至少2帧有人脸才通过
"""

import asyncio
import aiohttp
import os
import sys
import subprocess
import cv2
import sqlite3
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.scraper.platforms.douyin_feed_scraper import DouyinScraper
from app.core.platforms.platform_handlers.douyin_worker import fetch_douyin_stream

# ========== 配置区域 ==========
TARGET_CATEGORIES = ['娱乐', '知识', '电商']  # 要录制的三个分区
MAX_RECORDING = 6  # 最多同时录制6个
MAX_MONITORING = 4  # 最多监控4个
TOTAL_LIMIT = 10  # 总数限制（录制+监控）
RECORD_DURATION = 7200  # 单个视频最长2小时（7200秒）
CHECK_INTERVAL = 300  # 检测间隔5分钟
TASK_DELAY = 20  # 任务间延迟20秒
SYNC_INTERVAL = 900  # 同步间隔15分钟
SEGMENT_DURATION = 3600  # 视频分段1小时
FACE_DETECTION = True  # 开启人脸检测
MIN_FACE_CONFIDENCE = 0.5  # 人脸检测置信度
VIDEO_SAVE_PATH = Path("/mnt/disk022/dataset_w/zhibo-video/douyin")  # 视频保存根目录
DB_PATH = Path("streamcap.db")  # 数据库路径
# =============================

class FullFeatureRecorder:
    def __init__(self):
        # 录制状态
        self.recording_tasks = {}  # 正在录制的任务
        self.monitoring_tasks = {}  # 正在监控的任务
        self.recorded_rooms = set()  # 已录制的房间（用于去重）
        
        # 统计信息
        self.stats = {
            'checked': 0,
            'found_live': 0,
            'recorded': 0,
            'face_passed': 0,
            'face_failed': 0,
            'failed': 0,
            'fixed': 0
        }
        
        # 创建目录
        VIDEO_SAVE_PATH.mkdir(parents=True, exist_ok=True)
        for cat in TARGET_CATEGORIES:
            (VIDEO_SAVE_PATH / cat).mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self.init_database()
        
        self.log("=" * 60)
        self.log("🚀 抖音自动录制服务启动（完整功能版）")
        self.log("=" * 60)
        self.log(f"目标分区: {', '.join(TARGET_CATEGORIES)}")
        self.log(f"最大录制: {MAX_RECORDING}, 最大监控: {MAX_MONITORING}")
        self.log(f"录制时长: {RECORD_DURATION/3600}小时")
        self.log(f"检测间隔: {CHECK_INTERVAL/60}分钟")
        self.log(f"人脸检测: {'开启' if FACE_DETECTION else '关闭'}")
        self.log(f"人脸策略: 前8帧中连续3帧至少2帧通过")
        self.log(f"保存路径: {VIDEO_SAVE_PATH}")
        self.log("=" * 60)
    
    def log(self, msg, level="INFO", end="\n"):
        """统一的日志输出"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] [{level}] {msg}", end=end)
    
    def init_database(self):
        """初始化SQLite数据库（用于去重和记录）"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # 创建爬取记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scraped_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                room_id TEXT,
                category TEXT,
                anchor_name TEXT,
                scraped_at TIMESTAMP,
                status TEXT,
                face_detected BOOLEAN,
                UNIQUE(platform, room_id)
            )
        ''')
        
        # 创建录制日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recording_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT,
                platform TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration INTEGER,
                file_path TEXT,
                status TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        self.log("✅ 数据库初始化完成")
    
    def check_duplicate(self, platform, room_id):
        """检查是否重复录制"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM scraped_rooms WHERE platform=? AND room_id=?",
            (platform, room_id)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            self.log(f"   ⚠️ 房间 {room_id} 已存在，状态: {result[0]}")
            return True
        return False
    
    def save_to_database(self, room, status="pending", face_detected=None):
        """保存房间信息到数据库"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO scraped_rooms 
                (platform, room_id, category, anchor_name, scraped_at, status, face_detected)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                "douyin",
                room.room_id,
                room.category,
                room.anchor_name,
                datetime.now(),
                status,
                face_detected
            ))
            conn.commit()
        except Exception as e:
            self.log(f"数据库写入失败: {e}", "ERROR")
        finally:
            conn.close()
    
    def log_recording(self, room_id, file_path, duration, status="completed"):
        """记录录制日志"""
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO recording_logs 
                (room_id, platform, start_time, end_time, duration, file_path, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                room_id,
                "douyin",
                datetime.now() - timedelta(seconds=duration),
                datetime.now(),
                duration,
                str(file_path),
                status
            ))
            conn.commit()
        except Exception as e:
            self.log(f"录制日志写入失败: {e}", "ERROR")
        finally:
            conn.close()
    
    async def detect_face(self, stream_url):
        """检测直播流前8帧，连续3帧中至少2帧有人脸"""
        if not FACE_DETECTION:
            return True
        
        self.log(f"   🔍 检测人脸 (8帧内连续3帧至少2帧)...")
        
        try:
            # 打开视频流
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                self.log(f"   ❌ 无法打开视频流")
                return False
            
            # 加载人脸检测器
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            
            frames_checked = 0
            max_frames = 8
            face_results = []  # 存储每帧的检测结果
            frame_details = []  # 存储每帧的详细信息
            
            while frames_checked < max_frames:
                ret, frame = cap.read()
                if not ret:
                    self.log(f"   ⚠️ 第{frames_checked+1}帧读取失败")
                    break
                
                # 转换为灰度图
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # 检测人脸
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(50, 50)  # 要求稍大的人脸，适合唇语识别
                )
                
                has_face = len(faces) > 0
                face_results.append(has_face)
                
                if has_face:
                    face_count = len(faces)
                    frame_details.append(f"第{frames_checked+1}帧: ✅ 检测到{face_count}张人脸")
                    # 找出最大的人脸
                    max_face_size = max([w*h for (x,y,w,h) in faces]) if face_count > 0 else 0
                    frame_details[-1] += f" (最大{int(max_face_size**0.5)}px)"
                else:
                    frame_details.append(f"第{frames_checked+1}帧: ❌ 无人脸")
                
                frames_checked += 1
                
                # 实时显示进度（可选）
                if frames_checked % 2 == 0:
                    self.log(f"     {' '.join(frame_details[-2:])}")
            
            cap.release()
            
            # 显示所有帧的结果
            self.log(f"     检测结果: {' '.join(['✅' if r else '❌' for r in face_results])}")
            
            # 判断是否通过（连续3帧中至少2帧有人脸）
            passed = False
            if len(face_results) >= 3:
                for i in range(len(face_results) - 2):
                    three_frames = face_results[i:i+3]
                    if sum(three_frames) >= 2:
                        passed = True
                        self.log(f"     第{i+1}-{i+3}帧: {sum(three_frames)}/3有人脸 ✅ 通过")
                        break
            
            if passed:
                self.stats['face_passed'] += 1
                self.log(f"   ✅ 人脸检测通过!")
                return True
            else:
                self.stats['face_failed'] += 1
                if len(face_results) < 3:
                    self.log(f"   ❌ 检测帧数不足({len(face_results)}帧)，不通过")
                else:
                    self.log(f"   ❌ 无连续3帧满足至少2帧有人脸，不通过")
                return False
            
        except Exception as e:
            self.log(f"   ❌ 检测出错: {e}")
            return False
    
    async def crawl_live_rooms(self):
        """爬取所有目标分区的直播间"""
        self.log("=" * 60)
        self.log("🔄 开始爬取直播间")
        self.log("=" * 60)
        
        async with aiohttp.ClientSession() as session:
            scraper = DouyinScraper(session)
            rooms = await scraper.scrape_live_rooms(max_rooms=18)  # 每个分区6个
        
        self.log(f"✅ 爬取完成，共获取 {len(rooms)} 个直播间")
        
        # 按分区统计
        categories = {}
        for room in rooms:
            cat = room.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(room)
        
        for cat, room_list in categories.items():
            self.log(f"   {cat}: {len(room_list)}个")
        
        return rooms
    
    async def check_room_live(self, room):
        """检测单个直播间是否在直播"""
        try:
            result = await fetch_douyin_stream(
                url=room.room_url,
                proxy=None,
                cookies=os.getenv("DOUYIN_COOKIE"),
                quality="ld"
            )
            
            if result and result.get('is_live'):
                return {
                    'is_live': True,
                    'anchor': result.get('anchor_name'),
                    'title': result.get('title'),
                    'stream_url': result.get('record_url'),
                    'room': room
                }
            else:
                return {'is_live': False}
        except Exception as e:
            self.log(f"检测出错 {room.room_id}: {e}", "ERROR")
            return {'is_live': False}
    
    def get_video_path(self, room, segment_index=0):
        """生成视频保存路径（支持分段）"""
        now = datetime.now()
        date_str = now.strftime("%Y%m%d_%H%M%S")
        
        # 格式: 平台/类别/直播间ID/年月日时分秒/年月日时分秒_分段.mp4
        video_dir = VIDEO_SAVE_PATH / room.category / room.room_id / date_str
        video_dir.mkdir(parents=True, exist_ok=True)
        
        if segment_index > 0:
            return video_dir / f"{date_str}_{segment_index:03d}.mp4"
        else:
            return video_dir / f"{date_str}.mp4"
    
    async def fix_video(self, video_path):
        """修复视频文件"""
        if not video_path.exists():
            return video_path
        
        self.log(f"   🔧 正在修复视频...", end="")
        
        fixed_path = video_path.with_suffix('.tmp.mp4')
        fix_cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-c', 'copy',
            '-movflags', '+faststart',
            '-y',
            str(fixed_path)
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *fix_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.wait()
            
            if process.returncode == 0 and fixed_path.exists():
                fixed_path.replace(video_path)
                self.stats['fixed'] += 1
                self.log(f" ✅ 修复完成")
                return video_path
            else:
                if fixed_path.exists():
                    fixed_path.unlink()
                self.log(f" ⚠️ 修复失败")
                return video_path
                
        except Exception as e:
            self.log(f" ❌ 修复出错: {e}")
            if fixed_path.exists():
                fixed_path.unlink()
            return video_path
    
    async def start_recording(self, room, stream_info):
        """开始录制（包含人脸检测和去重检查）"""
        # 1. 检查是否已达最大并发
        if len(self.recording_tasks) >= MAX_RECORDING:
            self.log(f"达到最大并发数 {MAX_RECORDING}，跳过 {room.room_id}")
            return False
        
        # 2. 去重检查
        if self.check_duplicate("douyin", room.room_id):
            self.log(f"   ⚠️ 房间 {room.room_id} 已录制过，跳过")
            return False
        
        # 3. 人脸检测
        if FACE_DETECTION:
            has_face = await self.detect_face(stream_info['stream_url'])
            if not has_face:
                self.save_to_database(room, status="skipped", face_detected=False)
                self.log(f"   ❌ 人脸检测不通过，跳过录制")
                return False
            else:
                self.save_to_database(room, status="recording", face_detected=True)
        
        # 4. 开始录制
        video_path = self.get_video_path(room)
        
        cmd = [
            'ffmpeg',
            '-i', stream_info['stream_url'],
            '-t', str(RECORD_DURATION),
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-y',
            str(video_path)
        ]
        
        self.log(f"\n🎬 开始录制: {room.anchor_name}")
        self.log(f"   分区: {room.category}")
        self.log(f"   标题: {stream_info['title']}")
        self.log(f"   保存: {video_path}")
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.recording_tasks[room.room_id] = {
                'process': process,
                'room': room,
                'video_path': video_path,
                'start_time': datetime.now()
            }
            
            self.stats['recorded'] += 1
            return True
            
        except Exception as e:
            self.log(f"启动录制失败: {e}", "ERROR")
            self.stats['failed'] += 1
            self.save_to_database(room, status="failed")
            return False
    
    async def monitor_recordings(self):
        """监控正在录制的任务"""
        finished = []
        for room_id, task in self.recording_tasks.items():
            if task['process'].returncode is not None:
                finished.append(room_id)
                
                if task['video_path'].exists():
                    duration = (datetime.now() - task['start_time']).total_seconds()
                    size = task['video_path'].stat().st_size / 1024 / 1024
                    self.log(f"\n✅ 录制完成: {task['room'].anchor_name} - {duration:.0f}秒 - {size:.1f}MB")
                    
                    # 记录日志
                    self.log_recording(
                        room_id,
                        task['video_path'],
                        duration
                    )
                    
                    # 修复视频
                    await self.fix_video(task['video_path'])
                else:
                    self.log(f"\n❌ 录制失败: {task['room'].anchor_name}")
                    self.log_recording(room_id, None, 0, status="failed")
        
        for room_id in finished:
            del self.recording_tasks[room_id]
    
    async def run_once(self):
        """运行一次完整的爬取+录制流程"""
        # 1. 爬取直播间
        rooms = await self.crawl_live_rooms()
        
        if not rooms:
            self.log("❌ 没有获取到任何直播间")
            return
        
        # 2. 检测在线状态
        self.log("\n🔍 正在检测直播间在线状态...")
        
        for i, room in enumerate(rooms):
            self.stats['checked'] += 1
            
            # 检查总数限制
            if len(self.recording_tasks) + len(self.monitoring_tasks) >= TOTAL_LIMIT:
                self.log(f"达到总数限制 {TOTAL_LIMIT}，停止检测")
                break
            
            self.log(f"   检测 {i+1}/{len(rooms)}: {room.room_id} - {room.anchor_name}")
            
            # 任务间延迟
            await asyncio.sleep(random.uniform(1, TASK_DELAY))
            
            result = await self.check_room_live(room)
            
            if result['is_live']:
                self.log(f"   🔴 直播中!")
                self.stats['found_live'] += 1
                
                # 检查是否已达录制上限
                if len(self.recording_tasks) >= MAX_RECORDING:
                    self.log(f"   ⚠️ 已达录制上限，转为监控")
                    room.monitor_start = datetime.now()
                    self.monitoring_tasks[room.room_id] = room
                else:
                    await self.start_recording(room, result)
            else:
                self.log(f"   ⚪ 未开播")
        
        # 3. 清理长时间未开播的监控任务
        current_time = datetime.now()
        expired_monitoring = []
        for room_id, room in self.monitoring_tasks.items():
            # 如果监控超过24小时，清理
            if hasattr(room, 'monitor_start') and (current_time - room.monitor_start) > timedelta(hours=24):
                expired_monitoring.append(room_id)
        
        for room_id in expired_monitoring:
            self.log(f"清理过期监控: {room_id}")
            del self.monitoring_tasks[room_id]
        
        # 4. 等待录制完成
        if self.recording_tasks:
            self.log(f"\n⏳ 等待 {len(self.recording_tasks)} 个录制任务完成...")
            await self.monitor_recordings()
        
        # 5. 打印统计
        self.log("\n" + "=" * 60)
        self.log("📊 本轮统计")
        self.log("=" * 60)
        self.log(f"检查直播间: {self.stats['checked']}")
        self.log(f"发现直播: {self.stats['found_live']}")
        self.log(f"人脸通过: {self.stats['face_passed']}")
        self.log(f"人脸失败: {self.stats['face_failed']}")
        self.log(f"成功录制: {self.stats['recorded']}")
        self.log(f"录制失败: {self.stats['failed']}")
        self.log(f"修复视频: {self.stats['fixed']}")
        self.log("=" * 60)
    
    async def run_forever(self):
        """无限循环运行"""
        while True:
            try:
                await self.run_once()
                self.log(f"\n⏰ 等待 {CHECK_INTERVAL/60} 分钟后下一次检测...")
                await asyncio.sleep(CHECK_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log(f"执行出错: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(60)

async def main():
    recorder = FullFeatureRecorder()
    await recorder.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 程序已停止")
