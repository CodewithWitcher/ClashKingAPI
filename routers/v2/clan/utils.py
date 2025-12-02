import statistics
import pendulum as pend
from collections import defaultdict, Counter
from typing import Dict, Any, List, Optional
import math

# Constants
PLAYER_TAGS_EMPTY = "player_tags cannot be empty"
CLAN_TAGS_EMPTY = "clan_tags cannot be empty"
ERROR_FETCHING_DATA = "Error fetching data"


def create_join_leave_filters(
    timestamp_start: int = 0,
    time_stamp_end: int = 9999999999,
    season: Optional[str] = None,
    current_season: Optional[bool] = False,
    limit: int = 50,
    filter_leave_join_enabled: bool = False,
    filter_join_leave_enabled: bool = False,
    filter_time: Optional[int] = 86400,
    only_type: Optional[str] = None,
    townhall: Optional[List[int]] = None,
    event_type: Optional[str] = None,
    tag: Optional[List[str]] = None,
    name_contains: Optional[str] = None
):
    """Create JoinLeaveQueryParams object from individual parameters.

    Args:
        timestamp_start: Start timestamp filter
        time_stamp_end: End timestamp filter
        season: Season filter (format YYYY-MM)
        current_season: Filter for current season
        limit: Maximum number of results
        filter_leave_join_enabled: Enable leave-join filtering
        filter_join_leave_enabled: Enable join-leave filtering
        filter_time: Time window for filtering in seconds
        only_type: Filter by join/leave pattern type
        townhall: Filter by townhall levels
        event_type: Filter by join or leave type
        tag: Filter by player tags
        name_contains: Filter by player name substring

    Returns:
        JoinLeaveQueryParams object
    """
    from routers.v2.clan.models import JoinLeaveQueryParams

    return JoinLeaveQueryParams(
        timestamp_start=timestamp_start,
        time_stamp_end=time_stamp_end,
        season=season,
        current_season=current_season,
        limit=limit,
        filter_leave_join_enabled=filter_leave_join_enabled,
        filter_join_leave_enabled=filter_join_leave_enabled,
        filter_time=filter_time,
        only_type=only_type,
        townhall=townhall,
        type=event_type,
        tag=tag,
        name_contains=name_contains
    )


def _should_skip_leave_join_pair(curr, next_evt, min_duration_seconds):
    """Check if a leave-join pair should be skipped based on duration."""
    if curr["type"] != "leave" or next_evt["type"] != "join":
        return False
    delta = (next_evt["time"] - curr["time"]).total_seconds()
    return delta < min_duration_seconds

def _filter_events_by_tag(evts, min_duration_seconds):
    """Filter events for a single tag, removing quick leave-join pairs."""
    evts.sort(key=lambda evt: evt["time"])
    skip_indices = set()
    i = 0
    while i < len(evts):
        if i + 1 < len(evts) and _should_skip_leave_join_pair(evts[i], evts[i + 1], min_duration_seconds):
            skip_indices.update([i, i + 1])
            i += 2
        else:
            i += 1
    return [evt for j, evt in enumerate(evts) if j not in skip_indices]

def filter_leave_join(events: list, min_duration_seconds: int) -> list:
    """
    Remove leave-join pairs for the same player when the rejoin is within a short time window,
    regardless of the order of the events.
    """
    by_tag = defaultdict(list)
    for e in events:
        by_tag[e["tag"]].append(e)

    filtered = []
    for tag, evts in by_tag.items():
        filtered.extend(_filter_events_by_tag(evts, min_duration_seconds))

    return sorted(filtered, key=lambda x: x["time"], reverse=True)

def _should_skip_join_leave_pair(e1, e2, min_duration_seconds):
    """Check if a join-leave pair should be skipped based on duration."""
    if e1["type"] != "join" or e2["type"] != "leave":
        return False
    delta = (e2["time"] - e1["time"]).total_seconds()
    return delta < min_duration_seconds

def _filter_join_leave_by_tag(evts, min_duration_seconds):
    """Filter join-leave events for a single tag."""
    evts.sort(key=lambda evt: evt["time"])
    skip = set()
    i = 0
    while i < len(evts) - 1:
        if _should_skip_join_leave_pair(evts[i], evts[i + 1], min_duration_seconds):
            skip.update([i, i + 1])
            i += 2
        else:
            i += 1
    return [evt for j, evt in enumerate(evts) if j not in skip]

def filter_join_leave(events: list, min_duration_seconds: int) -> list:
    """
    Remove join-leave pairs for the same player when the leave happens soon after the join.
    """
    by_tag = defaultdict(list)
    for e in events:
        by_tag[e["tag"]].append(e)

    filtered = []
    for tag, evts in by_tag.items():
        filtered.extend(_filter_join_leave_by_tag(evts, min_duration_seconds))

    return sorted(filtered, key=lambda x: x["time"], reverse=True)

def _matches_direction_and_types(e1, e2, direction):
    """Check if two events match the expected direction and types."""
    if direction == "join_leave":
        return e1["type"] == "join" and e2["type"] == "leave"
    if direction == "leave_join":
        return e1["type"] == "leave" and e2["type"] == "join"
    return False

def _extract_pairs_by_tag(evts, max_duration_seconds, direction):
    """Extract event pairs for a single tag."""
    evts.sort(key=lambda evt: evt["time"])
    pairs = []
    i = 0
    while i < len(evts) - 1:
        e1, e2 = evts[i], evts[i + 1]
        if _matches_direction_and_types(e1, e2, direction):
            delta = (e2["time"] - e1["time"]).total_seconds()
            if delta < max_duration_seconds:
                pairs.extend([e1, e2])
                i += 2
                continue
        i += 1
    return pairs

def extract_join_leave_pairs(events: list, max_duration_seconds: int, direction: str = "join_leave") -> list:
    """
    Return only join-leave (or leave-join) pairs where both actions happened within a short time window.
    direction: "join_leave" or "leave_join"
    """
    by_tag = defaultdict(list)
    for e in events:
        by_tag[e["tag"]].append(e)

    pairs = []
    for tag, evts in by_tag.items():
        pairs.extend(_extract_pairs_by_tag(evts, max_duration_seconds, direction))

    return sorted(pairs, key=lambda x: x["time"], reverse=True)

def _calculate_join_leave_time_deltas(tag_events):
    """Calculate time deltas between join-leave pairs."""
    time_deltas = []
    for tag, evs in tag_events.items():
        evs_sorted = sorted(evs, key=lambda x: x["time"])
        for i in range(len(evs_sorted) - 1):
            if evs_sorted[i]["type"] == "join" and evs_sorted[i + 1]["type"] == "leave":
                delta = (evs_sorted[i + 1]["time"] - evs_sorted[i]["time"]).total_seconds()
                time_deltas.append(delta)
    return time_deltas

def _get_players_by_last_event_type(tag_events, event_type):
    """Get set of players whose last event was of a specific type."""
    players = set()
    for tag, evs in tag_events.items():
        evs_sorted = sorted(evs, key=lambda x: x["time"])
        if evs_sorted[-1]["type"] == event_type:
            players.add(tag)
    return players

def _track_active_players(events):
    """Track which players are currently active based on join/leave events."""
    active_players = set()
    seen_players = set()
    for e in sorted(events, key=lambda x: x["time"]):
        if e["type"] == "join":
            active_players.add(e["tag"])
        elif e["type"] == "leave":
            active_players.discard(e["tag"])
        seen_players.add(e["tag"])
    return active_players, seen_players

def generate_stats(events):
    join_events = [e for e in events if e["type"] == "join"]
    leave_events = [e for e in events if e["type"] == "leave"]

    tags = [e["tag"] for e in events]
    players_by_tag = Counter(tags)

    tag_events = defaultdict(list)
    for e in events:
        tag_events[e["tag"]].append(e)

    active_players, seen_players = _track_active_players(events)
    time_deltas = _calculate_join_leave_time_deltas(tag_events)

    hours = [e["time"].hour for e in events]
    most_common_hour = Counter(hours).most_common(1)[0][0] if hours else None

    top_users = Counter(tags).most_common(3)
    top_users_named = [{"tag": t, "count": c, "name": next(e['name'] for e in events if e["tag"] == t)} for t, c in top_users]

    still_in_clan = _get_players_by_last_event_type(tag_events, "join")
    left_and_never_came_back = _get_players_by_last_event_type(tag_events, "leave")

    return {
        "total_events": len(events),
        "total_joins": len(join_events),
        "total_leaves": len(leave_events),
        "unique_players": len(seen_players),
        "moving_players": len(active_players),
        "rejoined_players": sum(1 for v in players_by_tag.values() if v > 1),
        "first_event": min(e["time"] for e in events).isoformat() if events else None,
        "last_event": max(e["time"] for e in events).isoformat() if events else None,
        "most_moving_hour": most_common_hour,
        "avg_time_between_join_leave": round(statistics.mean(time_deltas), 2) if time_deltas else None,
        "players_still_in_clan": len(still_in_clan),
        "players_left_forever": len(left_and_never_came_back),
        "most_moving_players": top_users_named,
    }

def _format_raid_summary(raid):
    """Format a raid summary with calculated averages."""
    if not raid:
        return None
    return {
        "startTime": raid.get("startTime"),
        "capitalTotalLoot": raid.get("capitalTotalLoot"),
        "totalRewards": raid.get("totalRewards"),
        "raidsCompleted": raid.get("raidsCompleted"),
        "totalAttacks": raid.get("totalAttacks"),
        "enemyDistrictsDestroyed": raid.get("enemyDistrictsDestroyed"),
        "avgAttacksPerRaid": round(raid.get("totalAttacks", 0) / max(raid.get("raidsCompleted", 0), 1), 2),
        "avgAttacksPerDistrict": round(raid.get("totalAttacks", 0) / max(raid.get("enemyDistrictsDestroyed", 0), 1), 2),
    }

def _update_best_worst_raids(raid, total_rewards, best_raid, worst_raid):
    """Update best and worst raid trackers."""
    updated_best = best_raid
    updated_worst = worst_raid

    if best_raid is None or total_rewards > best_raid.get("totalRewards", 0):
        updated_best = raid.copy()
        updated_best["totalRewards"] = total_rewards

    if raid.get("state") == "ended" and (worst_raid is None or total_rewards < worst_raid.get("totalRewards", 0)):
        updated_worst = raid.copy()
        updated_worst["totalRewards"] = total_rewards

    return updated_best, updated_worst

def _calculate_raid_averages(total_loot, total_attacks, number_weeks, total_raids, total_districts_destroyed, total_offensive_rewards, total_defensive_rewards):
    """Calculate average statistics from totals."""
    return {
        "avgLootPerAttack": round(total_loot / total_attacks, 2) if total_attacks else 0,
        "avgLootPerWeek": round(total_loot / number_weeks, 2) if number_weeks else 0,
        "avgAttacksPerWeek": round(total_attacks / number_weeks, 2) if number_weeks else 0,
        "avgAttacksPerRaid": round(total_attacks / total_raids, 2) if total_raids else 0,
        "avgAttacksPerDistrict": round(total_attacks / max(total_districts_destroyed, 1), 2) if total_districts_destroyed else 0,
        "avgOffensiveRewards": round(total_offensive_rewards / number_weeks, 2) if number_weeks else 0,
        "avgDefensiveRewards": round(total_defensive_rewards / number_weeks, 2) if number_weeks else 0,
    }

def generate_raids_clan_stats(history: list):
    total_loot = 0
    total_attacks = 0
    total_raids = 0
    number_weeks = 0
    total_districts_destroyed = 0
    best_raid = None
    worst_raid = None
    total_offensive_rewards = 0
    total_defensive_rewards = 0

    for raid in history:
        total_loot += raid.get("capitalTotalLoot", 0)
        total_attacks += raid.get("totalAttacks", 0)
        number_weeks += 1
        total_raids += raid.get("raidsCompleted", 0)
        total_districts_destroyed += raid.get("enemyDistrictsDestroyed", 0)
        total_offensive_rewards = 6 * raid.get("offensiveReward", 0)
        total_defensive_rewards = raid.get("defensiveReward", 0)
        total_rewards = total_defensive_rewards + total_offensive_rewards

        best_raid, worst_raid = _update_best_worst_raids(raid, total_rewards, best_raid, worst_raid)

    if number_weeks > 1:
        number_weeks -= 1

    averages = _calculate_raid_averages(
        total_loot, total_attacks, number_weeks, total_raids,
        total_districts_destroyed, total_offensive_rewards, total_defensive_rewards
    )

    return {
        "totalLoot": total_loot,
        "totalAttacks": total_attacks,
        "numberOfWeeks": number_weeks,
        "totalRaids": total_raids,
        "totalDistrictsDestroyed": total_districts_destroyed,
        "totalOffensiveRewards": total_offensive_rewards,
        "totalDefensiveRewards": total_defensive_rewards,
        **averages,
        "bestRaid": _format_raid_summary(best_raid),
        "worstRaid": _format_raid_summary(worst_raid),
    }


def predict_rewards(history: list):
    """
    Predicts offensive and defensive rewards for each raid season in the history.
    Modifies the history in place.
    """

    for raid_season in history:
        capital_loot = raid_season.get('capitalTotalLoot', 0)
        total_attacks = raid_season.get('totalAttacks', 0)

        if not capital_loot or not total_attacks:
            continue

        # Calculate average loot per attack
        avg_loot_per_attack = capital_loot / total_attacks

        # Calculate avg defense loot if available (fallback to avg_loot if not)
        avg_def_loot = avg_loot_per_attack  # Default fallback
        def_attacks = raid_season.get('defenseLog', [])
        if def_attacks:
            total_def_loot = sum(
                sum(district.get('totalLooted', 0) for district in attack.get('districts', []))
                for attack in def_attacks
            )
            total_def_attacks = sum(
                sum(district.get('attackCount', 0) for district in attack.get('districts', []))
                for attack in def_attacks
            )
            if total_def_attacks > 0:
                avg_def_loot = total_def_loot / total_def_attacks

        # Predict performance
        upper_bound = 5 * math.sqrt(capital_loot + 100000) - 500
        loot_difference = avg_def_loot - avg_loot_per_attack
        deduction_center = loot_difference + 700
        deduction_bottom = (loot_difference + 2000) / 20
        deduction_top = loot_difference / 20 + 1400
        deduction = max(min(max(deduction_center, deduction_bottom), deduction_top), 0)
        predicted_performance = max(upper_bound - deduction, 0)

        # Estimate offensiveReward and defensiveReward based on predicted performance
        predicted_offensive_reward = predicted_performance * 0.8  # Roughly 80% comes from offense
        predicted_defensive_reward = predicted_performance * 0.2  # Roughly 20% comes from defense

        # Fill missing rewards if needed
        if raid_season.get('offensiveReward', 0) == 0:
            raid_season['offensiveReward'] = int(predicted_offensive_reward)
        if raid_season.get('defensiveReward', 0) == 0:
            raid_season['defensiveReward'] = int(predicted_defensive_reward)


############################
# New helper functions for endpoints refactoring
############################

def calculate_clan_games_points(clan_stats: Dict[str, Any], season: str, previous_season: str) -> int:
    """Calculate total clan games points from current or previous season.

    Args:
        clan_stats: Clan statistics document
        season: Current season identifier
        previous_season: Previous season identifier

    Returns:
        Total clan games points
    """
    clan_games_points = 0

    if not clan_stats:
        return 0

    for s in [season, previous_season]:
        for tag, data in clan_stats.get(s, {}).items():
            # Can be None sometimes, fallback to zero
            clan_games_points += data.get('clan_games', 0) or 0
        if clan_games_points != 0:
            # If non-zero, CG has happened this season
            break

    return clan_games_points


def calculate_donations(clan_stats: Dict[str, Any], season: str) -> Dict[str, int]:
    """Calculate total donated and received troops for a season.

    Args:
        clan_stats: Clan statistics document
        season: Season identifier

    Returns:
        Dict with total_donated and total_received
    """
    total_donated = 0
    total_received = 0

    if not clan_stats:
        return {"total_donated": 0, "total_received": 0}

    for tag, data in clan_stats.get(season, {}).items():
        total_donated += data.get('donated', 0)
        total_received += data.get('received', 0)

    return {
        "total_donated": total_donated,
        "total_received": total_received
    }


def calculate_capital_donations(player_stats: List[Dict[str, Any]], raid_dates: List[str]) -> int:
    """Calculate total capital gold donated across raid weeks.

    Args:
        player_stats: List of player statistics
        raid_dates: List of raid date strings

    Returns:
        Total capital gold donated
    """
    donated_cc = 0

    for date in raid_dates:
        donated_cc += sum(
            sum(player.get('capital_gold', {}).get(f'{date}', {}).get('donate', []))
            for player in player_stats
        )

    return donated_cc


def calculate_activity_stats(player_stats: List[Dict[str, Any]], season: str, previous_season: str) -> Dict[str, Any]:
    """Calculate player activity statistics for the last 30 days and 48 hours.

    Args:
        player_stats: List of player statistics
        season: Current season identifier
        previous_season: Previous season identifier

    Returns:
        Dict with per_day average, last_48h count, and total score
    """
    now = pend.now(tz=pend.UTC)
    thirty_days_ago = now.subtract(days=30)
    forty_eight_hours_ago = now.subtract(hours=48)

    time_add = defaultdict(set)
    recent_active = set()

    for player in player_stats:
        for season_key in [season, previous_season]:
            for timestamp in player.get('last_online_times', {}).get(season_key, []):
                date = pend.from_timestamp(timestamp, tz=pend.UTC)

                # Only keep dates within the last 30 days
                if date >= thirty_days_ago:
                    time_add[date.date()].add(player.get("tag"))

                # Track players active in the last 48 hours
                if date >= forty_eight_hours_ago:
                    recent_active.add(player.get("tag"))

    num_players_day = [len(players) for players in time_add.values()]
    total_players = sum(num_players_day)
    avg_players = int(total_players / len(num_players_day)) if num_players_day else 0
    total_active_48h = len(recent_active)

    return {
        "per_day": avg_players,
        "last_48h": total_active_48h,
        "score": total_players
    }


def build_join_leave_query(
    clan_tag: str,
    timestamp_start: int,
    time_stamp_end: int,
    filters: Any
) -> Dict[str, Any]:
    """Build MongoDB query for join/leave events with filters.

    Args:
        clan_tag: Clan tag to filter
        timestamp_start: Start timestamp
        time_stamp_end: End timestamp
        filters: JoinLeaveQueryParams object with additional filters

    Returns:
        MongoDB query dict
    """
    base_query = {
        "$and": [
            {"clan": clan_tag},
            {"time": {"$gte": pend.from_timestamp(timestamp_start, tz=pend.UTC)}},
            {"time": {"$lte": pend.from_timestamp(time_stamp_end, tz=pend.UTC)}}
        ]
    }

    if hasattr(filters, 'type') and filters.type:
        base_query["$and"].append({"type": filters.type})
    if hasattr(filters, 'townhall') and filters.townhall:
        base_query["$and"].append({"th": {"$in": filters.townhall}})
    if hasattr(filters, 'tag') and filters.tag:
        base_query["$and"].append({"tag": {"$in": filters.tag}})
    if hasattr(filters, 'name_contains') and filters.name_contains:
        base_query["$and"].append({"name": {"$regex": filters.name_contains, "$options": "i"}})

    return base_query


def apply_join_leave_filters(result: List[Dict[str, Any]], filters: Any) -> List[Dict[str, Any]]:
    """Apply join/leave filters to results.

    Args:
        result: List of join/leave events
        filters: JoinLeaveQueryParams with filter settings

    Returns:
        Filtered list of events
    """
    if hasattr(filters, 'filter_leave_join_enabled') and filters.filter_leave_join_enabled:
        result = filter_leave_join(result, filters.filter_time)

    if hasattr(filters, 'filter_join_leave_enabled') and filters.filter_join_leave_enabled:
        result = filter_join_leave(result, filters.filter_time)

    if hasattr(filters, 'only_type') and filters.only_type in ("join_leave", "leave_join"):
        result = extract_join_leave_pairs(result, filters.filter_time, direction=filters.only_type)

    return result


def get_default_programmatic_filters() -> Dict[str, Any]:
    """Get default filters for programmatic calls.

    Returns:
        Dict with default filter values
    """
    return {
        "current_season": True,
        "limit": 50,
        "filter_leave_join_enabled": False,
        "filter_join_leave_enabled": False,
        "filter_time": 48,
        "only_type": None,
        "type": None,
        "townhall": None,
        "tag": None,
        "name_contains": None
    }


def build_programmatic_join_leave_query(
    clan_tag: str,
    programmatic_filters: Dict[str, Any]
) -> tuple[Dict[str, Any], int, int]:
    """Build query for programmatic join/leave calls.

    Args:
        clan_tag: Clan tag
        programmatic_filters: Dict with filter settings

    Returns:
        Tuple of (query dict, timestamp_start, timestamp_end)
    """
    from utils.time_utils import season_start_end

    # Determine time range
    if programmatic_filters.get("current_season", True):
        season_start, season_end = season_start_end(pend.now(tz=pend.UTC).format("YYYY-MM"))
        timestamp_start = int(season_start.timestamp())
        time_stamp_end = int(season_end.timestamp())
    else:
        timestamp_start = programmatic_filters.get("timestamp_start", 0)
        time_stamp_end = programmatic_filters.get("time_stamp_end", 9999999999)

    # Build base query
    base_query: Dict[str, Any] = {
        "$and": [
            {"clan": clan_tag},
            {"time": {"$gte": pend.from_timestamp(timestamp_start, tz=pend.UTC)}},
            {"time": {"$lte": pend.from_timestamp(time_stamp_end, tz=pend.UTC)}}
        ]
    }

    # Add optional filters
    if programmatic_filters.get("type"):
        base_query["$and"].append({"type": programmatic_filters["type"]})
    if programmatic_filters.get("townhall"):
        base_query["$and"].append({"th": {"$in": programmatic_filters["townhall"]}})
    if programmatic_filters.get("tag"):
        base_query["$and"].append({"tag": {"$in": programmatic_filters["tag"]}})
    if programmatic_filters.get("name_contains"):
        base_query["$and"].append({"name": {"$regex": programmatic_filters["name_contains"], "$options": "i"}})

    return base_query, timestamp_start, time_stamp_end


def apply_programmatic_filters(
    result: List[Dict[str, Any]],
    programmatic_filters: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Apply filters to results for programmatic calls.

    Args:
        result: List of join/leave events
        programmatic_filters: Dict with filter settings

    Returns:
        Filtered list of events
    """
    if programmatic_filters.get("filter_leave_join_enabled"):
        result = filter_leave_join(result, programmatic_filters.get("filter_time", 48))

    if programmatic_filters.get("filter_join_leave_enabled"):
        result = filter_join_leave(result, programmatic_filters.get("filter_time", 48))

    only_type = programmatic_filters.get("only_type")
    if only_type and only_type in ("join_leave", "leave_join"):
        result = extract_join_leave_pairs(
            result,
            programmatic_filters.get("filter_time", 48),
            direction=str(only_type)
        )

    return result


def process_member_buckets(member: Any, tag_to_location: Dict[str, Dict]) -> Dict[str, Any]:
    """Process a single clan member to extract bucket data.

    Args:
        member: Clan member object
        tag_to_location: Dict mapping tags to location info

    Returns:
        Dict with member's contribution to buckets
    """
    buckets_update = {
        "townhall": member.town_hall if member.town_hall != 0 else None,
        "trophies": str((member.trophies // 1000) * 1000) if member.trophies >= 1000 else '100',
        "role": member.role.in_game_name,
        "league": member.league.name,
        "location": None
    }

    if member.tag in tag_to_location:
        location = tag_to_location[member.tag]
        if location.get("country_code") is not None:
            buckets_update["location"] = location.get("country_code")

    return buckets_update
