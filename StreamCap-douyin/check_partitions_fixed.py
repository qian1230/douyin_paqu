import asyncio
import aiohttp
import os
import json
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": os.getenv("DOUYIN_COOKIE", ""),
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    print(f"❌ {name}({pid}): HTTP {resp.status}")
                    return
                
                text = await resp.text()
                try:
                    data = json.loads(text)
                except:
                    print(f"❌ {name}({pid}): JSON解析失败")
                    return
                
                # 安全判断
                if not isinstance(data, dict):
                    print(f"❌ {name}({pid}): 返回数据不是字典")
                    return
                
                # 检查状态码
                if data.get("status_code") != 0:
                    print(f"❌ {name}({pid}): 状态码错误 {data.get('status_code')}")
                    return
                
                inner = data.get("data")
                if not isinstance(inner, dict):
                    print(f"❌ {name}({pid}): data字段不是字典")
                    return
                
                items = inner.get("data", [])
                if not isinstance(items, list):
                    print(f"❌ {name}({pid}): data.data不是列表")
                    return
                
                if not items:
                    print(f"⚠️ {name}({pid}): 直播间列表为空")
                    return
                
                print(f"\n✅ {name}({pid}): 找到 {len(items)} 个直播间")
                for i, item in enumerate(items[:3]):
                    if not isinstance(item, dict):
                        continue
                    room = item.get("room", {})
                    if not isinstance(room, dict):
                        continue
                    title = room.get("title", "无标题")
                    owner = item.get("owner", {})
                    anchor = owner.get("nickname", "未知")
                    print(f"   {i+1}. {title[:50]}... - {anchor}")
                    
    except asyncio.TimeoutError:
        print(f"❌ {name}({pid}): 请求超时")
    except Exception as e:
        print(f"❌ {name}({pid}): 错误 - {type(e).__name__}: {e}")

async def main():
    print("=" * 60)
    print("🔍 检查新发现的分区")
    print("=" * 60)
    
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
