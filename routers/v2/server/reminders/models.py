from pydantic import BaseModel, field_validator
from typing import Optional, List
import re


def validate_time_format(time_str: str, reminder_type: str) -> str:
    """Validate time format and limits based on reminder type.

    Args:
        time_str: Time string in format "X hr" or "X.X hr"
        reminder_type: Type of reminder ("War", "Clan Capital", "Clan Games", "Inactivity")

    Returns:
        The validated time string

    Raises:
        ValueError: If format is invalid or exceeds limits
    """
    # Check format is "X hr" or "X.X hr"
    pattern = r'^(\d+(?:\.\d+)?)\s+hr$'
    match = re.match(pattern, time_str)

    if not match:
        raise ValueError("Time must be in format 'X hr' where X is a number (e.g., '6 hr', '0.5 hr')")

    hours = float(match.group(1))

    if hours <= 0:
        raise ValueError("Time must be a positive number")

    # Check against type-specific limits
    limits = {
        "War": 48,
        "Clan Games": 336,  # 2 weeks
        "Clan Capital": 168,  # 1 week
        "Inactivity": None,  # No limit
        "roster": 48
    }

    max_hours = limits.get(reminder_type)

    if max_hours is not None and hours > max_hours:
        raise ValueError(f"Time must be less than or equal to {max_hours} hours for {reminder_type} reminders")

    return time_str


class ReminderConfig(BaseModel):
    """Configuration for a single reminder"""
    id: str
    type: str  # "War", "Clan Capital", "Clan Games", "Inactivity", "roster"
    clan_tag: Optional[str] = None
    channel_id: Optional[str] = None
    time: str
    custom_text: Optional[str] = None
    townhall_filter: Optional[List[int]] = None
    roles: Optional[List[str]] = None

    # War-specific
    war_types: Optional[List[str]] = None  # ["Random", "Friendly", "CWL"]

    # Clan Games-specific
    point_threshold: Optional[int] = None

    # Capital-specific
    attack_threshold: Optional[int] = None

    # Roster-specific
    roster_id: Optional[str] = None
    ping_type: Optional[str] = None


class ServerRemindersResponse(BaseModel):
    """All reminders for a server grouped by type"""
    war_reminders: List[ReminderConfig] = []
    capital_reminders: List[ReminderConfig] = []
    clan_games_reminders: List[ReminderConfig] = []
    inactivity_reminders: List[ReminderConfig] = []
    roster_reminders: List[ReminderConfig] = []


class CreateReminderRequest(BaseModel):
    """Request to create a new reminder"""
    type: str
    clan_tag: Optional[str] = None
    channel_id: str
    time: str
    custom_text: Optional[str] = None
    townhall_filter: Optional[List[int]] = None
    roles: Optional[List[str]] = None
    war_types: Optional[List[str]] = None
    point_threshold: Optional[int] = None
    attack_threshold: Optional[int] = None
    roster_id: Optional[str] = None
    ping_type: Optional[str] = None

    @field_validator('time')
    def validate_time(cls, v, info):
        """Validate time format and limits based on reminder type"""
        reminder_type = info.data.get('type', 'War')
        return validate_time_format(v, reminder_type)


class UpdateReminderRequest(BaseModel):
    """Request to update a reminder"""
    channel_id: Optional[str] = None
    time: Optional[str] = None
    custom_text: Optional[str] = None
    townhall_filter: Optional[List[int]] = None
    roles: Optional[List[str]] = None
    war_types: Optional[List[str]] = None
    point_threshold: Optional[int] = None
    attack_threshold: Optional[int] = None
    ping_type: Optional[str] = None
