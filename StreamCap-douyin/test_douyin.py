#!/usr/bin/env python3
"""测试抖音爬虫和 streamget 库是否能正常工作"""
import asyncio
import os
import sys
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.scraper.platforms.douyin_feed_scraper import DouyinScraper
from app.core.platforms.platform_handlers.handlers import DouyinHandler
from app.core.platforms.platform_handlers.douyin_worker import fetch_douyin_stream


async def test_scraper():
    """测试爬虫是否能正常获取直播间列表"""
    print("=" * 60)
    print("测试1: 抖音爬虫 (scraper)")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        scraper = DouyinScraper(session)
        try:
            rooms = await scraper.scrape_live_rooms(max_rooms=5)
            print(f"✅ 爬虫成功获取 {len(rooms)} 个直播间")
            if rooms:
                print(f"   示例房间1: {rooms[0].room_id} - {rooms[0].anchor_name}")
                if len(rooms) > 1:
                    print(f"   示例房间2: {rooms[1].room_id} - {rooms[1].anchor_name}")
                return rooms[0].room_id if rooms else None
            else:
                print("   ⚠️  爬虫返回空列表")
                return None
        except Exception as e:
            print(f"❌ 爬虫失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None


async def test_streamget_direct(room_id: str):
    """直接测试 streamget 库（不通过子进程）"""
    print("\n" + "=" * 60)
    print("测试2: streamget 库（直接调用）")
    print("=" * 60)
    
    if not room_id:
        print("⚠️  跳过测试：没有可用的房间ID")
        return
    
    url = f"https://live.douyin.com/{room_id}"
    cookie = os.getenv("DOUYIN_COOKIE", "")
    
    try:
        result = await fetch_douyin_stream(
            url=url,
            proxy=None,
            cookies=cookie if cookie else None,
            quality=None
        )
        print(f"✅ streamget 直接调用成功")
        print(f"   房间ID: {room_id}")
        print(f"   是否开播: {result.get('is_live')}")
        print(f"   主播名: {result.get('anchor_name')}")
        print(f"   标题: {result.get('title')}")
        return True
    except Exception as e:
        print(f"❌ streamget 直接调用失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_streamget_handler(room_id: str):
    """测试通过 DouyinHandler（子进程方式）"""
    print("\n" + "=" * 60)
    print("测试3: DouyinHandler（子进程方式）")
    print("=" * 60)
    
    if not room_id:
        print("⚠️  跳过测试：没有可用的房间ID")
        return
    
    url = f"https://live.douyin.com/{room_id}"
    cookie = os.getenv("DOUYIN_COOKIE", "")
    
    handler = DouyinHandler(
        proxy=None,
        cookies=cookie if cookie else None,
        record_quality=None
    )
    
    try:
        stream_data = await handler.get_stream_info(url)
        print(f"✅ DouyinHandler 成功")
        print(f"   房间ID: {room_id}")
        print(f"   是否开播: {stream_data.is_live}")
        print(f"   主播名: {stream_data.anchor_name}")
        print(f"   标题: {stream_data.title}")
        print(f"   有FLV: {bool(stream_data.flv_url)}")
        print(f"   有M3U8: {bool(stream_data.m3u8_url)}")
        return True
    except Exception as e:
        print(f"❌ DouyinHandler 失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print(f"\n开始测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"DOUYIN_COOKIE 环境变量: {'已设置' if os.getenv('DOUYIN_COOKIE') else '未设置'}")
    
    # 测试1: 爬虫
    room_id = await test_scraper()
    
    # 测试2: streamget 直接调用
    await test_streamget_direct(room_id)
    
    # 测试3: DouyinHandler（子进程）
    await test_streamget_handler(room_id)
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

