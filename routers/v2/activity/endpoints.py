import hikari
import linkd
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import pendulum as pend

logger = logging.getLogger(__name__)
from utils.database import MongoClient
from utils.security import check_authentication
from utils.config import Config
from utils.custom_coc import CustomClashClient
from utils.sentry_utils import capture_endpoint_errors
from .models import (
    GuildActivitySummary,
    InactivePlayersResponse
)
from .utils import (
    calculate_clan_activity,
    find_inactive_players,
    process_clan_safely
)

config = Config()
security = HTTPBearer()

router = APIRouter(prefix="/v2/activity", tags=["Activity & Inactivity"], include_in_schema=True)


@router.get("/guild-summary",
            name="Get guild activity summary",
            response_model=GuildActivitySummary)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_guild_activity_summary(
    guild_id: int,
    inactive_threshold_days: int = 7,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    _rest: hikari.RESTApp,
    coc_client: CustomClashClient
) -> GuildActivitySummary:
    """Get server-wide activity overview across all clans.

    Provides aggregate statistics including:
    - Total members and activity rates
    - Donation statistics
    - Clan-by-clan breakdown

    Args:
        guild_id: Discord server ID
        inactive_threshold_days: Days without activity to consider inactive (default 7)
        _user_id: Authenticated user ID (injected by @check_authentication, not directly used)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (required for auth, not directly used)
        coc_client: Clash of Clans API client

    Returns:
        GuildActivitySummary: Comprehensive activity summary with clan-by-clan breakdown

    Raises:
        HTTPException: 404 if server not found
    """
    # Verify server exists and user has access
    server = await mongo.server_db.find_one({"server": guild_id})
    if not server:
        raise HTTPException(status_code=404, detail="Server hasn't been set up yet")

    # Get all clans for this server
    clans = await mongo.clan_db.find({"server": guild_id}).to_list(length=None)
    if not clans:
        return GuildActivitySummary(
            guild_id=guild_id,
            total_clans=0,
            total_members=0,
            total_active_members=0,
            total_inactive_members=0,
            overall_activity_rate=0.0,
            total_donations_sent=0,
            total_donations_received=0,
            clans=[]
        )

    # Prepare clan data
    clan_name_map = {clan["tag"]: clan["name"] for clan in clans}
    inactive_threshold = pend.now(tz=pend.UTC).subtract(days=inactive_threshold_days)

    # Process all clans and collect activity data
    clan_activities = []
    for clan in clans:
        clan_tag = clan["tag"]
        clan_name = clan_name_map[clan_tag]

        activity = await process_clan_safely(
            clan_tag, clan_name, coc_client,
            calculate_clan_activity, inactive_threshold
        )

        if activity:
            clan_activities.append(activity)

    # Calculate aggregate statistics
    total_members = sum(c.total_members for c in clan_activities)
    total_active = sum(c.active_members for c in clan_activities)
    total_inactive = sum(c.inactive_members for c in clan_activities)
    total_donations_sent = sum(c.total_donations_sent for c in clan_activities)
    total_donations_received = sum(c.total_donations_received for c in clan_activities)
    overall_activity_rate = (total_active / total_members * 100) if total_members > 0 else 0.0

    return GuildActivitySummary(
        guild_id=guild_id,
        total_clans=len(clan_activities),
        total_members=total_members,
        total_active_members=total_active,
        total_inactive_members=total_inactive,
        overall_activity_rate=overall_activity_rate,
        total_donations_sent=total_donations_sent,
        total_donations_received=total_donations_received,
        clans=clan_activities
    )


@router.get("/inactive-players",
            name="Get inactive players",
            response_model=InactivePlayersResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_inactive_players(
    guild_id: int,
    inactive_threshold_days: int = 7,
    min_townhall: Optional[int] = None,
    clan_tag: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    _rest: hikari.RESTApp,
    coc_client: CustomClashClient
) -> InactivePlayersResponse:
    """Get list of inactive members across server clans.

    Returns players who haven't been active within the threshold period.

    Args:
        guild_id: Discord server ID
        inactive_threshold_days: Days without activity to consider inactive (default 7)
        min_townhall: Optional minimum townhall level filter
        clan_tag: Optional specific clan to check (defaults to all server clans)
        limit: Maximum number of players to return (default 100)
        offset: Number of players to skip for pagination (default 0)
        _user_id: Authenticated user ID (injected by @check_authentication, not directly used)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance
        _rest: Hikari REST client (required for auth, not directly used)
        coc_client: Clash of Clans API client

    Returns:
        InactivePlayersResponse: Paginated list of inactive players with details

    Raises:
        HTTPException: 404 if server not found
    """
    # Verify server exists and user has access
    server = await mongo.server_db.find_one({"server": guild_id})
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Get clans to check
    if clan_tag:
        # Check specific clan
        clan_query = {"server": guild_id, "tag": clan_tag}
    else:
        # Check all server clans
        clan_query = {"server": guild_id}

    clans = await mongo.clan_db.find(clan_query).to_list(length=None)
    if not clans:
        return InactivePlayersResponse(
            guild_id=guild_id,
            inactive_threshold_days=inactive_threshold_days,
            players=[],
            total_count=0,
            limit=limit,
            offset=offset
        )

    # Prepare clan data
    clan_name_map = {clan["tag"]: clan["name"] for clan in clans}
    inactive_threshold = pend.now(tz=pend.UTC).subtract(days=inactive_threshold_days)

    # Collect inactive players from all clans
    all_inactive_players = []
    for clan in clans:
        clan_tag_check = clan["tag"]
        clan_name = clan_name_map[clan_tag_check]

        inactive_players = await process_clan_safely(
            clan_tag_check, clan_name, coc_client,
            find_inactive_players, inactive_threshold, min_townhall
        )

        if inactive_players:
            all_inactive_players.extend(inactive_players)

    # Sort by days inactive (most inactive first)
    all_inactive_players.sort(
        key=lambda p: p.days_inactive if p.days_inactive is not None else 9999,
        reverse=True
    )

    # Apply pagination
    total_count = len(all_inactive_players)
    paginated_players = all_inactive_players[offset:offset + limit]

    return InactivePlayersResponse(
        guild_id=guild_id,
        inactive_threshold_days=inactive_threshold_days,
        players=paginated_players,
        total_count=total_count,
        limit=limit,
        offset=offset
    )
