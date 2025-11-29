import pendulum as pend

from bson.objectid import ObjectId
from fastapi import APIRouter, Depends
from fastapi_cache.decorator import cache
from routers.v2.clan.models import JoinLeaveList
from utils.utils import fix_tag
from utils.database import MongoClient
import linkd

router = APIRouter(tags=["Clan Endpoints"])


class ClanFilterParams:
    def __init__(
        self,
        location_id: int | None = None,
        min_members: int | None = None,
        max_members: int | None = None,
        min_level: int | None = None,
        max_level: int | None = None,
        open_type: str | None = None,
        min_war_win_streak: int | None = None,
        min_war_wins: int | None = None,
        min_clan_trophies: int | None = None,
        max_clan_trophies: int | None = None,
        capital_league: str | None = None,
        war_league: str | None = None,
    ):
        self.location_id = location_id
        self.min_members = min_members
        self.max_members = max_members
        self.min_level = min_level
        self.max_level = max_level
        self.open_type = open_type
        self.min_war_win_streak = min_war_win_streak
        self.min_war_wins = min_war_wins
        self.min_clan_trophies = min_clan_trophies
        self.max_clan_trophies = max_clan_trophies
        self.capital_league = capital_league
        self.war_league = war_league


@router.get("/clan/{clan_tag}/basic",
         name="Basic Clan Object")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def clan_basic(clan_tag: str, *, mongo: MongoClient):
    clan_tag = fix_tag(clan_tag)
    result = await mongo.basic_clan.find_one({"tag": clan_tag})
    if result is not None:
        del result["_id"]
    return result


@router.get(
        path="/clan/{clan_tag}/join-leave",
        name="Join Leaves in a season",
        response_model=JoinLeaveList)
@cache(expire=300)
@linkd.ext.fastapi.inject
async def clan_join_leave(clan_tag: str, timestamp_start: int = 0, time_stamp_end: int = 9999999999, limit: int = 250, *, mongo: MongoClient):
    clan_tag = fix_tag(clan_tag)
    result = await mongo.join_leave_history.find(
        {"$and" : [
            {"clan" : clan_tag},
            {"time" : {"$gte" : pend.from_timestamp(timestamp=timestamp_start, tz=pend.UTC)}},
            {"time": {"$lte": pend.from_timestamp(timestamp=time_stamp_end, tz=pend.UTC)}}
        ]
    }, {"_id" : 0}).sort({"time" : -1}).limit(limit=limit).to_list(length=None)
    return {"items" : result}




@router.get("/clan/search",
         name="Search Clans by Filtering")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def clan_filter(
    limit: int = 100,
    member_list: bool = True,
    before: str | None = None,
    after: str | None = None,
    filters: ClanFilterParams = Depends(),
    *,
    mongo: MongoClient
):
    queries = {'$and': []}
    if filters.location_id:
        queries['$and'].append({'location.id': filters.location_id})

    if filters.min_members:
        queries['$and'].append({"members": {"$gte": filters.min_members}})

    if filters.max_members:
        queries['$and'].append({"members": {"$lte": filters.max_members}})

    if filters.min_level:
        queries['$and'].append({"level": {"$gte": filters.min_level}})

    if filters.max_level:
        queries['$and'].append({"level": {"$lte": filters.max_level}})

    if filters.open_type:
        queries['$and'].append({"type": filters.open_type})

    if filters.capital_league:
        queries['$and'].append({"capitalLeague": filters.capital_league})

    if filters.war_league:
        queries['$and'].append({"warLeague": filters.war_league})

    if filters.min_war_win_streak:
        queries['$and'].append({"warWinStreak": {"$gte": filters.min_war_win_streak}})

    if filters.min_war_wins:
        queries['$and'].append({"warWins": {"$gte": filters.min_war_wins}})

    if filters.min_clan_trophies:
        queries['$and'].append({"clanPoints": {"$gte": filters.min_clan_trophies}})

    if filters.max_clan_trophies:
        queries['$and'].append({"clanPoints": {"$gte": filters.max_clan_trophies}})

    if after:
        queries['$and'].append({"_id": {"$gt": ObjectId(after)}})

    if before:
        queries['$and'].append({"_id": {"$lt": ObjectId(before)}})


    if not queries["$and"]:
        queries = {}

    limit = min(limit, 1000)
    results = await mongo.basic_clan.find(queries).limit(limit).sort("_id", 1).to_list(length=limit)
    return_data = {"items": [], "before": "", "after": ""}
    if results:
        return_data["before"] = str(results[0].get("_id"))
        return_data["after"] = str(results[-1].get("_id"))
        for data in results:
            del data["_id"]
            if not member_list:
                del data["memberList"]
        return_data["items"] = results
    return return_data




@router.get("/clan/{clan_tag}/historical",
         name="Historical data for a clan of player events")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def clan_historical(clan_tag: str, timestamp_start: int = 0, time_stamp_end: int = 9999999999, limit: int = 100, *, mongo: MongoClient):
    clan_tag = fix_tag(clan_tag)

    historical_data = await mongo.player_history.find(
        {"$and": [
            {"clan": clan_tag},
            {"time": {"$gte": int(pend.from_timestamp(timestamp=timestamp_start, tz=pend.UTC).timestamp())}},
            {"time": {"$lte": int(pend.from_timestamp(timestamp=time_stamp_end, tz=pend.UTC).timestamp())}}
        ]
        }, {"_id": 0}).sort({"time": -1}).limit(limit=limit).to_list(length=25000)

    return {"items" : historical_data}
