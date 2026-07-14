import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

# 常见分区ID范围（根据经验）
POSSIBLE_IDS = [
    # 已知有效的
    201, 202, 203, 204, 205, 206, 207, 208, 209, 210,
    211, 212, 213, 214, 215, 216, 217, 218, 219, 220,
    # 扩展范围
    221, 222, 223, 224, 225, 226, 227, 228, 229, 230,
    231, 232, 233, 234, 235, 236, 237, 238, 239, 240,
    241, 242, 243, 244, 245, 246, 247, 248, 249, 250,
    251, 252, 253, 254, 255, 256, 257, 258, 259, 260,
    261, 262, 263, 264, 265, 266, 267, 268, 269, 270,
    271, 272, 273, 274, 275, 276, 277, 278, 279, 280,
    281, 282, 283, 284, 285, 286, 287, 288, 289, 290,
    291, 292, 293, 294, 295, 296, 297, 298, 299, 300,
]

# 已知的类别名称（供参考）
CATEGORY_NAMES = {
    201: "游戏", 202: "娱乐", 203: "知识", 204: "美食", 205: "体育",
    206: "音乐", 207: "舞蹈", 208: "情感", 209: "访谈", 210: "电商",
    211: "演讲", 212: "新闻", 213: "汽车", 214: "科技", 215: "亲子",
    216: "宠物", 217: "时尚", 218: "美妆", 219: "健身", 220: "旅行",
}

async def test_partition(session, pid):
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
        async with session.get(url, params=params, headers=headers, timeout=5) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if not isinstance(data, dict):
                return None
            inner = data.get("data")
            if not isinstance(inner, dict):
                return None
            items = inner.get("data", [])
            return len(items) if isinstance(items, list) else None
    except:
        return None

async def main():
    print("=" * 60)
    print("🔍 扫描可用分区ID")
    print("=" * 60)
    
    results = []
    async with aiohttp.ClientSession() as session:
        for pid in POSSIBLE_IDS:
            count = await test_partition(session, pid)
            if count is not None and count > 0:
                name = CATEGORY_NAMES.get(pid, f"未知{pid}")
                results.append((pid, name, count))
                print(f"✅ 分区 {pid:3d} | {name:10s} | {count:2d} 个直播间")
            
            if pid % 10 == 0:
                print(f"进度: {pid}/300")
            
            await asyncio.sleep(0.2)
    
    print("\n" + "=" * 60)
    print("📊 找到的有效分区:")
    print("-" * 40)
    for pid, name, count in sorted(results):
        print(f"  {pid:3d} | {name:10s} | {count:2d} 个直播间")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
