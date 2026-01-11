from typing import Union, List, Optional, Tuple
import logging
import coc
from fastapi import HTTPException
import pendulum as pend
import sentry_sdk
from routers.v2.war.utils import fetch_current_war_info_bypass
from utils.database import MongoClient
from utils.time_utils import is_raids
from utils.utils import fix_tag

logger = logging.getLogger(__name__)

# Constants
PLAYER_NOT_FOUND = "Player not found"
COC_API_MAINTENANCE = "Clash of Clans API is currently in maintenance. Please try again later."
COC_API_DOWN = "Clash of Clans API is currently down. Please try again later."


def get_legend_season_range(date: pend.DateTime) -> Tuple[pend.DateTime, pend.DateTime]:
    """Return the start and end of the Legend League season (Monday 5am UTC to Monday 5am UTC) for a given date.

    Args:
        date: The date to calculate the legend season range for

    Returns:
        Tuple of (season_start, season_end) as pendulum DateTime objects
    """

    # Find the last Monday of the month at 5am UTC
    last_monday_this_month = date.end_of("month")
    while last_monday_this_month.day_of_week != pend.MONDAY:
        last_monday_this_month = last_monday_this_month.subtract(days=1)
    season_start = last_monday_this_month.replace(hour=0, minute=0, second=0, microsecond=0)

    # If the date is before the last Monday of the month, it's part of the previous season
    if date < season_start:
        last_monday_previous_month = date.subtract(months=1).end_of("month")
        while last_monday_previous_month.day_of_week != pend.MONDAY:
            last_monday_previous_month = last_monday_previous_month.subtract(days=1)
        season_start = last_monday_previous_month.replace(hour=0, minute=0, second=0, microsecond=0)

    # If the date is after the last Monday of the month, it's part of the next season
    last_monday_next_month = season_start.add(months=1).end_of("month")
    while last_monday_next_month.day_of_week != pend.MONDAY:
        last_monday_next_month = last_monday_next_month.subtract(days=1)
    season_end = last_monday_next_month.replace(hour=0, minute=0, second=0, microsecond=0).subtract(seconds=1)

    return season_start, season_end


async def get_legend_stats_common(player_tags: Union[str, List[str]], mongo: MongoClient) -> Union[dict, List[dict]]:
    """Returns enriched legend stats for a single tag or list of tags.

    Args:
        player_tags: A single player tag (str) or list of player tags
        mongo: MongoDB client instance

    Returns:
        Single dict if input was str, List of dicts if input was List[str].
        Each dict contains tag and legends_by_season data.

    Raises:
        HTTPException: 404 if single player not found
    """
    if isinstance(player_tags, str):
        fixed_tag = fix_tag(player_tags)
        player = await mongo.player_stats.find_one(
            {'tag': fixed_tag},
            {'_id': 0, 'tag': 1, 'legends': 1}
        )
        if not player:
            raise HTTPException(status_code=404, detail=f"{PLAYER_NOT_FOUND}: {fixed_tag}")
        grouped_legends = process_legend_stats(player.get("legends", {}))
        return {
            "tag": fixed_tag,
            "legends_by_season": grouped_legends
        }

    fixed_tags = [fix_tag(tag) for tag in player_tags]
    players_info = await mongo.player_stats.find(
        {'tag': {'$in': fixed_tags}},
        {'_id': 0, 'tag': 1, 'legends': 1}
    ).to_list(length=None)

    return [
        {
            "tag": player["tag"],
            "legends_by_season": process_legend_stats(player.get("legends", {}))
        } for player in players_info
    ]


def initialize_season_data(season_start, season_end) -> dict:
    """Initialize empty season data structure.

    Args:
        season_start: Season start date
        season_end: Season end date

    Returns:
        Dictionary with initialized season statistics
    """
    return {
        "season_start": season_start.to_date_string(),
        "season_end": season_end.to_date_string(),
        "season_duration": 0,
        "season_days_in_legend": 0,
        "season_end_trophies": 0,
        "season_trophies_gained_total": 0,
        "season_trophies_lost_total": 0,
        "season_trophies_net": 0,
        "season_total_attacks": 0,
        "season_total_defenses": 0,
        "season_stars_distribution_attacks": {0: 0, 1: 0, 2: 0, 3: 0},
        "season_stars_distribution_defenses": {0: 0, 1: 0, 2: 0, 3: 0},
        "season_stars_distribution_attacks_percentages": {},
        "season_stars_distribution_defenses_percentages": {},
        "season_average_trophies_gained_per_attack": 0,
        "season_average_trophies_lost_per_defense": 0,
        "season_total_attacks_defenses_possible": 0,
        "season_total_gained_lost_possible": 0,
        "season_trophies_gained_ratio": 0,
        "season_trophies_lost_ratio": 0,
        "season_total_attacks_ratio": 0,
        "season_total_defenses_ratio": 0,
        "days": {}
    }


def process_day_attacks(new_attacks: list, season: dict) -> None:
    """Process attack events and update star distribution.

    Args:
        new_attacks: List of attack events
        season: Season data dictionary to update
    """
    if new_attacks:
        for attack in new_attacks:
            stacked_value = attack.get("change", 0)
            individual_attacks = estimate_individual_attacks_from_stacked(stacked_value)
            for trophies in individual_attacks:
                if 5 <= trophies <= 15:
                    season["season_stars_distribution_attacks"][1] += 1
                elif 16 <= trophies <= 32:
                    season["season_stars_distribution_attacks"][2] += 1
                elif trophies == 40:
                    season["season_stars_distribution_attacks"][3] += 1
                else:
                    season["season_stars_distribution_attacks"][2] += 1


def process_day_defenses(new_defenses: list, season: dict) -> None:
    """Process defense events and update star distribution.

    Args:
        new_defenses: List of defense events
        season: Season data dictionary to update
    """
    if new_defenses:
        for defense in new_defenses:
            stacked_value = defense.get("change", 0)
            individual_defenses = estimate_individual_defenses_from_stacked(stacked_value)
            for trophies in individual_defenses:
                if 0 <= trophies <= 4:
                    season["season_stars_distribution_defenses"][0] += 1
                elif 5 <= trophies <= 15:
                    season["season_stars_distribution_defenses"][1] += 1
                elif 16 <= trophies <= 32:
                    season["season_stars_distribution_defenses"][2] += 1
                elif trophies == 40:
                    season["season_stars_distribution_defenses"][3] += 1
                else:
                    season["season_stars_distribution_defenses"][2] += 1


def enrich_day_data_new_format(day_data: dict) -> None:
    """Enrich day data from new format (new_attacks/new_defenses).

    Args:
        day_data: Day data dictionary to enrich
    """
    new_attacks = day_data.get("new_attacks", [])
    new_defenses = day_data.get("new_defenses", [])
    all_events = sorted(new_attacks + new_defenses, key=lambda x: x.get("time", 0))

    if all_events and "trophies" in all_events[-1]:
        # Only calculate if not already set by process_legend_stats
        if "end_trophies" not in day_data:
            day_data["end_trophies"] = all_events[-1]["trophies"]
        if "trophies_gained_total" not in day_data:
            day_data["trophies_gained_total"] = sum(e.get("change", 0) for e in new_attacks)
        if "trophies_lost_total" not in day_data:
            day_data["trophies_lost_total"] = sum(e.get("change", 0) for e in new_defenses)
        if "trophies_total" not in day_data:
            day_data["trophies_total"] = day_data["trophies_gained_total"] - day_data["trophies_lost_total"]
        if "start_trophies" not in day_data:
            day_data["start_trophies"] = all_events[0]["trophies"]


def enrich_day_data_old_format(day_data: dict) -> None:
    """Enrich day data from old format (attacks/defenses lists).

    Args:
        day_data: Day data dictionary to enrich
    """
    attacks = day_data.get("attacks", [])
    defenses = day_data.get("defenses", [])

    trophies_gained = sum(attacks)
    trophies_lost = sum(defenses)
    trophies_total = trophies_gained + trophies_lost

    day_data["trophies_gained_total"] = trophies_gained
    day_data["trophies_lost_total"] = trophies_lost
    day_data["trophies_total"] = trophies_total


def update_season_with_day_data(season: dict, day_str: str, day_data: dict) -> None:
    """Update season cumulative statistics with day data.

    Args:
        season: Season data dictionary to update
        day_str: Day string key
        day_data: Day data to add to season
    """
    gained = day_data.get("trophies_gained_total", 0)
    lost = day_data.get("trophies_lost_total", 0)
    attacks = day_data.get("num_attacks", 0)
    defenses = day_data.get("num_defenses", 0)
    end_trophies = day_data.get("end_trophies", 0)

    season["season_end_trophies"] = end_trophies
    season["days"][day_str] = day_data

    season["season_trophies_gained_total"] += gained
    season["season_trophies_lost_total"] += lost
    season["season_trophies_net"] += (gained - lost)
    season["season_total_attacks"] += attacks
    season["season_total_defenses"] += defenses


def update_season_ratios(season: dict) -> None:
    """Calculate and update season performance ratios.

    Args:
        season: Season data dictionary to update
    """
    total_possible = len(season["days"]) * 8
    season["season_total_attacks_defenses_possible"] = total_possible
    season["season_total_gained_lost_possible"] = total_possible * 40

    if season["season_total_gained_lost_possible"] > 0:
        season["season_trophies_gained_ratio"] = round(
            season["season_trophies_gained_total"] / season["season_total_gained_lost_possible"], 2)
        season["season_trophies_lost_ratio"] = round(
            season["season_trophies_lost_total"] / season["season_total_gained_lost_possible"], 2)

    if season["season_total_attacks_defenses_possible"] > 0:
        season["season_total_attacks_ratio"] = round(
            season["season_total_attacks"] / season["season_total_attacks_defenses_possible"], 2)
        season["season_total_defenses_ratio"] = round(
            season["season_total_defenses"] / season["season_total_attacks_defenses_possible"], 2)


def finalize_season_stats(season: dict) -> None:
    """Calculate final season statistics and percentages.

    Args:
        season: Season data dictionary to finalize
    """
    total_attacks = season.get("season_total_attacks", 0)
    total_defenses = season.get("season_total_defenses", 0)

    if total_attacks > 0:
        season["season_stars_distribution_attacks_percentages"] = {
            str(i): round(season["season_stars_distribution_attacks"].get(i, 0) / total_attacks * 100, 1)
            for i in range(4)
        }
        season["season_average_trophies_gained_per_attack"] = round(
            season["season_trophies_gained_total"] / total_attacks, 2
        )

    if total_defenses > 0:
        season["season_stars_distribution_defenses_percentages"] = {
            str(i): round(season["season_stars_distribution_defenses"].get(i, 0) / total_defenses * 100, 1)
            for i in range(4)
        }
        season["season_average_trophies_lost_per_defense"] = round(
            season["season_trophies_lost_total"] / total_defenses, 2
        )

    season["season_days_in_legend"] = len(season["days"])
    try:
        start = pend.parse(season["season_start"])
        end = pend.parse(season["season_end"])
        season["season_duration"] = (end - start).days + 1
    except ValueError:
        season["season_duration"] = 0


def _parse_day_and_get_season(day_str: str) -> Optional[Tuple[str, pend.DateTime, pend.DateTime]]:
    """Parse day string and get season range.

    Args:
        day_str: Date string to parse

    Returns:
        Tuple of (season_key, season_start, season_end) or None if parsing fails
    """
    try:
        day = pend.parse(day_str)
        season_start, season_end = get_legend_season_range(day)
        return season_start.to_date_string(), season_start, season_end
    except (ValueError, AttributeError):
        return None


def _enrich_and_process_day_data(day_data: dict, season: dict, day_str: str) -> None:
    """Enrich day data and process attacks/defenses.

    Args:
        day_data: Day data to enrich
        season: Season data to update
        day_str: Date string key
    """
    # Enrich day data based on format
    is_new_format = "new_attacks" in day_data or "new_defenses" in day_data
    if is_new_format:
        enrich_day_data_new_format(day_data)
    else:
        enrich_day_data_old_format(day_data)

    # Update season with day data
    update_season_with_day_data(season, day_str, day_data)


def _process_attacks_and_defenses(day_data: dict, season: dict) -> None:
    """Process attacks and defenses for star distribution.

    Args:
        day_data: Day data containing attacks/defenses
        season: Season data to update
    """
    # Process attacks
    new_attacks = day_data.get("new_attacks", [])
    if new_attacks:
        process_day_attacks(new_attacks, season)
    else:
        old_attacks = [{"change": val} for val in day_data.get("attacks", [])]
        process_day_attacks(old_attacks, season)

    # Process defenses
    new_defenses = day_data.get("new_defenses", [])
    if new_defenses:
        process_day_defenses(new_defenses, season)
    else:
        old_defenses = [{"change": val} for val in day_data.get("defenses", [])]
        process_day_defenses(old_defenses, season)


def group_legends_by_season(legends: dict) -> dict:
    """Group daily legends data into seasons with cumulative stats.

    Args:
        legends: Dictionary of daily legend league data, keyed by date string

    Returns:
        Dictionary keyed by season start date, containing aggregated season statistics:
        - Daily stats grouped by season
        - Cumulative trophy gains/losses
        - Attack and defense statistics
        - Star distributions
        - Performance ratios
    """
    grouped = {}

    for day_str, day_data in legends.items():
        if not isinstance(day_data, dict):
            continue  # Skip non-date keys like "streak"

        season_info = _parse_day_and_get_season(day_str)
        if not season_info:
            continue

        season_key, season_start, season_end = season_info

        if season_key not in grouped:
            grouped[season_key] = initialize_season_data(season_start, season_end)

        season = grouped[season_key]

        # Enrich and process day data
        _enrich_and_process_day_data(day_data, season, day_str)

        # Process attacks and defenses
        _process_attacks_and_defenses(day_data, season)

        # Update performance ratios
        update_season_ratios(season)

    # Finalize all season statistics
    for season in grouped.values():
        finalize_season_stats(season)

    return grouped


def count_number_of_attacks_from_list(attacks: list[int]) -> int:
    """Count the number of attacks from a list of attack trophies.

    Args:
        attacks: List of stacked trophy values from attacks

    Returns:
        Total number of individual attacks
    """
    count = 0
    for value in attacks:
        if 280 < value <= 320:
            count += 8
        elif 240 < value <= 280:
            count += 7
        elif 200 < value <= 240:
            count += 6
        elif 160 < value <= 200:
            count += 5
        elif 120 < value <= 160:
            count += 4
        elif 80 < value <= 120:
            count += 3
        elif 40 < value <= 80:
            count += 2
        else:
            count += 1
    return count


def estimate_individual_attacks_from_stacked(stacked_value: int) -> list[int]:
    """Unstack a stacked trophy value into individual attack trophy values.

    Args:
        stacked_value: Cumulative trophy value from multiple attacks

    Returns:
        List of estimated individual attack trophy values
    """
    individual_attacks = []
    remaining = stacked_value
    
    # Work backwards from the highest possible values
    while remaining > 0:
        if remaining >= 40:
            individual_attacks.append(40)  # 3-star attack
            remaining -= 40
        elif remaining >= 32:
            individual_attacks.append(32)  # 2-star attack
            remaining -= 32
        elif remaining >= 16:
            individual_attacks.append(16)  # 2-star attack (low end)
            remaining -= 16
        elif remaining >= 15:
            individual_attacks.append(15)  # 1-star attack
            remaining -= 15
        elif remaining >= 5:
            individual_attacks.append(remaining)  # 1-star attack (variable)
            remaining = 0
        else:
            # Handle edge cases - assume minimum attack value
            individual_attacks.append(max(remaining, 5))
            remaining = 0
    
    return individual_attacks


def estimate_individual_defenses_from_stacked(stacked_value: int) -> list[int]:
    """Unstack a stacked trophy value into individual defense trophy values.

    Args:
        stacked_value: Cumulative trophy loss value from multiple defenses (typically negative)

    Returns:
        List of estimated individual defense trophy values
    """
    individual_defenses = []
    remaining = abs(stacked_value)  # Defense values are typically negative, make positive
    
    # Work backwards from the highest possible values
    while remaining > 0:
        if remaining >= 40:
            individual_defenses.append(40)  # 3-star defense
            remaining -= 40
        elif remaining >= 32:
            individual_defenses.append(32)  # 2-star defense
            remaining -= 32
        elif remaining >= 16:
            individual_defenses.append(16)  # 2-star defense (low end)
            remaining -= 16
        elif remaining >= 15:
            individual_defenses.append(15)  # 1-star defense
            remaining -= 15
        elif remaining > 0:
            # 1-star defense (5-15 trophies) or 0-star defense (0-4 trophies)
            individual_defenses.append(remaining)
            remaining = 0
    
    return individual_defenses


def process_legend_stats(raw_legends: dict) -> dict:
    """Enrich raw legends days and group them by season.

    Args:
        raw_legends: Raw daily legend data from MongoDB

    Returns:
        Grouped legend data by season with enriched statistics
    """
    for day, data in raw_legends.items():
        if not isinstance(data, dict):
            continue

        new_attacks = data.get("new_attacks", [])
        new_defenses = data.get("new_defenses", [])

        all_events = sorted(new_attacks + new_defenses, key=lambda x: x.get("time", 0))
        if all_events:
            # Get actual start and end trophies from the chronological events
            first_event = all_events[0]
            last_event = all_events[-1]
            
            end_trophies = last_event.get("trophies", 0)
            trophies_gained = sum(entry.get("change", 0) for entry in new_attacks)
            trophies_lost = sum(entry.get("change", 0) for entry in new_defenses)
            trophies_total = trophies_gained - trophies_lost
            
            # Calculate start_trophies by working backwards from the first event
            # If first event is defense: before_trophies = after_trophies + change
            # If first event is attack: before_trophies = after_trophies - change
            if first_event in new_defenses:
                start_trophies = first_event.get("trophies", 0) + first_event.get("change", 0)
            else:  # attack
                start_trophies = first_event.get("trophies", 0) - first_event.get("change", 0)

            data["start_trophies"] = start_trophies
            data["end_trophies"] = end_trophies
            data["trophies_gained_total"] = trophies_gained
            data["trophies_lost_total"] = trophies_lost
            data["trophies_total"] = trophies_total
            data["num_defenses"] = count_number_of_attacks_from_list(data.get("defenses", []))

    return group_legends_by_season(raw_legends)


async def get_legend_rankings_for_tag(tag: str, limit: int = 10, mongo: MongoClient = None) -> list[dict]:
    """Get historical legend rankings for a player tag.

    Args:
        tag: Player tag
        limit: Maximum number of historical rankings to return
        mongo: MongoDB client instance

    Returns:
        List of historical ranking records sorted by season (most recent first)
    """
    tag = fix_tag(tag)
    results = await mongo.history_db.find({"tag": tag}).sort("season", -1).limit(limit).to_list(length=None)
    for result in results:
        result.pop("_id", None)
    return results


async def get_current_rankings(tag: str, mongo: MongoClient = None) -> dict:
    """Get current leaderboard rankings for a player.

    Args:
        tag: Player tag
        mongo: MongoDB client instance

    Returns:
        Dictionary containing country_code, country_name, local_rank, and global_rank.
        Returns None values if player is not ranked.
    """
    ranking_data = await mongo.leaderboard_db.find_one({"tag": tag}, projection={"_id": 0})
    if not ranking_data:
        ranking_data = {
            "country_code": None,
            "country_name": None,
            "local_rank": None,
            "global_rank": None
        }
    if ranking_data.get("global_rank") is None:
        fallback = await mongo.legend_rankings.find_one({"tag": tag})
        if fallback:
            ranking_data["global_rank"] = fallback.get("rank")
    return ranking_data


async def fetch_player_api_data(session, tag: str):
    """Fetch player data from Clash of Clans API.

    Args:
        session: aiohttp ClientSession
        tag: Player tag

    Returns:
        Player data dictionary from API, or None if not found

    Raises:
        HTTPException: 503 if API is in maintenance
        HTTPException: 500 if API is down
    """
    url = f"https://proxy.clashk.ing/v1/players/{tag.replace('#', '%23')}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            elif response.status == 503:
                raise HTTPException(status_code=503, detail=COC_API_MAINTENANCE)
            elif response.status == 500:
                raise HTTPException(status_code=500, detail=COC_API_DOWN)
        return None
    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "function": "fetch_player_api_data",
            "tag": tag
        })
        logger.error(f"Error fetching player API data for {tag}: {e}")
        return None


async def fetch_raid_data(session, tag: str, player_clan_tag: str):
    """Fetch capital raid weekend data for a player.

    Args:
        session: aiohttp ClientSession
        tag: Player tag
        player_clan_tag: Clan tag to check for raid data

    Returns:
        Dictionary with attacks_done and attack_limit, or empty dict if no active raid
    """
    raid_data = {}
    if not player_clan_tag:
        return raid_data

    try:
        url = f"https://proxy.clashk.ing/v1/clans/{player_clan_tag.replace('#', '%23')}/capitalraidseasons?limit=1"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("items"):
                    raid_weekend_entry = coc.RaidLogEntry(data=data["items"][0], client=None, clan_tag=player_clan_tag)
                    if raid_weekend_entry.end_time.seconds_until >= 0:
                        raid_member = raid_weekend_entry.get_member(tag=tag)
                        if raid_member:
                            raid_data = {
                                "attacks_done": raid_member.attack_count,
                                "attack_limit": raid_member.attack_limit + raid_member.bonus_attack_limit,
                            }
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "function": "fetch_raid_data",
            "tag": tag,
            "clan_tag": player_clan_tag
        })
        logger.error(f"Error fetching raid data for {tag}: {e}")

    return raid_data


async def fetch_full_player_data(session, tag: str, mongo_data: dict, clan_tag: Optional[str], mongo: MongoClient = None):
    """Fetch complete player data including raid and war information.

    Args:
        session: aiohttp ClientSession
        tag: Player tag
        mongo_data: Pre-fetched MongoDB player stats data
        clan_tag: Optional clan tag for raid/war context
        mongo: MongoDB client instance

    Returns:
        Tuple of (tag, raid_data, war_data, mongo_data)
    """
    war_data = {}
    raid_data = await fetch_raid_data(session, tag, clan_tag) if is_raids() else {}
    war_timer = await mongo.war_timers.find_one({"_id": tag}, {"_id": 0}) or {} if mongo else {}
    if clan_tag not in war_timer.get("clans", []):
        clans_list = war_timer.get("clans", [])
        war_clan_tag = clans_list[0] if clans_list else None
        if war_clan_tag:  # Only fetch war data if we have a valid clan tag
            war_data = await fetch_current_war_info_bypass(war_clan_tag, session)
    return tag, raid_data, war_data, mongo_data


async def assemble_full_player_data(tag, raid_data, war_data, mongo_data, legends_data, mongo: MongoClient = None):
    """Assemble complete player profile by combining all data sources.

    Args:
        tag: Player tag
        raid_data: Capital raid weekend data
        war_data: Current war data
        mongo_data: MongoDB tracking statistics
        legends_data: Legend league statistics by season
        mongo: MongoDB client instance

    Returns:
        Complete player data dictionary with all enriched information
    """
    player_data = mongo_data or {}

    # Add legends data
    player_data["legends_by_season"] = legends_data.get(tag, {})
    player_data.pop("legends", None)

    # Add additional stats
    player_data["legend_eos_ranking"] = await get_legend_rankings_for_tag(tag, mongo=mongo)
    player_data["rankings"] = await get_current_rankings(tag, mongo=mongo)
    player_data["raid_data"] = raid_data
    player_data["war_data"] = war_data

    return player_data


def fetch_nested_key(data: dict, attr: str):
    """Extract nested value from dict using dot notation for player stats.

    Args:
        data: Dictionary to extract from
        attr: Dot-separated path (e.g., "gold.2024-01")

    Returns:
        Value at the path, or 0 if not found
    """
    keys = attr.split(".")
    for i, key in enumerate(keys):
        data = data.get(key, {}) if i < len(keys) - 1 else data.get(key, 0)
    return data


def calculate_capital_gold_donated(player_data: dict, season_raid_weeks: list) -> int:
    """Calculate total capital gold donated for a season.

    Args:
        player_data: Player stats document
        season_raid_weeks: List of raid week identifiers for the season

    Returns:
        Total capital gold donated
    """
    total = 0
    for week in season_raid_weeks:
        week_result = player_data.get('capital_gold', {}).get(week, {})
        total += sum(week_result.get('donate', []))
    return total


def calculate_capital_gold_raided(player_data: dict, season_raid_weeks: list) -> int:
    """Calculate total capital gold raided for a season.

    Args:
        player_data: Player stats document
        season_raid_weeks: List of raid week identifiers for the season

    Returns:
        Total capital gold raided
    """
    total = 0
    for week in season_raid_weeks:
        week_result = player_data.get('capital_gold', {}).get(week, {})
        total += sum(week_result.get('raid', []))
    return total


def _process_list_lookup(data: dict, key: str):
    """Process list lookup pattern like achievements[name=test].

    Args:
        data: Dictionary containing the list
        key: Key with list lookup pattern

    Returns:
        Matched item or None if not found
    """
    list_key, condition = key[:-1].split("[", 1)

    if "=" not in condition:
        return None

    cond_key, cond_value = condition.split("=", 1)

    if list_key not in data or not isinstance(data[list_key], list):
        return None

    for item in data[list_key]:
        if isinstance(item, dict) and item.get(cond_key) == cond_value:
            return item

    return None


def fetch_nested_attribute(data: dict, attr: str):
    """Fetch a nested attribute from a dictionary using dot notation.

    Supports:
    - Standard dictionary lookups (e.g., "name" -> data["name"])
    - Nested dictionary lookups (e.g., "league.name" -> data["league"]["name"])
    - List item lookups (e.g., "achievements[name=test].value" -> gets "value" from achievement where name="test")

    Args:
        data: The dictionary to fetch the attribute from
        attr: The attribute path in dot notation

    Returns:
        The fetched value or None if not found
    """
    # Handle special case for cumulative heroes
    if attr == "cumulative_heroes":
        return sum([h.get("level") for h in data.get("heroes", []) if h.get("village") == "home"])

    keys = attr.split(".")
    for i, key in enumerate(keys):
        # Handle list lookup pattern
        if "[" in key and "]" in key:
            data = _process_list_lookup(data, key)
            if data is None:
                return None
        else:
            # Standard dict navigation
            is_last_key = (i == len(keys) - 1)
            data = data.get(key) if is_last_key else data.get(key, {})

        if data is None:
            return None

    return data