from pydantic import BaseModel, Field
from typing import Optional, List


class RaidAttack(BaseModel):
    """Single raid attack details"""
    attacker_tag: str
    attacker_name: str
    defender_tag: Optional[str] = None
    defender_name: Optional[str] = None
    destruction: float
    stars: int


class PlayerRaidStats(BaseModel):
    """Raid statistics for a single player"""
    player_tag: str
    player_name: str
    clan_tag: str
    clan_name: str
    total_attacks: int = 0
    total_destruction: float = 0.0
    total_capital_gold_looted: int = 0
    total_raid_medals: int = 0
    average_destruction: float = 0.0
    attacks: List[RaidAttack] = []


class CapitalPlayerStatsResponse(BaseModel):
    """Response for capital player stats endpoint"""
    season: Optional[str] = None
    players: List[PlayerRaidStats]
    total_count: int
    limit: int
    offset: int


class ClanRaidLeaderboard(BaseModel):
    """Single clan entry in raid leaderboard"""
    clan_tag: str
    clan_name: str
    total_raids: int = 0
    total_capital_gold_looted: int = 0
    total_raid_medals: int = 0
    average_capital_gold_per_raid: float = 0.0
    average_raid_medals_per_raid: float = 0.0
    total_attacks: int = 0
    average_destruction: float = 0.0


class CapitalGuildLeaderboardResponse(BaseModel):
    """Response for capital guild leaderboard endpoint"""
    guild_id: int
    season: Optional[str] = None
    clans: List[ClanRaidLeaderboard]
    total_count: int
