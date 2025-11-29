from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ClanActivity(BaseModel):
    """Activity statistics for a single clan"""
    clan_tag: str
    clan_name: str
    total_members: int = 0
    active_members: int = 0
    inactive_members: int = 0
    activity_rate: float = 0.0
    average_donations_sent: float = 0.0
    average_donations_received: float = 0.0
    total_donations_sent: int = 0
    total_donations_received: int = 0
    total_attacks_wins: int = 0
    average_trophies: float = 0.0


class GuildActivitySummary(BaseModel):
    """Summary of activity across all clans in a server"""
    guild_id: int
    total_clans: int
    total_members: int = 0
    total_active_members: int = 0
    total_inactive_members: int = 0
    overall_activity_rate: float = 0.0
    total_donations_sent: int = 0
    total_donations_received: int = 0
    clans: List[ClanActivity]


class InactivePlayer(BaseModel):
    """Details of an inactive player"""
    player_tag: str
    player_name: str
    clan_tag: str
    clan_name: str
    townhall_level: int
    role: str
    last_seen: Optional[datetime] = None
    days_inactive: Optional[int] = None
    trophies: int = 0
    donations_sent: int = 0
    donations_received: int = 0


class InactivePlayersResponse(BaseModel):
    """Response for inactive players endpoint"""
    guild_id: int
    inactive_threshold_days: int
    players: List[InactivePlayer]
    total_count: int
    limit: int
    offset: int
