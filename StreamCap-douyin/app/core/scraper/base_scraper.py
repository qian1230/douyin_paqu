from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import aiohttp
from app.models.recording.scraped_room_model import ScrapedRoom

class BaseScraper(ABC):
    PLATFORM: str
    BASE_URL: str
    
    def __init__(self, session: aiohttp.ClientSession, proxy: Optional[str] = None):
        self.session = session
        self.proxy = proxy
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    @abstractmethod
    async def scrape_live_rooms(self, max_rooms: int = 10) -> List[ScrapedRoom]:
        """Scrape live rooms from the platform"""
        pass
    
    async def make_request(self, url: str, method: str = 'GET', **kwargs) -> Dict[str, Any]:
        """Helper method to make HTTP requests"""
        kwargs['headers'] = {**self.headers, **kwargs.get('headers', {})}
        if self.proxy:
            kwargs['proxy'] = self.proxy
            
        async with self.session.request(method, url, **kwargs) as response:
            response.raise_for_status()
            if 'application/json' in response.headers.get('content-type', ''):
                return await response.json()
            return await response.text()
