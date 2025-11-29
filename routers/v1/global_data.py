import coc
import pendulum as pend
import linkd

from fastapi import APIRouter
from fastapi_cache.decorator import cache
from utils.database import MongoClient

router = APIRouter(tags=["Global Data"])


@router.get(
        path="/boost-rate",
        name="Super Troop Boost Rate, for a season (YYYY-MM)")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def super_troop_boost_rate(start_season: str, end_season: str, *, mongo: MongoClient):
    start_year = start_season[:4]; start_month = start_season[-2:]
    end_year = end_season[:4]; end_month = end_season[-2:]

    season_start = coc.utils.get_season_start(month=int(start_month) - 1, year=int(start_year))
    season_end = coc.utils.get_season_end(month=int(end_month) - 1, year=int(end_year))

    pipeline = [
        {
            "$match": {
                "$and": [
                    {
                        "type": {
                            "$in": coc.enums.SUPER_TROOP_ORDER,
                        },
                    },
                    {
                        "time": {
                            "$gte": season_start.timestamp(),
                        },
                    },
                    {"time" : {
                        "$lte" : season_end.timestamp()
                    }}
                ],
            },
        },
        {
            "$facet": {
                "grouped": [{"$group": {"_id": "$type", "boosts": {"$sum": 1}}}],
                "total": [{"$count": "count"}]
            }
        },
        {
            "$unwind": "$grouped",
        },
        {
            "$unwind": "$total",
        },
        {
            "$set": {
                "usagePercent": {
                    "$multiply": [{"$divide": ["$grouped.boosts", "$total.count"]}, 100],
                },
            },
        },
        {"$set": {"name": "$grouped._id", "boosts": "$grouped.boosts"}},
        {"$unset": ["grouped", "total"]}
    ]
    results = await mongo.player_history.aggregate(pipeline=pipeline).to_list(length=None)
    return results


@router.get(
        path="/global/counts",
        name="Number of clans in war, players in war, player in legends etc")
@linkd.ext.fastapi.inject
async def global_counts(*, mongo: MongoClient):
    # Measure timer_counts
    timer_counts = await mongo.war_timer.estimated_document_count()

    # Measure war_counts
    now = int(pend.now(tz=pend.UTC).timestamp())
    war_counts = await mongo.clan_wars.count_documents({"endTime": {"$gte": now}})

    # Measure legend_count
    legend_count = await mongo.legend_rankings.estimated_document_count({})

    # Measure player_count
    player_count = await mongo.player_stats_db.estimated_document_count({})

    # Measure clan_count
    clan_count = await mongo.basic_clan.estimated_document_count({})

    # Measure wars_stored
    wars_stored = await mongo.clan_wars.estimated_document_count({})

    # Measure join_leaves_total
    join_leaves_total = await mongo.join_leave_history.estimated_document_count({})

    return {
        "players_in_war": timer_counts,
        "clans_in_war": war_counts * 2,
        "total_join_leaves": join_leaves_total,
        "players_in_legends": legend_count,
        "player_count": player_count,
        "clan_count": clan_count,
        "wars_stored": wars_stored
    }




