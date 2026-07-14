import asyncio
import aiohttp
import os
from dotenv import load_dotenv
from app.core.scraper.platforms.douyin_feed_scraper import DouyinScraper

load_dotenv()

async def test():
    async with aiohttp.ClientSession() as session:
        scraper = DouyinScraper(session)
        rooms = await scraper.scrape_live_rooms(max_rooms=18)  # 每个分区3个
        
        print(f"\n总共获取到 {len(rooms)} 个直播间")
        
        # 按分区统计
        partitions = {}
        for room in rooms:
            cat = room.category
            if cat not in partitions:
                partitions[cat] = []
            partitions[cat].append(room)
        
        print("\n各分区数量分布：")
        for cat, rooms_list in partitions.items():
            print(f"  {cat}: {len(rooms_list)}个")
        
        print("\n示例直播间：")
        for i, room in enumerate(rooms[:10]):
            print(f"  {i+1}. [{room.category}] {room.title[:40]}...")

if __name__ == "__main__":
    asyncio.run(test())
