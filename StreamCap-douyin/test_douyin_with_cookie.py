#!/usr/bin/env python3
"""测试抖音 streamget 库（带 Cookie）"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.platforms.platform_handlers.douyin_worker import fetch_douyin_stream

async def test():
    cookie = os.getenv("DOUYIN_COOKIE", "")
    if not cookie:
        print("❌ 请设置 DOUYIN_COOKIE 环境变量")
        return
    
    url = "https://live.douyin.com/848618224474"
    
    try:
        result = await fetch_douyin_stream(
            url=url,
            proxy=None,
            cookies=cookie,
            quality=None
        )
        print(f"✅ 成功（带 Cookie）")
        print(f"   是否开播: {result.get('is_live')}")
        print(f"   主播名: {result.get('anchor_name')}")
        print(f"   标题: {result.get('title')}")
    except Exception as e:
        print(f"❌ 失败（带 Cookie）: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())

