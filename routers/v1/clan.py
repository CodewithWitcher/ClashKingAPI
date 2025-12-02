import pendulum as pend

from bson.objectid import ObjectId
from fastapi import APIRouter, Depends
from fastapi_cache.decorator import cache
from routers.v2.clan.models import JoinLeaveList
from utils.utils import fix_tag
from utils.database import MongoClient
import linkd

router = APIRouter(tags=["Clan Endpoints"])


def _build_range_filters(filters: 'ClanFilterParams') -> list[dict]:
    """Build MongoDB range filter queries from filter parameters.

    Args:
        filters: ClanFilterParams instance

    Returns:
        List of MongoDB query conditions
    """
    conditions = []

    # Member count filters
    if filters.min_members:
        conditions.append({"members": {"$gte": filters.min_members}})
    if filters.max_members:
        conditions.append({"members": {"$lte": filters.max_members}})

    # Level filters
    if filters.min_level:
        conditions.append({"level": {"$gte": filters.min_level}})
    if filters.max_level:
        conditions.append({"level": {"$lte": filters.max_level}})

    # War filters
    if filters.min_war_win_streak:
        conditions.append({"warWinStreak": {"$gte": filters.min_war_win_streak}})
    if filters.min_war_wins:
        conditions.append({"warWins": {"$gte": filters.min_war_wins}})

    # Trophy filters
    if filters.min_clan_trophies:
        conditions.append({"clanPoints": {"$gte": filters.min_clan_trophies}})
    if filters.max_clan_trophies:
        conditions.append({"clanPoints": {"$gte": filters.max_clan_trophies}})

    return conditions


def _build_exact_match_filters(filters: 'ClanFilterParams') -> list[dict]:
    """Build MongoDB exact match filter queries from filter parameters.

    Args:
        filters: ClanFilterParams instance

    Returns:
        List of MongoDB query conditions
    """
    conditions = []

    if filters.location_id:
        conditions.append({'location.id': filters.location_id})
    if filters.open_type:
        conditions.append({"type": filters.open_type})
    if filters.capital_league:
        conditions.append({"capitalLeague": filters.capital_league})
    if filters.war_league:
        conditions.append({"warLeague": filters.war_league})

    return conditions


def _build_pagination_filters(before: str | None, after: str | None) -> list[dict]:
    """Build MongoDB pagination filter queries.

    Args:
        before: ObjectId string for pagination before cursor
        after: ObjectId string for pagination after cursor

    Returns:
        List of MongoDB query conditions
    """
    conditions = []

    if after:
        conditions.append({"_id": {"$gt": ObjectId(after)}})
    if before:
        conditions.append({"_id": {"$lt": ObjectId(before)}})

    return conditions


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
    # Build all filter conditions
    all_conditions = []
    all_conditions.extend(_build_exact_match_filters(filters))
    all_conditions.extend(_build_range_filters(filters))
    all_conditions.extend(_build_pagination_filters(before, after))

    # Build final query
    queries = {'$and': all_conditions} if all_conditions else {}

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
