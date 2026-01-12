import secrets
import string
import pendulum as pend
from datetime import timedelta
import hikari
from fastapi import HTTPException, APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import linkd

from utils.database import MongoClient
from utils.security import check_authentication
from utils.utils import remove_id_fields, to_str
from utils.config import Config
from utils.cache_decorator import cache_endpoint
from .models import StrikeRequest

router = APIRouter(prefix="/v2/server", tags=["Server Strikes"], include_in_schema=True)
security = HTTPBearer()


@cache_endpoint(ttl=120, key_prefix="server_members_strikes")
async def get_server_members_with_cache(rest: hikari.RESTApp, server_id: int, bot_token: str) -> dict:
    """Fetch all members for a Discord server with caching.

    Args:
        rest: Hikari REST client
        server_id: Discord server ID
        bot_token: Bot authentication token

    Returns:
        Dictionary mapping user_id (str) to member object with username and avatar
    """
    members_dict = {}
    if not bot_token:
        return members_dict

    try:
        async with rest.acquire(token=bot_token, token_type=hikari.TokenType.BOT) as client:
            async for member in client.fetch_members(server_id):
                user_id = str(member.user.id)
                display_name = member.nickname or member.user.username
                avatar_url = str(member.user.make_avatar_url()) if member.user.avatar_hash else None

                members_dict[user_id] = {
                    'username': display_name,
                    'avatar_url': avatar_url
                }
    except Exception as e:
        print(f"Error fetching server members for {server_id}: {e}")

    return members_dict


def convert_strike_user_ids(strikes: list) -> list:
    """Convert user ID fields to strings to preserve precision in JSON"""
    for strike in strikes:
        if 'added_by' in strike:
            strike['added_by'] = to_str(strike['added_by'])
    return strikes


@router.get("/{server_id}/strikes",
            name="Get strikes for a server")
@linkd.ext.fastapi.inject
@check_authentication
async def get_strikes(
    server_id: int,
    player_tag: str = None,
    view_expired: bool = False,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    rest: hikari.RESTApp,
    config: Config
):
    """
    Get all strikes for a server, optionally filtered by player tag.

    Args:
        server_id: Discord server ID
        player_tag: Optional player tag to filter strikes
        view_expired: Include expired strikes (default: False)
        _user_id: Authenticated user ID (injected by decorator)
        _credentials: HTTP bearer credentials (injected by FastAPI)
        mongo: MongoDB client (injected by linkd)

    Returns:
        List of strikes
    """
    # Build query
    query = {"server": server_id}

    if player_tag:
        query["tag"] = player_tag

    # Filter out expired strikes unless requested
    if not view_expired:
        gte = int(pend.now(tz=pend.UTC).timestamp())
        query["$or"] = [
            {"rollover_date": None},
            {"rollover_date": {"$gte": gte}}
        ]

    strikes = await mongo.strike_list.find(query).sort("date_created", -1).to_list(length=None)
    strikes = convert_strike_user_ids(strikes)

    # Get Discord members with caching (120s TTL)
    members_dict = await get_server_members_with_cache(rest, server_id, config.bot_token)

    # Enrich strikes with Discord user info
    for strike in strikes:
        if 'added_by' in strike:
            user_id = str(strike['added_by'])
            if user_id in members_dict:
                strike['added_by_username'] = members_dict[user_id].get('username')
                strike['added_by_avatar_url'] = members_dict[user_id].get('avatar_url')

    return remove_id_fields({"items": strikes, "count": len(strikes)})


@router.post("/{server_id}/strikes/{player_tag}",
             name="Add a strike to a player")
@linkd.ext.fastapi.inject
@check_authentication
async def add_strike(
    server_id: int,
    player_tag: str,
    strike_data: StrikeRequest,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
):
    """
    Add a strike to a player on a server.

    Args:
        server_id: Discord server ID
        player_tag: Player tag to strike
        strike_data: Strike details (reason, added_by, etc.)
        _user_id: Authenticated user ID (injected by decorator)
        _credentials: HTTP bearer credentials (injected by FastAPI)
        mongo: MongoDB client (injected by linkd)

    Returns:
        Created strike information
    """
    now = pend.now(tz=pend.UTC)
    dt_string = now.strftime('%Y-%m-%d %H:%M:%S')

    # Generate unique strike ID using cryptographically secure random
    source = string.ascii_letters
    strike_id = ''.join(secrets.choice(source) for _ in range(5)).upper()

    # Ensure uniqueness
    is_used = await mongo.strike_list.find_one({'strike_id': strike_id})
    while is_used is not None:
        strike_id = ''.join(secrets.choice(source) for _ in range(5)).upper()
        is_used = await mongo.strike_list.find_one({'strike_id': strike_id})

    # Calculate rollover date if specified
    rollover_timestamp = None
    if strike_data.rollover_days is not None:
        rollover_date = now + timedelta(days=strike_data.rollover_days)
        rollover_timestamp = int(rollover_date.timestamp())

    # Create strike entry
    strike_entry = {
        'tag': player_tag,
        'date_created': dt_string,
        'reason': strike_data.reason,
        'server': server_id,
        'added_by': strike_data.added_by,
        'strike_weight': strike_data.strike_weight,
        'rollover_date': rollover_timestamp,
        'strike_id': strike_id,
    }

    if strike_data.image:
        strike_entry['image'] = strike_data.image

    await mongo.strike_list.insert_one(strike_entry)

    # Get total strikes for this player
    gte = int(pend.now(tz=pend.UTC).timestamp())
    total_strikes = await mongo.strike_list.find({
        '$and': [
            {'tag': player_tag},
            {'server': server_id},
            {
                '$or': [
                    {'rollover_date': None},
                    {'rollover_date': {'$gte': gte}}
                ]
            }
        ]
    }).to_list(length=None)

    total_weight = sum([s.get('strike_weight', 1) for s in total_strikes])

    return {
        "status": "created",
        "strike_id": strike_id,
        "player_tag": player_tag,
        "server_id": server_id,
        "total_strikes": len(total_strikes),
        "total_weight": total_weight
    }


@router.delete("/{server_id}/strikes/{strike_id}",
               name="Remove a strike by ID")
@linkd.ext.fastapi.inject
@check_authentication
async def remove_strike(
    server_id: int,
    strike_id: str,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
):
    """
    Remove a strike by its ID.

    Args:
        server_id: Discord server ID
        strike_id: Strike ID to remove
        _user_id: Authenticated user ID (injected by decorator)
        _credentials: HTTP bearer credentials (injected by FastAPI)
        mongo: MongoDB client (injected by linkd)

    Returns:
        Deletion confirmation
    """
    strike_id = strike_id.upper()

    # Check if strike exists
    strike = await mongo.strike_list.find_one({
        '$and': [
            {'strike_id': strike_id},
            {'server': server_id}
        ]
    })

    if not strike:
        raise HTTPException(
            status_code=404,
            detail=f"Strike with ID {strike_id} not found on server {server_id}"
        )

    # Delete the strike
    await mongo.strike_list.delete_one({
        '$and': [
            {'strike_id': strike_id},
            {'server': server_id}
        ]
    })

    return {
        "status": "deleted",
        "strike_id": strike_id,
        "player_tag": strike.get('tag'),
        "server_id": server_id
    }


@router.get("/{server_id}/strikes/player/{player_tag}/summary",
            name="Get strike summary for a player")
@linkd.ext.fastapi.inject
@check_authentication
async def get_player_strike_summary(
    server_id: int,
    player_tag: str,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
):
    """
    Get a summary of active strikes for a specific player.

    Args:
        server_id: Discord server ID
        player_tag: Player tag
        _user_id: Authenticated user ID (injected by decorator)
        _credentials: HTTP bearer credentials (injected by FastAPI)
        mongo: MongoDB client (injected by linkd)

    Returns:
        Strike summary with total count and weight
    """
    gte = int(pend.now(tz=pend.UTC).timestamp())

    strikes = await mongo.strike_list.find({
        '$and': [
            {'tag': player_tag},
            {'server': server_id},
            {
                '$or': [
                    {'rollover_date': None},
                    {'rollover_date': {'$gte': gte}}
                ]
            }
        ]
    }).sort("date_created", -1).to_list(length=None)
    strikes = convert_strike_user_ids(strikes)

    total_weight = sum([s.get('strike_weight', 1) for s in strikes])

    return {
        "player_tag": player_tag,
        "server_id": server_id,
        "total_strikes": len(strikes),
        "total_weight": total_weight,
        "strikes": remove_id_fields({"items": strikes})["items"]
    }
