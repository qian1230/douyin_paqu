import httpx
import random
import logging

logger = logging.getLogger(__name__)

class DouyinCrawler:
    def __init__(self):
        # 你提供的接口 URL (去掉了部分动态参数以便脚本生成)
        self.api_url = "https://live.douyin.com/webcast/feed/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://live.douyin.com/",
            "Cookie": "UIFID_TEMP=9f119777b70db29e092f16dc2972b95ccc9df01a979ae01132052c40ee3e10ba3429c46950bfb54056b94af55b74ac8ab1e1b0ddd1e9d9efb68ed83c696141afb33d0e15036e9683517e5835082535b6; hevc_supported=true; fpk1=U2FsdGVkX18vdyPhxgFwB40m4Cs8vvkwiqmJjPnDeRjkFCKmOJQI7cSC/qa+UHcQkAcowoGXY6PHk0sUbCAFEg==; fpk2=d6dcc0a6def5582f8d3a9f7f2addb88b; UIFID=9f119777b70db29e092f16dc2972b95ccc9df01a979ae01132052c40ee3e10ba8446070ebddb5539877845a094836d0bd919d6f11bdd3fddfeaa6b78ee84b7c5b9f50847059c2c5fd6659900ebb93b6355a2c60afa0352cbedc66f27d226387f0a302ab1a993e46146a2f518970f4283c503d6ccf50e5ab8f22e78beab0974a79be2f463a30e81fd7294d22853bd33be8b4edbdca9437a36045a0d0225d2e592; xgplayer_device_id=79867379125; xgplayer_user_id=22429078880; my_rd=2; SEARCH_RESULT_LIST_TYPE=%22single%22; volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Atrue%2C%22volume%22%3A0.6%7D; enter_pc_once=1; __live_version__=%221.1.4.5166%22; webcast_local_quality=null; live_can_add_dy_2_desktop=%220%22; live_use_vvc=%22false%22; record_force_login=%7B%22timestamp%22%3A1765180298173%2C%22force_login_video%22%3A0%2C%22force_login_live%22%3A1%2C%22force_login_direct_video%22%3A0%7D; h265ErrorNum=-1; __ac_nonce=06939289a004155f1ad5b; __ac_signature=_02B4Z6wo00f01Ww0mXQAAIDDX6FvNlHLv7lsFJ3AADI36a; s_v_web_id=verify_mizpyxy2_jKpQKbGM_vQsm_4F1L_9Qw4_nbOL7KKTuj7z; douyin.com; xg_device_score=7.4996782433341505; device_web_cpu_core=8; device_web_memory_size=8; dy_swidth=1440; dy_sheight=900; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1440%2C%5C%22screen_height%5C%22%3A900%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A8%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A200%7D%22; strategyABtestKey=%221765353630.769%22; is_dash_user=1; passport_csrf_token=67d657f4af6fec0c21bf262b579dd492; passport_csrf_token_default=67d657f4af6fec0c21bf262b579dd492; bd_ticket_guard_client_web_domain=2; sdk_source_info=7e276470716a68645a606960273f276364697660272927676c715a6d6069756077273f276364697660272927666d776a68605a607d71606b766c6a6b5a7666776c7571273f275e5927666d776a686028607d71606b766c6a6b3f2a2a636261616869696b69696e64696464626e626d666e6a6c6b646068686a6275602a7677662a7666776c7571762a666a6b71606b712a696a6664716c6a6b2876756a6a636c6b622b6f76592758272927666a6b766a69605a696c6061273f27636469766027292762696a6764695a7364776c6467696076273f275e582729277672715a646971273f2763646976602729277f6b5a666475273f2763646976602729276d6a6e5a6b6a716c273f2763646976602729276c6b6f5a7f6367273f27636469766027292771273f273d313637363336303630333234272927676c715a75776a716a666a69273f2763646976602778; bit_env=wqJjnnCl3Iy47ULMVwCsE4YlSzVVJ70Y2gll5GQkG8UMBxJlSJPBdrjSB6qWrvpyD1cBi_QpElfdnt1EeYviZu0mY4a0NGWhcBSoT1u2BK4-xdXvqhcniVsqSSWlxY5c2TpPkMK-9lC_Z8T_-3P3-XWFuxvThVxoXZzEk7DRWEXl1i70B8OrxMHymw_MQL3Gm67Wk_9OupncxCL32ikD6Cv_p1NCgT5BgeVGwv8tFGHpX1NUEyi46T-gQqx_S5WFJ22nqG-xRYwncfV38T-6GM0fpVUA7qXcXny-Zu7YfAnYOXt-n-Wd39EQP1iz3O85K6OzByC7vrlEtLf-HA3S4kyuEG6Yvh1Hs128BLAkJfXT-Tvz42RqX5c_yY8xKxHklPeeZIh5lfwNvyKOYCVVY_XicxhlSX8qBkKPKtkrByv-ookCHL9jburuQb1WAw8YRzcWOW4WLQTqswJAghZds-i6Y0oYgMgmdoON8QP8bGdJiXRGmG3THR-id3Xz6p2sOvYJedEee07sdX-UiRVUQaEuIshvLf_RW9oEMxzQ-W0%3D; gulu_source_res=eyJwX2luIjoiYjYwM2IxOTA2OTIxYzA2MTQyN2RmODI4Y2MzNWMxYTIyNTE4ZTZiNmQxMGQyYmRiY2Q0Y2MzOTQ0ODNlM2E4YiJ9; passport_auth_mix_state=8jpv4nzpv8er5s3w40gzqrguyv1178hp2p8z2tj8zsd9x7vv; passport_mfa_token=CjflcZm6Ecn0bbrsKtnrxS25SXPfsW4CBSoAdSfoYsKJ3NqWiNZiIpAIspJdmVxy1zZOfTVsC%2FWMGkoKPAAAAAAAAAAAAABP0G1x%2B8q5ytzpEu1hE8G5wy7zMEHD3FRJNlXAhCJGuFXvmz4PqZ%2F%2B%2BzsM4NEYElMbFBCq54MOGPax0WwgAiIBA5s1Oxk%3D; d_ticket=5856ef3834db88847f17281cb14242c98299a; passport_assist_user=CkGXE3MlIJt0mt87HDLw7Vh5HEDIE8A8YxEPUCyg_0GnIDTGNJtZBFzJySZJ8bIcQfJgTiOeAGjzY0apDqfCEkMSAhpKCjwAAAAAAAAAAAAAT9CqYPe-HoGTgOcLF3hjC2iOlaDRet-6ugev2bIgAO56pqOI6AaqQiAJHVbdsUP2jFMQreeDDhiJr9ZUIAEiAQOwJ0ow; n_mh=RpKuGn3WVKqlR56ztQC3bxNJ4iY5j7FaGtLsbPojdt0; sid_guard=b7911dc180d5a959ba3c9d1a3f03c4fc%7C1765353650%7C5184000%7CSun%2C+08-Feb-2026+08%3A00%3A50+GMT; uid_tt=97fc6b3cc5935acf2829c917d69d9fad; uid_tt_ss=97fc6b3cc5935acf2829c917d69d9fad; sid_tt=b7911dc180d5a959ba3c9d1a3f03c4fc; sessionid=b7911dc180d5a959ba3c9d1a3f03c4fc; sessionid_ss=b7911dc180d5a959ba3c9d1a3f03c4fc; session_tlb_tag=sttt%7C1%7Ct5EdwYDVqVm6PJ0aPwPE_P_________5DhV7lknpRLyWC4KAqa49vuBw8lHqRbna4miLgCUUSJM%3D; session_tlb_tag_bk=sttt%7C1%7Ct5EdwYDVqVm6PJ0aPwPE_P_________5DhV7lknpRLyWC4KAqa49vuBw8lHqRbna4miLgCUUSJM%3D; is_staff_user=false; sid_ucp_v1=1.0.0-KGZlMjNmNGJiZWE1NDA3ODExN2NlYWQ2NGI5NjI4MzhlOTYwODU0ZTcKIQjYmfDPq_STAxCy0eTJBhjvMSAMMJnKrvkFOAVA-wdIBBoCbHEiIGI3OTExZGMxODBkNWE5NTliYTNjOWQxYTNmMDNjNGZj; ssid_ucp_v1=1.0.0-KGZlMjNmNGJiZWE1NDA3ODExN2NlYWQ2NGI5NjI4MzhlOTYwODU0ZTcKIQjYmfDPq_STAxCy0eTJBhjvMSAMMJnKrvkFOAVA-wdIBBoCbHEiIGI3OTExZGMxODBkNWE5NTliYTNjOWQxYTNmMDNjNGZj; _bd_ticket_crypt_cookie=149bf371111796df51d9b4f3d3327c61; login_time=1765353650048; publish_badge_show_info=%220%2C0%2C0%2C1765353650458%22; DiscoverFeedExposedAd=%7B%7D; IsDouyinActive=true; SelfTabRedDotControl=%5B%5D; FOLLOW_LIVE_POINT_INFO=%22MS4wLjABAAAAhgWttco0bCwFGhV2hwKb8Xx5oiwPcRTeuGyC8GG25veVn5Gq1vBGsdhqU_0HES34%2F1765382400000%2F0%2F1765353652121%2F0%22; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCUGZvbndkb0ZFT0JDZWlEVkFDS1BVL0ltNXdGMk1KZVBjQ0RMMVl0NDJucXdYV3FGempVR05JTHRMclRZSFFqNzBqcVhNQkVQQUdoMTd3Q0lqYW5pdVk9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; home_can_add_dy_2_desktop=%221%22; ttwid=1%7CElzlBXtIDOw107UNKTZFKm4Ys8xbMbUsPEYljajG5fg%7C1765353652%7C165eb569b1edeb528790e446a3628f2d3f8c1c2ff1102ca39a3e90bb9cd91f1e; odin_tt=d5ef601f6360015bbf83c0f79f10114c5b2aad12c28b065ee10f8f1862a2df046ce4a1c219a6c57f8443bccfeec0c64e8d4d62c9dd1e00265b10c4a196dd37c0; biz_trace_id=1e0a3741; __security_mc_1_s_sdk_crypt_sdk=d150f2b3-4b9d-930f; __security_mc_1_s_sdk_cert_key=b372d03e-4a47-9b03; __security_mc_1_s_sdk_sign_data_key_web_protect=368db8d4-4b74-8103; bd_ticket_guard_client_data_v2=eyJyZWVfcHVibGljX2tleSI6IkJQZm9ud2RvRkVPQkNlaURWQUNLUFUvSW01d0YyTUplUGNDREwxWXQ0Mm5xd1hXcUZ6alVHTklMdExyVFlIUWo3MGpxWE1CRVBBR2gxN3dDSWphbml1WT0iLCJ0c19zaWduIjoidHMuMi45NDQ2YWM2YmUwZDQ4ZjdkYjhjNWYwOTViZTNhZjhlOTQyNDQyYTAxYWNmZDkyMTJlYzhkYjUwNTNjMjU4MGZlYzRmYmU4N2QyMzE5Y2YwNTMxODYyNGNlZGExNDkxMWNhNDA2ZGVkYmViZWRkYjJlMzBmY2U4ZDRmYTAyNTc1ZCIsInJlcV9jb250ZW50Ijoic2VjX3RzIiwicmVxX3NpZ24iOiJaOG1yby9wQVpQYkFhUzhldXQ2WXZmZUZiM09rUFpCd1JtYStLTmE4NjJVPSIsInNlY190cyI6IiM5WFVGZktWajNSRW02cURSYUg0SjdUeEl4Vys4ZXBBQUFlY3Z6QlU1TWVBUWVXc1ZVZFhhK0hhQy9nRUwifQ%3D%3D" # 建议从配置中读取或使用抓包获取的
        }

    async def fetch_live_rooms(self):
        """
        获取直播间列表
        :return: list of dict [{'url': '...', 'name': '...', 'title': '...'}]
        """
        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "enter_from": "page_refresh",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "120.0.0.0",
            "channel": "channel_pc_web",
            "request_tag_from": "web",
            "need_map": "1",
            "liveid": "1",
            "is_draw": "1",
            "custom_count": "10", # 每次爬取数量
            "action": "load_more",
            "action_type": "loadmore",
            "enter_source": "web_homepage_hot_web_live_card",
            "source_key": "web_homepage_hot_web_live_card",
            # 注意：msToken 和 a_bogus 等签名参数通常有时效性
            # 如果接口校验严格，可能需要定期更新或动态生成。
            # 这里暂时使用你提供的作为示例，如果过期可能需要更新。
        }

        rooms = []
        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=10) as client:
                response = await client.get(self.api_url, params=params)
                if response.status_code != 200:
                    logger.warning(f"Douyin Crawler API Error: {response.status_code}")
                    return []
                
                json_data = response.json()
                
                # 解析数据结构
                # 结构：data -> list -> item -> data -> {short_id, title, user{nickname, signature}, ...}
                data_list = json_data.get("data", [])
                
                for item in data_list:
                    # 某些广告或特殊卡片可能没有 data 字段，跳过
                    if "data" not in item:
                        continue
                        
                    inner_data = item["data"]
                    short_id = inner_data.get("short_id") or inner_data.get("web_rid")
                    title = inner_data.get("title", "")
                    
                    # 获取主播信息
                    user_info = inner_data.get("user", {})
                    nickname = user_info.get("nickname", "Unknown")
                    
                    # 如果 short_id 存在，拼接 URL
                    if short_id:
                        room_url = f"https://live.douyin.com/{short_id}"
                        rooms.append({
                            "url": room_url,
                            "name": nickname,
                            "title": title,
                            "platform": "douyin"
                        })
                        
                logger.info(f"Douyin Crawler: Found {len(rooms)} rooms.")
                return rooms

        except Exception as e:
            logger.error(f"Douyin Crawler Exception: {e}")
            return []