import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def check_partition(pid, name):
    url = "https://live.douyin.com/webcast/web/partition/detail/room/v2/"
    params = {
        "aid": "6383",
        "app_name": "douyin_web",
        "live_id": "1",
        "device_platform": "web",
        "count": "5",
        "offset": "0",
        "partition": str(pid),
        "partition_type": "4",
    }
    headers = {"Cookie": os.getenv("DOUYIN_COOKIE", "")}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    print(f"❌ {name}({pid}): HTTP {resp.status}")
                    return
                
                data = await resp.json()
                inner = data.get("data", {})
                items = inner.get("data", [])
                
                print(f"\n✅ {name}({pid}): {len(items)} 个直播间")
                for i, item in enumerate(items[:3]):
                    room = item.get("room", {})
                    title = room.get("title", "无标题")
                    owner = item.get("owner", {})
                    anchor = owner.get("nickname", "未知")
                    print(f"   {i+1}. {title[:50]}... - {anchor}")
    except Exception as e:
        print(f"❌ {name}({pid}): {e}")

async def main():
    partitions = [
        (274, "分区274"),
        (280, "分区280"),
        (293, "分区293"),
    ]
    
    for pid, name in partitions:
        await check_partition(pid, name)
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
