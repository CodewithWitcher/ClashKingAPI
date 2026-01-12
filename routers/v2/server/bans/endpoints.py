import pendulum as pend
import linkd
import coc
import hikari
from fastapi import HTTPException, APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from utils.utils import remove_id_fields, to_str, fix_tag
from utils.database import MongoClient
from utils.custom_coc import CustomClashClient
from utils.security import check_authentication
from utils.config import Config
from utils.cache_decorator import cache_endpoint
from .models import BanRequest

router = APIRouter(prefix="/v2/server", tags=["Server Bans"], include_in_schema=True)
security = HTTPBearer()


@cache_endpoint(ttl=120, key_prefix="server_members_bans")
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


def convert_ban_user_ids(bans: list) -> list:
    """Convert user ID fields to strings to preserve precision in JSON"""
    for ban in bans:
        if 'added_by' in ban:
            ban['added_by'] = to_str(ban['added_by'])
        # Also handle edited_by which may contain user IDs
        if 'edited_by' in ban and isinstance(ban['edited_by'], list):
            for edit in ban['edited_by']:
                if 'user' in edit:
                    edit['user'] = to_str(edit['user'])
    return bans


@router.get("/{server_id}/bans",
            name="Get bans for a server")
@linkd.ext.fastapi.inject
@check_authentication
async def get_bans(
    server_id: int,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    rest: hikari.RESTApp,
    config: Config
):
    bans = await mongo.banlist.find({'server': server_id}).sort([("_id", -1)]).to_list(length=None)
    bans = convert_ban_user_ids(bans)

    # Get Discord members with caching (120s TTL)
    members_dict = await get_server_members_with_cache(rest, server_id, config.bot_token)

    # Enrich bans with Discord user info
    for ban in bans:
        if 'added_by' in ban:
            # Ensure added_by is a string (already converted by convert_ban_user_ids, but double-check)
            ban['added_by'] = to_str(ban['added_by'])
            user_id = str(ban['added_by'])
            if user_id in members_dict:
                ban['added_by_username'] = members_dict[user_id].get('username')
                ban['added_by_avatar_url'] = members_dict[user_id].get('avatar_url')

    # Ensure added_by remains as string after remove_id_fields (which uses json_util)
    result = remove_id_fields({"items": bans, "count": len(bans)})
    
    # Re-convert added_by to string in case json_util converted it back to number
    if 'items' in result:
        for ban in result['items']:
            if 'added_by' in ban:
                ban['added_by'] = to_str(ban['added_by'])
            # Also handle edited_by
            if 'edited_by' in ban and isinstance(ban['edited_by'], list):
                for edit in ban['edited_by']:
                    if 'user' in edit:
                        edit['user'] = to_str(edit['user'])
    
    return result


@router.post("/{server_id}/bans/{player_tag}",
             name="Add or update a ban")
@linkd.ext.fastapi.inject
@check_authentication
async def add_ban(
    server_id: int,
    player_tag: str,
    ban_data: BanRequest,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    coc_client: CustomClashClient
):
    """Add or update a ban for a player in a specific server"""
    # Normalize player tag to ensure it has # prefix
    normalized_tag = fix_tag(player_tag)
    
    # Verify player exists and get player name from COC API
    try:
        player = await coc_client.get_player(normalized_tag)
        player_name = player.name
    except coc.NotFound:
        raise HTTPException(status_code=404, detail=f"Player {normalized_tag} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch player info: {str(e)}")

    find_ban = await mongo.banlist.find_one({'VillageTag': normalized_tag, 'server': server_id})

    if find_ban:
        print("Updating existing ban entry: ", normalized_tag, player_name)
        # Update existing ban
        await mongo.banlist.update_one(
            {'VillageTag': normalized_tag, 'server': server_id},
            {
                '$set': {'Notes': ban_data.reason},
                '$push': {
                    'edited_by': {
                        'user': ban_data.added_by,
                        'previous': {
                            'reason': find_ban.get('Notes'),
                        },
                    }
                },
            }
        )
        return {"status": "updated", "player_tag": normalized_tag, "player_name": player_name, "server_id": server_id}
    else:
        # Insert new ban - use normalized tag with #
        ban_entry = {
            'VillageTag': normalized_tag,  # Store tag with # prefix
            'VillageName': player_name,
            'DateCreated': pend.now("UTC").format("YYYY-MM-DD HH:mm:ss"),
            'Notes': ban_data.reason,
            'server': server_id,
            'added_by': ban_data.added_by,
            'image': ban_data.image,
        }
        await mongo.banlist.insert_one(ban_entry)
        return {"status": "created", "player_tag": normalized_tag, "player_name": player_name, "server_id": server_id}



@router.delete("/{server_id}/bans/{player_tag}",
               name="Remove a ban")
@linkd.ext.fastapi.inject
@check_authentication
async def remove_ban(
    server_id: int,
    player_tag: str,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
):
    """Delete a ban for a player in a specific server"""
    # Normalize player tag to ensure it has # prefix
    normalized_tag = fix_tag(player_tag)

    results = await mongo.banlist.find_one({'$and': [{'VillageTag': normalized_tag}, {'server': server_id}]})
    if not results:
        raise HTTPException(status_code=404, detail=f"Player {normalized_tag} is not banned on server {server_id}.")

    await mongo.banlist.find_one_and_delete({'$and': [{'VillageTag': normalized_tag}, {'server': server_id}]})
    return {"status": "deleted", "player_tag": normalized_tag, "server_id": server_id}