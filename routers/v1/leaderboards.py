import pendulum as pend
import linkd

from fastapi import HTTPException, APIRouter, Query
from fastapi_cache.decorator import cache
from utils.utils import leagues
from utils.database import MongoClient


router = APIRouter(tags=["Leaderboards"])


def validate_weekend(weekend: str):
    """Validate that the raid weekend has been completed for at least 4 hours."""
    weekend_to_iso = pend.parse(weekend, strict=False)
    if (pend.now(tz=pend.UTC) - weekend_to_iso).total_seconds() <= 273600:
        raise HTTPException(status_code=404, detail="Please wait until 4 hours after Raid Weekend is completed to collect stats")


def flatten_ranking(results: list) -> list:
    """Transform results by flattening the ranking field."""
    for result in results:
        result["rank"] = result["ranking"]["rank"]
        del result["ranking"]
    return results


async def get_capital_leaderboard(
    collection,
    weekend: str,
    stat_type: str,
    lower: int,
    upper: int,
    league: str
) -> dict:
    """Fetch capital leaderboard data from MongoDB collection."""
    validate_weekend(weekend)

    results = await collection.find({
        "$and": [
            {"weekend": weekend},
            {"type": stat_type},
            {"ranking.league": league},
            {"ranking.rank": {"$gte": lower, "$lte": upper}}
        ]
    }, {"_id": 0, "type": 0}).sort({"ranking.rank": 1}).limit(250).to_list(length=None)

    return {"items": flatten_ranking(results)}


@router.get(
        path="/leaderboard/players/capital",
        name="Capital Attribute Leaderboard for Players (weekend: YYYY-MM-DD)")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def leaderboard_players_capital(
                            weekend: str = Query(example="2024-05-03"),
                            stat_type: str = Query(enum=["capital_looted"], alias="type"),
                            lower: int = Query(ge=1, default=1),
                            upper: int = Query(le=1000, default=50),
                            league: str = Query(enum=["All"] + leagues),
                            *,
                            mongo: MongoClient):

    return await get_capital_leaderboard(
        mongo.player_capital_lb,
        weekend,
        stat_type,
        lower,
        upper,
        league
    )


@router.get(
        path="/leaderboard/clans/capital",
        name="Leaderboard of capital loot for clans (weekend: YYYY-MM-DD)")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def leaderboard_clans_capital(
                        weekend: str = Query(example="2024-05-03"),
                        stat_type: str = Query(enum=["capitalTotalLoot", "raidsCompleted", "enemyDistrictsDestroyed", "medals"], alias="type"),
                        lower: int = Query(ge=1, default=1),
                        upper: int = Query(le=1000, default=50),
                        league: str = Query(enum=["All"] + leagues),
                        *,
                        mongo: MongoClient):

    return await get_capital_leaderboard(
        mongo.clan_capital_lb,
        weekend,
        stat_type,
        lower,
        upper,
        league
    )







