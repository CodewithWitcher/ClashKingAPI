from pydantic import BaseModel
from typing import Optional, List


class LogConfig(BaseModel):
    """Configuration for a single log type"""
    enabled: bool
    channel: Optional[str] = None
    thread: Optional[str] = None
    webhook: Optional[str] = None
    include_buttons: Optional[bool] = None
    ping_role: Optional[str] = None
    clans: Optional[List[str]] = None


class ServerLogsConfig(BaseModel):
    """Complete logs configuration for a server"""
    join_leave_log: Optional[LogConfig] = None
    donation_log: Optional[LogConfig] = None
    war_log: Optional[LogConfig] = None
    capital_donation_log: Optional[LogConfig] = None
    capital_raid_log: Optional[LogConfig] = None
    player_upgrade_log: Optional[LogConfig] = None
    legend_log: Optional[LogConfig] = None
    ban_log: Optional[LogConfig] = None
    strike_log: Optional[LogConfig] = None


class ChannelInfo(BaseModel):
    """Discord channel information"""
    id: str
    name: str
    type: str
    parent_id: Optional[str] = None
    parent_name: Optional[str] = None