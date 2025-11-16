import hikari
import linkd
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List

from utils.database import MongoClient
from utils.security import check_authentication
from utils.config import Config
from routers.v2.server.logs_models import ServerLogsConfig, LogConfig, ChannelInfo

config = Config()
security = HTTPBearer()

router = APIRouter(prefix="/v2/server", tags=["Server Logs"], include_in_schema=True)


@router.get("/{server_id}/logs", name="Get server logs configuration")
@linkd.ext.fastapi.inject
@check_authentication
async def get_server_logs(
        server_id: int,
        user_id: str = None,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        rest: hikari.RESTApp
) -> ServerLogsConfig:
    """
    Get the complete logs configuration for a server.
    Returns configuration for all log types.
    """
    # Find server settings
    server = await mongo.clan_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Extract logs configuration from server document
    logs_config = server.get("logs", {})
    print(logs_config)

    # Build response with all log types
    return ServerLogsConfig(
        join_leave_log=_parse_log_config(logs_config.get("join_leave_log")),
        donation_log=_parse_log_config(logs_config.get("donation_log")),
        war_log=_parse_log_config(logs_config.get("war_log")),
        capital_donation_log=_parse_log_config(logs_config.get("capital_donation_log")),
        capital_raid_log=_parse_log_config(logs_config.get("capital_raid_log")),
        player_upgrade_log=_parse_log_config(logs_config.get("player_upgrade_log")),
        legend_log=_parse_log_config(logs_config.get("legend_log")),
        ban_log=_parse_log_config(logs_config.get("ban_log")),
        strike_log=_parse_log_config(logs_config.get("strike_log")),
    )


@router.put("/{server_id}/logs", name="Update server logs configuration")
@linkd.ext.fastapi.inject
@check_authentication
async def update_server_logs(
        server_id: int,
        logs_config: ServerLogsConfig,
        user_id: str = None,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        rest: hikari.RESTApp
) -> dict:
    """
    Update the complete logs configuration for a server.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Build update document
    update_doc = {}
    if logs_config.join_leave_log is not None:
        update_doc["logs.join_leave_log"] = logs_config.join_leave_log.model_dump(exclude_none=True)
    if logs_config.donation_log is not None:
        update_doc["logs.donation_log"] = logs_config.donation_log.model_dump(exclude_none=True)
    if logs_config.war_log is not None:
        update_doc["logs.war_log"] = logs_config.war_log.model_dump(exclude_none=True)
    if logs_config.capital_donation_log is not None:
        update_doc["logs.capital_donation_log"] = logs_config.capital_donation_log.model_dump(exclude_none=True)
    if logs_config.capital_raid_log is not None:
        update_doc["logs.capital_raid_log"] = logs_config.capital_raid_log.model_dump(exclude_none=True)
    if logs_config.player_upgrade_log is not None:
        update_doc["logs.player_upgrade_log"] = logs_config.player_upgrade_log.model_dump(exclude_none=True)
    if logs_config.legend_log is not None:
        update_doc["logs.legend_log"] = logs_config.legend_log.model_dump(exclude_none=True)
    if logs_config.ban_log is not None:
        update_doc["logs.ban_log"] = logs_config.ban_log.model_dump(exclude_none=True)
    if logs_config.strike_log is not None:
        update_doc["logs.strike_log"] = logs_config.strike_log.model_dump(exclude_none=True)

    # Update database
    result = await mongo.server_db.update_one(
        {"server": server_id},
        {"$set": update_doc}
    )

    if result.modified_count == 0 and result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Server not found")

    return {
        "message": "Logs configuration updated successfully",
        "server_id": server_id,
        "updated_logs": len(update_doc)
    }


@router.patch("/{server_id}/logs/{log_type}", name="Update specific log type")
@linkd.ext.fastapi.inject
@check_authentication
async def update_log_type(
        server_id: int,
        log_type: str,
        log_config: LogConfig,
        user_id: str = None,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient,
        rest: hikari.RESTApp
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

    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Update specific log type
    update_field = f"logs.{log_type}"
    result = await mongo.server_db.update_one(
        {"server": server_id},
        {"$set": {update_field: log_config.model_dump(exclude_none=True)}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Server not found")

    return {
        "message": f"{log_type} configuration updated successfully",
        "server_id": server_id,
        "log_type": log_type
    }


@router.get("/{server_id}/channels", name="Get server Discord channels")
@linkd.ext.fastapi.inject
@check_authentication
async def get_server_channels(
        server_id: int,
        user_id: str = None,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        rest: hikari.RESTApp,
        mongo: MongoClient
) -> List[ChannelInfo]:
    """
    Get all text channels for a Discord server.
    Only returns channels where the bot has access.
    """
    try:
        # Fetch guild channels using bot token
        async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
            try:
                channels = await client.fetch_guild_channels(server_id)
            except hikari.ForbiddenError:
                raise HTTPException(
                    status_code=403,
                    detail="Bot does not have access to this server"
                )
            except hikari.NotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail="Server not found"
                )

        # Filter for text channels and threads
        result = []
        for channel in channels:
            # Include text channels, news channels, and voice channels
            if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel)):
                channel_type = "text" if isinstance(channel, hikari.GuildTextChannel) else "news"

                # Get parent category name if exists
                parent_name = None
                if channel.parent_id:
                    parent_channel = next((c for c in channels if c.id == channel.parent_id), None)
                    if parent_channel and hasattr(parent_channel, 'name'):
                        parent_name = parent_channel.name

                result.append(ChannelInfo(
                    id=str(channel.id),
                    name=channel.name,
                    type=channel_type,
                    parent_id=str(channel.parent_id) if channel.parent_id else None,
                    parent_name=parent_name
                ))

        # Sort by parent category and then by name
        result.sort(key=lambda x: (x.parent_name or "", x.name))

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch channels: {str(e)}"
        )


def _parse_log_config(data: dict | None) -> LogConfig | None:
    """
    Helper function to parse log configuration from database.
    Returns None if data is None or empty.
    """
    if not data:
        return None

    return LogConfig(
        enabled=data.get("enabled", False),
        channel=str(data.get("channel")) if data.get("channel") else None,
        thread=str(data.get("thread")) if data.get("thread") else None,
        webhook=str(data.get("webhook")) if data.get("webhook") else None,
        include_buttons=data.get("include_buttons"),
        ping_role=str(data.get("ping_role")) if data.get("ping_role") else None,
        clans=data.get("clans", [])
    )
