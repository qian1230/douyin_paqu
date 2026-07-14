import asyncio
import json
import sys
import argparse
from typing import Any, Dict, Optional

import streamget


async def fetch_douyin_stream(
    url: str,
    proxy: Optional[str],
    cookies: Optional[str],
    quality: Optional[str],
) -> Dict[str, Any]:
    """
    子进程中调用 streamget 获取抖音直播间信息，返回可 JSON 化的 dict。
    这里完全隔离在单独进程里，即使底层阻塞也不会卡主主进程的事件循环。
    """
    live_stream = streamget.DouyinLiveStream(proxy_addr=proxy, cookies=cookies)

    if "v.douyin.com" in url:
        json_data = await live_stream.fetch_app_stream_data(url=url)
    else:
        json_data = await live_stream.fetch_web_stream_data(url=url)

    # streamget 的 fetch_stream_url 按当前项目约定会返回兼容 StreamData 的对象
    sd = await live_stream.fetch_stream_url(json_data, quality)

    return {
        "platform": getattr(sd, "platform", "抖音)"),
        "anchor_name": getattr(sd, "anchor_name", None),
        "is_live": getattr(sd, "is_live", None),
        "title": getattr(sd, "title", None),
        "quality": getattr(sd, "quality", None),
        "m3u8_url": getattr(sd, "m3u8_url", None),
        "flv_url": getattr(sd, "flv_url", None),
        "record_url": getattr(sd, "record_url", None),
        "new_cookies": getattr(sd, "new_cookies", None),
        "new_token": getattr(sd, "new_token", None),
        "extra": getattr(sd, "extra", None),
        "danmu_ws_url": getattr(sd, "ws_url", None),
        "real_room_id": getattr(sd, "room_id", None),

    }


async def _amain() -> None:
    parser = argparse.ArgumentParser(description="Douyin streamget worker (subprocess).")
    parser.add_argument("--url", required=True)
    parser.add_argument("--proxy", default=None)
    parser.add_argument("--cookies", default=None)
    parser.add_argument("--quality", default=None)
    args = parser.parse_args()

    try:
        data = await fetch_douyin_stream(
            url=args.url,
            proxy=args.proxy or None,
            cookies=args.cookies or None,
            quality=args.quality or None,
        )
        sys.stdout.write(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
    except Exception as e:  # pragma: no cover - 子进程错误直接写 stderr
        # 尽量输出简洁可读的错误信息，方便主进程日志记录
        sys.stdout.write(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()


