import hikari
import linkd
from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Annotated, Optional

from utils.database import MongoClient, OldMongoClient
from utils.security import check_authentication
from utils.config import Config
from utils.sentry_utils import capture_endpoint_errors
from .models import (
    CapitalPlayerStatsResponse,
    PlayerRaidStats,
    RaidAttack,
    CapitalGuildLeaderboardResponse,
    ClanRaidLeaderboard
)
from .utils import (
    verify_server_exists,
    get_server_clans,
    build_raid_match_query,
    build_player_stats_pipeline,
    build_count_pipeline,
    build_clan_leaderboard_pipeline,
    format_player_stats
)

config = Config()
security = HTTPBearer()

router = APIRouter(prefix="/v2/capital", tags=["Capital Raids"], include_in_schema=True)


@router.get("/player-stats",
            name="Get capital player statistics",
            response_model=CapitalPlayerStatsResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_capital_player_stats(
    guild_id: int,
    clan_tags: Annotated[List[str], Query()],
    season: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    _rest: hikari.RESTApp
) -> CapitalPlayerStatsResponse:
    """Get capital raid player statistics across specified clans.

    Aggregates raid stats by player including:
    - Total attacks and destruction
    - Capital gold looted and raid medals earned
    - Individual attack details

    Args:
        guild_id: Discord server ID
        clan_tags: List of clan tags to include
        season: Optional raid season (format: YYYY-MM). If not provided, returns current/latest season
        limit: Maximum number of players to return (default 100)
        offset: Number of players to skip for pagination (default 0)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        CapitalPlayerStatsResponse: Player statistics aggregated across all specified clans

    Raises:
        HTTPException: 404 if server or clans not found
        HTTPException: 400 if invalid season format
    """
    # Verify server exists
    await verify_server_exists(guild_id, mongo)

    # Get clans for this server (filtered by provided tags)
    clans, clan_name_map = await get_server_clans(guild_id, mongo, clan_tags)
    clan_tags_list = [clan["tag"] for clan in clans]

    # Build match query with optional season filter
    match_query = build_raid_match_query(clan_tags_list, season)

    # Build and execute aggregation pipelines
    pipeline = build_player_stats_pipeline(match_query, limit, offset)
    cursor = await OldMongoClient.raid_weekend_db.aggregate(pipeline)
    results = await cursor.to_list(length=None)

    # Get total count for pagination
    count_pipeline = build_count_pipeline(match_query)
    count_cursor = await OldMongoClient.raid_weekend_db.aggregate(count_pipeline)
    count_result = await count_cursor.to_list(length=1)
    total_count = count_result[0]["total"] if count_result else 0

    # Format response using helper
    players = [
        PlayerRaidStats(**format_player_stats(player_data, clan_name_map))
        for player_data in results
    ]

    return CapitalPlayerStatsResponse(
        season=season,
        players=players,
        total_count=total_count,
        limit=limit,
        offset=offset
    )


@router.get("/guild-leaderboard",
            name="Get capital guild leaderboard",
            response_model=CapitalGuildLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_capital_guild_leaderboard(
    guild_id: int,
    season: Optional[str] = None,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    _rest: hikari.RESTApp
) -> CapitalGuildLeaderboardResponse:
    """Get server-specific capital raid leaderboard.

    Shows aggregate statistics for all clans in the server including:
    - Total raids participated
    - Capital gold looted and raid medals earned
    - Average performance metrics

    Args:
        guild_id: Discord server ID
        season: Optional raid season (format: YYYY-MM). If not provided, returns current/latest season
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        CapitalGuildLeaderboardResponse: Leaderboard of clans ranked by capital gold looted

    Raises:
        HTTPException: 404 if server not found
        HTTPException: 400 if invalid season format
    """
    # Verify server exists
    await verify_server_exists(guild_id, mongo)

    # Get all clans for this server
    clans_query = {"server": guild_id}
    clans = await mongo.clan_db.find(clans_query).to_list(length=None)

    # Return empty response if no clans
    if not clans:
        return CapitalGuildLeaderboardResponse(
            guild_id=guild_id,
            season=season,
            clans=[],
            total_count=0
        )

    clan_tags = [clan["tag"] for clan in clans]
    clan_name_map = {clan["tag"]: clan["name"] for clan in clans}

    # Build match query with optional season filter
    match_query = build_raid_match_query(clan_tags, season)

    # Build and execute aggregation pipeline
    pipeline = build_clan_leaderboard_pipeline(match_query)
    cursor = await OldMongoClient.raid_weekend_db.aggregate(pipeline)
    results = await cursor.to_list(length=None)

    # Format response
    clan_leaderboard = []
    for clan_data in results:
        clan_leaderboard.append(ClanRaidLeaderboard(
            clan_tag=clan_data["clan_tag"],
            clan_name=clan_name_map.get(clan_data["clan_tag"], "Unknown"),
            total_raids=clan_data["total_raids"],
            total_capital_gold_looted=clan_data["total_capital_gold_looted"],
            total_raid_medals=clan_data["total_raid_medals"],
            average_capital_gold_per_raid=clan_data["average_capital_gold_per_raid"],
            average_raid_medals_per_raid=clan_data["average_raid_medals_per_raid"],
            total_attacks=clan_data["total_attacks"],
            average_destruction=clan_data["average_destruction"]
        ))

    return CapitalGuildLeaderboardResponse(
        guild_id=guild_id,
        season=season,
        clans=clan_leaderboard,
        total_count=len(clan_leaderboard)
    )
