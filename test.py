import aiohttp
import asyncio
import orjson
import os
from dotenv import load_dotenv

# Try to import asyncio_throttle, provide fallback if not available
try:
    from asyncio_throttle import Throttler
except ImportError:
    # Fallback: simple semaphore-based throttler
    class Throttler:
        def __init__(self, rate_limit):
            self.semaphore = asyncio.Semaphore(rate_limit)

        async def __aenter__(self):
            await self.semaphore.acquire()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.semaphore.release()

load_dotenv()

url = "https://api.clashroyale.com/v1/globaltournaments"
# Load token from environment variable instead of hardcoding
token = os.getenv("CLASH_ROYALE_API_TOKEN", "")
total_429s = 0
throttler = Throttler(2000)

async def fetch(session: aiohttp.ClientSession):
    global throttler
    global total_429s
    async with throttler:
        async with session.get(url, headers={"Authorization": f"Bearer {token}"}) as response:
            if response.status == 200:
                data = await response.json()
            else:
                data = await response.text()
                print(data)
                total_429s += 1
    return data

async def tester():
    http_session = aiohttp.ClientSession(json_serialize=orjson.loads)

    tasks = [fetch(session=http_session) for _ in range(1000)]
    await asyncio.gather(*tasks)
    await http_session.close()
    print(total_429s, "429s")



asyncio.run(tester())