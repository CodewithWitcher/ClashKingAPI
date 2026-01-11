import re
import linkd.ext.fastapi
from fastapi import APIRouter, Query, Request
from utils.utils import fix_tag
from utils.security import check_authentication
from utils.database import MongoClient
from utils.custom_coc import CustomClashClient

from routers.v2.search.utils import (
    build_clan_dict,
    determine_search_type,
    fetch_user_search_data,
    fetch_guild_clans,
    fetch_local_clans,
    fetch_clan_from_api,
    filter_clans_by_query,
    sort_clans_by_type,
    update_bookmark,
    update_recent_search,
    create_group,
    get_group,
    add_api_search_results,
    TYPE_FIELD_MAP
)

router = APIRouter(prefix="/v2", tags=["Search"], include_in_schema=True)


@router.get("/search/clan", name="Search for a clan by name or tag")
@linkd.ext.fastapi.inject
async def search_clan(
        query: str = Query(default=""),
        _request: Request = Request,
        user_id: int = 0,
        guild_id: int = 0,
        *,
        mongo: Mongo,
        coc_client: CustomClashClient
):
    """Search for clans using various sources.

    Returns results from:
    - User's recent searches (up to 5)
    - User's bookmarks (up to 20)
    - Guild-linked clans
    - Clash of Clans API search

    Args:
        query: Search query (clan name or tag)
        _request: FastAPI request object
        user_id: Discord user ID for personalized results
        guild_id: Discord guild ID for guild clan filtering
        mongo: MongoDB client instance (injected)
        coc_client: Clash of Clans API client (injected)

    Returns:
        Dictionary with "items" list of clan data
    """
    # Fetch user's search history
    recent_tags, bookmarked_tags = await fetch_user_search_data(user_id, mongo)

    # Fetch guild clans
    guild_clans = await fetch_guild_clans(guild_id, query, mongo)

    # Combine all tags
    all_tags = set(recent_tags + bookmarked_tags + guild_clans)

    # Fetch clan data from local database
    local_search = await fetch_local_clans(list(all_tags), mongo)

    # Build results from local data
    final_data = []
    for result in local_search:
        tag = result.get("tag")
        find_type = determine_search_type(tag, bookmarked_tags, recent_tags)
        final_data.append(build_clan_dict(result, find_type))
        all_tags.discard(tag)

    # Fetch remaining clans from API
    for tag in all_tags:
        clan = await fetch_clan_from_api(coc_client, tag)
        if not clan:
            continue

        find_type = determine_search_type(tag, bookmarked_tags, recent_tags)
        final_data.append(build_clan_dict(clan, find_type))

    # Filter by query
    final_data = filter_clans_by_query(final_data, query)
    tags_found = {d.get("tag") for d in final_data}

    # Add API search results if needed
    await add_api_search_results(final_data, tags_found, query, coc_client)

    # Sort by type priority
    final_data = sort_clans_by_type(final_data)

    return {"items": final_data}


@router.get("/search/{guild_id}/banned-players", name="Search for a banned player")
@linkd.ext.fastapi.inject
@check_authentication
async def search_banned_players(
        query: str = Query(default=""),
        guild_id: int = 0,
        _request: Request = Request,
        *,
        mongo: Mongo
):
    """Search for banned players in a guild.

    Args:
        query: Player name search query
        guild_id: Discord guild ID
        _request: FastAPI request object
        mongo: MongoDB client instance (injected)

    Returns:
        Dictionary with "items" list of banned player data
    """
    query_escaped = re.escape(query)

    if query_escaped == '':
        docs = await mongo.banlist.find({'server': guild_id}, limit=25).to_list(length=25)
    else:
        docs = await mongo.banlist.find(
            {
                '$and': [
                    {'server': guild_id},
                    {'VillageName': {'$regex': f'^(?i).*{query_escaped}.*$'}},
                ]
            },
            limit=25,
        ).to_list(length=25)

    return {"items": [{"tag": doc["VillageTag"], "name": doc.get("VillageName", "Missing")} for doc in docs]}


@router.post("/search/bookmark/{user_id}/{search_type}/{tag}",
             name="Add a bookmark for a clan or player for a user")
@linkd.ext.fastapi.inject
@check_authentication
async def bookmark_search(
        user_id: int,
        search_type: int,
        tag: str,
        _request: Request = Request,
        *,
        mongo: Mongo
):
    """Add or update a bookmark for a user.

    Args:
        user_id: Discord user ID
        search_type: Type ID (0=player, 1=clan)
        tag: Clan or player tag to bookmark
        _request: FastAPI request object
        mongo: MongoDB client instance (injected)

    Returns:
        Success status
    """
    type_field = TYPE_FIELD_MAP.get(search_type, "clan")
    await update_bookmark(user_id, type_field, tag, mongo)
    return {"success": True}


@router.post("/search/recent/{user_id}/{search_type}/{tag}",
             name="Add a recent search for a clan or player for a user")
@linkd.ext.fastapi.inject
@check_authentication
async def recent_search(
        user_id: int,
        search_type: int,
        tag: str,
        _request: Request = Request,
        *,
        mongo: Mongo
):
    """Add a tag to user's recent searches.

    Args:
        user_id: Discord user ID
        search_type: Type ID (0=player, 1=clan)
        tag: Clan or player tag to add
        _request: FastAPI request object
        mongo: MongoDB client instance (injected)

    Returns:
        Success status
    """
    type_field = TYPE_FIELD_MAP.get(search_type, "clan")
    await update_recent_search(user_id, type_field, tag, mongo)
    return {"success": True}


@router.post("/search/groups/create/{user_id}/{name}/{search_type}",
             name="Create a player or clan group")
@linkd.ext.fastapi.inject
@check_authentication
async def group_create(
        user_id: int,
        name: str,
        search_type: int,
        _request: Request = Request,
        *,
        mongo: Mongo
):
    """Create a new group for organizing clans or players.

    Args:
        user_id: Discord user ID
        name: Group name
        search_type: Type ID (0=player, 1=clan)
        _request: FastAPI request object
        mongo: MongoDB client instance (injected)

    Returns:
        Success status
    """
    type_field = TYPE_FIELD_MAP.get(search_type, "clan")
    await create_group(user_id, name, type_field, mongo)
    return {"success": True}


@router.post("/search/groups/{group_id}/add/{tag}",
             name="Add a player or clan to a group")
@linkd.ext.fastapi.inject
@check_authentication
async def group_add(
        group_id: str,
        tag: str,
        _request: Request = Request,
        *,
        mongo: MongoClient
):
    """Add a tag to a group.

    Args:
        group_id: Group ID
        tag: Clan or player tag to add
        _request: FastAPI request object

    Returns:
        Success status
    """
    await mongo.groups.update_one(
        {"group_id": group_id},
        {"$addToSet": {"tags": fix_tag(tag)}}
    )
    return {"success": True}


@router.post("/search/groups/{group_id}/remove/{tag}",
             name="Remove a player or clan from a group")
@linkd.ext.fastapi.inject
@check_authentication
async def group_remove(
        group_id: str,
        tag: str,
        _request: Request = Request,
        *,
        mongo: MongoClient
):
    """Remove a tag from a group.

    Args:
        group_id: Group ID
        tag: Clan or player tag to remove
        _request: FastAPI request object

    Returns:
        Success status
    """
    await mongo.groups.update_one(
        {"group_id": group_id},
        {"$pull": {"tags": fix_tag(tag)}}
    )
    return {"success": True}


@router.get("/search/groups/{group_id}",
            name="Get a specific group")
@linkd.ext.fastapi.inject
@check_authentication
async def group_get(
        group_id: str,
        _request: Request = Request,
        *,
        mongo: MongoClient
):
    """Get details for a specific group.

    Args:
        group_id: Group ID
        _request: FastAPI request object
        mongo: MongoDB client instance (injected)

    Returns:
        Group document with tags and metadata
    """
    return await get_group(group_id, mongo)


@router.get("/search/groups/{user_id}/list",
            name="List groups for a user")
@linkd.ext.fastapi.inject
@check_authentication
async def group_list(
        user_id: int,
        _request: Request = Request,
        *,
        mongo: MongoClient
):
    """List all groups for a user.

    Args:
        user_id: Discord user ID
        _request: FastAPI request object

    Returns:
        Dictionary with "items" list of groups
    """
    groups = await mongo.groups.find({"user_id": user_id}, {"_id": 0}).to_list(length=None)
    return {"items": groups}


@router.delete("/search/groups/{group_id}",
               name="Delete a specific group")
@linkd.ext.fastapi.inject
@check_authentication
async def group_delete(
        group_id: int,
        _request: Request = Request,
        *,
        mongo: MongoClient
):
    """Delete a group.

    Args:
        group_id: Group ID
        _request: FastAPI request object

    Returns:
        Success status
    """
    await mongo.groups.delete_one({"group_id": group_id})
    return {"success": True}
