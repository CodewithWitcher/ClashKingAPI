import asyncio
from collections import defaultdict
import logging

import aiohttp
from fastapi import APIRouter, Request, HTTPException, Query
import linkd
import sentry_sdk

from utils.time_utils import get_season_raid_weeks, season_start_end, CLASH_ISO_FORMAT
from utils.utils import fix_tag, remove_id_fields, bulk_requests
from utils.database import MongoClient
from routers.v2.player.models import PlayerTagsRequest
from routers.v2.player.utils import (
    get_legend_rankings_for_tag,
    get_legend_stats_common,
    assemble_full_player_data,
    fetch_full_player_data,
    fetch_player_api_data,
    fetch_nested_attribute,
    fetch_nested_key,
    calculate_capital_gold_donated,
    calculate_capital_gold_raided
)

logger = logging.getLogger(__name__)

# Constants
INTERNAL_SERVER_ERROR = "Internal server error"
PLAYER_TAGS_EMPTY = "player_tags cannot be empty"
PLAYER_TAG_REQUIRED = "player_tag is required"

# MongoDB pipeline constants
MONGO_PROJECT = "$project"
MONGO_DATA_CLAN_TAG = "$data.clan.tag"
MONGO_DATA_OPPONENT_TAG = "$data.opponent.tag"

router = APIRouter(prefix="/v2",tags=["Player"], include_in_schema=True)


@router.post("/players/location",
             name="Get locations for a list of players")
@linkd.ext.fastapi.inject
async def player_location_list(body: PlayerTagsRequest, *, mongo: MongoClient):
    """Get country/location information for a list of players.

    Returns location data from the leaderboard database for players who are ranked.
    Players not in any leaderboard will not appear in the response.

    Args:
        body: Request body containing list of player tags

    Returns:
        Dictionary with "items" list containing tag, country_name, and country_code for each player

    Raises:
        HTTPException: 500 if database error occurs
    """
    try:
        player_tags = [fix_tag(tag) for tag in body.player_tags]
        location_info = await mongo.leaderboard_db.find(
            {'tag': {'$in': player_tags}},
            {'_id': 0, 'tag': 1, 'country_name': 1, 'country_code': 1}
        ).to_list(length=None)

        return {"items": remove_id_fields(location_info)}

    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"endpoint": "/players/location"})
        logger.error(f"Error fetching player locations: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)


@router.post("/players/sorted/{attribute}",
             name="Get players sorted by an attribute")
async def player_sorted(attribute: str, body: PlayerTagsRequest):
    """Get players sorted by a specified attribute from the API.

    Fetches player data from the CoC API and sorts by any attribute using dot notation.
    Supports nested attributes (e.g., "league.name") and list lookups (e.g., "achievements[name=test].value").

    Args:
        attribute: The attribute path to sort by (supports dot notation and list lookups)
        body: Request body containing list of player tags

    Returns:
        Dictionary with "items" list containing name, tag, value (sorted attribute), and clan info

    Raises:
        HTTPException: 400 if player_tags is empty
        HTTPException: 500 if API error occurs
    """
    try:
        if not body.player_tags:
            raise HTTPException(status_code=400, detail=PLAYER_TAGS_EMPTY)

        urls = [f"players/{fix_tag(t).replace('#', '%23')}" for t in body.player_tags]
        player_responses = await bulk_requests(urls=urls)

        new_data = [
            {
                "name" : p.get("name"),
                "tag" : p.get("tag"),
                "value" : fetch_nested_attribute(data=p, attr=attribute),
                "clan" : p.get("clan", {})
            }
            for p in player_responses
        ]

        return {"items": sorted(new_data, key=lambda x: (x["value"] is not None, x["value"]), reverse=True)}

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "endpoint": "/players/sorted",
            "attribute": attribute
        })
        logger.error(f"Error sorting players by attribute {attribute}: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)


@router.post("/players/summary/{season}/top",
             name="Get summary of top stats for a list of players")
@linkd.ext.fastapi.inject
async def players_summary_top(season: str, body: PlayerTagsRequest, limit: int = 10, *, mongo: MongoClient):
    """Get top performers in various categories for a season.

    Returns leaderboards for donations, capital contributions, war stars, and season statistics
    like gold/elixir/dark elixir looting and attack wins.

    Args:
        season: Season identifier (e.g., "2023-01")
        body: Request body containing list of player tags
        limit: Maximum number of top players to return per category (default: 10)

    Returns:
        Dictionary with "items" list containing category-wise top performers with tags, values, and rankings

    Raises:
        HTTPException: 400 if player_tags is empty
        HTTPException: 500 if database error occurs
    """
    try:
        if not body.player_tags:
            raise HTTPException(status_code=400, detail=PLAYER_TAGS_EMPTY)

        results = await mongo.player_stats.find(
            {'$and': [{'tag': {'$in': body.player_tags}}]}
        ).to_list(length=None)

        new_data = defaultdict(list)

        # Process standard season stats
        options = [
            f'gold.{season}', f'elixir.{season}', f'dark_elixir.{season}',
            f'activity.{season}', f'attack_wins.{season}', f'season_trophies.{season}',
            (f'donations.{season}.donated', "donated"), (f'donations.{season}.received', "received"),
        ]

        for option_item in options:
            if isinstance(option_item, tuple):
                option_path, name = option_item
            else:
                option_path = option_item
                name = option_item.split(".")[0]

            top_results = sorted(results, key=lambda d, path=option_path: fetch_nested_key(d, attr=path), reverse=True)[:limit]
            for count, result in enumerate(top_results, 1):
                field = fetch_nested_key(result, attr=option_path)
                new_data[name].append({"tag" : result["tag"], "value" : field, "count" : count})

        # Process capital gold stats
        season_raid_weeks = get_season_raid_weeks(season=season)

        top_capital_donos = sorted(
            results,
            key=lambda elem: calculate_capital_gold_donated(elem, season_raid_weeks),
            reverse=True
        )[:limit]
        for count, result in enumerate(top_capital_donos, 1):
            cg_donated = calculate_capital_gold_donated(result, season_raid_weeks)
            new_data["capital_donated"].append({"tag": result["tag"], "value": cg_donated, "count": count})

        top_capital_raided = sorted(
            results,
            key=lambda elem: calculate_capital_gold_raided(elem, season_raid_weeks),
            reverse=True
        )[:limit]
        for count, result in enumerate(top_capital_raided, 1):
            cg_raided = calculate_capital_gold_raided(result, season_raid_weeks)
            new_data["capital_raided"].append({"tag": result["tag"], "value": cg_raided, "count": count})

        # ADD HITRATE
        season_start, season_end = season_start_end(season=season)
        season_start_str = season_start.format(CLASH_ISO_FORMAT)
        season_end_str = season_end.format(CLASH_ISO_FORMAT)

        pipeline = [
            {
                '$match': {
                    '$and': [
                        {
                            '$or': [
                                {'data.clan.members.tag': {'$in': body.player_tags}},
                                {'data.opponent.members.tag': {'$in': body.player_tags}},
                            ]
                        },
                        {'data.preparationStartTime': {'$gte': season_start_str}},
                        {'data.preparationStartTime': {'$lte': season_end_str}},
                        {'type': {'$ne': 'friendly'}},
                    ]
                }
            },
            {
                MONGO_PROJECT: {
                    '_id': 0,
                    'uniqueKey': {
                        '$concat': [
                            {
                                '$cond': {
                                    'if': {'$lt': [MONGO_DATA_CLAN_TAG, MONGO_DATA_OPPONENT_TAG]},
                                    'then': MONGO_DATA_CLAN_TAG,
                                    'else': MONGO_DATA_OPPONENT_TAG,
                                }
                            },
                            {
                                '$cond': {
                                    'if': {'$lt': [MONGO_DATA_OPPONENT_TAG, MONGO_DATA_CLAN_TAG]},
                                    'then': MONGO_DATA_OPPONENT_TAG,
                                    'else': MONGO_DATA_CLAN_TAG,
                                }
                            },
                            '$data.preparationStartTime',
                        ]
                    },
                    'data': 1,
                }
            },
            {'$group': {'_id': '$uniqueKey', 'data': {'$first': '$data'}}},
            {MONGO_PROJECT: {'members': {'$concatArrays': ['$data.clan.members', '$data.opponent.members']}}},
            {'$unwind': '$members'},
            {'$match': {'members.tag': {'$in': body.player_tags}}},
            {
                MONGO_PROJECT: {
                    '_id': 0,
                    'tag': '$members.tag',
                    'name': '$members.name',
                    'stars': {'$sum': '$members.attacks.stars'},
                }
            },
            {
                '$group': {
                    '_id': '$tag',
                    'name': {'$last': '$name'},
                    'totalStars': {'$sum': '$stars'},
                }
            },
            {'$sort': {'totalStars': -1}},
            {'$limit': limit},
        ]
        cursor = await mongo.clan_wars.aggregate(pipeline=pipeline)
        war_star_results = await cursor.to_list(length=None)

        new_data["war_stars"] = [{"tag": result["_id"], "value": result["totalStars"], "count": count}
                                 for count, result in enumerate(war_star_results, 1)]

        return {"items" : [{key : value} for key, value in new_data.items()]}

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "endpoint": "/players/summary/top",
            "season": season
        })
        logger.error(f"Error fetching player summary for season {season}: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)


# ============================================================================
# BASIC PLAYER DATA ENDPOINTS
# ============================================================================

@router.post("/players", name="Get basic API data for multiple players")
async def get_players_basic_stats(body: PlayerTagsRequest):
    """Retrieve basic Clash of Clans API data for multiple players.

    Fast endpoint that returns only core player information from the CoC API:
    - Basic player stats (trophies, level, townhall, etc.)
    - Clan information (if player is in a clan)
    - Heroes, troops, spells, and achievements
    - No extended tracking data or MongoDB statistics

    Args:
        body: Request body containing list of player tags

    Returns:
        Dictionary with "items" list containing basic API data for each player

    Raises:
        HTTPException: 400 if player_tags is empty
        HTTPException: 503 if CoC API is in maintenance
        HTTPException: 500 if CoC API is down or server error
    """
    try:
        if not body.player_tags:
            raise HTTPException(status_code=400, detail=PLAYER_TAGS_EMPTY)

        player_tags = [fix_tag(tag) for tag in body.player_tags]

        async with aiohttp.ClientSession() as session:
            fetch_tasks = [fetch_player_api_data(session, tag) for tag in player_tags]
            api_results = await asyncio.gather(*fetch_tasks)

        result = []
        for tag, data in zip(player_tags, api_results):
            if isinstance(data, HTTPException):
                if data.status_code == 503 or data.status_code == 500:
                    raise data
                else:
                    continue
            if data:
                result.append({
                    "tag": tag,
                    **data
                })

        return {"items": result}

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"endpoint": "/players"})
        logger.error(f"Error fetching basic player stats: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)


# ============================================================================
# EXTENDED PLAYER DATA ENDPOINTS
# ============================================================================

@router.post("/players/extended", name="Get comprehensive stats for multiple players")
@linkd.ext.fastapi.inject
async def get_players_extended_stats(body: PlayerTagsRequest, *, mongo: MongoClient):
    """Retrieve comprehensive player data combining API and tracking statistics.

    Returns enriched player profiles including:
    - Core API data (trophies, level, townhall, etc.)
    - Extended tracking stats (donations, clan games, activity, etc.)
    - Season-based statistics (gold, elixir, dark elixir earnings)
    - Capital gold contributions and raid data
    - Legend league statistics and rankings
    - War performance data

    Args:
        body: Request body containing list of player tags and optional clan_tags mapping

    Returns:
        Dictionary with "items" list containing comprehensive player data

    Raises:
        HTTPException: 400 if player_tags is empty
        HTTPException: 500 if server error occurs
    """
    try:
        if not body.player_tags:
            raise HTTPException(status_code=400, detail=PLAYER_TAGS_EMPTY)

        player_tags = [fix_tag(tag) for tag in body.player_tags]

        # Fetch MongoDB player_stats in bulk
        players_info = await mongo.player_stats.find(
            {"tag": {"$in": player_tags}},
            {
                "_id": 0,
                "tag": 1,
                "donations": 1,
                "clan_games": 1,
                "season_pass": 1,
                "activity": 1,
                "last_online": 1,
                "last_online_time": 1,
                "attack_wins": 1,
                "dark_elixir": 1,
                "gold": 1,
                "capital_gold": 1,
                "season_trophies": 1,
                "last_updated": 1
            }
        ).to_list(length=None)

        mongo_data_dict = {player["tag"]: player for player in players_info}

        # Load legends data in bulk
        legends_data = await get_legend_stats_common(player_tags, mongo)
        tag_to_legends = {entry["tag"]: entry["legends_by_season"] for entry in legends_data}

        # Fetch API, raid & war data per player in parallel
        async with aiohttp.ClientSession() as session:
            fetch_tasks = [
                fetch_full_player_data(
                    session,
                    tag,
                    mongo_data_dict.get(tag, {}),
                    body.clan_tags.get(tag) if body.clan_tags else None,
                    mongo
                )
                for tag in player_tags
            ]

            player_results = await asyncio.gather(*fetch_tasks)

        # Assemble enriched player data in parallel
        combined_results = await asyncio.gather(*[
            assemble_full_player_data(tag, raid_data, war_data, mongo_data, tag_to_legends, mongo)
            for tag, raid_data, war_data, mongo_data in player_results
        ])

        return {"items": remove_id_fields(combined_results)}

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"endpoint": "/players/extended"})
        logger.error(f"Error fetching extended player stats: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)


@router.get("/player/{player_tag}/extended", name="Get comprehensive stats for single player")
@linkd.ext.fastapi.inject
async def get_player_extended_stats(player_tag: str, clan_tag: str = Query(None), *, mongo: MongoClient):
    """Retrieve comprehensive data for a single player.

    Same as /players/extended but optimized for single player queries.
    Includes all tracking statistics, legends data, and war performance.
    Optional clan_tag parameter for clan-specific context.

    Args:
        player_tag: Player tag from URL path
        clan_tag: Optional clan tag for raid/war context

    Returns:
        Complete player data dictionary with all enriched information

    Raises:
        HTTPException: 400 if player_tag is missing
        HTTPException: 500 if server error occurs
    """
    try:
        if not player_tag:
            raise HTTPException(status_code=400, detail=PLAYER_TAG_REQUIRED)

        fixed_tag = fix_tag(player_tag)

        mongo_data = await mongo.player_stats.find_one(
            {"tag": fixed_tag},
            {
                '_id': 0,
                'tag': 1,
                'donations': 1,
                'clan_games': 1,
                'season_pass': 1,
                'activity': 1,
                'last_online': 1,
                'last_online_time': 1,
                'attack_wins': 1,
                'dark_elixir': 1,
                'gold': 1,
                'capital_gold': 1,
                'season_trophies': 1,
                'last_updated': 1
            }
        )

        if not mongo_data:
            mongo_data = {}

        # Load legends data
        legends_data_list = await get_legend_stats_common([fixed_tag], mongo)
        tag_to_legends = {entry["tag"]: entry["legends_by_season"] for entry in legends_data_list}

        # Fetch API, raid & war data
        async with aiohttp.ClientSession() as session:
            tag, raid_data, war_data, mongo_data = await fetch_full_player_data(
                session,
                fixed_tag,
                mongo_data,
                clan_tag,
                mongo
            )

        # Assemble enriched player data
        player_data = await assemble_full_player_data(tag, raid_data, war_data, mongo_data, tag_to_legends, mongo)

        return remove_id_fields(player_data)

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "endpoint": "/player/extended",
            "player_tag": player_tag if player_tag else "unknown"
        })
        logger.error(f"Error fetching extended player stats for {player_tag}: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)


# ============================================================================
# LEGEND LEAGUE ENDPOINTS
# ============================================================================

@router.post("/players/legend-days", name="Get legend league statistics for multiple players")
@linkd.ext.fastapi.inject
async def get_players_legend_stats(body: PlayerTagsRequest, *, mongo: MongoClient):
    """Retrieve legend league daily statistics for multiple players.

    Returns detailed legend league performance data including:
    - Daily trophy gains/losses by season
    - Attack and defense statistics
    - Ranking history and best finishes
    - Season-over-season performance trends

    Args:
        body: Request body containing list of player tags

    Returns:
        Dictionary with "items" list containing legend league stats by season for each player

    Raises:
        HTTPException: 400 if player_tags is empty
        HTTPException: 500 if server error occurs
    """
    if not body.player_tags:
        raise HTTPException(status_code=400, detail=PLAYER_TAGS_EMPTY)

    try:
        return {"items": await get_legend_stats_common(body.player_tags, mongo)}
    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"endpoint": "/players/legend-days"})
        logger.error(f"Error fetching legend stats: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)


@router.post("/players/legend_rankings", name="Get historical legend league rankings for multiple players")
@linkd.ext.fastapi.inject
async def get_multiple_legend_rankings(body: PlayerTagsRequest, limit: int = 10, *, mongo: MongoClient):
    """Retrieve historical legend league rankings for multiple players.

    Returns each player's best legend league finishes with timestamps.
    Processes multiple players in parallel for efficient bulk queries.

    Args:
        body: Request body containing list of player tags
        limit: Maximum number of historical rankings per player (default: 10)

    Returns:
        Dictionary with "items" list containing tag and rankings for each player

    Raises:
        HTTPException: 400 if player_tags is empty
        HTTPException: 500 if server error occurs
    """
    try:
        if not body.player_tags:
            raise HTTPException(status_code=400, detail=PLAYER_TAGS_EMPTY)

        player_tags = [fix_tag(tag) for tag in body.player_tags]
        results = []

        for tag in player_tags:
            rankings = await get_legend_rankings_for_tag(tag, limit, mongo)
            results.append({
                "tag": tag,
                "rankings": rankings
            })

        return {"items": results}

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"endpoint": "/players/legend_rankings"})
        logger.error(f"Error fetching legend rankings: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)

