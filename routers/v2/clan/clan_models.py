from pydantic import BaseModel, Field
from datetime import datetime

class Location(BaseModel):
    emoji: str
    name: str

class Ranking(BaseModel):
    world: int
    country: int

class ClanBoardSeasonStats(BaseModel):
    month: str
    tracked: bool
    clan_games: int
    attack_wins: int
    donations: int
    received: int
    active_daily: int

class TownhallComp(BaseModel):
    level: int
    count: int


class ClanBoard(BaseModel):
    name: str
    tag: str
    link: str
    badge: str

    trophies: int
    builder_trophies: int
    required_townhall: int
    type: str
    location: Location
    ranking: Ranking

    leader: str
    level: int
    member_count: int

    cwl_league: str
    war_wins: int
    wars_lost: int | None
    win_streak: int | None
    win_ratio: float | None

    capital_league: str
    capital_points: int
    capital_hall: int

    description: str

    season: ClanBoardSeasonStats
    townhall_composition: list[TownhallComp]


class JoinLeaveEntry(BaseModel):
    name: str
    tag: str
    townhall: int = Field(alias="th")
    time: datetime
    clan_tag: str = Field(alias="clan")
    type: str

class JoinLeaveList(BaseModel):
    items: list[JoinLeaveEntry]

class PlayerTagsRequest(BaseModel):
    player_tags: list[str]