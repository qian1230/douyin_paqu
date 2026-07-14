#!/usr/bin/env python3
"""
统计指定分区（电商、娱乐、知识）的视频总时长
"""

import os
import subprocess
from pathlib import Path
from datetime import timedelta

# 视频保存根目录
VIDEO_ROOT = Path("/mnt/disk022/dataset_w/zhibo-video/douyin")

# 要统计的分区
TARGET_CATEGORIES = ['电商', '娱乐', '知识']

def get_video_duration(video_path):
    """用ffprobe获取视频时长（秒）"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except:
        return 0

def format_time(seconds):
    """将秒数格式化为 时:分:秒"""
    return str(timedelta(seconds=int(seconds)))

def main():
    print("=" * 60)
    print("📊 抖音录制视频统计（指定分区）")
    print("=" * 60)
    
    if not VIDEO_ROOT.exists():
        print(f"❌ 目录不存在: {VIDEO_ROOT}")
        return
    
    total_seconds = 0
    video_count = 0
    category_stats = {}
    
    # 只遍历目标分区
    for category in TARGET_CATEGORIES:
        category_path = VIDEO_ROOT / category
        if not category_path.exists():
            print(f"⚠️ 分区不存在: {category}")
            continue
        
        category_seconds = 0
        category_count = 0
        
        print(f"\n📁 分区: {category}")
        print("-" * 40)
        
        # 遍历所有直播间
        for room_dir in category_path.iterdir():
            if not room_dir.is_dir():
                continue
            
            # 遍历该直播间下的所有录制时间目录
            for date_dir in room_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                
                # 遍历该时间下的所有视频文件
                for video_file in date_dir.glob("*.mp4"):
                    duration = get_video_duration(video_file)
                    if duration > 0:
                        total_seconds += duration
                        category_seconds += duration
                        video_count += 1
                        category_count += 1
        
        category_stats[category] = {
            'count': category_count,
            'seconds': category_seconds,
            'hours': category_seconds / 3600
        }
        
        if category_count > 0:
            print(f"   视频数: {category_count}")
            print(f"   总时长: {format_time(category_seconds)} ({category_seconds/3600:.2f}小时)")
    
    # 汇总统计
    print("\n" + "=" * 60)
    print("📈 汇总统计（电商+娱乐+知识）")
    print("=" * 60)
    print(f"总视频数: {video_count}")
    print(f"总时长: {format_time(total_seconds)}")
    print(f"        ({total_seconds/3600:.2f}小时)")
    print(f"        ({total_seconds/86400:.2f}天)")
    
    if video_count > 0:
        avg_duration = total_seconds / video_count
        print(f"平均时长: {format_time(avg_duration)}")

if __name__ == "__main__":
    main()
