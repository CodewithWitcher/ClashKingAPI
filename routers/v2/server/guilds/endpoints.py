import hikari
import linkd
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List

from utils.database import MongoClient
from utils.security import check_authentication
from routers.v2.auth.utils import get_valid_discord_access_token
from utils.config import Config
from .models import GuildInfo, GuildDetails

config = Config()

security = HTTPBearer()
router = APIRouter(prefix="/v2/guilds", tags=["Guilds"], include_in_schema=True)
guild_router = APIRouter(prefix="/v2/guild", tags=["Guild"], include_in_schema=True)


def get_user_role_in_guild(guild) -> str:
    """Determine user's role in a guild based on permissions.

    Args:
        guild: Discord guild object with permissions

    Returns:
        Role name: "Owner", "Administrator", "Manager", or "Member"
    """
    is_owner = getattr(guild, 'is_owner', False)
    if is_owner:
        return "Owner"

    perms = getattr(guild, 'my_permissions', hikari.Permissions.NONE)
    if perms & hikari.Permissions.ADMINISTRATOR:
        return "Administrator"
    if perms & hikari.Permissions.MANAGE_GUILD:
        return "Manager"

    return "Member"


def build_guild_info(guild, has_bot: bool) -> GuildInfo:
    """Build GuildInfo response object from Discord guild.

    Args:
        guild: Discord guild object
        has_bot: Whether ClashKing bot is in this guild

    Returns:
        GuildInfo object with all guild details
    """
    guild_id = str(guild.id)
    member_count = getattr(guild, 'approximate_member_count', None)
    role = get_user_role_in_guild(guild)

    icon_url = str(guild.icon_url) if guild.icon_url else "https://cdn.discordapp.com/embed/avatars/0.png"
    permissions = str(getattr(guild, 'my_permissions', "0"))
    features = list(guild.features) if hasattr(guild, 'features') else []
    is_owner = getattr(guild, 'is_owner', False)

    return GuildInfo(
        id=guild_id,
        name=guild.name,
        icon=icon_url,
        owner=is_owner,
        permissions=permissions,
        role=role,
        features=features,
        has_bot=has_bot,
        member_count=member_count
    )


def filter_admin_guilds(guilds_response) -> list:
    """Filter guilds where user has MANAGE_GUILD permission.

    Args:
        guilds_response: List of Discord guild objects

    Returns:
        List of guilds where user has admin permissions
    """
    admin_guilds = []
    for guild in guilds_response:
        permissions = int(guild.my_permissions) if hasattr(guild, 'my_permissions') else 0
        has_manage = bool(permissions & 0x20)
        is_owner = getattr(guild, 'is_owner', False)
        if has_manage or is_owner:
            admin_guilds.append(guild)
    return admin_guilds


async def fetch_bot_guild_ids(rest, bot_token: str) -> set:
    """Fetch set of guild IDs where bot is present.

    Args:
        rest: Hikari REST client
        bot_token: Bot authentication token

    Returns:
        Set of guild ID strings where bot is present
    """
    try:
        async with rest.acquire(token=bot_token, token_type=hikari.TokenType.BOT) as bot_client:
            bot_guilds = await bot_client.fetch_my_guilds()
            return {str(g.id) for g in bot_guilds}
    except Exception as e:
        print(f"⚠️ Could not fetch bot guilds: {e}")
        return set()


async def fetch_guild_with_client(client, server_id: int):
    """Fetch guild from Discord API with error handling.

    Args:
        client: Hikari REST client
        server_id: Discord server/guild ID

    Returns:
        Guild object

    Raises:
        HTTPException: 404 if guild not found, 403 if bot lacks access
    """
    try:
        return await client.fetch_guild(server_id)
    except hikari.NotFoundError:
        raise HTTPException(status_code=404, detail="Guild not found")
    except hikari.ForbiddenError:
        raise HTTPException(status_code=403, detail="Bot does not have access to this guild")


async def verify_user_in_guild(client, server_id: int, user_id: str) -> None:
    """Verify that user is a member of the guild.

    Args:
        client: Hikari REST client
        server_id: Discord server/guild ID
        user_id: User ID to verify

    Raises:
        HTTPException: 403 if user is not a member
        HTTPException: 400 if user_id is invalid
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")

    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    try:
        await client.fetch_member(server_id, user_id_int)
    except hikari.NotFoundError:
        raise HTTPException(status_code=403, detail="You are not a member of this guild")


@router.get("", name="Get user guilds with bot status")
@linkd.ext.fastapi.inject
@check_authentication
async def get_user_guilds(
    user_id: str = None,
    device_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient = None,
    rest: hikari.RESTApp = None
) -> List[GuildInfo]:
    """
    Fetch user's Discord guilds and check which ones have ClashKing bot.
    Only returns guilds where user has MANAGE_GUILD permission.
    """
    try:
        # Get valid Discord access token for this user
        discord_access_token = await get_valid_discord_access_token(user_id, rest, mongo, device_id)

        # Fetch user's guilds from Discord
        async with rest.acquire(token=discord_access_token, token_type=hikari.TokenType.BEARER) as client:
            try:
                guilds_response = await client.fetch_my_guilds()
            except hikari.UnauthorizedError:
                raise HTTPException(
                    status_code=401,
                    detail="Discord token expired or invalid. Please log in again."
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch guilds from Discord: {str(e)}"
                )

        # Filter guilds where user has admin permissions
        admin_guilds = filter_admin_guilds(guilds_response)

        # Get bot's guilds to check presence
        bot_guild_ids = await fetch_bot_guild_ids(rest, config.bot_token)

        # Build response with bot presence info
        result = []
        for guild in admin_guilds:
            guild_id = str(guild.id)
            has_bot = guild_id in bot_guild_ids
            result.append(build_guild_info(guild, has_bot))

        print(f"🔍 Returning {len(result)} guilds with bot status")
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@guild_router.get("/{server_id}", name="Get guild details by ID")
@linkd.ext.fastapi.inject
@check_authentication
async def get_guild_details(
    server_id: int,
    user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    _mongo: MongoClient = None,
    rest: hikari.RESTApp = None
) -> GuildDetails:
    """
    Fetch detailed information about a specific Discord guild/server.
    User must be a member of the guild.
    """
    try:
        # Verify bot token is configured
        if not config.bot_token:
            raise HTTPException(status_code=500, detail="Bot token not configured")

        # Fetch guild details using bot token
        async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
            # Fetch guild with error handling
            guild = await fetch_guild_with_client(client, server_id)

            # Verify user is a member of this guild
            await verify_user_in_guild(client, server_id, user_id)

        # Build response
        return GuildDetails(
            id=str(guild.id),
            name=guild.name,
            icon=str(guild.icon_url) if guild.icon_url else None,
            owner_id=str(guild.owner_id) if guild.owner_id else None,
            features=list(guild.features) if guild.features else [],
            member_count=guild.approximate_member_count if hasattr(guild, 'approximate_member_count') else None,
            description=guild.description if hasattr(guild, 'description') else None,
            banner=str(guild.banner_url) if hasattr(guild, 'banner_url') and guild.banner_url else None,
            premium_tier=guild.premium_tier.value if hasattr(guild, 'premium_tier') and guild.premium_tier else 0,
            boost_count=guild.premium_subscription_count if hasattr(guild, 'premium_subscription_count') else 0
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch guild details: {str(e)}"
        )
