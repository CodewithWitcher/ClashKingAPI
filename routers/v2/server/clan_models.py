from pydantic import BaseModel, Field
from typing import Optional


class MemberCountWarningUpdate(BaseModel):
    """Member count warning configuration"""
    channel: Optional[int] = None
    above: Optional[int] = None
    below: Optional[int] = None
    role: Optional[int] = None


class ClanSettingsUpdate(BaseModel):
    """
    Update clan settings. All fields are optional.
    Only provided fields will be updated.
    """
    # Basic Settings
    generalRole: Optional[int] = Field(None, description="Member role ID", alias="member_role")
    leaderRole: Optional[int] = Field(None, description="Leader role ID", alias="leader_role")
    clanChannel: Optional[int] = Field(None, description="Clan channel ID", alias="clan_channel")
    category: Optional[str] = Field(None, description="Clan category")
    abbreviation: Optional[str] = Field(None, description="Clan abbreviation for nicknames")
    greeting: Optional[str] = Field(None, description="Clan welcome message")
    auto_greet_option: Optional[str] = Field(None, description="Auto-greet option: Never/Always/On Join")
    leadership_eval: Optional[bool] = Field(None, description="Enable/disable leadership eval")

    # War Settings
    warCountdown: Optional[int] = Field(None, description="War countdown channel ID", alias="war_countdown")
    warTimerCountdown: Optional[int] = Field(None, description="War timer countdown channel ID", alias="war_timer_countdown")
    ban_alert_channel: Optional[int] = Field(None, description="Ban alert channel ID")

    # Member Count Warning
    member_count_warning: Optional[MemberCountWarningUpdate] = Field(None, description="Member count warning settings")

    # Log Buttons (join_log)
    join_log_profile_button: Optional[bool] = Field(None, description="Enable profile button on join logs")

    # Log Buttons (leave_log)
    leave_log_strike_button: Optional[bool] = Field(None, description="Enable strike button on leave logs")
    leave_log_ban_button: Optional[bool] = Field(None, description="Enable ban button on leave logs")

    class Config:
        populate_by_name = True


class ClanSettingsResponse(BaseModel):
    """Response after updating clan settings"""
    message: str
    server_id: int
    clan_tag: str
    updated_fields: int


class AddClanRequest(BaseModel):
    """Request to add a clan to a server"""
    tag: str = Field(..., description="Clan tag (with or without #)")
    name: Optional[str] = Field(None, description="Clan name (fetched from API if not provided)")


class AddClanResponse(BaseModel):
    """Response after adding a clan"""
    message: str
    server_id: int
    clan_tag: str
    clan_name: str


class RemoveClanResponse(BaseModel):
    """Response after removing a clan"""
    message: str
    server_id: int
    clan_tag: str
    deleted_count: int
