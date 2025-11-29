from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class PlayerLegendsDay(BaseModel):
    """Legends statistics for a player on a specific day"""
    player_tag: str
    player_name: str
    townhall_level: int
    date: str
    starting_trophies: int = 0
    ending_trophies: int = 0
    net_trophies: int = 0
    attacks: int = 0
    defenses: int = 0
    attack_wins: int = 0
    defense_wins: int = 0


class ClanLegendsStats(BaseModel):
    """Aggregate legends statistics for a clan"""
    clan_tag: str
    clan_name: str
    total_players_in_legends: int = 0
    average_trophies: float = 0.0
    total_trophies: int = 0
    highest_trophies: int = 0
    lowest_trophies: int = 0
    total_attacks: int = 0
    total_defenses: int = 0
    average_attacks_per_player: float = 0.0
    average_defenses_per_player: float = 0.0


class GuildLegendsStats(BaseModel):
    """Aggregate legends statistics for a guild"""
    guild_id: int
    season: Optional[str] = None
    total_players_in_legends: int = 0
    total_clans: int = 0
    average_trophies: float = 0.0
    total_trophies: int = 0
    top_players: List[Dict[str, Any]] = []
    clans: List[ClanLegendsStats]


class DailyTrackingData(BaseModel):
    """Daily trophy progression for a player"""
    date: str
    starting_trophies: int
    ending_trophies: int
    net_change: int
    attacks: int = 0
    defenses: int = 0
    attack_wins: int = 0
    defense_wins: int = 0


class PlayerDailyTracking(BaseModel):
    """Daily tracking for a single player"""
    player_tag: str
    player_name: str
    clan_tag: Optional[str] = None
    clan_name: Optional[str] = None
    townhall_level: int
    current_trophies: int
    daily_data: List[DailyTrackingData]


class LegendsDailyTrackingResponse(BaseModel):
    """Response for legends daily tracking endpoint"""
    guild_id: int
    start_date: str
    end_date: str
    players: List[PlayerDailyTracking]
    total_count: int
