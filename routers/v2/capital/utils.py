"""Helper functions for capital raids endpoints."""
import logging
import pendulum as pend
from typing import Dict, List, Any, Tuple, Optional
from fastapi import HTTPException
from datetime import datetime

from utils.database import MongoClient
from utils.utils import fix_tag

logger = logging.getLogger(__name__)

# Constants
SERVER_NOT_FOUND = "Server not found"
NO_CLANS_FOUND = "No clans found for this server"
INVALID_SEASON_FORMAT = "Invalid season format. Use YYYY-MM"

# MongoDB aggregation operator constants
MATCH_OP = "$match"
GROUP_OP = "$group"
COND_OP = "$cond"
DIVIDE_OP = "$divide"
TOTAL_RAIDS_FIELD = "$total_raids"


async def verify_server_exists(guild_id: int, mongo: MongoClient) -> Dict[str, Any]:
    """Verify that a server exists.

    Args:
        guild_id: Discord server ID
        mongo: MongoDB client instance

    Returns:
        Server document

    Raises:
        HTTPException: 404 if server not found
    """
    server = await mongo.server_db.find_one({"server": guild_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)
    return server


async def get_server_clans(
    guild_id: int,
    mongo: MongoClient,
    clan_tags_filter: Optional[List[str]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Get clans for a server, optionally filtered by tags.

    Args:
        guild_id: Discord server ID
        mongo: MongoDB client instance
        clan_tags_filter: Optional list of clan tags to filter by

    Returns:
        Tuple of (clan documents, clan_tag -> clan_name mapping)

    Raises:
        HTTPException: 404 if no clans found
    """
    query = {"server": guild_id}

    if clan_tags_filter:
        normalized_tags = [fix_tag(tag) for tag in clan_tags_filter]
        query["tag"] = {"$in": normalized_tags}

    clans = await mongo.clan_db.find(query).to_list(length=None)

    if not clans:
        raise HTTPException(status_code=404, detail=NO_CLANS_FOUND)

    clan_name_map = {clan["tag"]: clan["name"] for clan in clans}
    return clans, clan_name_map


def parse_season_dates(season: str) -> Tuple[datetime, datetime]:
    """Parse season string into start and end datetime objects.

    Args:
        season: Season string in YYYY-MM format

    Returns:
        Tuple of (start_date, end_date)

    Raises:
        HTTPException: 400 if invalid season format
    """
    try:
        year, month = season.split('-')
        start_date = pend.datetime(int(year), int(month), 1, tz=pend.UTC)

        if int(month) == 12:
            end_date = pend.datetime(int(year) + 1, 1, 1, tz=pend.UTC)
        else:
            end_date = pend.datetime(int(year), int(month) + 1, 1, tz=pend.UTC)

        return start_date, end_date
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail=INVALID_SEASON_FORMAT)


def build_raid_match_query(clan_tags: List[str], season: Optional[str] = None) -> Dict[str, Any]:
    """Build MongoDB match query for raid weekends.

    Args:
        clan_tags: List of clan tags to filter
        season: Optional season string (YYYY-MM)

    Returns:
        MongoDB match query dict

    Raises:
        HTTPException: 400 if invalid season format
    """
    match_query = {"data.clan.tag": {"$in": clan_tags}}

    if season:
        start_date, end_date = parse_season_dates(season)
        match_query["data.endTime"] = {
            "$gte": start_date.strftime("%Y%m%dT%H%M%S.000Z"),
            "$lt": end_date.strftime("%Y%m%dT%H%M%S.000Z")
        }

    return match_query


def build_player_stats_pipeline(
    match_query: Dict[str, Any],
    limit: int,
    offset: int
) -> List[Dict[str, Any]]:
    """Build aggregation pipeline for player statistics.

    Args:
        match_query: MongoDB match query
        limit: Maximum number of results
        offset: Number of results to skip

    Returns:
        MongoDB aggregation pipeline
    """
    return [
        {MATCH_OP: match_query},
        {"$unwind": "$data.members"},
        {
            GROUP_OP: {
                "_id": "$data.members.tag",
                "player_name": {"$first": "$data.members.name"},
                "clans": {"$addToSet": "$data.clan.tag"},
                "total_attacks": {"$sum": "$data.members.attacks"},
                "total_capital_gold_looted": {"$sum": "$data.members.capitalResourcesLooted"},
                "attacks_details": {"$push": "$data.members.attackLog"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "player_tag": "$_id",
                "player_name": 1,
                "total_attacks": 1,
                "total_capital_gold_looted": 1,
                "clans": 1,
                "attacks_details": 1
            }
        },
        {"$sort": {"total_capital_gold_looted": -1}},
        {"$skip": offset},
        {"$limit": limit}
    ]


def build_count_pipeline(match_query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build aggregation pipeline for counting players.

    Args:
        match_query: MongoDB match query

    Returns:
        MongoDB aggregation pipeline
    """
    return [
        {MATCH_OP: match_query},
        {"$unwind": "$data.members"},
        {GROUP_OP: {"_id": "$data.members.tag"}},
        {"$count": "total"}
    ]


def _safe_divide_expression(numerator: str, denominator: str) -> Dict[str, Any]:
    """Create a MongoDB conditional division expression that handles division by zero.

    Args:
        numerator: Field name for numerator (e.g., "$total_capital_gold_looted")
        denominator: Field name for denominator (e.g., "$total_raids")

    Returns:
        MongoDB conditional expression that returns 0 if denominator is 0, otherwise divides
    """
    return {
        COND_OP: [
            {"$eq": [denominator, 0]},
            0,
            {DIVIDE_OP: [numerator, denominator]}
        ]
    }

def build_clan_leaderboard_pipeline(match_query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build aggregation pipeline for clan leaderboard.

    Args:
        match_query: MongoDB match query

    Returns:
        MongoDB aggregation pipeline
    """
    return [
        {MATCH_OP: match_query},
        {
            GROUP_OP: {
                "_id": "$data.clan.tag",
                "total_raids": {"$sum": 1},
                "total_capital_gold_looted": {"$sum": "$data.capitalTotalLoot"},
                "total_raid_medals": {"$sum": "$data.totalRaidMedals"},
                "total_attacks": {"$sum": "$data.attackLog.attackCount"},
                "total_destruction": {"$sum": "$data.destructionPercent"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "clan_tag": "$_id",
                "total_raids": 1,
                "total_capital_gold_looted": 1,
                "total_raid_medals": 1,
                "total_attacks": 1,
                "average_capital_gold_per_raid": _safe_divide_expression("$total_capital_gold_looted", TOTAL_RAIDS_FIELD),
                "average_raid_medals_per_raid": _safe_divide_expression("$total_raid_medals", TOTAL_RAIDS_FIELD),
                "average_destruction": _safe_divide_expression("$total_destruction", "$total_attacks")
            }
        },
        {"$sort": {"total_capital_gold_looted": -1}}
    ]


def process_attack_details(attack_logs: List[List[Dict[str, Any]]], player_tag: str, player_name: str) -> Tuple[List[Any], float]:
    """Process attack details from raid logs and calculate total destruction.

    Args:
        attack_logs: List of attack log arrays from aggregation
        player_tag: Player tag for the attacker
        player_name: Player name for the attacker

    Returns:
        Tuple of (list of RaidAttack objects, total destruction percentage)
    """
    from .models import RaidAttack

    attacks = []
    total_destruction = 0.0

    for attack_log in attack_logs:
        if not attack_log:
            continue

        for attack in attack_log:
            if not attack:
                continue

            attacks.append(RaidAttack(
                attacker_tag=player_tag,
                attacker_name=player_name,
                defender_tag=attack.get("defenderTag"),
                defender_name=attack.get("defenderName"),
                destruction=attack.get("destructionPercent", 0),
                stars=attack.get("stars", 0)
            ))
            total_destruction += attack.get("destructionPercent", 0)

    return attacks, total_destruction


def format_player_stats(player_data: Dict[str, Any], clan_name_map: Dict[str, str]) -> Dict[str, Any]:
    """Format aggregated player data into PlayerRaidStats structure.

    Args:
        player_data: Raw player data from aggregation
        clan_name_map: Mapping of clan tags to clan names

    Returns:
        Dict containing formatted player statistics
    """
    # Process attacks and calculate destruction
    attacks, total_destruction = process_attack_details(
        player_data.get("attacks_details", []),
        player_data["player_tag"],
        player_data["player_name"]
    )

    # Calculate average destruction
    avg_destruction = total_destruction / len(attacks) if attacks else 0.0

    # Get primary clan
    primary_clan_tag = player_data["clans"][0] if player_data["clans"] else ""

    return {
        "player_tag": player_data["player_tag"],
        "player_name": player_data["player_name"],
        "clan_tag": primary_clan_tag,
        "clan_name": clan_name_map.get(primary_clan_tag, "Unknown"),
        "total_attacks": player_data["total_attacks"],
        "total_destruction": total_destruction,
        "total_capital_gold_looted": player_data["total_capital_gold_looted"],
        "total_raid_medals": 0,  # Raid medals are not tracked in attack logs
        "average_destruction": avg_destruction,
        "attacks": attacks
    }
