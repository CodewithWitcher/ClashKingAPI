from pydantic import BaseModel, Field
from typing import Optional, Literal
from utils.utils import to_str


# Server-level countdown types (stored in server_db)
ServerCountdownType = Literal[
    "cwl",           # CWL countdown
    "clan_games",    # Clan Games countdown
    "raid_weekend",  # Raid Weekend countdown
    "eos",           # End of Season countdown
    "member_count",  # Clan Member Count
    "season_day",    # Season Day counter
]

# Clan-level countdown types (stored in clan_db)
ClanCountdownType = Literal[
    "war_score",     # War Score display
    "war_timer",     # War Timer countdown
]

# All countdown types
CountdownType = Literal[
    "cwl",
    "clan_games",
    "raid_weekend",
    "eos",
    "member_count",
    "season_day",
    "war_score",
    "war_timer",
]

# Mapping from countdown type to DB field name
COUNTDOWN_DB_FIELDS = {
    # Server-level
    "cwl": "cwlCountdown",
    "clan_games": "gamesCountdown",
    "raid_weekend": "raidCountdown",
    "eos": "eosCountdown",
    "member_count": "memberCount",
    "season_day": "eosDayCountdown",
    # Clan-level
    "war_score": "warCountdown",
    "war_timer": "warTimerCountdown",
}

# Countdown display names
COUNTDOWN_NAMES = {
    "cwl": "CWL",
    "clan_games": "Clan Games",
    "raid_weekend": "Raid Weekend",
    "eos": "End of Season",
    "member_count": "Clan Member Count",
    "season_day": "Season Day",
    "war_score": "War Score",
    "war_timer": "War Timer",
}

# Server-level countdown types list
SERVER_COUNTDOWN_TYPES = ["cwl", "clan_games", "raid_weekend", "eos", "member_count", "season_day"]

# Clan-level countdown types list
CLAN_COUNTDOWN_TYPES = ["war_score", "war_timer"]


class CountdownStatus(BaseModel):
    """Status of a single countdown"""
    type: str
    name: str
    enabled: bool
    channel_id: Optional[str] = None


class ServerCountdownsResponse(BaseModel):
    """Response with all server-level countdowns status"""
    server_id: str
    countdowns: list[CountdownStatus]


class ClanCountdownsResponse(BaseModel):
    """Response with all clan-level countdowns status"""
    server_id: str
    clan_tag: str
    countdowns: list[CountdownStatus]


class EnableCountdownRequest(BaseModel):
    """Request to enable a countdown"""
    countdown_type: CountdownType = Field(..., description="Type of countdown to enable")
    clan_tag: Optional[str] = Field(None, description="Clan tag (required for war_score and war_timer)")


class EnableCountdownResponse(BaseModel):
    """Response after enabling a countdown"""
    message: str
    countdown_type: str
    channel_id: str
    channel_name: str


class DisableCountdownRequest(BaseModel):
    """Request to disable a countdown"""
    countdown_type: CountdownType = Field(..., description="Type of countdown to disable")
    clan_tag: Optional[str] = Field(None, description="Clan tag (required for war_score and war_timer)")


class DisableCountdownResponse(BaseModel):
    """Response after disabling a countdown"""
    message: str
    countdown_type: str
