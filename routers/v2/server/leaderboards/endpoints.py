import hikari
import linkd
import pendulum
from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from utils.database import MongoClient
from utils.security import check_authentication
from utils.sentry_utils import capture_endpoint_errors
from utils.custom_coc import CustomClashClient
from .utils import (
    verify_server_exists,
    get_server_clans,
    get_server_player_tags,
    validate_and_get_season,
    get_player_info_map,
    calculate_legend_stats,
    get_clan_info_from_player,
    process_war_stats,
    process_raid_stats,
    extract_looting_stats
)

# Constants for error messages and descriptions
SERVER_NOT_FOUND = "Server not found"
INVALID_SEASON_FORMAT = "Invalid season format. Use YYYY-MM"
SEASON_FORMAT_DESC = "Season in YYYY-MM format (defaults to current)"
from .models import (
    PlayerLeaderboardEntry,
    ClanLeaderboardEntry,
    ServerLeaderboardResponse,
    WarPerformanceEntry,
    WarPerformanceLeaderboardResponse,
    DonationsEntry,
    DonationsLeaderboardResponse,
    CapitalRaidEntry,
    CapitalRaidLeaderboardResponse,
    LegendLeagueEntry,
    LegendLeagueLeaderboardResponse,
    ClanGamesEntry,
    ClanGamesLeaderboardResponse,
    ActivityEntry,
    ActivityLeaderboardResponse,
    LootingEntry,
    LootingLeaderboardResponse
)

security = HTTPBearer()
router = APIRouter(prefix="/v2/server", tags=["Server Leaderboards"], include_in_schema=True)


@router.get("/{server_id}/leaderboards",
            name="Get server leaderboards",
            response_model=ServerLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_server_leaderboards(
        server_id: int,
        limit_players: int = Query(default=100, le=500, ge=1),
        limit_clans: int = Query(default=50, le=200, ge=1),
        sort_by: str = Query(default="global_rank", enum=["global_rank", "local_rank", "trophies", "legend_trophies"]),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp,
        _coc_client: CustomClashClient
) -> ServerLeaderboardResponse:
    """Get comprehensive leaderboards for a Discord server.

    Returns top players and clans based on various ranking metrics.

    Args:
        server_id: Discord server ID
        limit_players: Maximum number of players to return (default 100, max 500)
        limit_clans: Maximum number of clans to return (default 50, max 200)
        sort_by: Sort criterion (global_rank, local_rank, trophies, legend_trophies)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)
        _coc_client: Custom COC client (injected, not used)

    Returns:
        Leaderboards showing top players and clans from the server
    """
    # Verify server exists and get clans
    await verify_server_exists(server_id, mongo)
    clans, _, clan_tags = await get_server_clans(server_id, mongo)

    # Get all linked player tags for this server
    player_tags = await get_server_player_tags(server_id, mongo)

    # Fetch player rankings from leaderboard_db
    player_rankings = await mongo.leaderboard_db.find(
        {"tag": {"$in": player_tags}}
    ).to_list(length=None)

    # Create map for quick lookup
    player_ranking_map = {p["tag"]: p for p in player_rankings}

    # Fetch player stats to get current info
    player_stats = await mongo.player_stats.find(
        {"tag": {"$in": player_tags}},
        {"tag": 1, "name": 1, "townhall": 1, "trophies": 1, "clan": 1}
    ).to_list(length=None)

    # Build player leaderboard entries
    player_entries = []

    for player in player_stats:
        player_tag = player.get("tag")
        ranking = player_ranking_map.get(player_tag, {})

        # Get clan info
        player_clan = player.get("clan", {})
        player_clan_tag = player_clan.get("tag") if isinstance(player_clan, dict) else None
        player_clan_name = player_clan.get("name") if isinstance(player_clan, dict) else None

        entry = PlayerLeaderboardEntry(
            player_tag=player_tag,
            player_name=player.get("name", "Unknown"),
            townhall_level=player.get("townhall"),
            clan_tag=player_clan_tag,
            clan_name=player_clan_name,
            trophies=player.get("trophies"),
            global_rank=ranking.get("global_rank"),
            local_rank=ranking.get("local_rank"),
            country_code=ranking.get("country_code"),
            country_name=ranking.get("country_name"),
            legend_trophies=ranking.get("legend_trophies")
        )

        player_entries.append(entry)

    # Sort players based on sort_by parameter
    if sort_by == "global_rank":
        # Sort by global rank (lower is better), None values go to end
        player_entries.sort(key=lambda x: (x.global_rank is None, x.global_rank or float('inf')))
    elif sort_by == "local_rank":
        player_entries.sort(key=lambda x: (x.local_rank is None, x.local_rank or float('inf')))
    elif sort_by == "trophies":
        player_entries.sort(key=lambda x: -(x.trophies or 0))
    elif sort_by == "legend_trophies":
        player_entries.sort(key=lambda x: -(x.legend_trophies or 0))

    # Limit players
    player_entries = player_entries[:limit_players]

    # Fetch clan rankings from clan_leaderboard_db
    clan_rankings = await mongo.clan_leaderboard_db.find(
        {"tag": {"$in": clan_tags}}
    ).to_list(length=None)

    clan_ranking_map = {c["tag"]: c for c in clan_rankings}

    # Fetch clan stats
    clan_stats_list = await mongo.clan_stats.find(
        {"tag": {"$in": clan_tags}}
    ).to_list(length=None)

    clan_stats_map = {c["tag"]: c for c in clan_stats_list}

    # Build clan leaderboard entries
    clan_entries = []

    for clan in clans:
        clan_tag = clan.get("tag")
        ranking = clan_ranking_map.get(clan_tag, {})
        stats = clan_stats_map.get(clan_tag, {})

        entry = ClanLeaderboardEntry(
            clan_tag=clan_tag,
            clan_name=clan.get("name", "Unknown"),
            clan_level=stats.get("level"),
            clan_points=stats.get("points"),
            member_count=stats.get("memberCount"),
            global_rank=ranking.get("global_rank"),
            local_rank=ranking.get("local_rank"),
            country_code=ranking.get("country_code"),
            country_name=ranking.get("country_name"),
            capital_points=stats.get("capitalPoints")
        )

        clan_entries.append(entry)

    # Sort clans by global rank
    clan_entries.sort(key=lambda x: (x.global_rank is None, x.global_rank or float('inf')))

    # Limit clans
    clan_entries = clan_entries[:limit_clans]

    return ServerLeaderboardResponse(
        server_id=server_id,
        total_players=len(player_stats),
        total_clans=len(clans),
        players=player_entries,
        clans=clan_entries
    )

@router.get("/{server_id}/leaderboards/war-performance",
            name="Get war performance leaderboard",
            response_model=WarPerformanceLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_war_performance_leaderboard(
        server_id: int,
        limit: int = Query(default=100, le=500, ge=1),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> WarPerformanceLeaderboardResponse:
    """
    Get war performance leaderboard for a Discord server.

    Returns top players by war stars, destruction, and attack success.

    Args:
        server_id: Discord server ID
        limit: Maximum number of players to return (default 100, max 500)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        War performance leaderboard
    """
    # Verify server exists and get clans
    await verify_server_exists(server_id, mongo)
    _, clan_name_map, _ = await get_server_clans(server_id, mongo)

    # Get all linked player tags for this server
    player_tags = await get_server_player_tags(server_id, mongo)

    # Aggregate war hits data from OldMongoClient
    from utils.database import OldMongoClient

    # Use aggregation to get war stats per player
    pipeline = [
        {
            "$match": {
                "$or": [
                    {"data.clan.members.tag": {"$in": player_tags}},
                    {"data.opponent.members.tag": {"$in": player_tags}}
                ]
            }
        },
        {
            "$project": {
                "clan_members": "$data.clan.members",
                "opponent_members": "$data.opponent.members"
            }
        }
    ]

    wars = await OldMongoClient.clan_wars.aggregate(pipeline).to_list(length=None)

    # Build war stats per player using helper function
    player_war_stats = process_war_stats(wars, player_tags)

    # Fetch player current info
    player_info_map = await get_player_info_map(player_tags, mongo)

    # Build leaderboard entries
    entries = []

    for player_tag, stats in player_war_stats.items():
        player_info = player_info_map.get(player_tag, {})
        player_clan_tag, player_clan_name = get_clan_info_from_player(player_info, clan_name_map)

        attack_count = stats["attack_count"]
        avg_stars = stats["total_stars"] / attack_count if attack_count > 0 else 0.0
        avg_destruction = stats["total_destruction"] / attack_count if attack_count > 0 else 0.0

        entry = WarPerformanceEntry(
            player_tag=player_tag,
            player_name=player_info.get("name", stats["name"]),
            townhall_level=player_info.get("townhall", stats["townhall"]),
            clan_tag=player_clan_tag,
            clan_name=player_clan_name,
            total_stars=stats["total_stars"],
            total_destruction=round(stats["total_destruction"], 2),
            attack_count=attack_count,
            defense_count=stats["defense_count"],
            triple_stars=stats["triple_stars"],
            average_stars=round(avg_stars, 2),
            average_destruction=round(avg_destruction, 2),
            war_count=stats["war_count"]
        )

        entries.append(entry)

    # Sort by total stars (descending)
    entries.sort(key=lambda x: (-x.total_stars, -x.average_stars, -x.triple_stars))

    # Limit results
    entries = entries[:limit]

    return WarPerformanceLeaderboardResponse(
        server_id=server_id,
        total_count=len(player_war_stats),
        players=entries
    )


@router.get("/{server_id}/leaderboards/donations",
            name="Get donations leaderboard",
            response_model=DonationsLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_donations_leaderboard(
        server_id: int,
        limit: int = Query(default=100, le=500, ge=1),
        sort_by: str = Query(default="sent", enum=["sent", "received", "ratio"]),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp,
        _coc_client: CustomClashClient
) -> DonationsLeaderboardResponse:
    """
    Get donations leaderboard for a Discord server.

    Returns top players by donations sent, received, or ratio.

    Args:
        server_id: Discord server ID
        limit: Maximum number of players to return (default 100, max 500)
        sort_by: Sort by sent, received, or ratio (default: sent)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)
        _coc_client: Custom COC client (injected, not used)

    Returns:
        Donations leaderboard
    """
    # Verify server exists and get clans
    await verify_server_exists(server_id, mongo)
    _, clan_name_map, clan_tags = await get_server_clans(server_id, mongo)

    # Fetch current clan data from CoC API to get donations
    entries = []

    for clan_tag in clan_tags:
        try:
            clan = await _coc_client.get_clan(clan_tag)

            for member in clan.members:
                # Calculate ratio
                ratio = None
                if member.received > 0:
                    ratio = round(member.donations / member.received, 2)

                entry = DonationsEntry(
                    player_tag=member.tag,
                    player_name=member.name,
                    townhall_level=member.town_hall,
                    clan_tag=clan_tag,
                    clan_name=clan_name_map.get(clan_tag, clan.name),
                    donations_sent=member.donations,
                    donations_received=member.received,
                    donation_ratio=ratio
                )

                entries.append(entry)

        except Exception as e:
            print(f"Error fetching clan {clan_tag}: {e}")
            continue

    # Sort based on sort_by parameter
    if sort_by == "sent":
        entries.sort(key=lambda x: -x.donations_sent)
    elif sort_by == "received":
        entries.sort(key=lambda x: -x.donations_received)
    elif sort_by == "ratio":
        entries.sort(key=lambda x: -(x.donation_ratio or 0))

    # Limit results
    entries = entries[:limit]

    return DonationsLeaderboardResponse(
        server_id=server_id,
        total_count=len(entries),
        players=entries
    )


@router.get("/{server_id}/leaderboards/capital-raids",
            name="Get capital raids leaderboard",
            response_model=CapitalRaidLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_capital_raids_leaderboard(
        server_id: int,
        limit: int = Query(default=100, le=500, ge=1),
        weekend: Optional[str] = Query(None, description="Weekend date YYYY-MM-DD (optional, defaults to latest)"),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> CapitalRaidLeaderboardResponse:
    """
    Get capital raids leaderboard for a Discord server.

    Returns top players by capital gold looted.

    Args:
        server_id: Discord server ID
        limit: Maximum number of players to return (default 100, max 500)
        weekend: Optional weekend date (YYYY-MM-DD), defaults to latest
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        Capital raids leaderboard
    """
    # Verify server exists and get clans
    await verify_server_exists(server_id, mongo)
    _, clan_name_map, _ = await get_server_clans(server_id, mongo)

    # Get all linked player tags for this server
    player_tags = await get_server_player_tags(server_id, mongo)

    # Fetch capital raid data from OldMongoClient
    from utils.database import OldMongoClient

    # Build query
    query = {"data.members.tag": {"$in": player_tags}}

    if weekend:
        query["data.startTime"] = {"$regex": f"^{weekend}"}

    # Fetch raids
    raids = await OldMongoClient.raid_weekend_db.find(query).sort("data.startTime", -1).limit(10).to_list(length=None)

    # Aggregate player stats using helper function
    player_raid_stats = process_raid_stats(raids, player_tags)

    # Fetch player current info
    player_info_map = await get_player_info_map(player_tags, mongo)

    # Build leaderboard entries
    entries = []

    for player_tag, stats in player_raid_stats.items():
        player_info = player_info_map.get(player_tag, {})
        player_clan_tag, player_clan_name = get_clan_info_from_player(player_info, clan_name_map)

        avg_gold = stats["total_capital_gold"] / stats["total_raids"] if stats["total_raids"] > 0 else 0.0

        entry = CapitalRaidEntry(
            player_tag=player_tag,
            player_name=player_info.get("name", stats["name"]),
            townhall_level=player_info.get("townhall"),
            clan_tag=player_clan_tag,
            clan_name=player_clan_name,
            total_capital_gold=stats["total_capital_gold"],
            total_raids=stats["total_raids"],
            average_capital_gold=round(avg_gold, 2),
            total_attacks=stats["total_attacks"]
        )

        entries.append(entry)

    # Sort by total capital gold (descending)
    entries.sort(key=lambda x: -x.total_capital_gold)

    # Limit results
    entries = entries[:limit]

    return CapitalRaidLeaderboardResponse(
        server_id=server_id,
        total_count=len(player_raid_stats),
        players=entries
    )


@router.get("/{server_id}/leaderboards/legends",
            name="Get legend league leaderboard",
            response_model=LegendLeagueLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_legend_league_leaderboard(
        server_id: int,
        limit: int = Query(default=100, le=500, ge=1),
        days: int = Query(default=7, le=30, ge=1, description="Number of days to analyze (1-30)"),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> LegendLeagueLeaderboardResponse:
    """
    Get legend league leaderboard for a Discord server.

    Returns top players by legend league performance over a specified period.

    Args:
        server_id: Discord server ID
        limit: Maximum number of players to return (default 100, max 500)
        days: Number of days to analyze (default 7, max 30)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        Legend league leaderboard
    """
    
    # Verify server exists
    await verify_server_exists(server_id, mongo)

    # Get all linked player tags for this server
    player_tags = await get_server_player_tags(server_id, mongo)

    if not player_tags:
        return LegendLeagueLeaderboardResponse(
            server_id=server_id,
            total_count=0,
            players=[]
        )

    # Generate list of dates to query
    today = pendulum.now(tz="UTC")
    dates = [today.subtract(days=i).strftime("%Y-%m-%d") for i in range(days)]

    # Build projection for legend days
    projection = {
        "tag": 1,
        "name": 1,
        "townhall": 1,
        "clan": 1,
        "legends.streak": 1
    }
    for date in dates:
        projection[f"legends.{date}"] = 1

    # Fetch legend data
    player_stats = await mongo.player_stats.find(
        {"tag": {"$in": player_tags}},
        projection
    ).to_list(length=None)

    # Get all clans for this server for clan name mapping
    # Get clans for clan name mapping
    _, clan_name_map, _ = await get_server_clans(server_id, mongo)

    # Process legend stats
    entries = []

    for player in player_stats:
        player_tag = player.get("tag")
        legends_data = player.get("legends", {})

        # Calculate stats using helper function
        stats = calculate_legend_stats(legends_data, dates)
        if stats is None:
            continue

        # Get clan info using helper function
        player_clan_tag, player_clan_name = get_clan_info_from_player(player, clan_name_map)

        entry = LegendLeagueEntry(
            player_tag=player_tag,
            player_name=player.get("name", "Unknown"),
            townhall_level=player.get("townhall"),
            clan_tag=player_clan_tag,
            clan_name=player_clan_name,
            current_trophies=stats["current_trophies"],
            trophy_change=stats["trophy_change"],
            attack_wins=stats["attack_wins"],
            defense_wins=stats["defense_wins"],
            total_attacks=stats["total_attacks"],
            total_defenses=stats["total_defenses"],
            streak=stats["streak"]
        )

        entries.append(entry)

    # Sort by trophy change (descending), then by current trophies
    entries.sort(key=lambda x: (-x.trophy_change, -x.current_trophies))

    # Limit results
    entries = entries[:limit]

    return LegendLeagueLeaderboardResponse(
        server_id=server_id,
        total_count=len(entries),
        players=entries
    )


@router.get("/{server_id}/leaderboards/clan-games",
            name="Get clan games leaderboard",
            response_model=ClanGamesLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_clan_games_leaderboard(
        server_id: int,
        limit: int = Query(default=100, le=500, ge=1),
        season: Optional[str] = Query(None, description=SEASON_FORMAT_DESC),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> ClanGamesLeaderboardResponse:
    """
    Get clan games leaderboard for a Discord server.

    Returns top players by clan games points for a season.

    Args:
        server_id: Discord server ID
        limit: Maximum number of players to return (default 100, max 500)
        season: Season in YYYY-MM format (defaults to current season)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        Clan games leaderboard
    """

    # Verify server exists
    await verify_server_exists(server_id, mongo)

    # Validate and get season (defaults to current if not provided)
    season = validate_and_get_season(season)

    # Get all linked player tags for this server
    player_tags = await get_server_player_tags(server_id, mongo)

    if not player_tags:
        return ClanGamesLeaderboardResponse(
            server_id=server_id,
            season=season,
            total_count=0,
            players=[]
        )

    # Fetch player stats with clan games data
    player_stats = await mongo.player_stats.find(
        {"tag": {"$in": player_tags}},
        {"tag": 1, "name": 1, "townhall": 1, "clan": 1, f"clan_games.{season}": 1}
    ).to_list(length=None)

    # Get all clans for this server for clan name mapping
    # Get clans for clan name mapping
    _, clan_name_map, _ = await get_server_clans(server_id, mongo)

    # Build entries
    entries = []

    for player in player_stats:
        player_tag = player.get("tag")
        clan_games_data = player.get("clan_games", {})
        season_data = clan_games_data.get(season, {})

        points = season_data.get("points", 0) if isinstance(season_data, dict) else 0

        # Skip players with 0 points
        if points == 0:
            continue

        # Get clan info
        player_clan = player.get("clan", {})
        player_clan_tag = player_clan.get("tag") if isinstance(player_clan, dict) else None
        player_clan_name = clan_name_map.get(player_clan_tag) if player_clan_tag else None

        entry = ClanGamesEntry(
            player_tag=player_tag,
            player_name=player.get("name", "Unknown"),
            townhall_level=player.get("townhall"),
            clan_tag=player_clan_tag,
            clan_name=player_clan_name,
            points=points
        )

        entries.append(entry)

    # Sort by points (descending)
    entries.sort(key=lambda x: -x.points)

    # Limit results
    entries = entries[:limit]

    return ClanGamesLeaderboardResponse(
        server_id=server_id,
        season=season,
        total_count=len(entries),
        players=entries
    )


@router.get("/{server_id}/leaderboards/activity",
            name="Get activity leaderboard",
            response_model=ActivityLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_activity_leaderboard(
        server_id: int,
        limit: int = Query(default=100, le=500, ge=1),
        season: Optional[str] = Query(None, description=SEASON_FORMAT_DESC),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> ActivityLeaderboardResponse:
    """
    Get activity leaderboard for a Discord server.

    Returns top players by activity count and last online time.

    Args:
        server_id: Discord server ID
        limit: Maximum number of players to return (default 100, max 500)
        season: Season in YYYY-MM format (defaults to current season)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        Activity leaderboard
    """
    from datetime import datetime

    # Verify server exists
    await verify_server_exists(server_id, mongo)

    # Validate and get season (defaults to current if not provided)
    season = validate_and_get_season(season)

    # Get all linked player tags for this server
    player_tags = await get_server_player_tags(server_id, mongo)

    if not player_tags:
        return ActivityLeaderboardResponse(
            server_id=server_id,
            season=season,
            total_count=0,
            players=[]
        )

    # Fetch player stats with activity data
    player_stats = await mongo.player_stats.find(
        {"tag": {"$in": player_tags}},
        {"tag": 1, "name": 1, "townhall": 1, "clan": 1, f"activity.{season}": 1, "last_online": 1}
    ).to_list(length=None)

    # Get all clans for this server for clan name mapping
    # Get clans for clan name mapping
    _, clan_name_map, _ = await get_server_clans(server_id, mongo)

    # Build entries
    entries = []
    now_timestamp = int(datetime.now().timestamp())

    for player in player_stats:
        player_tag = player.get("tag")
        activity_data = player.get("activity", {})
        activity_count = activity_data.get(season, 0) if isinstance(activity_data, dict) else 0

        last_online = player.get("last_online")
        days_since_online = None
        if last_online is not None:
            days_since_online = (now_timestamp - last_online) // 86400  # Convert to days

        # Get clan info
        player_clan = player.get("clan", {})
        player_clan_tag = player_clan.get("tag") if isinstance(player_clan, dict) else None
        player_clan_name = clan_name_map.get(player_clan_tag) if player_clan_tag else None

        entry = ActivityEntry(
            player_tag=player_tag,
            player_name=player.get("name", "Unknown"),
            townhall_level=player.get("townhall"),
            clan_tag=player_clan_tag,
            clan_name=player_clan_name,
            activity_count=activity_count,
            last_online=last_online,
            days_since_online=days_since_online
        )

        entries.append(entry)

    # Sort by activity count (descending), then by last online (most recent first)
    entries.sort(key=lambda x: (-x.activity_count, -(x.last_online or 0)))

    # Limit results
    entries = entries[:limit]

    return ActivityLeaderboardResponse(
        server_id=server_id,
        season=season,
        total_count=len(entries),
        players=entries
    )


@router.get("/{server_id}/leaderboards/looting",
            name="Get looting leaderboard",
            response_model=LootingLeaderboardResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_looting_leaderboard(
        server_id: int,
        limit: int = Query(default=100, le=500, ge=1),
        season: Optional[str] = Query(None, description=SEASON_FORMAT_DESC),
        sort_by: str = Query(default="total", enum=["gold", "elixir", "dark_elixir", "total"]),
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> LootingLeaderboardResponse:
    """
    Get looting/resources leaderboard for a Discord server.

    Returns top players by resources looted (gold, elixir, dark elixir).

    Args:
        server_id: Discord server ID
        limit: Maximum number of players to return (default 100, max 500)
        season: Season in YYYY-MM format (defaults to current season)
        sort_by: Sort by gold, elixir, dark_elixir, or total (default: total)
        _user_id: Authenticated user ID (injected by @check_authentication, not used)
        _credentials: HTTP Bearer credentials (required for auth, not used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (injected, not used)

    Returns:
        Looting leaderboard
    """

    # Verify server exists
    await verify_server_exists(server_id, mongo)

    # Validate and get season (defaults to current if not provided)
    season = validate_and_get_season(season)

    # Get all linked player tags for this server
    player_tags = await get_server_player_tags(server_id, mongo)

    if not player_tags:
        return LootingLeaderboardResponse(
            server_id=server_id,
            season=season,
            total_count=0,
            sort_by=sort_by,
            players=[]
        )

    # Fetch player stats with looting data
    player_stats = await mongo.player_stats.find(
        {"tag": {"$in": player_tags}},
        {
            "tag": 1,
            "name": 1,
            "townhall": 1,
            "clan": 1,
            f"gold.{season}": 1,
            f"elixir.{season}": 1,
            f"dark_elixir.{season}": 1
        }
    ).to_list(length=None)

    # Get all clans for this server for clan name mapping
    # Get clans for clan name mapping
    _, clan_name_map, _ = await get_server_clans(server_id, mongo)

    # Build entries
    entries = []

    for player in player_stats:
        player_tag = player.get("tag")

        # Extract looting stats using helper function
        loot_stats = extract_looting_stats(player, season)

        # Skip players with 0 loot
        if loot_stats["total_looted"] == 0:
            continue

        # Get clan info using helper function
        player_clan_tag, player_clan_name = get_clan_info_from_player(player, clan_name_map)

        entry = LootingEntry(
            player_tag=player_tag,
            player_name=player.get("name", "Unknown"),
            townhall_level=player.get("townhall"),
            clan_tag=player_clan_tag,
            clan_name=player_clan_name,
            gold_looted=loot_stats["gold_looted"],
            elixir_looted=loot_stats["elixir_looted"],
            dark_elixir_looted=loot_stats["dark_elixir_looted"],
            total_looted=loot_stats["total_looted"]
        )

        entries.append(entry)

    # Sort based on sort_by parameter
    if sort_by == "gold":
        entries.sort(key=lambda x: -x.gold_looted)
    elif sort_by == "elixir":
        entries.sort(key=lambda x: -x.elixir_looted)
    elif sort_by == "dark_elixir":
        entries.sort(key=lambda x: -x.dark_elixir_looted)
    else:  # total
        entries.sort(key=lambda x: -x.total_looted)

    # Limit results
    entries = entries[:limit]

    return LootingLeaderboardResponse(
        server_id=server_id,
        season=season,
        total_count=len(entries),
        sort_by=sort_by,
        players=entries
    )
