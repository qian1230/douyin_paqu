import os
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import aiohttp
from aiohttp import ClientConnectorError, ClientError

from app.core.scraper.base_scraper import BaseScraper
from app.core.scraper.platforms.douyin_abogus import get_a_bogus
from app.models.recording.scraped_room_model import ScrapedRoom, ScrapedRoomStatus

logger = logging.getLogger(__name__)

class DouyinScraper(BaseScraper):
    PLATFORM = "douyin"
    BASE_URL = "https://live.douyin.com/"

    def __init__(self, session: aiohttp.ClientSession, proxy: Optional[str] = None):
        super().__init__(session, proxy)
        
        # ========== 九类别分区API配置 ==========
        self.partition_apis = {
            # 原有三个
            "娱乐": os.getenv(
                "DOUYIN_API_ENTERTAINMENT",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=202&partition_type=4&req_from=2",
            ),
            "知识": os.getenv(
                "DOUYIN_API_KNOWLEDGE",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=203&partition_type=4&req_from=2",
            ),
            "电商": os.getenv(
                "DOUYIN_API_ECOMMERCE",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=210&partition_type=4&req_from=2",
            ),
            # 新增六个
            "二次元": os.getenv(
                "DOUYIN_API_ERCIYUAN",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=104&partition_type=4&req_from=2",
            ),
            "游戏": os.getenv(
                "DOUYIN_API_GAME",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=103&partition_type=4&req_from=2",
            ),
            "运动": os.getenv(
                "DOUYIN_API_SPORTS",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=108&partition_type=4&req_from=2",
            ),
            "舞蹈": os.getenv(
                "DOUYIN_API_DANCE",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=105&partition_type=4&req_from=2",
            ),
            "音乐": os.getenv(
                "DOUYIN_API_MUSIC",
                "https://live.douyin.com/webcast/web/partition/detail/room/v2/?aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=page_refresh&cookie_enabled=true&screen_width=801&screen_height=858&browser_language=zh-CN&browser_platform=MacIntel&browser_name=Chrome&browser_version=142.0.0.0&count=15&offset=30&partition=102&partition_type=4&req_from=2",
            ),
        }
        
        cookie = os.getenv("DOUYIN_COOKIE", "")
        self.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://live.douyin.com/",
            **({"Cookie": cookie} if cookie else {}),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://live.douyin.com",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        })

    async def scrape_live_rooms(self, max_rooms: int = 27) -> List[ScrapedRoom]:
        """
        从抖音按九个分区抓取直播间信息
        Args:
            max_rooms: 最多返回的房间数量，默认27个（9个分区，每个分区3个）
        """
        rooms: List[ScrapedRoom] = []
        max_retries = 3
        retry_delay = 2
        
        # 计算每个分区应该获取的数量（9个分区均匀分配）
        rooms_per_partition = max(1, (max_rooms + 8) // 9)  # 向上取整
        partition_list = list(self.partition_apis.items())
        
        try:
            for idx, (category, url) in enumerate(partition_list):
                # 计算当前分区应该获取的数量
                if idx < len(partition_list) - 1:
                    target_count_for_partition = rooms_per_partition
                else:
                    target_count_for_partition = max_rooms - len(rooms)
                
                if len(rooms) >= max_rooms:
                    break
                
                rooms_before_partition = len(rooms)
                
                for attempt in range(max_retries):
                    try:
                        # 添加 a_bogus 签名
                        parsed = urlparse(url)
                        params = dict(parse_qsl(parsed.query))
                        bogus = get_a_bogus(params)
                        if bogus:
                            params["a_bogus"] = bogus
                        final_url = urlunparse(parsed._replace(query=urlencode(params)))

                        async with self.session.get(final_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status != 200:
                                logger.warning(f"Douyin partition '{category}' HTTP {resp.status}")
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(retry_delay * (attempt + 1))
                                    continue
                                break

                            try:
                                data = await resp.json()
                            except:
                                try:
                                    text = await resp.text()
                                    data = json.loads(text)
                                except:
                                    logger.error(f"Failed to parse JSON for {category}")
                                    break

                            if not isinstance(data, dict):
                                logger.warning(f"Douyin partition '{category}' root is not dict")
                                break

                            inner_data = data.get("data") or {}
                            if not isinstance(inner_data, dict):
                                break

                            items = inner_data.get("data") or []
                            if not isinstance(items, list):
                                break

                            for item in items:
                                if len(rooms) - rooms_before_partition >= target_count_for_partition:
                                    break
                                if len(rooms) >= max_rooms:
                                    break
                                
                                if not isinstance(item, dict):
                                    continue
                                
                                room_data = item.get("room") or {}
                                if not isinstance(room_data, dict):
                                    continue

                                owner = item.get("owner") or room_data.get("owner") or {}
                                slug = str(
                                    item.get("web_rid")
                                    or room_data.get("id_str")
                                    or room_data.get("id")
                                    or ""
                                ).strip()
                                title = room_data.get("title") or ""
                                nickname = (
                                    owner.get("nickname")
                                    or room_data.get("owner_nickname")
                                    or title
                                    or "Unknown"
                                )

                                if not slug:
                                    continue

                                room_url = f"https://live.douyin.com/{slug}"
                                viewer_count = room_data.get("user_count") or 0

                                cover_url = ""
                                cover = room_data.get("cover") or {}
                                if isinstance(cover, dict):
                                    url_list = cover.get("url_list") or []
                                    if isinstance(url_list, list) and url_list:
                                        cover_url = url_list[0]

                                rooms.append(
                                    ScrapedRoom(
                                        platform=self.PLATFORM,
                                        room_id=str(slug),
                                        room_url=room_url,
                                        title=title,
                                        anchor_name=nickname,
                                        viewer_count=viewer_count,
                                        cover_url=cover_url,
                                        status=ScrapedRoomStatus.PENDING,
                                        category=category,
                                    )
                                )
                            
                            # 成功获取，跳出重试
                            break

                    except Exception as e:
                        logger.error(f"Error fetching {category}: {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (attempt + 1))
                        else:
                            break

            logger.info(f"Douyin partitions: parsed {len(rooms)} rooms across 9 categories")
            return rooms
            
        except Exception as e:
            logger.error(f"Douyin scraping error: {e}", exc_info=True)
            return rooms