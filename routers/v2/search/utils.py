import coc
import pendulum as pend
from hashids import Hashids
from fastapi import HTTPException

from utils.database import MongoClient
from utils.utils import fix_tag

# Constants
GROUP_NOT_FOUND = "Group not found"
GROUP_ALREADY_EXISTS = "Group already exists"
SEARCH_TYPE_BOOKMARKED = "bookmarked"
SEARCH_TYPE_RECENT = "recent_search"
SEARCH_TYPE_GUILD = "guild_search"
SEARCH_TYPE_RESULT = "search_result"

# Type field mapping
TYPE_FIELD_MAP = {
    0: "player",
    1: "clan"
}


def build_clan_dict(clan, find_type: str) -> dict:
    """Build standardized clan dictionary.

    Args:
        clan: Clan object or dict with clan data
        find_type: Type of search result (bookmarked, recent_search, etc.)

    Returns:
        Dictionary with standardized clan data
    """
    if isinstance(clan, dict):
        return {
            "name": clan.get("name") or "Not Stored",
            "tag": clan.get("tag"),
            "memberCount": clan.get("members") or 0,
            "level": clan.get("level") or 0,
            "warLeague": clan.get("warLeague") or "Unranked",
            "type": find_type
        }
    else:
        # It's a coc.Clan object
        return {
            "name": clan.name,
            "tag": clan.tag,
            "memberCount": clan.member_count,
            "level": clan.level,
            "warLeague": clan.war_league.name,
            "type": find_type
        }


def determine_search_type(tag: str, bookmarked_tags: list, recent_tags: list) -> str:
    """Determine the search type for a tag.

    Args:
        tag: Clan/player tag
        bookmarked_tags: List of bookmarked tags
        recent_tags: List of recent search tags

    Returns:
        Search type string
    """
    if tag in bookmarked_tags:
        return SEARCH_TYPE_BOOKMARKED
    elif tag in recent_tags:
        return SEARCH_TYPE_RECENT
    else:
        return SEARCH_TYPE_GUILD


async def fetch_user_search_data(user_id: int, mongo: MongoClient) -> tuple[list, list]:
    """Fetch user's recent searches and bookmarks.

    Args:
        user_id: Discord user ID
        mongo: MongoDB client instance

    Returns:
        Tuple of (recent_tags, bookmarked_tags)
    """
    if not user_id:
        return [], []

    result = await mongo.user_settings.find_one(
        {"discord_user": user_id},
        {"search.clan": 1, "_id": 0}
    )
    if not result:
        return [], []

    search_data = result.get("search", {}).get("clan", {})
    recent_tags = search_data.get("recent", [])
    bookmarked_tags = search_data.get("bookmarked", [])

    return recent_tags, bookmarked_tags


async def fetch_guild_clans(guild_id: int, query: str, mongo: MongoClient) -> list:
    """Fetch clans linked to a guild, optionally filtered by query.

    Args:
        guild_id: Discord guild ID
        query: Search query string
        mongo: MongoDB client instance

    Returns:
        List of clan tags
    """
    if not guild_id:
        return []

    if len(query) <= 1:
        pipeline = [
            {'$match': {'server': guild_id}},
            {'$sort': {'name': 1}},
            {'$limit': 25},
        ]
    else:
        pipeline = [
            {
                '$search': {
                    'index': 'clan_name',
                    'autocomplete': {
                        'query': query,
                        'path': 'name',
                    },
                }
            },
            {'$match': {'server': guild_id}},
        ]

    cursor = await mongo.clan_db.aggregate(pipeline=pipeline)
    results = await cursor.to_list(length=None)
    return [doc.get("tag") for doc in results]


async def fetch_local_clans(tags: list, mongo: MongoClient) -> list:
    """Fetch clan data from local database.

    Args:
        tags: List of clan tags to fetch
        mongo: MongoDB client instance

    Returns:
        List of clan documents
    """
    return await mongo.basic_clan.find(
        {"tag": {"$in": tags}},
        {"name": 1, "tag": 1, "members": 1, "level": 1, "warLeague": 1}
    ).to_list(length=None)


async def fetch_clan_from_api(coc_client: coc.Client, tag: str):
    """Safely fetch clan from CoC API.

    Args:
        coc_client: Clash of Clans API client
        tag: Clan tag

    Returns:
        Clan object or None if not found
    """
    try:
        return await coc_client.get_clan(tag=tag)
    except Exception:
        return None


async def search_clans_by_name(coc_client: coc.Client, query: str, limit: int = 10) -> list:
    """Search for clans by name using CoC API.

    Args:
        coc_client: Clash of Clans API client
        query: Search query
        limit: Maximum results to return

    Returns:
        List of clan objects
    """
    try:
        return await coc_client.search_clans(name=query, limit=limit)
    except Exception:
        return []


def filter_clans_by_query(clans: list, query: str) -> list:
    """Filter clans by query string (name or tag).

    Args:
        clans: List of clan dictionaries
        query: Search query

    Returns:
        Filtered list of clans
    """
    if not query:
        return clans

    query_lower = query.lower()
    return [
        clan for clan in clans
        if query_lower in clan.get("name", "").lower() or
        query_lower == clan.get("tag", "").lower()
    ]


def sort_clans_by_type(clans: list) -> list:
    """Sort clans by search type priority.

    Args:
        clans: List of clan dictionaries

    Returns:
        Sorted list of clans
    """
    type_order = {
        SEARCH_TYPE_RECENT: 0,
        SEARCH_TYPE_BOOKMARKED: 1,
        SEARCH_TYPE_GUILD: 2,
        SEARCH_TYPE_RESULT: 3
    }
    return sorted(clans, key=lambda x: type_order.get(x["type"], 99))


async def update_bookmark(user_id: int, type_field: str, tag: str, mongo: MongoClient) -> None:
    """Add or move a tag to the front of user's bookmarks.

    Args:
        user_id: Discord user ID
        type_field: Type field ("player" or "clan")
        tag: Clan/player tag to bookmark
        mongo: MongoDB client instance
    """
    tag = fix_tag(tag)

    # Remove if exists
    await mongo.user_settings.update_one(
        {"discord_user": user_id},
        {"$pull": {f"search.{type_field}.bookmarked": tag}}
    )

    # Add to front with limit of 20
    await mongo.user_settings.update_one(
        {"discord_user": user_id},
        {"$push": {f"search.{type_field}.bookmarked": {"$each": [tag], "$position": 0, "$slice": 20}}}
    )


async def update_recent_search(user_id: int, type_field: str, tag: str, mongo: MongoClient) -> None:
    """Add or move a tag to the front of user's recent searches.

    Args:
        user_id: Discord user ID
        type_field: Type field ("player" or "clan")
        tag: Clan/player tag to add to recent
        mongo: MongoDB client instance
    """
    tag = fix_tag(tag)

    # Remove if exists
    await mongo.user_settings.update_one(
        {"discord_user": user_id},
        {"$pull": {"search.clan.recent": tag}}
    )

    # Add to front with limit of 20
    await mongo.user_settings.update_one(
        {"discord_user": user_id},
        {"$push": {f"search.{type_field}.recent": {"$each": [tag], "$position": 0, "$slice": 20}}}
    )


async def create_group(user_id: int, name: str, type_field: str, mongo: MongoClient) -> str:
    """Create a new player or clan group.

    Args:
        user_id: Discord user ID
        name: Group name
        type_field: Group type ("player" or "clan")
        mongo: MongoDB client instance

    Returns:
        Generated group ID

    Raises:
        HTTPException: 400 if group already exists
    """
    # Check if group exists
    group = await mongo.groups.find_one(
        {"$and": [
            {"user_id": user_id},
            {"type": type_field},
            {"name": name}
        ]},
        {"_id": 0}
    )

    if group:
        raise HTTPException(status_code=400, detail=GROUP_ALREADY_EXISTS)

    # Generate unique ID
    hashids = Hashids(min_length=7)
    custom_id = hashids.encode(user_id + pend.now(tz=pend.UTC).int_timestamp)

    # Create group
    await mongo.groups.insert_one({
        "group_id": custom_id,
        "user_id": user_id,
        "type": type_field,
        "tags": []
    })

    return custom_id


async def get_group(group_id: str, mongo: MongoClient) -> dict:
    """Get a specific group by ID.

    Args:
        group_id: Group ID
        mongo: MongoDB client instance

    Returns:
        Group document

    Raises:
        HTTPException: 404 if group not found
    """
    group = await mongo.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(status_code=404, detail=GROUP_NOT_FOUND)
    return group


async def add_api_search_results(
    final_data: list, tags_found: set, query: str, coc_client: coc.Client
) -> None:
    """Add API search results to final_data if needed.

    Args:
        final_data: List to append results to
        tags_found: Set of tags already in results
        query: Search query string
        coc_client: Clash of Clans API client
    """
    if len(final_data) >= 25 or len(query) < 3:
        return

    clan = None
    if coc.utils.is_valid_tag(query):
        clan = await fetch_clan_from_api(coc_client, query)

    if clan is None:
        results = await search_clans_by_name(coc_client, query, limit=10)
        for clan in results:
            if clan.tag in tags_found:
                continue
            final_data.append(build_clan_dict(clan, SEARCH_TYPE_RESULT))
    else:
        final_data.append(build_clan_dict(clan, SEARCH_TYPE_RESULT))
