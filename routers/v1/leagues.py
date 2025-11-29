import orjson
import aiofiles

from fastapi import APIRouter
from fastapi_cache.decorator import cache


router = APIRouter(tags=["Leagues"])


@router.get("/builderbaseleagues",
         tags=["Leagues"],
         name="Builder Base Leagues w/ Icons")
@cache(expire=300)
async def builder_base_leagues():
    file_path = "assets/json/builder_league.json"
    async with aiofiles.open(file_path, 'rb') as json_file:
        content = await json_file.read()
        data = orjson.loads(content)
        for item in data.get("items"):
            league = item.get("name")
            split = league.split(" ")
            if len(split) == 3:
                if "IV" in split[-1]:
                    tier = 4
                elif "V" in split[-1]:
                    tier = 5
                else:
                    tier = len(split[-1])
            else:
                tier = 1
            item["iconUrls"] = {"medium" : f"https://assets.clashk.ing/bot/builder-base-leagues/builder_base_{split[0].lower()}_{split[1].lower()}_{tier}.png"}
        return data