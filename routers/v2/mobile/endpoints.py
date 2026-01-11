import asyncio
from typing import Any, Dict

from fastapi import HTTPException, APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import linkd

from routers.v2.player.models import PlayerTagsRequest
from utils.utils import fix_tag
from utils.config import Config
from utils.database import MongoClient
from utils.security import check_authentication
from utils.sentry_utils import capture_endpoint_errors
from .utils import (
    fetch_players_basic_data,
    fetch_players_extended_data,
    fetch_all_clan_data,
    extract_clan_tags_from_players,
    fetch_player_war_stats,
)

security = HTTPBearer()

router = APIRouter(
    prefix='/v2/mobile', tags=['Mobile App'], include_in_schema=True
)


@router.get('/public-config', name='Get public app configuration')
async def get_public_config() -> Dict[str, Any]:
    """Get non-sensitive configuration values needed by the mobile app.

    No authentication required - only returns safe, public config values.

    Returns:
        Dict with public configuration including:
            - sentry_dsn: Sentry DSN for mobile error tracking
    """
    return {
        'sentry_dsn': Config.sentry_dsn_mobile,
    }


@router.post('/initialization', name='Initialize all account data for mobile app')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def app_initialization(
    body: PlayerTagsRequest,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> Dict[str, Any]:
    """Mobile app initialization endpoint - bulk fetches all account data in parallel.

    This endpoint replaces 8+ sequential mobile API calls with parallel server-side calls,
    significantly improving mobile app startup performance.

    Args:
        body: PlayerTagsRequest containing list of player tags
        _user_id: Authenticated user ID (injected by @check_authentication, not directly used)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)

    Returns:
        Dict containing:
            - players: Extended player data with tracking stats
            - players_basic: Basic API player data
            - clans: All clan-related data (details, stats, war logs, etc.)
            - war_stats: Player war statistics
            - clan_tags: List of unique clan tags
            - metadata: Fetch statistics

    Raises:
        HTTPException: 400 if player_tags is empty
    """
    if not body.player_tags:
        raise HTTPException(status_code=400, detail='player_tags cannot be empty')

    player_tags = [fix_tag(tag) for tag in body.player_tags]

    # Fetch both basic and extended player data in parallel
    players_basic, players_extended, war_stats_result = await asyncio.gather(
        fetch_players_basic_data(player_tags),
        fetch_players_extended_data(player_tags, mongo),
        fetch_player_war_stats(body, mongo),
    )

    # Extract clan tags from player data
    clan_tags_list = extract_clan_tags_from_players(players_basic)

    # If no clans found, return early with player data only
    if not clan_tags_list:
        return {
            'players': players_basic,
            'players_basic': players_basic,
            'clans': {
                'clan_details': {},
                'clan_stats': {},
                'war_data': [],
                'join_leave_data': {},
                'capital_data': [],
                'war_log_data': [],
                'clan_war_stats': [],
                'cwl_data': [],
            },
            'war_stats': war_stats_result.get('items', []),
            'clan_tags': [],
            'metadata': {
                'total_players': len(player_tags),
                'total_clans': 0,
                'fetch_time': 'endpoint_calls',
            },
        }

    # Fetch all clan-related data in parallel
    clan_data = await fetch_all_clan_data(clan_tags_list, mongo)

    # Structure the final response
    return {
        'players': players_extended,
        'players_basic': players_basic,
        'clans': {
            **clan_data,
            'clan_stats': {},  # Reserved for future use
            'cwl_data': [],  # Reserved for future use
        },
        'war_stats': war_stats_result.get('items', []),
        'clan_tags': clan_tags_list,
        'metadata': {
            'total_players': len(player_tags),
            'total_clans': len(clan_tags_list),
            'fetch_time': 'endpoint_calls',
        },
    }
