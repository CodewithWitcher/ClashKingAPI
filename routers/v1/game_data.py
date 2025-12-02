import json
import os

from fastapi import APIRouter


router = APIRouter(tags=["Game Data"])

@router.get("/assets",
         name="Link to download a zip with all assets", include_in_schema=False)
async def assets():
    return {"download-link" : "https://cdn.clashking.xyz/Out-Sprites.zip"}



@router.get("/json/{data_type}",
         name="View json game data (/json/list, for list of types)")
async def json(data_type: str):
    if data_type == "list":
        return {"types" : ["troops", "heroes", "hero_equipment", "spells", "buildings", "pets", "supers", "townhalls", "translations"]}
    file_name = f"assets/json/{data_type}.json"
    file_path = os.path.join(os.getcwd(), file_name)
    with open(file_path, mode='r', encoding='utf-8') as json_file:
        data = json.load(json_file)
        return data