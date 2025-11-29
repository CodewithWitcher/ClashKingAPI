import logging

import hikari
import linkd
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from utils.database import MongoClient
from utils.security import check_authentication
from utils.config import Config
from utils.custom_coc import CustomClashClient
from utils.sentry_utils import capture_endpoint_errors
from .models import (
    LinkedAccount,
    MemberLinks,
    ServerLinksResponse,
    BulkUnlinkRequest
)
from coc.utils import correct_tag

logger = logging.getLogger(__name__)
config = Config()
security = HTTPBearer()

# Constants
SERVER_NOT_FOUND = "Server not found"

router = APIRouter(prefix="/v2/server", tags=["Server Links"], include_in_schema=True)


async def reorder_user_accounts(mongo: MongoClient, user_id: str) -> None:
    """Reorder remaining accounts after unlinking to maintain sequential indices.

    Args:
        mongo: MongoDB client instance
        user_id: Discord user ID whose accounts need reordering
    """
    from pymongo import UpdateOne

    remaining_accounts = await mongo.coc_accounts.find(
        {"user_id": user_id}
    ).sort("order_index", 1).to_list(length=None)

    updates = []
    for index, account in enumerate(remaining_accounts):
        updates.append(UpdateOne(
            {"_id": account["_id"]},
            {"$set": {"order_index": index}}
        ))

    if updates:
        await mongo.coc_accounts.bulk_write(updates, ordered=False)


async def get_links_aggregation(mongo: MongoClient) -> list:
    """Get all links grouped by user with aggregation statistics.

    Args:
        mongo: MongoDB client instance

    Returns:
        List of grouped links with account counts
    """
    pipeline = [
        {"$group": {
            "_id": "$user_id",
            "links": {"$push": {
                "player_tag": "$player_tag",
                "is_verified": "$is_verified",
                "added_at": "$added_at"
            }},
            "account_count": {"$sum": 1},
            "verified_count": {"$sum": {"$cond": ["$is_verified", 1, 0]}}
        }},
        {"$sort": {"account_count": -1}}
    ]

    links_by_user_cursor = await mongo.coc_accounts.aggregate(pipeline)
    return await links_by_user_cursor.to_list(length=None)


async def fetch_users_from_db(mongo: MongoClient, user_ids: list) -> dict:
    """Fetch user data from MongoDB users collection.

    Args:
        mongo: MongoDB client instance
        user_ids: List of user IDs to fetch

    Returns:
        Dictionary mapping user_id to user data
    """
    user_ids_int = []
    for uid in user_ids:
        try:
            user_ids_int.append(int(uid))
        except (ValueError, TypeError):
            user_ids_int.append(uid)

    users_data = await mongo.users.find(
        {"user_id": {"$in": user_ids_int}},
        {"_id": 0, "user_id": 1, "username": 1, "avatar_url": 1}
    ).to_list(length=None)

    return {str(user["user_id"]): user for user in users_data}


async def fetch_missing_members_from_discord(rest, server_id: int, missing_user_ids: list, bot_token: str) -> dict:
    """Fetch member data from Discord API for users not in database.

    Args:
        rest: Hikari REST client
        server_id: Discord server ID
        missing_user_ids: List of user IDs to fetch from Discord
        bot_token: Bot authentication token

    Returns:
        Dictionary mapping user_id to Discord member object
    """
    members_dict = {}
    if not missing_user_ids or not bot_token:
        return members_dict

    async with rest.acquire(token=bot_token, token_type=hikari.TokenType.BOT) as client:
        for user_id in missing_user_ids:
            try:
                member = await client.fetch_member(server_id, int(user_id))
                members_dict[user_id] = member
            except (hikari.NotFoundError, hikari.ForbiddenError):
                continue
            except Exception as e:
                logger.warning(f"Error fetching member {user_id}: {e}")

    return members_dict


def build_member_links_object(group: dict, users_dict: dict, members_dict: dict) -> MemberLinks:
    """Build MemberLinks object from grouped data.

    Args:
        group: Grouped link data with user_id and links
        users_dict: User data from MongoDB
        members_dict: Member data from Discord API

    Returns:
        MemberLinks object with all data populated
    """
    user_id = group["_id"]

    # Build linked accounts list
    linked_accounts = []
    for link in group["links"]:
        linked_accounts.append(LinkedAccount(
            player_tag=link["player_tag"],
            player_name=None,
            town_hall=None,
            is_verified=link.get("is_verified", False),
            added_at=str(link.get("added_at")) if link.get("added_at") else None
        ))

    # Get Discord user info - try MongoDB first, then Discord API
    user_data = users_dict.get(user_id)
    member = members_dict.get(user_id)

    if member:
        username = member.user.username
        display_name = member.nickname or member.user.username
        avatar_url = str(member.user.avatar_url) if member.user.avatar_url else None
    elif user_data:
        username = user_data.get("username", f"User {user_id}")
        display_name = username
        avatar_url = user_data.get("avatar_url")
    else:
        username = f"User {user_id}"
        display_name = f"User {user_id}"
        avatar_url = None

    return MemberLinks(
        user_id=user_id,
        username=username,
        display_name=display_name,
        avatar_url=avatar_url,
        linked_accounts=linked_accounts,
        account_count=len(linked_accounts)
    )

@router.get("/{server_id}/links", name="Get all member links for a server")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_server_links(
        server_id: int,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        rest: hikari.RESTApp,
        _coc_client: CustomClashClient = None  # Not used, kept for injection compatibility
) -> ServerLinksResponse:
    """Get all Discord members in a server with their linked CoC accounts.

    Uses Discord's fetch_members() API to efficiently retrieve member info.
    Only fetches members that have linked accounts (early exit optimization).
    Supports pagination and search by player tags.

    Args:
        server_id: Discord server ID
        limit: Maximum number of results per page (default: 100)
        offset: Offset for pagination (default: 0)
        search: Optional search query to filter by player tags
        _user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth)
        mongo: MongoDB client instance
        rest: Discord REST client for fetching member info
        _coc_client: Clash of Clans client (not used)

    Returns:
        ServerLinksResponse with members and their linked accounts

    Raises:
        HTTPException: 404 if server not found
        HTTPException: 401 if bot token invalid
        HTTPException: 500 if server error occurs
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    try:
        # Get all links grouped by user with statistics
        links_grouped = await get_links_aggregation(mongo)

        # Calculate total stats
        total_linked_accounts = sum(group["account_count"] for group in links_grouped)
        verified_accounts = sum(group["verified_count"] for group in links_grouped)
        total_members_with_links = len(links_grouped)

        # Apply search filter if provided (on player tags only, since we don't have Discord info yet)
        if search:
            search_lower = search.lower()
            links_grouped = [
                group for group in links_grouped
                if any(search_lower in link["player_tag"].lower() for link in group["links"])
            ]

        # Apply pagination on the grouped results
        total_filtered = len(links_grouped)
        paginated_groups = links_grouped[offset:offset + limit]

        # Strategy: MongoDB first (fast), then Discord API for missing members
        user_ids_to_fetch = [group["_id"] for group in paginated_groups]

        # Step 1: Try MongoDB first (cached user info from auth)
        users_dict = await fetch_users_from_db(mongo, user_ids_to_fetch)

        # Step 2: For users not in MongoDB, fetch from Discord API
        missing_user_ids = [uid for uid in user_ids_to_fetch if uid not in users_dict]
        members_dict = await fetch_missing_members_from_discord(rest, server_id, missing_user_ids, config.bot_token)

        # Build the response for paginated results
        member_links_list = []
        for group in paginated_groups:
            member_links_list.append(build_member_links_object(group, users_dict, members_dict))

        paginated_members = member_links_list
        members_with_links = total_members_with_links

        return ServerLinksResponse(
            members=paginated_members,
            total_members=total_filtered,
            members_with_links=members_with_links,
            total_linked_accounts=total_linked_accounts,
            verified_accounts=verified_accounts
        )

    except HTTPException:
        raise
    except Exception as e:
        # Log the full exception for debugging
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch server links: {str(e)}"
        )

@router.delete("/{server_id}/links/{user_discord_id}/{player_tag}", name="Unlink account from member")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def unlink_member_account(
        server_id: int,
        user_discord_id: str,
        player_tag: str,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp = None
) -> dict:
    """
    Unlink a specific CoC account from a Discord member.
    Requires manage server permissions (handled by @check_authentication).
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Normalize player tag
    normalized_tag = correct_tag(tag=player_tag)

    # Delete the link
    result = await mongo.coc_accounts.delete_one({
        "user_id": user_discord_id,
        "player_tag": normalized_tag
    })

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Link not found or already removed"
        )

    # Reorder remaining accounts for this user
    await reorder_user_accounts(mongo, user_discord_id)

    return {
        "message": "Account unlinked successfully",
        "player_tag": normalized_tag,
        "user_id": user_discord_id
    }

@router.post("/{server_id}/links/bulk-unlink", name="Bulk unlink accounts from member")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def bulk_unlink_accounts(
        server_id: int,
        request: BulkUnlinkRequest,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp = None
) -> dict:
    """
    Unlink multiple CoC accounts from a Discord member at once.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Normalize all tags
    normalized_tags = [correct_tag(tag=tag) for tag in request.player_tags]

    # Delete all specified links
    result = await mongo.coc_accounts.delete_many({
        "user_id": request.user_id,
        "player_tag": {"$in": normalized_tags}
    })

    # Reorder remaining accounts
    await reorder_user_accounts(mongo, request.user_id)

    return {
        "message": f"{result.deleted_count} accounts unlinked successfully",
        "deleted_count": result.deleted_count,
        "user_id": request.user_id
    }