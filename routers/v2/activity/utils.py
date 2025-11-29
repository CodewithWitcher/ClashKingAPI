"""Helper functions for activity tracking and analysis."""
import logging
from typing import Dict, List, Optional
import coc
import linkd
import pendulum as pend
from utils.database import MongoClient
from utils.custom_coc import CustomClashClient
from .models import ClanActivity, InactivePlayer

logger = logging.getLogger(__name__)

@linkd.ext.fastapi.inject
async def fetch_player_activity_map(player_tags: List[str]) -> Dict[str, pend.DateTime]:
    """Fetch last online timestamps for a list of player tags.

    Args:
        player_tags: List of player tags to fetch activity for

    Returns:
        dict: Mapping of player_tag -> last_online timestamp (pendulum DateTime)
    """
    player_last_online = await MongoClient.last_online.aggregate([
        {"$match": {"tag": {"$in": player_tags}}},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "player_tag": "$tag",
            "last_online": {"$first": "$$ROOT"}
        }}
    ]).to_list(length=None)

    return {
        item["player_tag"]: item["last_online"]["timestamp"]
        for item in player_last_online
    }


async def calculate_clan_activity(
    clan: coc.Clan,
    clan_name: str,
    inactive_threshold: pend.DateTime
) -> ClanActivity:
    """Calculate activity statistics for a single clan.

    Args:
        clan: CoC Clan object
        clan_name: Display name for the clan
        inactive_threshold: Pendulum DateTime before which players are considered inactive

    Returns:
        ClanActivity: Calculated activity statistics
    """
    # Fetch player activity data
    player_tags = [member.tag for member in clan.members]
    last_seen_map = await fetch_player_activity_map(player_tags)

    # Initialize counters
    active_count = 0
    inactive_count = 0
    donations_sent = 0
    donations_received = 0
    total_trophies = 0
    attacks_wins = 0

    # Process each member
    for member in clan.members:
        # Check activity status
        last_seen = last_seen_map.get(member.tag)
        if last_seen and last_seen >= inactive_threshold:
            active_count += 1
        else:
            inactive_count += 1

        # Aggregate statistics
        donations_sent += member.donations
        donations_received += member.received
        total_trophies += member.trophies
        attacks_wins += getattr(member, 'attack_wins', 0)

    # Calculate averages
    member_count = len(clan.members)
    activity_rate = (active_count / member_count * 100) if member_count > 0 else 0.0
    avg_donations_sent = donations_sent / member_count if member_count > 0 else 0.0
    avg_donations_received = donations_received / member_count if member_count > 0 else 0.0
    avg_trophies = total_trophies / member_count if member_count > 0 else 0.0

    return ClanActivity(
        clan_tag=clan.tag,
        clan_name=clan_name,
        total_members=member_count,
        active_members=active_count,
        inactive_members=inactive_count,
        activity_rate=activity_rate,
        average_donations_sent=avg_donations_sent,
        average_donations_received=avg_donations_received,
        total_donations_sent=donations_sent,
        total_donations_received=donations_received,
        total_attacks_wins=attacks_wins,
        average_trophies=avg_trophies
    )


async def find_inactive_players(
    clan: coc.Clan,
    clan_name: str,
    inactive_threshold: pend.DateTime,
    min_townhall: Optional[int] = None
) -> List[InactivePlayer]:
    """Find all inactive players in a clan.

    Args:
        clan: CoC Clan object
        clan_name: Display name for the clan
        inactive_threshold: Pendulum DateTime before which players are considered inactive
        min_townhall: Optional minimum townhall level filter

    Returns:
        List[InactivePlayer]: List of inactive players with their details
    """
    # Fetch player activity data
    player_tags = [member.tag for member in clan.members]
    last_seen_map = await fetch_player_activity_map(player_tags)

    inactive_players = []

    for member in clan.members:
        # Apply townhall filter if specified
        if min_townhall and member.town_hall < min_townhall:
            continue

        # Check if player is inactive
        last_seen = last_seen_map.get(member.tag)
        is_inactive = (not last_seen) or (last_seen < inactive_threshold)

        if is_inactive:
            # Calculate days inactive
            if last_seen:
                days_inactive = (pend.now(tz=pend.UTC) - last_seen).days
            else:
                days_inactive = None

            inactive_players.append(InactivePlayer(
                player_tag=member.tag,
                player_name=member.name,
                clan_tag=clan.tag,
                clan_name=clan_name,
                townhall_level=member.town_hall,
                role=member.role.name if member.role else "Member",
                last_seen=last_seen,
                days_inactive=days_inactive,
                trophies=member.trophies,
                donations_sent=member.donations,
                donations_received=member.received
            ))

    return inactive_players


async def process_clan_safely(
    clan_tag: str,
    clan_name: str,
    coc_client: CustomClashClient,
    processor_func,
    *args
):
    """Process a clan with error handling.

    Args:
        clan_tag: Clan tag to process
        clan_name: Display name for the clan
        coc_client: CoC API client
        processor_func: Function to process the clan (async)
        *args: Additional arguments to pass to processor_func

    Returns:
        Result from processor_func or None if error occurred
    """
    try:
        clan = await coc_client.get_clan(clan_tag)
        return await processor_func(clan, clan_name, *args)
    except coc.NotFound:
        logger.warning(f"Clan {clan_tag} not found, skipping")
        return None
    except Exception as e:
        logger.error(f"Error processing clan {clan_tag}: {e}", exc_info=True)
        return None
