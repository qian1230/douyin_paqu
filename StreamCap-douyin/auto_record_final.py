#!/usr/bin/env python3
"""
抖音直播自动录制脚本 - 自动补充版
永远保持6个在录，录完一个立即补下一个
完全隐藏FFmpeg输出，只显示自定义日志
"""

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

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.scraper.platforms.douyin_feed_scraper import DouyinScraper
from app.core.platforms.platform_handlers.douyin_worker import fetch_douyin_stream

# ========== 配置区域 ==========
TARGET_CATEGORIES = ['娱乐', '知识', '电商']  # 要录制的三个分区
MAX_RECORDING = 6  # 最多同时录制6个
RECORD_DURATION = 7200  # 单个视频最长2小时
CHECK_INTERVAL = 300  # 检测间隔5分钟
TASK_DELAY = 20  # 任务间延迟20秒
FACE_DETECTION = True  # 开启人脸检测
VIDEO_SAVE_PATH = Path("/mnt/disk022/dataset_w/zhibo-video/douyin")
DB_PATH = Path("streamcap.db")
MAX_EMPTY_RESULTS = 3
BAN_WAIT_TIME = 1800
# =============================

class AutoRecorder:
    def __init__(self):
        self.recording_tasks = {}  # 正在录制的任务
        self.waiting_list = []      # 等待队列（已检测通过但未录制的）
        self.consecutive_empty = 0
        
        self.stats = {
            'checked': 0,
            'found_live': 0,
            'recorded': 0,
            'face_passed': 0,
            'face_failed': 0,
            'failed': 0,
            'fixed': 0,
            'ban_detected': 0
        }
        
        # 创建目录
        VIDEO_SAVE_PATH.mkdir(parents=True, exist_ok=True)
        for cat in TARGET_CATEGORIES:
            (VIDEO_SAVE_PATH / cat).mkdir(parents=True, exist_ok=True)
        
        self.log("=" * 60)
        self.log("🚀 抖音自动录制服务启动（自动补充版）")
        self.log("=" * 60)
        self.log(f"目标分区: {', '.join(TARGET_CATEGORIES)}")
        self.log(f"最大录制: {MAX_RECORDING}")
        self.log("=" * 60)
    
    def log(self, msg, level="INFO", end="\n"):
        """统一的日志输出"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] [{level}] {msg}", end=end)
    
    def log_recording(self, room_id, file_path, duration, status="completed"):
        """记录录制日志"""
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
                datetime.now() - timedelta(seconds=duration),
                datetime.now(),
                duration,
                str(file_path),
                status
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            self.log(f"数据库写入失败: {e}", "ERROR")
    
    async def detect_face(self, stream_url):
        """人脸检测"""
        if not FACE_DETECTION:
            return True
        
        try:
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                return False
            
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            
            faces_detected = 0
            for _ in range(8):
                ret, frame = cap.read()
                if not ret:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(50,50))
                if len(faces) > 0:
                    faces_detected += 1
            
            cap.release()
            return faces_detected >= 2
        except:
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
        return rooms
    
    async def check_room_live(self, room):
        """检测是否在直播"""
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
            return {'is_live': False}
        except Exception as e:
            self.log(f"检测出错 {room.room_id}: {e}", "ERROR")
            return {'is_live': False}
    
    def get_video_path(self, room):
        """生成保存路径"""
        now = datetime.now()
        date_str = now.strftime("%Y%m%d_%H%M%S")
        video_dir = VIDEO_SAVE_PATH / room.category / room.room_id / date_str
        video_dir.mkdir(parents=True, exist_ok=True)
        return video_dir / f"{date_str}.mp4"
    
    async def fix_video(self, video_path):
        """修复视频"""
        if not video_path.exists():
            return
        
        fixed_path = video_path.with_suffix('.tmp.mp4')
        cmd = ['ffmpeg', '-i', str(video_path), '-c', 'copy', '-movflags', '+faststart', '-y', str(fixed_path)]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await process.wait()
            if process.returncode == 0 and fixed_path.exists():
                fixed_path.replace(video_path)
                self.stats['fixed'] += 1
        except:
            pass
    
    async def start_recording(self, room, stream_info):
        """开始录制 - 完全隐藏FFmpeg输出"""
        if len(self.recording_tasks) >= MAX_RECORDING:
            # 满了就进等待队列
            self.waiting_list.append({
                'room': room,
                'stream_info': stream_info,
                'detected_time': datetime.now()
            })
            self.log(f"   ⏳ 已达上限，加入等待队列 (队列长度: {len(self.waiting_list)})")
            return False
        
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
        
        # 显示录制信息
        self.log(f"\n🎬 开始录制: {room.anchor_name}")
        self.log(f"   分区: {room.category}")
        self.log(f"   标题: {stream_info['title']}")
        self.log(f"   保存: {video_path}")
        
        try:
            # 将FFmpeg输出重定向到黑洞，完全不显示
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            self.recording_tasks[room.room_id] = {
                'process': process,
                'room': room,
                'video_path': video_path,
                'start_time': datetime.now()
            }
            self.stats['recorded'] += 1
            
            # 显示当前录制状态
            self.log(f"   ✅ 录制中，当前: {len(self.recording_tasks)}/{MAX_RECORDING}, 队列: {len(self.waiting_list)}")
            return True
            
        except Exception as e:
            self.log(f"❌ 启动录制失败: {e}", "ERROR")
            return False
    
    async def check_waiting_list(self):
        """检查等待队列，有空位就补上"""
        if not self.waiting_list:
            return
        
        while self.waiting_list and len(self.recording_tasks) < MAX_RECORDING:
            next_one = self.waiting_list.pop(0)
            self.log(f"\n🔄 从等待队列取出一个，队列剩余: {len(self.waiting_list)}")
            await self.start_recording(next_one['room'], next_one['stream_info'])
    
    async def monitor_recordings(self):
        """监控录制任务"""
        finished = []
        for room_id, task in self.recording_tasks.items():
            if task['process'].returncode is not None:
                finished.append(room_id)
                if task['video_path'].exists():
                    duration = (datetime.now() - task['start_time']).total_seconds()
                    self.log(f"\n✅ 录制完成: {task['room'].anchor_name} - {duration:.0f}秒")
                    self.log(f"   类别: {task['room'].category}")
                    self.log(f"   文件: {task['video_path']}")
                    
                    # 记录到数据库
                    self.log_recording(room_id, task['video_path'], duration)
                    
                    # 修复视频（已隐藏输出）
                    await self.fix_video(task['video_path'])
                    
                    # 有录制完成，立即检查等待队列
                    await self.check_waiting_list()
        
        for room_id in finished:
            del self.recording_tasks[room_id]
    
    async def run_once(self):
        """运行一次"""
        # 先监控现有任务
        await self.monitor_recordings()
        
        # 爬取新直播间
        rooms = await self.crawl_live_rooms()
        if not rooms:
            self.log("❌ 没有获取到任何直播间")
            self.consecutive_empty += 1
            if self.consecutive_empty >= MAX_EMPTY_RESULTS:
                self.log(f"🚨 可能被封，等待30分钟")
                await asyncio.sleep(BAN_WAIT_TIME)
                self.consecutive_empty = 0
            return
        
        self.consecutive_empty = 0
        self.log(f"\n🔍 开始检测直播间，当前录制: {len(self.recording_tasks)}/{MAX_RECORDING}")
        
        for i, room in enumerate(rooms):
            # 每检测一个前先检查现有任务
            await self.monitor_recordings()
            
            self.stats['checked'] += 1
            self.log(f"   检测 {i+1}/{len(rooms)}: {room.anchor_name}")
            
            await asyncio.sleep(random.uniform(1, TASK_DELAY))
            
            result = await self.check_room_live(room)
            if result['is_live']:
                self.log(f"   🔴 直播中!")
                self.stats['found_live'] += 1
                
                if FACE_DETECTION:
                    has_face = await self.detect_face(result['stream_url'])
                    if not has_face:
                        self.stats['face_failed'] += 1
                        self.log(f"   ❌ 人脸检测不通过")
                        continue
                    self.stats['face_passed'] += 1
                    self.log(f"   ✅ 人脸检测通过")
                
                # 尝试录制，如果满了会自动进等待队列
                await self.start_recording(room, result)
            else:
                self.log(f"   ⚪ 未开播")
        
        # 打印统计
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
        self.log(f"检测到封禁: {self.stats['ban_detected']}")
        self.log(f"当前录制中: {len(self.recording_tasks)}")
        self.log(f"等待队列: {len(self.waiting_list)}")
        self.log("=" * 60)
    
    async def run_forever(self):
        """无限循环"""
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
    recorder = AutoRecorder()
    await recorder.run_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 程序已停止")