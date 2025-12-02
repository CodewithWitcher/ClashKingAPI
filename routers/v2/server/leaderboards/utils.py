"""Helper functions for server leaderboards endpoints."""
import logging
from typing import Dict, List, Any, Tuple, Optional
from fastapi import HTTPException

from utils.database import MongoClient

logger = logging.getLogger(__name__)

# Constants
SERVER_NOT_FOUND = "Server not found"
NO_CLANS_FOUND = "No clans found for this server"


async def verify_server_exists(server_id: int, mongo: MongoClient) -> Dict[str, Any]:
    """Verify that a server exists.

    Args:
        server_id: Discord server ID
        mongo: MongoDB client instance

    Returns:
        Server document

    Raises:
        HTTPException: 404 if server not found
    """
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)
    return server


async def get_server_clans(
    server_id: int,
    mongo: MongoClient
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[str]]:
    """Get clans for a server.

    Args:
        server_id: Discord server ID
        mongo: MongoDB client instance

    Returns:
        Tuple of (clan documents, clan_tag -> clan_name mapping, list of clan tags)

    Raises:
        HTTPException: 404 if no clans found
    """
    clans = await mongo.clan_db.find({"server": server_id}).to_list(length=None)

    if not clans:
        raise HTTPException(status_code=404, detail=NO_CLANS_FOUND)

    clan_tags = [clan["tag"] for clan in clans]
    clan_name_map = {clan["tag"]: clan["name"] for clan in clans}

    return clans, clan_name_map, clan_tags


async def get_server_player_tags(server_id: int, mongo: MongoClient) -> List[str]:
    """Get all linked player tags for a server.

    Args:
        server_id: Discord server ID
        mongo: MongoDB client instance

    Returns:
        List of unique player tags
    """
    all_links = await mongo.coc_accounts.find(
        {"server": server_id}
    ).to_list(length=None)

    return list({link["player_tag"] for link in all_links})


def validate_and_get_season(season: str = None) -> str:
    """Validate season format and return season string.

    Args:
        season: Optional season string in YYYY-MM format

    Returns:
        Valid season string (current season if not provided)

    Raises:
        HTTPException: 400 if invalid season format
    """
    import pendulum

    # Default to current season if not provided
    if not season:
        now = pendulum.now(tz="UTC")
        season = now.strftime("%Y-%m")

    # Validate season format
    try:
        pendulum.from_format(season, "YYYY-MM")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid season format. Use YYYY-MM")

    return season


async def get_player_info_map(player_tags: List[str], mongo: MongoClient) -> Dict[str, Dict[str, Any]]:
    """Get player info for a list of player tags.

    Args:
        player_tags: List of player tags
        mongo: MongoDB client instance

    Returns:
        Dictionary mapping player_tag to player info (tag, name, townhall, clan)
    """
    player_stats = await mongo.player_stats.find(
        {"tag": {"$in": player_tags}},
        {"tag": 1, "name": 1, "townhall": 1, "clan": 1}
    ).to_list(length=None)

    return {p["tag"]: p for p in player_stats}


def _process_attacks(attacks: List[Any], stats: Dict[str, Any]) -> None:
    """Process attacks and count wins."""
    if not isinstance(attacks, list):
        return
    stats["total_attacks"] += len(attacks)
    for attack in attacks:
        if isinstance(attack, dict) and attack.get("stars", 0) >= 1:
            stats["attack_wins"] += 1

def _process_defenses(defenses: List[Any], stats: Dict[str, Any]) -> None:
    """Process defenses and count wins."""
    if not isinstance(defenses, list):
        return
    stats["total_defenses"] += len(defenses)
    for defense in defenses:
        if isinstance(defense, dict) and defense.get("stars", 0) == 0:
            stats["defense_wins"] += 1

def process_legend_day_data(day_data: Dict[str, Any], stats: Dict[str, Any]) -> None:
    """Process legend league data for a single day.

    Args:
        day_data: Day data from legends collection
        stats: Stats dictionary to update (modified in place)
    """
    if not isinstance(day_data, dict):
        return

    # Get trophy counts
    if stats["first_trophies"] is None:
        stats["first_trophies"] = day_data.get("start", 0)
    stats["last_trophies"] = day_data.get("end", 0)

    # Process attacks and defenses
    attacks = day_data.get("attacks", day_data.get("new_attacks", []))
    _process_attacks(attacks, stats)

    defenses = day_data.get("defenses", day_data.get("new_defenses", []))
    _process_defenses(defenses, stats)


def calculate_legend_stats(legends_data: Dict[str, Any], dates: List[str]) -> Optional[Dict[str, Any]]:
    """Calculate legend league stats across multiple days.

    Args:
        legends_data: Player's legends data
        dates: List of dates to process

    Returns:
        Dictionary with calculated stats or None if no activity
    """
    if not isinstance(legends_data, dict):
        return None

    stats = {
        "total_attacks": 0,
        "total_defenses": 0,
        "attack_wins": 0,
        "defense_wins": 0,
        "first_trophies": None,
        "last_trophies": None
    }

    for date in reversed(dates):  # Process chronologically
        day_data = legends_data.get(date)
        process_legend_day_data(day_data, stats)

    # Skip players with no legend activity
    if stats["total_attacks"] == 0 and stats["total_defenses"] == 0:
        return None

    # Calculate trophy change
    trophy_change = 0
    current_trophies = 0
    if stats["first_trophies"] is not None and stats["last_trophies"] is not None:
        trophy_change = stats["last_trophies"] - stats["first_trophies"]
        current_trophies = stats["last_trophies"]

    stats["trophy_change"] = trophy_change
    stats["current_trophies"] = current_trophies
    stats["streak"] = legends_data.get("streak")

    return stats


def get_clan_info_from_player(player: Dict[str, Any], clan_name_map: Dict[str, str]) -> Tuple[str, str]:
    """Extract clan tag and name from player data.

    Args:
        player: Player document
        clan_name_map: Mapping of clan_tag to clan_name

    Returns:
        Tuple of (clan_tag, clan_name)
    """
    player_clan = player.get("clan", {})
    player_clan_tag = player_clan.get("tag") if isinstance(player_clan, dict) else None
    player_clan_name = clan_name_map.get(player_clan_tag) if player_clan_tag else None
    return player_clan_tag, player_clan_name


def process_war_member_attacks(member: Dict[str, Any], stats: Dict[str, Any]) -> None:
    """Process attacks for a war member.

    Args:
        member: War member data
        stats: Stats dictionary to update (modified in place)
    """
    attacks = member.get("attacks", [])
    for attack in attacks:
        stats["attack_count"] += 1
        stats["total_stars"] += attack.get("stars", 0)
        stats["total_destruction"] += attack.get("destructionPercentage", 0.0)

        if attack.get("stars", 0) == 3:
            stats["triple_stars"] += 1


def init_war_stats(member: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize war stats for a player.

    Args:
        member: War member data

    Returns:
        Initialized stats dictionary
    """
    return {
        "name": member.get("name", "Unknown"),
        "townhall": member.get("townhallLevel"),
        "total_stars": 0,
        "total_destruction": 0.0,
        "attack_count": 0,
        "defense_count": 0,
        "triple_stars": 0,
        "war_count": 0
    }


def process_war_stats(wars: List[Dict[str, Any]], player_tags: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process war data to build per-player stats.

    Args:
        wars: List of war documents
        player_tags: List of player tags to track

    Returns:
        Dictionary mapping player_tag to war stats
    """
    player_war_stats = {}
    player_tags_set = set(player_tags)

    for war in wars:
        all_members = war.get("clan_members", []) + war.get("opponent_members", [])

        for member in all_members:
            tag = member.get("tag")
            if tag not in player_tags_set:
                continue

            if tag not in player_war_stats:
                player_war_stats[tag] = init_war_stats(member)

            stats = player_war_stats[tag]
            stats["war_count"] += 1

            # Process attacks
            process_war_member_attacks(member, stats)

            # Count defenses
            if member.get("bestOpponentAttack"):
                stats["defense_count"] += 1

    return player_war_stats


def process_raid_stats(raids: List[Dict[str, Any]], player_tags: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process capital raid data to build per-player stats.

    Args:
        raids: List of raid weekend documents
        player_tags: List of player tags to track

    Returns:
        Dictionary mapping player_tag to raid stats
    """
    player_raid_stats = {}
    player_tags_set = set(player_tags)

    for raid in raids:
        members = raid.get("data", {}).get("members", [])

        for member in members:
            tag = member.get("tag")
            if tag not in player_tags_set:
                continue

            if tag not in player_raid_stats:
                player_raid_stats[tag] = {
                    "name": member.get("name", "Unknown"),
                    "total_capital_gold": 0,
                    "total_raids": 0,
                    "total_attacks": 0
                }

            stats = player_raid_stats[tag]
            stats["total_capital_gold"] += member.get("capitalResourcesLooted", 0)
            stats["total_raids"] += 1
            stats["total_attacks"] += member.get("attacks", 0)

    return player_raid_stats


def extract_looting_stats(player: Dict[str, Any], season: str) -> Dict[str, int]:
    """Extract looting stats for a player for a given season.

    Args:
        player: Player document
        season: Season string (YYYY-MM format)

    Returns:
        Dictionary with gold, elixir, dark_elixir, and total looted amounts
    """
    gold_data = player.get("gold", {})
    elixir_data = player.get("elixir", {})
    dark_elixir_data = player.get("dark_elixir", {})

    gold_looted = gold_data.get(season, 0) if isinstance(gold_data, dict) else 0
    elixir_looted = elixir_data.get(season, 0) if isinstance(elixir_data, dict) else 0
    dark_elixir_looted = dark_elixir_data.get(season, 0) if isinstance(dark_elixir_data, dict) else 0

    total_looted = gold_looted + elixir_looted + dark_elixir_looted

    return {
        "gold_looted": gold_looted,
        "elixir_looted": elixir_looted,
        "dark_elixir_looted": dark_elixir_looted,
        "total_looted": total_looted
    }
