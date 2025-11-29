import hikari
import linkd
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Annotated, Dict, Optional, Any

from utils.database import MongoClient
from utils.security import check_authentication
from utils.config import Config
from utils.sentry_utils import capture_endpoint_errors
from utils.cache_decorator import cache_endpoint
from .models import (
    ServerLogsConfig, LogConfig, ChannelInfo, ThreadInfo,
    ClanLogsConfig, ClanLogTypeConfig, UpdateClanLogRequest
)

config = Config()
security = HTTPBearer()

router = APIRouter(prefix="/v2/server", tags=["Server Logs"], include_in_schema=True)

# Constants
SERVER_NOT_FOUND = "Server not found"


# ============================================================================
# Helper Functions
# ============================================================================

def get_log_mapping() -> Dict[str, str]:
    """
    Get mapping from database log names to API response names.

    Returns:
        Dictionary mapping database log field names to API log type names.
    """
    return {
        "join_log": "join_leave_log",
        "leave_log": "join_leave_log",
        "donation_log": "donation_log",
        "clan_achievement_log": "clan_achievement_log",
        "clan_requirements_log": "clan_requirements_log",
        "clan_description_log": "clan_description_log",
        "war_log": "war_log",
        "war_panel": "war_panel",
        "cwl_lineup_change_log": "cwl_lineup_change_log",
        "capital_donations": "capital_donation_log",
        "capital_attacks": "capital_raid_log",
        "raid_panel": "raid_panel",
        "capital_weekly_summary": "capital_weekly_summary",
        "role_change": "player_upgrade_log",
        "th_upgrade": "player_upgrade_log",
        "troop_upgrade": "player_upgrade_log",
        "hero_upgrade": "player_upgrade_log",
        "spell_upgrade": "player_upgrade_log",
        "hero_equipment_upgrade": "player_upgrade_log",
        "super_troop_boost": "player_upgrade_log",
        "league_change": "player_upgrade_log",
        "name_change": "player_upgrade_log",
        "legend_log_attacks": "legend_log",
        "legend_log_defenses": "legend_log",
    }


def get_api_to_db_mapping() -> Dict[str, List[str]]:
    """
    Get mapping from API log names to database log names.

    Returns:
        Dictionary mapping API log type names to lists of database field names.
    """
    return {
        "join_leave_log": ["join_log", "leave_log"],
        "donation_log": ["donation_log"],
        "clan_achievement_log": ["clan_achievement_log"],
        "clan_requirements_log": ["clan_requirements_log"],
        "clan_description_log": ["clan_description_log"],
        "war_log": ["war_log"],
        "war_panel": ["war_panel"],
        "cwl_lineup_change_log": ["cwl_lineup_change_log"],
        "capital_donation_log": ["capital_donations"],
        "capital_raid_log": ["capital_attacks"],
        "raid_panel": ["raid_panel"],
        "capital_weekly_summary": ["capital_weekly_summary"],
        "player_upgrade_log": [
            "th_upgrade", "troop_upgrade", "hero_upgrade", "spell_upgrade",
            "hero_equipment_upgrade", "super_troop_boost", "role_change",
            "league_change", "name_change"
        ],
    }


def _get_log_config_key(log_data: dict) -> tuple[str, Optional[str], str]:
    """
    Extract webhook ID, thread ID, and config key from log data.

    Args:
        log_data: Log configuration from database

    Returns:
        Tuple of (webhook_id, thread_id, config_key)
    """
    webhook_id = str(log_data.get("webhook"))
    thread_id = str(log_data.get("thread")) if log_data.get("thread") else None
    config_key = f"{webhook_id}_{thread_id}"
    return webhook_id, thread_id, config_key


def _initialize_log_config(webhook_id: str, thread_id: Optional[str]) -> Dict[str, Any]:
    """
    Create initial log configuration structure.

    Args:
        webhook_id: The webhook ID
        thread_id: The thread ID (optional)

    Returns:
        Dictionary with webhook, thread, and empty clans list
    """
    return {
        "webhook": webhook_id,
        "thread": thread_id,
        "clans": []
    }


def _process_clan_log_entry(
    aggregated_logs: Dict[str, Dict[str, Dict[str, Any]]],
    clan_tag: str,
    api_log_name: str,
    log_data: dict
) -> None:
    """
    Process a single log entry for a clan and add to aggregated logs.

    Args:
        aggregated_logs: The aggregated logs dictionary to update
        clan_tag: The clan tag
        api_log_name: API log type name
        log_data: Log configuration data
    """
    webhook_id, thread_id, config_key = _get_log_config_key(log_data)

    # Initialize API log name if not exists
    if api_log_name not in aggregated_logs:
        aggregated_logs[api_log_name] = {}

    # Initialize config key if not exists
    if config_key not in aggregated_logs[api_log_name]:
        aggregated_logs[api_log_name][config_key] = _initialize_log_config(webhook_id, thread_id)

    # Add clan tag if not already in list
    if clan_tag not in aggregated_logs[api_log_name][config_key]["clans"]:
        aggregated_logs[api_log_name][config_key]["clans"].append(clan_tag)


def aggregate_logs_from_clans(clans: List[dict], log_mapping: Dict[str, str]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Aggregate log configurations from multiple clans by log type.

    Groups logs by their API log type and configuration (webhook+thread combination).

    Args:
        clans: List of clan documents from the database
        log_mapping: Mapping from database log names to API log names

    Returns:
        Nested dictionary: {api_log_name: {config_key: {webhook, thread, clans}}}
    """
    aggregated_logs = {}

    for clan in clans:
        clan_tag = clan.get("tag")
        logs = clan.get("logs", {})

        for db_log_name, api_log_name in log_mapping.items():
            log_data = logs.get(db_log_name)
            if not log_data or not log_data.get("webhook"):
                continue

            _process_clan_log_entry(aggregated_logs, clan_tag, api_log_name, log_data)

    return aggregated_logs


async def fetch_channel_id_from_webhook(rest: hikari.RESTApp, webhook_id: str) -> Optional[str]:
    """
    Fetch the channel ID associated with a webhook.

    Args:
        rest: Hikari REST client
        webhook_id: The webhook ID to lookup

    Returns:
        The channel ID as a string, or None if webhook not found or error occurs
    """
    try:
        async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
            webhook = await client.fetch_webhook(int(webhook_id))
            return str(getattr(webhook, 'channel_id', None))
    except (hikari.NotFoundError, hikari.ForbiddenError, ValueError):
        return None


def build_server_logs_response(aggregated_logs: Dict[str, Dict], _rest: hikari.RESTApp) -> ServerLogsConfig:
    """
    Build the ServerLogsConfig response from aggregated logs.

    Args:
        aggregated_logs: Aggregated log configurations by type
        _rest: Hikari REST client for fetching channel IDs (unused, kept for signature compatibility)

    Returns:
        ServerLogsConfig object with all log configurations
    """
    result = {}

    for api_log_name, configs in aggregated_logs.items():
        if configs:
            first_config = next(iter(configs.values()))
            result[api_log_name] = LogConfig(
                enabled=True,
                channel=None,  # Will be populated asynchronously if needed
                thread=first_config["thread"],
                webhook=first_config["webhook"],
                clans=first_config["clans"]
            )

    return ServerLogsConfig(
        join_leave_log=result.get("join_leave_log"),
        donation_log=result.get("donation_log"),
        clan_achievement_log=result.get("clan_achievement_log"),
        clan_requirements_log=result.get("clan_requirements_log"),
        clan_description_log=result.get("clan_description_log"),
        war_log=result.get("war_log"),
        war_panel=result.get("war_panel"),
        cwl_lineup_change_log=result.get("cwl_lineup_change_log"),
        capital_donation_log=result.get("capital_donation_log"),
        capital_raid_log=result.get("capital_raid_log"),
        raid_panel=result.get("raid_panel"),
        capital_weekly_summary=result.get("capital_weekly_summary"),
        player_upgrade_log=result.get("player_upgrade_log"),
        legend_log=result.get("legend_log"),
        ban_log=result.get("ban_log"),
        strike_log=result.get("strike_log"),
    )


async def create_webhook_for_channel(rest: hikari.RESTApp, channel_id: int) -> int:
    """
    Create a webhook for the specified channel.

    Args:
        rest: Hikari REST client
        channel_id: The Discord channel ID

    Returns:
        The created webhook ID

    Raises:
        HTTPException: If webhook creation fails
    """
    try:
        async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
            webhook = await client.create_webhook(
                channel_id,
                name="ClashKing Logs",
                reason="Created by ClashKing Dashboard"
            )
            return webhook.id
    except hikari.ForbiddenError as e:
        raise HTTPException(
            status_code=403,
            detail=f"Bot does not have MANAGE_WEBHOOKS permission in channel {channel_id}"
        ) from e
    except hikari.NotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Channel {channel_id} not found"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to create webhook for channel {channel_id}: {str(e)}"
        ) from e


async def apply_log_updates(
    mongo: MongoClient,
    server_id: int,
    _api_log_name: str,
    db_log_names: List[str],
    _enabled: bool,
    webhook_id: Optional[int],
    thread_id: Optional[int],
    selected_clans: List[str]
) -> int:
    """
    Apply log configuration updates to the database.

    Args:
        mongo: MongoDB client
        server_id: The Discord server ID
        _api_log_name: API log type name (unused, kept for signature compatibility)
        db_log_names: List of database log field names
        _enabled: Whether the log is enabled (unused, kept for signature compatibility)
        webhook_id: The webhook ID (None to disable)
        thread_id: The thread ID (optional)
        selected_clans: List of clan tags to update (empty for all clans)

    Returns:
        Number of modified documents
    """
    updated_count = 0

    for db_log_name in db_log_names:
        if selected_clans:
            result = await mongo.clan_db.update_many(
                {"server": server_id, "tag": {"$in": selected_clans}},
                {"$set": {
                    f"logs.{db_log_name}.webhook": webhook_id,
                    f"logs.{db_log_name}.thread": thread_id
                }}
            )
        else:
            result = await mongo.clan_db.update_many(
                {"server": server_id},
                {"$set": {
                    f"logs.{db_log_name}.webhook": webhook_id,
                    f"logs.{db_log_name}.thread": thread_id
                }}
            )
        updated_count += result.modified_count

    return updated_count


async def _process_log_config_update(
    mongo: MongoClient,
    rest: hikari.RESTApp,
    server_id: int,
    api_log_name: str,
    log_config: dict,
    db_log_names: List[str]
) -> int:
    """
    Process a single log configuration update.

    Args:
        mongo: MongoDB client
        rest: Hikari REST client
        server_id: The Discord server ID
        api_log_name: API log type name
        log_config: Log configuration dictionary
        db_log_names: List of database log field names

    Returns:
        Number of modified documents
    """
    enabled = log_config.get("enabled", False)
    webhook_id = log_config.get("webhook")
    thread_id = log_config.get("thread")
    selected_clans = log_config.get("clans", [])

    # Handle disabled or no webhook
    if not enabled or not webhook_id:
        return await apply_log_updates(
            mongo, server_id, api_log_name, db_log_names,
            enabled, None, None, selected_clans
        )

    # Create webhook if needed
    if not webhook_id and log_config.get("channel"):
        channel_id = int(log_config["channel"])
        webhook_id = str(await create_webhook_for_channel(rest, channel_id))

    # Apply updates
    webhook_id_int = int(webhook_id) if webhook_id else None
    thread_id_int = int(thread_id) if thread_id else None

    return await apply_log_updates(
        mongo, server_id, api_log_name, db_log_names,
        enabled, webhook_id_int, thread_id_int, selected_clans
    )


async def fetch_discord_channels(rest: hikari.RESTApp, server_id: int) -> List[hikari.GuildChannel]:
    """
    Fetch all channels for a Discord server.

    Args:
        rest: Hikari REST client
        server_id: The Discord server ID

    Returns:
        List of guild channels

    Raises:
        HTTPException: If fetching fails or bot lacks access
    """
    try:
        async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
            return list(await client.fetch_guild_channels(server_id))
    except hikari.ForbiddenError as e:
        raise HTTPException(
            status_code=403,
            detail="Bot does not have access to this server"
        ) from e
    except hikari.NotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=SERVER_NOT_FOUND
        ) from e


def _get_channel_type(channel: hikari.GuildChannel) -> str:
    """
    Determine the channel type string.

    Args:
        channel: Guild channel object

    Returns:
        "text" for text channels, "news" for news channels
    """
    return "text" if isinstance(channel, hikari.GuildTextChannel) else "news"


def _find_parent_name(parent_id: int, channels: List[hikari.GuildChannel]) -> Optional[str]:
    """
    Find the parent channel name by ID.

    Args:
        parent_id: The parent channel ID
        channels: List of all guild channels

    Returns:
        Parent channel name or None if not found
    """
    parent_channel = next((c for c in channels if c.id == parent_id), None)
    if parent_channel and hasattr(parent_channel, 'name'):
        return parent_channel.name
    return None


def filter_text_channels(channels: List[hikari.GuildChannel]) -> List[ChannelInfo]:
    """
    Filter and format text channels from a list of guild channels.

    Args:
        channels: List of guild channels

    Returns:
        List of ChannelInfo objects for text and news channels
    """
    result = []

    for channel in channels:
        if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel)):
            channel_type = _get_channel_type(channel)
            parent_name = _find_parent_name(channel.parent_id, channels) if channel.parent_id else None

            result.append(ChannelInfo(
                id=str(channel.id),
                name=channel.name,
                type=channel_type,
                parent_id=str(channel.parent_id) if channel.parent_id else None,
                parent_name=parent_name
            ))

    result.sort(key=lambda x: (x.parent_name or "", x.name))
    return result


async def fetch_active_threads_from_channels(
    rest: hikari.RESTApp,
    channels: List[hikari.GuildChannel]
) -> List[ThreadInfo]:
    """
    Fetch all active threads from text channels.

    Args:
        rest: Hikari REST client
        channels: List of guild channels

    Returns:
        List of ThreadInfo objects
    """
    threads = []
    channel_map = {c.id: c.name for c in channels if hasattr(c, 'name')}

    async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
        for channel in channels:
            if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel)):
                try:
                    channel_threads = await client.fetch_active_threads(channel.id)
                    for thread in channel_threads:
                        threads.append(ThreadInfo(
                            id=str(thread.id),
                            name=thread.name,
                            parent_channel_id=str(thread.parent_id),
                            parent_channel_name=channel_map.get(thread.parent_id),
                            archived=False
                        ))
                except (hikari.ForbiddenError, hikari.NotFoundError):
                    continue

    return threads


async def build_webhook_channel_map(rest: hikari.RESTApp, webhook_ids: set) -> Dict[int, Optional[int]]:
    """
    Build a mapping from webhook IDs to their channel IDs.

    Args:
        rest: Hikari REST client
        webhook_ids: Set of webhook IDs to lookup

    Returns:
        Dictionary mapping webhook ID to channel ID
    """
    webhook_to_channel = {}

    async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
        for webhook_id in webhook_ids:
            try:
                webhook = await client.fetch_webhook(webhook_id)
                webhook_to_channel[webhook_id] = getattr(webhook, 'channel_id', None)
            except (hikari.ForbiddenError, hikari.NotFoundError):
                continue

    return webhook_to_channel


def parse_clan_log_type(data: Optional[dict], webhook_to_channel: Optional[Dict] = None) -> Optional[ClanLogTypeConfig]:
    """
    Parse a single log type configuration from database.

    Args:
        data: Log configuration data from database
        webhook_to_channel: Optional mapping from webhook ID to channel ID

    Returns:
        ClanLogTypeConfig object or None if no valid configuration
    """
    if not data or not isinstance(data, dict):
        return None

    webhook = data.get("webhook")
    thread = data.get("thread")

    if webhook is None and thread is None:
        return None

    # Get channel ID from webhook if available
    channel = None
    if webhook and webhook_to_channel:
        channel_id = webhook_to_channel.get(webhook)
        if channel_id:
            channel = str(channel_id)

    return ClanLogTypeConfig(
        webhook=str(webhook) if webhook is not None else None,
        channel=channel,
        thread=str(thread) if thread is not None else None
    )


async def validate_and_prepare_webhook(
    rest: hikari.RESTApp,
    channel_id: Optional[int],
    thread_id: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    """
    Validate thread and determine the target channel for webhook creation.

    Args:
        rest: Hikari REST client
        channel_id: Target channel ID
        thread_id: Optional thread ID

    Returns:
        Tuple of (target_channel_id, thread_id)

    Raises:
        HTTPException: If thread validation fails
    """
    target_channel_id = channel_id

    if thread_id:
        try:
            async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
                thread = await client.fetch_channel(thread_id)
                if hasattr(thread, 'parent_id') and thread.parent_id:
                    target_channel_id = thread.parent_id
        except hikari.NotFoundError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Thread {thread_id} not found"
            ) from e
        except hikari.ForbiddenError as e:
            raise HTTPException(
                status_code=403,
                detail=f"Bot doesn't have access to thread {thread_id}"
            ) from e
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch thread info: {str(e)}"
            ) from e

    return target_channel_id, thread_id


async def create_webhook_with_validation(
    rest: hikari.RESTApp,
    channel_id: int
) -> int:
    """
    Create a webhook after validating the channel exists and is accessible.

    Args:
        rest: Hikari REST client
        channel_id: The Discord channel ID

    Returns:
        The created webhook ID

    Raises:
        HTTPException: If channel validation or webhook creation fails
    """
    async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
        # Verify the channel exists and is accessible
        try:
            await client.fetch_channel(channel_id)
        except hikari.NotFoundError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Channel {channel_id} not found. It may have been deleted or the bot doesn't have access to it."
            ) from e
        except hikari.ForbiddenError as e:
            raise HTTPException(
                status_code=403,
                detail=f"Bot doesn't have access to channel {channel_id}."
            ) from e

        # Create the webhook
        try:
            webhook = await client.create_webhook(
                channel=channel_id,
                name="ClashKing",
                reason="Created by ClashKing Dashboard"
            )
            return webhook.id
        except hikari.ForbiddenError as e:
            raise HTTPException(
                status_code=403,
                detail="Bot does not have MANAGE_WEBHOOKS permission in this channel. Please ensure the bot has the 'Manage Webhooks' permission."
            ) from e


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/{server_id}/logs", name="Get server logs configuration")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_server_logs(
        server_id: int,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> ServerLogsConfig:
    """
    Get the complete logs configuration for a server.
    Returns configuration for all log types aggregated from all clans.
    """
    clans = await mongo.clan_db.find({"server": server_id}).to_list(length=None)
    if not clans:
        return ServerLogsConfig()

    log_mapping = get_log_mapping()
    aggregated_logs = aggregate_logs_from_clans(clans, log_mapping)
    return build_server_logs_response(aggregated_logs, _rest)


@router.put("/{server_id}/logs", name="Update server logs configuration")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_server_logs(
        server_id: int,
        logs_config: ServerLogsConfig,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        rest: hikari.RESTApp
) -> dict:
    """
    Update the complete logs configuration for a server.
    Updates webhook configurations in clan_db for selected clans.
    """
    all_clans = await mongo.clan_db.find({"server": server_id}).to_list(length=None)
    if not all_clans:
        raise HTTPException(status_code=404, detail="No clans found for this server")

    api_to_db_mapping = get_api_to_db_mapping()
    updated_count = 0

    for api_log_name, log_config in logs_config.model_dump(exclude_none=True).items():
        if log_config is None or not isinstance(log_config, dict):
            continue

        db_log_names = api_to_db_mapping.get(api_log_name, [])
        if not db_log_names:
            continue

        count = await _process_log_config_update(
            mongo, rest, server_id, api_log_name, log_config, db_log_names
        )
        updated_count += count

    return {
        "message": "Logs configuration updated successfully",
        "server_id": server_id,
        "updated_clans": updated_count
    }


@router.patch("/{server_id}/logs/{log_type}", name="Update specific log type")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_log_type(
        server_id: int,
        log_type: str,
        log_config: LogConfig,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> dict:
    """
    Update a specific log type configuration.

    Valid log types: join_leave_log, donation_log, war_log, capital_donation_log,
    capital_raid_log, player_upgrade_log, legend_log, ban_log, strike_log
    """
    valid_log_types = [
        "join_leave_log", "donation_log", "war_log", "capital_donation_log",
        "capital_raid_log", "player_upgrade_log", "legend_log", "ban_log", "strike_log"
    ]

    if log_type not in valid_log_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid log type. Must be one of: {', '.join(valid_log_types)}"
        )

    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    update_field = f"logs.{log_type}"
    result = await mongo.server_db.update_one(
        {"server": server_id},
        {"$set": {update_field: log_config.model_dump(exclude_none=True)}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    return {
        "message": f"{log_type} configuration updated successfully",
        "server_id": server_id,
        "log_type": log_type
    }


@router.get("/{server_id}/clans-basic", name="Get server clans (basic)")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_server_clans_basic(
        server_id: int,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> List[dict]:
    """
    Get all clans registered for a Discord server.
    Returns basic clan information (tag and name)
    """
    clans = await mongo.clan_db.find(
        {"server": server_id},
        {"tag": 1, "name": 1, "_id": 0}
    ).to_list(length=None)
    return clans


@router.get("/{server_id}/channels", name="Get server Discord channels")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
@cache_endpoint(ttl=30, key_prefix="channels")
async def get_server_channels(
        server_id: int,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        _mongo: MongoClient,
        rest: hikari.RESTApp
) -> List[ChannelInfo]:
    """
    Get all text channels for a Discord server.
    Only returns channels where the bot has access.
    """
    try:
        channels = await fetch_discord_channels(rest, server_id)
        return filter_text_channels(channels)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch channels: {str(e)}"
        ) from e


@router.get("/{server_id}/threads", name="Get server Discord threads")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
@cache_endpoint(ttl=30, key_prefix="threads")
async def get_server_threads(
        server_id: int,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        _mongo: MongoClient,
        rest: hikari.RESTApp
) -> List[ThreadInfo]:
    """
    Get all active threads for a Discord server.
    """
    try:
        async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
            try:
                channels = list(await client.fetch_guild_channels(server_id))
                return await fetch_active_threads_from_channels(rest, channels)
            except hikari.ForbiddenError as e:
                raise HTTPException(
                    status_code=403,
                    detail="Bot does not have access to this server"
                ) from e
            except hikari.NotFoundError as e:
                raise HTTPException(
                    status_code=404,
                    detail=SERVER_NOT_FOUND
                ) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch threads: {str(e)}"
        ) from e


@router.get("/{server_id}/clan-logs", name="Get all clans logs configuration")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_all_clans_logs(
        server_id: int,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        rest: hikari.RESTApp
) -> List[ClanLogsConfig]:
    """
    Get logs configuration for all clans in a server.
    Returns detailed log configuration for each clan (not aggregated).
    """
    clans = await mongo.clan_db.find({"server": server_id}).to_list(length=None)

    # Collect all unique webhook IDs
    webhook_ids = set()
    for clan in clans:
        logs_data = clan.get("logs", {})
        for log_data in logs_data.values():
            if isinstance(log_data, dict) and log_data.get("webhook"):
                webhook_ids.add(log_data["webhook"])

    # Fetch channel IDs for all webhooks
    webhook_to_channel = await build_webhook_channel_map(rest, webhook_ids)

    # Build result
    result = []
    for clan in clans:
        logs_data = clan.get("logs", {})
        clan_logs = ClanLogsConfig(
            tag=clan.get("tag"),
            name=clan.get("name"),
            # Clan logs
            join_log=parse_clan_log_type(logs_data.get("join_log"), webhook_to_channel),
            leave_log=parse_clan_log_type(logs_data.get("leave_log"), webhook_to_channel),
            donation_log=parse_clan_log_type(logs_data.get("donation_log"), webhook_to_channel),
            clan_achievement_log=parse_clan_log_type(logs_data.get("clan_achievement_log"), webhook_to_channel),
            clan_requirements_log=parse_clan_log_type(logs_data.get("clan_requirements_log"), webhook_to_channel),
            clan_description_log=parse_clan_log_type(logs_data.get("clan_description_log"), webhook_to_channel),
            # War logs
            war_log=parse_clan_log_type(logs_data.get("war_log"), webhook_to_channel),
            war_panel=parse_clan_log_type(logs_data.get("war_panel"), webhook_to_channel),
            cwl_lineup_change_log=parse_clan_log_type(logs_data.get("cwl_lineup_change_log"), webhook_to_channel),
            # Capital logs
            capital_donations=parse_clan_log_type(logs_data.get("capital_donations"), webhook_to_channel),
            capital_attacks=parse_clan_log_type(logs_data.get("capital_attacks"), webhook_to_channel),
            raid_panel=parse_clan_log_type(logs_data.get("raid_panel"), webhook_to_channel),
            capital_weekly_summary=parse_clan_log_type(logs_data.get("capital_weekly_summary"), webhook_to_channel),
            # Player logs
            role_change=parse_clan_log_type(logs_data.get("role_change"), webhook_to_channel),
            troop_upgrade=parse_clan_log_type(logs_data.get("troop_upgrade"), webhook_to_channel),
            super_troop_boost_log=parse_clan_log_type(logs_data.get("super_troop_boost"), webhook_to_channel),
            th_upgrade=parse_clan_log_type(logs_data.get("th_upgrade"), webhook_to_channel),
            league_change=parse_clan_log_type(logs_data.get("league_change"), webhook_to_channel),
            spell_upgrade=parse_clan_log_type(logs_data.get("spell_upgrade"), webhook_to_channel),
            hero_upgrade=parse_clan_log_type(logs_data.get("hero_upgrade"), webhook_to_channel),
            hero_equipment_upgrade=parse_clan_log_type(logs_data.get("hero_equipment_upgrade"), webhook_to_channel),
            name_change=parse_clan_log_type(logs_data.get("name_change"), webhook_to_channel),
            legend_log_attacks=parse_clan_log_type(logs_data.get("legend_log_attacks"), webhook_to_channel),
            legend_log_defenses=parse_clan_log_type(logs_data.get("legend_log_defenses"), webhook_to_channel)
        )
        result.append(clan_logs)

    return result


@router.put("/{server_id}/clan/{clan_tag}/logs", name="Update clan logs configuration")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_clan_logs(
        server_id: int,
        clan_tag: str,
        request: UpdateClanLogRequest,
        _user_id: Optional[str] = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        rest: hikari.RESTApp
) -> dict:
    """
    Update logs configuration for a specific clan.
    If channel_id is provided and no webhook exists, creates a new webhook.
    """
    print(f"Looking for clan - tag: {clan_tag!r} (type: {type(clan_tag)}), server: {server_id!r} (type: {type(server_id)})")
    clan = await mongo.clan_db.find_one({"tag": clan_tag, "server": server_id})
    print(f"Clan found: {clan is not None}")

    if not clan:
        raise HTTPException(status_code=404, detail=f"Clan {clan_tag} not found for this server")

    # Convert IDs to int
    webhook_id: Optional[int] = None
    thread_id: Optional[int] = int(request.thread_id) if request.thread_id is not None else None
    channel_id: Optional[int] = int(request.channel_id) if request.channel_id is not None else None

    print(f"Request - channel_id: {channel_id}, thread_id: {thread_id}, log_types: {request.log_types}")

    # Validate and prepare webhook creation
    target_channel_id, thread_id = await validate_and_prepare_webhook(rest, channel_id, thread_id)

    # Create webhook if needed
    if target_channel_id:
        print(f"Creating webhook for channel {target_channel_id}...")
        webhook_id = await create_webhook_with_validation(rest, target_channel_id)
        print(f"Webhook created: {webhook_id}")

    # Build update operations
    update_ops: Dict[str, Optional[int]] = {}
    for log_type in request.log_types:
        if webhook_id is not None:
            update_ops[f"logs.{log_type}.webhook"] = webhook_id
        if thread_id is not None:
            update_ops[f"logs.{log_type}.thread"] = thread_id
        elif webhook_id is not None:
            update_ops[f"logs.{log_type}.thread"] = None

    if not update_ops:
        raise HTTPException(status_code=400, detail="No updates to perform")

    print(f"Update operations: {update_ops}")
    result = await mongo.clan_db.update_one(
        {"tag": clan_tag, "server": server_id},
        {"$set": update_ops}
    )
    print(f"Update result - matched: {result.matched_count}, modified: {result.modified_count}")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Clan not found")

    return {
        "message": "Clan logs updated successfully",
        "clan_tag": clan_tag,
        "updated_log_types": request.log_types,
        "webhook_id": webhook_id,
        "thread_id": thread_id
    }


@router.delete("/{server_id}/clan/{clan_tag}/logs", name="Delete clan logs configuration")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def delete_clan_logs(
        server_id: int,
        clan_tag: str,
        log_types: Annotated[str, Query(description="Comma-separated list of log types to delete")],
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        _rest: hikari.RESTApp
) -> dict:
    """
    Delete clan logs configuration for specific log types.

    This will remove the webhook and thread configuration for the specified log types.
    The log types should be provided as a comma-separated string.

    Example: log_types=join_log,leave_log,donation_log
    """
    # Normalize clan tag
    if not clan_tag.startswith('#'):
        clan_tag = f'#{clan_tag}'

    # Parse comma-separated log types
    log_types_list = [lt.strip() for lt in log_types.split(',')]

    print(f"Looking for clan - tag: {clan_tag!r}, server: {server_id!r}")

    # Find the clan in database
    clan = await mongo.clan_db.find_one({"tag": clan_tag, "server": server_id})

    if not clan:
        raise HTTPException(status_code=404, detail=f"Clan {clan_tag} not found on this server")

    # Build unset document to remove log configurations
    unset_doc = {}
    for log_type in log_types_list:
        unset_doc[f"logs.{log_type}"] = ""

    print(f"Deleting log types: {log_types_list}")
    print(f"Unset operations: {unset_doc}")

    # Delete clan logs configuration
    result = await mongo.clan_db.update_one(
        {"tag": clan_tag, "server": server_id},
        {"$unset": unset_doc}
    )

    print(f"Delete result - matched: {result.matched_count}, modified: {result.modified_count}")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Clan not found")

    return {
        "message": "Clan logs deleted successfully",
        "clan_tag": clan_tag,
        "deleted_log_types": log_types_list
    }
