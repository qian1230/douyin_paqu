#!/usr/bin/env python3
"""
抖音直播自动录制脚本 - 九类别版（最稳定）
支持：知识、娱乐、电商、美食、情感、游戏、访谈、演讲、新闻
通过命令行指定要录制的类别，不是目标类别直接跳过
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

# ========== 九类别关键词库 ==========
CATEGORY_KEYWORDS = {
    '知识': [
        '知识', '科普', '教育', '学习', '教学', '课程', '课堂', '老师', '教授', '讲解',
        '知识分享', '干货', '培训', '讲座', '公开课', '读书', '阅读', '历史', '哲学',
        '心理学', '经济学', '编程', '代码', 'Python', 'Java', '技术', '科技', '科学'
    ],
    
    '娱乐': [
        '娱乐', '搞笑', '段子', '相声', '小品', '脱口秀', '才艺', '表演', '整活',
        '有趣', '幽默', '欢乐', '开心', '综艺', '真人秀', '模仿', 'cos', '变装',
        '娱乐直播', '主播', '网红'
    ],
    
    '电商': [
        '电商', '带货', '直播带货', '购物', '商品', '优惠', '促销', '秒杀', '限时',
        '福利', '好物', '推荐', '测评', '试用', '开箱', '种草', '店铺', '品牌',
        '旗舰店', '官方', '正品', '包邮', '特价', '折扣'
    ],
    
    '美食': [
        '美食', '吃播', '做饭', '烹饪', '料理', '菜谱', '烘焙', '甜品', '探店',
        '吃货', '美味', '好吃', '品尝', '餐厅', '小吃', '烧烤', '火锅', '日料',
        '西餐', '中餐', '面食', '甜点', '饮品', '咖啡', '茶', '下厨', '厨房'
    ],
    
    '情感': [
        '情感', '心理咨询', '树洞', '倾诉', '情感咨询', '恋爱', '婚姻', '家庭',
        '亲子', '关系', '相处', '沟通', '挽回', '分手', '复合', '情感故事',
        '人生感悟', '心灵鸡汤', '治愈', '陪伴'
    ],
    
    '游戏': [
        '游戏', '电竞', '王者荣耀', '王者', 'LOL', '英雄联盟', '吃鸡', '和平精英',
        '原神', 'DOTA', 'CF', 'CSGO', '永劫无间', '金铲铲', '云顶之弈', '炉石传说',
        '第五人格', '梦幻西游', '游戏解说', '游戏主播', '排位', '上分'
    ],
    
    '访谈': [
        '访谈', '对话', '采访', '问答', '对谈', '聊天', '座谈', '沙龙', '论坛',
        '对话节目', '名人访谈', '嘉宾', '主持人', '深度对话', '圆桌', '讨论'
    ],
    
    '演讲': [
        '演讲', '讲座', '分享会', '公开课', '演说', '致辞', '发言', '讲话',
        'TED', '演讲比赛', '口才', '表达', '沟通', '说服', '感染力', '舞台'
    ],
    
    '新闻': [
        '新闻', '资讯', '快讯', '报道', '记者', '现场', '直播', '突发', '最新',
        '时事', '热点', '要闻', '评论', '时评', '观察', '解读', '分析', '深度报道',
        '新闻联播', '新闻直播间', '新闻频道', '新闻现场'
    ]
}
# =================================

# ========== 配置区域 ==========
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

class NineCategoryRecorder:
    def __init__(self, target_categories):
        self.target_categories = target_categories
        self.recording_tasks = {}
        self.candidate_pool = []
        self.consecutive_empty = 0
        
        self.stats = {
            'checked': 0, 'skipped': 0, 'found_live': 0, 'recorded': 0,
            'face_passed': 0, 'face_failed': 0, 'failed': 0, 'fixed': 0,
            'pooled': 0, 'pool_used': 0, 'ban_detected': 0
        }
        
        # 创建目录
        VIDEO_SAVE_PATH.mkdir(parents=True, exist_ok=True)
        for cat in target_categories:
            (VIDEO_SAVE_PATH / cat).mkdir(parents=True, exist_ok=True)
        
        self.log("=" * 60)
        self.log("🚀 九类别录制脚本启动")
        self.log("=" * 60)
        self.log(f"目标类别: {', '.join(target_categories)}")
        self.log(f"最大录制: {MAX_RECORDING}")
        self.log("=" * 60)
    
    def log(self, msg, level="INFO"):
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] [{level}] {msg}")
    
    def classify_room(self, title, anchor_name):
        """判断直播间属于哪个类别，不是目标类别返回None"""
        text = f"{title} {anchor_name}".lower()
        
        for category in self.target_categories:
            keywords = CATEGORY_KEYWORDS.get(category, [])
            for keyword in keywords:
                if keyword.lower() in text:
                    return category
        return None
    
    async def crawl_live_rooms(self):
        """爬取直播间"""
        self.log("=" * 60)
        self.log("🔄 开始爬取")
        self.log("=" * 60)
        
        async with aiohttp.ClientSession() as session:
            scraper = DouyinScraper(session)
            rooms = await scraper.scrape_live_rooms(max_rooms=50)
        
        self.log(f"✅ 爬取完成，共获取 {len(rooms)} 个")
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
    
    def get_video_path(self, room, category):
        """生成保存路径"""
        now = datetime.now()
        date_str = now.strftime("%Y%m%d_%H%M%S")
        video_dir = VIDEO_SAVE_PATH / category / room.room_id / date_str
        video_dir.mkdir(parents=True, exist_ok=True)
        return video_dir / f"{date_str}.mp4"
    
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
    
    async def fix_video(self, video_path):
        """修复视频"""
        if not video_path.exists():
            return
        
        fixed_path = video_path.with_suffix('.tmp.mp4')
        cmd = ['ffmpeg', '-i', str(video_path), '-c', 'copy', '-movflags', '+faststart', '-y', str(fixed_path)]
        
        try:
            process = await asyncio.create_subprocess_exec(*cmd)
            await process.wait()
            if process.returncode == 0 and fixed_path.exists():
                fixed_path.replace(video_path)
                self.stats['fixed'] += 1
        except:
            pass
    
    async def start_recording(self, room, stream_info, category):
        """开始录制"""
        if len(self.recording_tasks) >= MAX_RECORDING:
            self.candidate_pool.append({
                'room': room, 'stream_info': stream_info, 'category': category
            })
            self.stats['pooled'] += 1
            return False
        
        video_path = self.get_video_path(room, category)
        cmd = [
            'ffmpeg', '-i', stream_info['stream_url'],
            '-t', str(RECORD_DURATION),
            '-c', 'copy', '-bsf:a', 'aac_adtstoasc', '-y',
            str(video_path)
        ]
        
        self.log(f"\n🎬 开始录制 [{category}]: {room.anchor_name}")
        
        try:
            process = await asyncio.create_subprocess_exec(*cmd)
            self.recording_tasks[room.room_id] = {
                'process': process, 'room': room,
                'video_path': video_path, 'start_time': datetime.now(),
                'category': category
            }
            self.stats['recorded'] += 1
            return True
        except Exception as e:
            self.log(f"启动失败: {e}", "ERROR")
            return False
    
    async def check_candidate_pool(self):
        """检查候选池"""
        if not self.candidate_pool:
            return
        
        need = MAX_RECORDING - len(self.recording_tasks)
        if need <= 0:
            return
        
        for _ in range(min(need, len(self.candidate_pool))):
            candidate = self.candidate_pool.pop(0)
            self.stats['pool_used'] += 1
            await self.start_recording(
                candidate['room'], candidate['stream_info'], candidate['category']
            )
    
    async def monitor_recordings(self):
        """监控录制任务"""
        finished = []
        for room_id, task in self.recording_tasks.items():
            if task['process'].returncode is not None:
                finished.append(room_id)
                if task['video_path'].exists():
                    duration = (datetime.now() - task['start_time']).total_seconds()
                    self.log(f"\n✅ 录制完成 [{task['category']}]: {task['room'].anchor_name} - {duration:.0f}秒")
                    self.log_recording(room_id, task['video_path'], duration)
                    await self.fix_video(task['video_path'])
                    await self.check_candidate_pool()
        
        for room_id in finished:
            del self.recording_tasks[room_id]
    
    async def run_once(self):
        """运行一次"""
        await self.monitor_recordings()
        rooms = await self.crawl_live_rooms()
        
        if not rooms:
            self.consecutive_empty += 1
            if self.consecutive_empty >= MAX_EMPTY_RESULTS:
                self.log(f"🚨 可能被封，等待30分钟")
                await asyncio.sleep(BAN_WAIT_TIME)
                self.consecutive_empty = 0
            return
        
        self.consecutive_empty = 0
        self.log("\n🔍 正在检测直播间...")
        
        for i, room in enumerate(rooms):
            await self.monitor_recordings()
            
            category = self.classify_room(room.title, room.anchor_name)
            if not category:
                self.stats['skipped'] += 1
                continue
            
            self.log(f"   [{category}] 检测 {i+1}/{len(rooms)}: {room.anchor_name}")
            await asyncio.sleep(random.uniform(1, TASK_DELAY))
            
            result = await self.check_room_live(room)
            if result['is_live']:
                self.stats['found_live'] += 1
                
                if FACE_DETECTION:
                    has_face = await self.detect_face(result['stream_url'])
                    if not has_face:
                        self.stats['face_failed'] += 1
                        continue
                    self.stats['face_passed'] += 1
                
                await self.start_recording(room, result, category)
        
        self.log("\n" + "=" * 60)
        self.log("📊 本轮统计")
        self.log("=" * 60)
        self.log(f"检查: {self.stats['checked']}")
        self.log(f"跳过: {self.stats['skipped']}")
        self.log(f"发现直播: {self.stats['found_live']}")
        self.log(f"人脸通过: {self.stats['face_passed']}")
        self.log(f"人脸失败: {self.stats['face_failed']}")
        self.log(f"成功录制: {self.stats['recorded']}")
        self.log(f"当前录制中: {len(self.recording_tasks)}")
        self.log("=" * 60)
    
    async def run_forever(self):
        """无限循环"""
        while True:
            try:
                await self.run_once()
                self.log(f"\n⏰ 等待 {CHECK_INTERVAL/60} 分钟")
                await asyncio.sleep(CHECK_INTERVAL)
            except KeyboardInterrupt:
                break

def main():
    if len(sys.argv) < 2:
        print("请指定要录制的类别，例如:")
        print("  python auto_record_nine.py 娱乐 知识 电商")
        print(f"支持的类别: {list(CATEGORY_KEYWORDS.keys())}")
        return
    
    target_categories = sys.argv[1:]
    invalid = [c for c in target_categories if c not in CATEGORY_KEYWORDS]
    if invalid:
        print(f"不支持的类别: {invalid}")
        return
    
    recorder = NineCategoryRecorder(target_categories)
    asyncio.run(recorder.run_forever())

if __name__ == "__main__":
    main()