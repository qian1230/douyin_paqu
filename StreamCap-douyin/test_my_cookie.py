import asyncio
import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.platforms.platform_handlers.handlers import DouyinHandler

async def test_cookie():
    print("=" * 60)
    print("抖音 Cookie 有效性测试")
    print("=" * 60)
    
    # 获取Cookie
    cookie = os.getenv("DOUYIN_COOKIE")
    if not cookie:
        print("❌ 错误: DOUYIN_COOKIE 环境变量未设置")
        return
    
    print(f"✅ Cookie 已加载 (长度: {len(cookie)} 字符)")
    print("-" * 60)
    
    # 测试几个直播间
    test_rooms = [
        "644546926573",  # 林渍
        "927964320282",  # 小丽丽
        "972033928761",  # 黎錦
    ]
    
    handler = DouyinHandler(
        proxy=None,
        cookies=cookie,
        record_quality="LD"
    )
    
    for room_id in test_rooms:
        url = f"https://live.douyin.com/{room_id}"
        print(f"\n测试直播间: {room_id}")
        
        try:
            stream_info = await handler.get_stream_info(url)
            if stream_info:
                print(f"  主播: {stream_info.anchor_name}")
                print(f"  状态: {'🔴 直播中' if stream_info.is_live else '⚫ 未开播'}")
                if stream_info.is_live:
                    print(f"  标题: {stream_info.title}")
            else:
                print(f"  ❌ 获取失败")
        except Exception as e:
            print(f"  ❌ 错误: {e}")

if __name__ == "__main__":
    asyncio.run(test_cookie())
