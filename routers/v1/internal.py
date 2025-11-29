import aiohttp
import orjson
import asyncio
import linkd

from fastapi import  Request, Response, HTTPException, Header
from fastapi import APIRouter
from typing import List
from utils.utils import fix_tag
from utils.database import MongoClient
from utils.config import Config
from expiring_dict import ExpiringDict


router = APIRouter(tags=["Internal Endpoints"])

api_cache = ExpiringDict()


async def fetch_image(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()




@router.get("/v1/{url:path}",
         name="Test a coc api endpoint, very high ratelimit, only for testing without auth",
         include_in_schema=False)
async def test_endpoint(url: str):

    full_url = f"https://proxy.clashk.ing/v1/{url}"
    full_url = full_url.replace("#", '%23').replace("!", '%23')

    async with aiohttp.ClientSession() as session:
        async with session.get(full_url) as api_response:
            if api_response.status != 200:
                content = await api_response.text()
                raise HTTPException(status_code=api_response.status, detail=content)
            item = await api_response.json()

    return item


@router.post("/v1/{url:path}",
             name="Test a coc api endpoint, very high ratelimit, only for testing without auth",
             include_in_schema=False)
async def test_post_endpoint(url: str, request: Request):

    # Construct the full URL with query parameters if any
    full_url = f"https://proxy.clashk.ing/v1/{url}"


    full_url = full_url.replace("#", '%23').replace("!", '%23')

    # Extract JSON body from the request
    body = await request.json()

    async with aiohttp.ClientSession() as session:
        async with session.post(full_url, json=body) as api_response:
            if api_response.status != 200:
                content = await api_response.text()
                raise HTTPException(status_code=api_response.status, detail=content)
            item = await api_response.json()

    return item

@router.get("/bot/config", include_in_schema=False)
@linkd.ext.fastapi.inject
async def bot_config(bot_token: str = Header(...), *, mongo: MongoClient):
    config_data = await mongo.bot_settings.find_one({"type" : "bot"}, {"_id" : 0})

    is_main = False
    is_beta = False
    is_custom = False

    if bot_token == config_data.get("prod_token"):
        is_main = True
    elif bot_token in config_data.get("beta_tokens", []):
        is_beta = True
    else:
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    extra_config = {
        "is_main": is_main,
        "is_beta": is_beta,
        "is_custom": is_custom
    }

    return config_data | extra_config


#fix one day + connect to db
@router.get("/permalink/{clan_tag}",
         name="Permanent Link to Clan Badge URL", include_in_schema=False)
@linkd.ext.fastapi.inject
async def permalink(clan_tag: str, *, mongo: MongoClient):

    clan_tag = fix_tag(clan_tag)
    db_clan_result = await mongo.global_clans.find_one({"_id" : clan_tag}, {"data."})
    if not db_clan_result:

        async with aiohttp.ClientSession() as http_session:
            async with http_session.get(
                    f"https://api.clashofclans.com/v1/clans/{clan_tag.replace('#', '%23')}") as resp:
                items = await resp.json()
        image_link = items["badgeUrls"]["large"]
    else:
        image_link = None

    async def fetch(badge_url, client_session):
        async with client_session.get(badge_url) as response:
            image_data = await response.read()
            return image_data

    tasks = []
    async with aiohttp.ClientSession() as session:
        tasks.append(fetch(image_link, session))
        responses = await asyncio.gather(*tasks)
        await session.close()
    image_bytes: bytes = responses[0]
    return Response(content=image_bytes, media_type="image/png")


@router.post("/ck/bulk",
         name="Only for internal use, rotates tokens and implements caching so that all other services dont need to",
         include_in_schema=False)
@linkd.ext.fastapi.inject
async def ck_bulk_proxy(urls: List[str], request: Request, *, config: Config):

    token = request.headers.get("authorization")
    if token != f"Bearer {config.internal_api_token}":
        raise HTTPException(status_code=401, detail="Invalid token")

    async def fetch_function(api_endpoint: str):
        encoded_url = api_endpoint.replace("#", '%23')
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://proxy.clashk.ing/v1/{encoded_url}") as response:
                item_bytes = await response.read()
                item = orjson.loads(item_bytes)
                if response.status != 200:
                    item = None
            await session.close()
            return item

    tasks = []
    for url in urls:
        tasks.append(asyncio.create_task(fetch_function(url)))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if r is not None and not isinstance(r, Exception)]


