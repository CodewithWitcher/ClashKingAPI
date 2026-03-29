"""War utilities for handling Clash of Clans war data.

Note: This module uses coc.py's _raw_data attribute, which despite the underscore
prefix is part of the library's documented public API for accessing underlying JSON data.
See: https://cocpy.readthedocs.io/
"""

import asyncio
import aiohttp
import coc
import sentry_sdk
from typing import List, TYPE_CHECKING
from collections import defaultdict
from fastapi import HTTPException

if TYPE_CHECKING:
    from routers.v2.war.models import PlayerWarhitsFilter

semaphore = asyncio.Semaphore(10)



def deconstruct_type(value):
    types = []
    if value & 1:
        types.append(1)
    if value & 2:
        types.append(2)
    if value & 4:
        types.append(4)
    return types


def _parse_townhall_filter(townhall_filter: str):
    """Parse and validate townhall filter string.

    Args:
        townhall_filter: Filter string like '13v14', 'all', 'equal', or '*v*'

    Returns:
        Tuple of (townhall_level, opponent_townhall_level)

    Raises:
        HTTPException: If filter is invalid
    """
    if townhall_filter == "all":
        townhall_filter = "*v*"
    elif townhall_filter == "equal":
        townhall_filter = "=v="

    if "v" not in townhall_filter:
        raise HTTPException(status_code=400, detail="Invalid townhall filter")

    townhall_level, opponent_townhall_level = townhall_filter.split("v")
    townhall_level = int(townhall_level.strip()) if townhall_level.isdigit() else townhall_level.strip()
    opponent_townhall_level = int(opponent_townhall_level.strip()) if opponent_townhall_level.isdigit() else opponent_townhall_level.strip()

    allowed = {"*", "="}
    invalid_tl = not (isinstance(townhall_level, int) or townhall_level in allowed)
    invalid_otl = not (isinstance(opponent_townhall_level, int) or opponent_townhall_level in allowed)

    if invalid_tl or invalid_otl:
        raise HTTPException(status_code=400, detail="Invalid townhall filter")

    return townhall_level, opponent_townhall_level


def _should_skip_attack(member, attack, townhall_level, opponent_townhall_level):
    """Check if attack should be skipped based on filter."""
    if townhall_level == "=" and opponent_townhall_level == "=":
        return member.town_hall != attack.defender.town_hall
    if isinstance(townhall_level, int) and townhall_level != member.town_hall:
        return True
    if isinstance(opponent_townhall_level, int) and opponent_townhall_level != attack.defender.town_hall:
        return True
    return False


def _update_attack_stats(spot, attack):
    """Update player stats with attack data."""
    spot["attacks"] += 1
    spot["destruction"] += attack.destruction
    spot["stars"] += attack.stars
    spot["fresh"] += 1 if attack.is_fresh_attack else 0
    spot["won"] += 1 if attack.war.status == "won" else 0
    spot["duration"] += attack.duration
    spot["order"] += attack.order
    spot["defensive_position"] += attack.defender.map_position
    spot["zero_stars"] += 1 if attack.stars == 0 else 0
    spot["one_stars"] += 1 if attack.stars == 1 else 0
    spot["two_stars"] += 1 if attack.stars == 2 else 0
    spot["three_stars"] += 1 if attack.stars == 3 else 0


def _initialize_player_stats(player_stats, member):
    """Initialize player stats if not already present."""
    if not player_stats[member.tag].get("name"):
        player_stats[member.tag]["name"] = member.name
        player_stats[member.tag]["tag"] = member.tag
        player_stats[member.tag]["townhall"] = member.town_hall

def _process_member_attacks(member, player_stats, townhall_level, opponent_townhall_level):
    """Process attacks for a member, keeping only the best attack per defender village."""
    best_per_defender: dict = {}
    for attack in member.attacks:
        if _should_skip_attack(member, attack, townhall_level, opponent_townhall_level):
            continue
        prev = best_per_defender.get(attack.defender.tag)
        if prev is None or attack.stars > prev.stars:
            best_per_defender[attack.defender.tag] = attack

    for attack in best_per_defender.values():
        spot = player_stats[attack.attacker.tag]["stats"]
        _update_attack_stats(spot, attack)

def _process_opponent_attacks_on_clan(war, player_stats):
    """Process opponent attacks to compute defensive stats for our clan members.

    Uses the best (most stars) attack per opponent per defender to avoid counting
    multiple cleanup attacks as separate defensive events.
    """
    clan_member_tags = {m.tag for m in war.clan.members}
    for opponent_member in war.opponent.members:
        best_per_defender: dict = {}
        for attack in opponent_member.attacks:
            if attack.defender.tag not in clan_member_tags:
                continue
            prev = best_per_defender.get(attack.defender.tag)
            if prev is None or attack.stars > prev.stars:
                best_per_defender[attack.defender.tag] = attack
        for attack in best_per_defender.values():
            defender_tag = attack.defender.tag
            player_stats[defender_tag]["defense"]["defenses"] += 1
            player_stats[defender_tag]["defense"]["stars_given"] += attack.stars


def _record_missed_attacks(member, player_stats, war):
    """Record missed attacks for a member."""
    for _ in range(war.attacks_per_member - len(member.attacks)):
        player_stats[member.tag]["missed"][f"{member.town_hall}"] += 1
        player_stats[member.tag]["missed"]["all"] += 1

def _calculate_averages(stats):
    """Calculate average statistics from totals."""
    attacks = stats["attacks"]
    if attacks:
        stats["avg_destruction"] = round(stats["destruction"] / attacks, 2)
        stats["avg_stars"] = round(stats["stars"] / attacks, 2)
        stats["avg_duration"] = round(stats["duration"] / attacks, 2)
        stats["avg_order"] = round(stats["order"] / attacks, 2)
        stats["avg_fresh"] = round(stats["fresh"] / attacks * 100, 2)
        stats["avg_won"] = round(stats["won"] / attacks * 100, 2)
        stats["avg_zero_stars"] = round(stats["zero_stars"] / attacks * 100, 2)
        stats["avg_one_stars"] = round(stats["one_stars"] / attacks * 100, 2)
        stats["avg_two_stars"] = round(stats["two_stars"] / attacks * 100, 2)
        stats["avg_three_stars"] = round(stats["three_stars"] / attacks * 100, 2)
        stats["avg_defender_position"] = round(stats["defensive_position"] / attacks, 2)
        del stats["defensive_position"]


def calculate_war_stats(
        wars: list[dict],
        clan_tags: set,
        townhall_filter: str
):
    """Calculate player war statistics with townhall filtering.

    Args:
        wars: List of war data dictionaries
        clan_tags: Set of clan tags to process
        townhall_filter: Filter string for townhall matching

    Returns:
        Dictionary with player statistics
    """
    townhall_level, opponent_townhall_level = _parse_townhall_filter(townhall_filter)
    player_stats = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    for war in wars:
        war = war.get("data")
        clan_tag = war.get("clan").get("tag")
        if clan_tag not in clan_tags:
            clan_tag = war.get("opponent").get("tag")
        war = coc.ClanWar(data=war, clan_tag=clan_tag, client=None)

        for member in war.clan.members:
            _initialize_player_stats(player_stats, member)
            _process_member_attacks(member, player_stats, townhall_level, opponent_townhall_level)
            _record_missed_attacks(member, player_stats, war)
        _process_opponent_attacks_on_clan(war, player_stats)

    for player, thvs in player_stats.items():
        for thv, stats in thvs.items():
            if isinstance(stats, (str, int)) or thv in ("missed", "defense"):
                continue
            _calculate_averages(stats)
        defense = thvs.get("defense")
        if defense:
            defenses = int(defense.get("defenses", 0))
            if defenses > 0:
                defense["avg_stars_given"] = round(defense["stars_given"] / defenses, 2)
            defense["defenses"] = defenses

    return {"items": list(player_stats.values())}


async def fetch_current_war_info(clan_tag, bypass=False):
    try:
        if clan_tag is None:
            sentry_sdk.capture_message("clan_tag is None in fetch_current_war_info", level="error")
            return None
        tag_encoded = clan_tag.replace("#", "%23")
        url = f"https://proxy.clashk.ing/v1/clans/{tag_encoded}/currentwar"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get("state") != "notInWar" and data.get("reason") != "accessDenied":
                        return {"state": "war", "currentWarInfo": data, "bypass": bypass}
                    elif data.get("state") == "notInWar":
                        return {"state": "notInWar"}
                elif res.status == 403:
                    return {"state": "accessDenied"}
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"function": "fetch_current_war_info", "clan_tag": clan_tag})

    return {"state": "notInWar"}


async def fetch_current_war_info_bypass(clan_tag, session):
    war = await fetch_current_war_info(clan_tag)
    if war and war.get("state") == "accessDenied":
        opponent_tag = await fetch_opponent_tag(clan_tag, session)
        if opponent_tag:
            return await fetch_current_war_info(opponent_tag, bypass=True)
    return war


async def fetch_league_info(clan_tag, session):
    try:
        if clan_tag is None:
            sentry_sdk.capture_message("clan_tag is None in fetch_league_info", level="error")
            return None
        tag_encoded = clan_tag.replace("#", "%23")
        url = f"https://proxy.clashk.ing/v1/clans/{tag_encoded}/currentwar/leaguegroup"
        async with session.get(url, timeout=15) as res:
            if res.status == 200:
                data = await res.json()
                if data.get("state") != "notInWar":
                    return data
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"function": "fetch_league_info", "clan_tag": clan_tag})
    return None


async def fetch_war_league_info(war_tag, session):
    if war_tag is None:
        sentry_sdk.capture_message("war_tag is None in fetch_war_league_info", level="error")
        return None
    war_tag_encoded = war_tag.replace('#', '%23')
    url = f"https://proxy.clashk.ing/v1/clanwarleagues/wars/{war_tag_encoded}"

    for _ in range(3):
        try:
            async with semaphore:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("state") != "notInWar":
                            data["war_tag"] = war_tag
                            return data
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError):
            await asyncio.sleep(5)
    return None


async def fetch_war_league_infos(war_tags, session):
    tasks = [
        fetch_war_league_info(tag, session)
        for tag in war_tags
        if tag != "#0"
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if r and not isinstance(r, Exception)]


async def fetch_opponent_tag(clan_tag, session):
    tag_clean = clan_tag.lstrip("#")
    url = f"https://proxy.clashk.ing/v1/war/{tag_clean}/basic"
    try:
        async with session.get(url) as res:
            if res.status == 200:
                data = await res.json()
                if "clans" in data and isinstance(data["clans"], list):
                    for tag in data["clans"]:
                        if tag != clan_tag:
                            return tag
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError):
        pass
    return None


def init_clan_summary_map(league_info):
    clan_summary_map = {}
    for clan in league_info.get("clans", []):
        tag = clan.get("tag")
        clan_summary_map[tag] = {
            "total_stars": 0,
            "attack_count": 0,
            "missed_attacks": 0,
            "missed_defenses": 0,
            "total_destruction": 0.0,
            "total_destruction_inflicted": 0.0,
            "wars_played": 0,
            "town_hall_levels": {},
            "own_th_level_list_attack": [],
            "opponent_th_level_list_attack": [],
            "own_th_level_list_defense": [],
            "attacker_th_level_list_defense": [],
            "members": defaultdict(lambda: {
                "name": None,
                "map_position": None,
                "avg_opponent_position": None,
                "avg_attack_order": None,
                "stars": 0,
                "3_stars": {},
                "2_stars": {},
                "1_star": {},
                "0_star": {},
                "stars_by_th": {},
                "defense_stars_by_th": {},
                "total_destruction": 0.0,
                "attack_count": 0,
                "missed_attacks": 0,
                "missed_defenses": 0,
                "defense_stars_taken": 0,
                "defense_3_stars": {},
                "defense_2_stars": {},
                "defense_1_star": {},
                "defense_0_star": {},
                "defense_total_destruction": 0.0,
                "defense_count": 0
            })
        }
    return clan_summary_map


def _initialize_member_stats_lists(stats):
    """Initialize stat tracking lists for a member if not present."""
    list_fields = [
        "own_th_level_list_attack", "opponent_th_level_list_attack",
        "own_th_level_list_defense", "attacker_th_level_list_defense"
    ]
    for field in list_fields:
        if field not in stats:
            stats[field] = []

    if "map_position_list" not in stats:
        stats["map_position_list"] = []
        stats["opponent_position_list"] = []
        stats["opponent_th_level_list"] = []
        stats["attack_order_list"] = []
        stats["attacker_position_list"] = []
        stats["defense_order_list"] = []
        stats["attacker_th_level_list"] = []

def _update_member_position_stats(stats, avg_pos_map, mtag):
    """Update member position statistics from position map."""
    if mtag not in avg_pos_map:
        return

    data = avg_pos_map[mtag]
    stats["map_position"] = data["map_position"]
    stats["avg_opponent_position"] = data["avg_opponent_position"]
    stats["avg_attack_order"] = data["avg_attack_order"]
    stats["avg_townhall_level"] = data["avg_townhall_level"]
    stats["avg_opponent_townhall_level"] = data["avg_opponent_townhall_level"]

    if data["map_position"] is not None:
        stats["map_position_list"].append(data["map_position"])
    if data["avg_opponent_position"] is not None:
        stats["opponent_position_list"].append(data["avg_opponent_position"])
    if data["avg_opponent_townhall_level"] is not None:
        stats["opponent_th_level_list"].append(data["avg_opponent_townhall_level"])
    if data["avg_attack_order"] is not None:
        stats["attack_order_list"].append(data["avg_attack_order"])
    if data["avg_attacker_position"] is not None:
        stats["attacker_position_list"].append(data["avg_attacker_position"])
    if data["avg_defense_order"] is not None:
        stats["defense_order_list"].append(data["avg_defense_order"])
    if data["avg_attacker_townhall_level"] is not None:
        stats["attacker_th_level_list"].append(data["avg_attacker_townhall_level"])

def _find_opponent_th_level(defender_tag, opponent_members):
    """Find townhall level of an opponent by tag."""
    for opp_member in opponent_members:
        if opp_member["tag"] == defender_tag:
            return opp_member.get("townhallLevel")
    return None

def _process_member_attack(member, stats, summary, war, side):
    """Process attack statistics for a member."""
    attacks = member.get("attacks")
    if not attacks:
        if war.get("state") == "warEnded":
            stats["missed_attacks"] += 1
            summary["missed_attacks"] += 1
        return

    attack = attacks[0] if isinstance(attacks, list) else attacks
    stars = attack["stars"]
    destruction = attack["destructionPercentage"]
    defender_tag = attack.get("defenderTag")
    own_th = member.get("townhallLevel")

    opponent_side = "opponent" if side == "clan" else "clan"
    opponent_members = war[opponent_side]["members"]
    defender_th = _find_opponent_th_level(defender_tag, opponent_members) if defender_tag else None

    if defender_th is not None:
        stats["stars_by_th"].setdefault(stars, {}).setdefault(defender_th, 0)
        stats["stars_by_th"][stars][defender_th] += 1
        stats["opponent_th_level_list_attack"].append(defender_th)
        stats["own_th_level_list_attack"].append(own_th)

    stats["stars"] += stars
    stats["total_destruction"] += destruction
    stats["attack_count"] += 1
    summary["total_destruction_inflicted"] += destruction
    summary["attack_count"] += 1

def _process_member_defense(member, stats, summary, war, side):
    """Process defense statistics for a member."""
    defense = member.get("bestOpponentAttack")
    if not defense:
        stats["missed_defenses"] += 1
        summary["missed_defenses"] += 1
        return

    stars = defense["stars"]
    attacker_tag = defense.get("attackerTag")
    defender_th = member.get("townhallLevel")

    opponent_side = "opponent" if side == "clan" else "clan"
    opponent_members = war[opponent_side]["members"]
    attacker_th = _find_opponent_th_level(attacker_tag, opponent_members) if attacker_tag else None

    if attacker_th is not None:
        stats["defense_stars_by_th"].setdefault(stars, {}).setdefault(attacker_th, 0)
        stats["defense_stars_by_th"][stars][attacker_th] += 1
        stats["attacker_th_level_list_defense"].append(attacker_th)
        stats["own_th_level_list_defense"].append(defender_th)

    stats["defense_stars_taken"] += stars
    stats["defense_total_destruction"] += defense["destructionPercentage"]
    stats["defense_count"] += 1
    summary["total_destruction"] += defense["destructionPercentage"]

def process_war_stats(war_league_infos, clan_summary_map):
    for war in war_league_infos:
        if war.get("state") not in ["inWar", "warEnded"]:
            continue

        for side in ["clan", "opponent"]:
            clan = war[side]
            tag = clan["tag"]
            if tag not in clan_summary_map:
                continue
            summary = clan_summary_map[tag]

            summary["total_stars"] += clan.get("stars", 0)
            summary["wars_played"] += 1

            avg_pos_map = compute_member_position_stats(war, side, "opponent" if side == "clan" else "clan")

            for member in clan.get("members", []):
                mtag = member.get("tag")
                stats = summary["members"][mtag]
                stats["name"] = member["name"]

                _initialize_member_stats_lists(stats)
                _update_member_position_stats(stats, avg_pos_map, mtag)
                _process_member_attack(member, stats, summary, war, side)
                _process_member_defense(member, stats, summary, war, side)


def compute_clan_ranking(clan_summary_map):
    clan_ranking = [
        {
            "tag": tag,
            "stars": summary["total_stars"],
            "destruction": summary["total_destruction_inflicted"]
        }
        for tag, summary in clan_summary_map.items()
    ]
    sorted_clans = sorted(clan_ranking, key=lambda x: (-x["stars"], -x["destruction"]))
    for idx, clan in enumerate(sorted_clans):
        clan["rank"] = idx + 1
    return sorted_clans


def _safe_average(values):
    """Calculate average of a list, returning None if empty."""
    return round(sum(values) / len(values), 1) if values else None

def _process_hit_stats(hit, tag_key, enemy_map, enemy_townhall_map, positions_list, th_levels_list, orders_list, stars_by_th):
    """Process statistics for an attack or defense hit."""
    target_tag = hit.get(tag_key)
    if target_tag in enemy_map:
        positions_list.append(enemy_map[target_tag])
    if target_tag in enemy_townhall_map:
        th_level = enemy_townhall_map[target_tag]
        th_levels_list.append(th_level)
        stars = hit.get("stars")
        if stars is not None:
            stars_by_th[stars][th_level] += 1
    if "order" in hit:
        orders_list.append(hit["order"])

def _process_attack_stats(attack, enemy_map, enemy_townhall_map, opponent_positions, opponent_th_levels, attack_orders, stars_by_th):
    """Process statistics for a single attack."""
    _process_hit_stats(attack, "defenderTag", enemy_map, enemy_townhall_map, opponent_positions, opponent_th_levels, attack_orders, stars_by_th)

def _process_defense_stats(defense, enemy_map, enemy_townhall_map, defense_positions, defense_orders, attacker_th_levels, defense_stars_by_th):
    """Process statistics for defense."""
    _process_hit_stats(defense, "attackerTag", enemy_map, enemy_townhall_map, defense_positions, attacker_th_levels, defense_orders, defense_stars_by_th)

def compute_member_position_stats(war, clan_key="clan", opponent_key="opponent"):
    enemy_map = {member["tag"]: member.get("mapPosition") for member in war[opponent_key]["members"]}
    enemy_townhall_map = {member["tag"]: member.get("townhallLevel") for member in war[opponent_key]["members"]}
    result = {}

    for member in war[clan_key]["members"]:
        tag = member["tag"]
        position = member.get("mapPosition")
        townhall = member.get("townhallLevel")
        attacks = member.get("attacks", [])
        defense = member.get("bestOpponentAttack")

        opponent_positions, opponent_th_levels, attack_orders = [], [], []
        defense_positions, defense_orders, attacker_th_levels = [], [], []
        stars_by_th = defaultdict(lambda: defaultdict(int))
        defense_stars_by_th = defaultdict(lambda: defaultdict(int))

        for attack in attacks:
            _process_attack_stats(attack, enemy_map, enemy_townhall_map, opponent_positions, opponent_th_levels, attack_orders, stars_by_th)

        if defense:
            _process_defense_stats(defense, enemy_map, enemy_townhall_map, defense_positions, defense_orders, attacker_th_levels, defense_stars_by_th)

        result[tag] = {
            "map_position": position,
            "avg_townhall_level": townhall,
            "avg_opponent_position": _safe_average(opponent_positions),
            "avg_opponent_townhall_level": _safe_average(opponent_th_levels),
            "avg_attack_order": _safe_average(attack_orders),
            "avg_attacker_position": _safe_average(defense_positions),
            "avg_defense_order": _safe_average(defense_orders),
            "avg_attacker_townhall_level": _safe_average(attacker_th_levels),
            "opponent_th_levels": opponent_th_levels,
            "attacker_th_levels": attacker_th_levels,
            "stars_by_th": dict(stars_by_th),
            "defense_stars_by_th": dict(defense_stars_by_th),
        }

    return result


def _count_th_matchups(own_th_list, opponent_th_list, comparator):
    """Count matchups based on townhall level comparison."""
    return sum(
        1 for own_th, enemy_th in zip(own_th_list, opponent_th_list)
        if comparator(enemy_th, own_th)
    )

def _build_member_enrichment(stats):
    """Build enrichment data for a member from their stats."""
    avg = lambda l: round(sum(l) / len(l), 1) if l else None

    return {
        "avgMapPosition": avg(stats.get("map_position_list", [])),
        "avgOpponentPosition": avg(stats.get("opponent_position_list", [])),
        "avgAttackOrder": avg(stats.get("attack_order_list", [])),
        "avgTownHallLevel": stats.get("avg_townhall_level"),
        "avgOpponentTownHallLevel": avg(stats.get("opponent_th_level_list", [])),
        "avgAttackerPosition": avg(stats.get("attacker_position_list", [])),
        "avgDefenseOrder": avg(stats.get("defense_order_list", [])),
        "avgAttackerTownHallLevel": avg(stats.get("attacker_th_level_list", [])),
        "attackLowerTHLevel": _count_th_matchups(
            stats.get("own_th_level_list_attack", []),
            stats.get("opponent_th_level_list_attack", []),
            lambda e, o: e < o
        ),
        "attackUpperTHLevel": _count_th_matchups(
            stats.get("own_th_level_list_attack", []),
            stats.get("opponent_th_level_list_attack", []),
            lambda e, o: e > o
        ),
        "defenseLowerTHLevel": _count_th_matchups(
            stats.get("own_th_level_list_defense", []),
            stats.get("attacker_th_level_list_defense", []),
            lambda e, o: e < o
        ),
        "defenseUpperTHLevel": _count_th_matchups(
            stats.get("own_th_level_list_defense", []),
            stats.get("attacker_th_level_list_defense", []),
            lambda e, o: e > o
        ),
        "attacks": {
            "stars": stats["stars"],
            "3_stars": dict(stats.get("stars_by_th", {}).get(3, {})),
            "2_stars": dict(stats.get("stars_by_th", {}).get(2, {})),
            "1_star": dict(stats.get("stars_by_th", {}).get(1, {})),
            "0_star": dict(stats.get("stars_by_th", {}).get(0, {})),
            "total_destruction": round(stats["total_destruction"], 2),
            "attack_count": stats["attack_count"],
            "missed_attacks": stats["missed_attacks"]
        },
        "defense": {
            "stars": stats["defense_stars_taken"],
            "3_stars": dict(stats.get("defense_stars_by_th", {}).get(3, {})),
            "2_stars": dict(stats.get("defense_stars_by_th", {}).get(2, {})),
            "1_star": dict(stats.get("defense_stars_by_th", {}).get(1, {})),
            "0_star": dict(stats.get("defense_stars_by_th", {}).get(0, {})),
            "total_destruction": round(stats["defense_total_destruction"], 2),
            "defense_count": stats["defense_count"],
            "missed_defenses": stats["missed_defenses"]
        }
    }

def _enrich_clan_summary(clan, summary, sorted_clans):
    """Enrich clan with summary statistics."""
    tag = clan.get("tag")
    clan["total_stars"] = summary["total_stars"]
    clan["total_destruction"] = round(summary["total_destruction"], 2)
    clan["total_destruction_inflicted"] = round(summary["total_destruction_inflicted"], 2)
    clan["wars_played"] = summary["wars_played"]
    clan["rank"] = next((r["rank"] for r in sorted_clans if r["tag"] == tag), None)
    clan["attack_count"] = summary["attack_count"]
    clan["missed_attacks"] = summary["missed_attacks"]

def _enrich_clan_members(clan, summary):
    """Enrich clan members with their statistics."""
    townhall_counts = defaultdict(int)
    for member in clan.get("members", []):
        mtag = member.get("tag")
        th_level = member.get("townHallLevel")
        if th_level:
            townhall_counts[th_level] += 1

        if mtag in summary["members"]:
            stats = summary["members"][mtag]
            member.update(_build_member_enrichment(stats))

    clan["town_hall_levels"] = dict(townhall_counts)

async def enrich_league_info(league_info, war_league_infos, session):
    clan_summary_map = init_clan_summary_map(league_info)
    process_war_stats(war_league_infos, clan_summary_map)
    sorted_clans = compute_clan_ranking(clan_summary_map)

    league_info["total_stars"] = sum(c["stars"] for c in sorted_clans)
    league_info["total_destruction"] = round(sum(c["destruction"] for c in sorted_clans), 2)

    for clan in league_info.get("clans", []):
        tag = clan.get("tag")
        if tag not in clan_summary_map:
            continue
        summary = clan_summary_map[tag]

        _enrich_clan_summary(clan, summary, sorted_clans)
        _enrich_clan_members(clan, summary)

    # Get clan with rank = 3 to get current league because they won't go up or down
    third_clan = next((clan for clan in league_info["clans"] if clan["rank"] == 3), None)
    if third_clan is None:
        sentry_sdk.capture_message("No clan found with rank 3 in league_info", level="warning")
        return league_info
    clan_tag = third_clan.get("tag", "").replace("#", "%23")
    url = f"https://proxy.clashk.ing/v1/clans/{clan_tag}"
    try:
        async with session.get(url) as res:
            if res.status == 200:
                data = await res.json()
                if "warLeague" in data:
                    league_info["war_league"] = data["warLeague"]["name"]
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError):
        pass

    return league_info


def _check_stars_filter(hit, warhit_filter):
    """Check if hit passes stars filtering."""
    if warhit_filter.min_stars is not None and hit["stars"] < warhit_filter.min_stars:
        return False
    if warhit_filter.max_stars is not None and hit["stars"] > warhit_filter.max_stars:
        return False
    if warhit_filter.stars is not None and hit["stars"] not in warhit_filter.stars:
        return False
    return True

def _check_destruction_filter(hit, warhit_filter):
    """Check if hit passes destruction filtering."""
    if warhit_filter.min_destruction is not None and hit["destructionPercentage"] < warhit_filter.min_destruction:
        return False
    if warhit_filter.max_destruction is not None and hit["destructionPercentage"] > warhit_filter.max_destruction:
        return False
    return True

def _check_th_filter(th_level, th_filter):
    """Check if townhall level passes filter (supports int or list)."""
    if th_filter is None:
        return True
    if isinstance(th_filter, list):
        return th_level in th_filter
    return th_level == th_filter

def _check_position_filter(position, min_pos, max_pos):
    """Check if position is within range."""
    if min_pos is not None and position < min_pos:
        return False
    if max_pos is not None and position > max_pos:
        return False
    return True

def _filter_hit(hit, is_attack, warhit_filter):
    """Filter a hit based on criteria."""
    th_key = "defender" if is_attack else "attacker"

    if not _check_stars_filter(hit, warhit_filter):
        return False
    if not _check_destruction_filter(hit, warhit_filter):
        return False

    enemy_th_level = hit[th_key].get("townhallLevel")
    if not _check_th_filter(enemy_th_level, warhit_filter.enemy_th):
        return False

    enemy_position = hit[th_key].get("mapPosition")
    if not _check_position_filter(enemy_position, warhit_filter.map_position_min, warhit_filter.map_position_max):
        return False

    own_th_level = hit["attacker"].get("townhallLevel")
    if not _check_th_filter(own_th_level, warhit_filter.own_th):
        return False

    return True

def _average_stat(key, lst):
    """Calculate average of a stat from list of hits."""
    return round(sum(hit[key] for hit in lst) / len(lst), 2) if lst else 0.0

def _count_stars(lst):
    """Count hits by number of stars."""
    star_count = defaultdict(int)
    for hit in lst:
        star_count[hit["stars"]] += 1
    return {str(k): star_count[k] for k in range(4)}

def _group_by_th_matchup(lst, is_attack=True):
    """Group hits by townhall matchup."""
    th2_key = "defender" if is_attack else "attacker"
    th1_key = "attacker" if is_attack else "defender"
    grouped = defaultdict(list)

    for hit in lst:
        attacker_th = hit[th1_key]["townhallLevel"]
        defender_th = hit[th2_key]["townhallLevel"]
        matchup = f"{attacker_th}vs{defender_th}"
        grouped[matchup].append(hit)

    result = {}
    for matchup, hits in grouped.items():
        result[matchup] = {
            "averageStars": _average_stat("stars", hits),
            "averageDestruction": _average_stat("destructionPercentage", hits),
            "count": len(hits),
            "starsCount": _count_stars(hits),
        }
    return result

def compute_warhit_stats(
        attacks: List[dict],
        defenses: List[dict],
        warhit_filter: "PlayerWarhitsFilter",
        missed_attacks: int = 0,
        missed_defenses: int = 0,
        num_wars: int = 0,
):
    filtered_attacks = [a for a in attacks if _filter_hit(a, True, warhit_filter)]
    filtered_defenses = [d for d in defenses if _filter_hit(d, False, warhit_filter)]

    return {
        "warsCounts": num_wars,
        "totalAttacks": len(filtered_attacks),
        "totalDefenses": len(filtered_defenses),
        "missedAttacks": missed_attacks,
        "missedDefenses": missed_defenses,
        "starsCount": _count_stars(filtered_attacks),
        "starsCountDef": _count_stars(filtered_defenses),
        "byEnemyTownhall": _group_by_th_matchup(filtered_attacks, is_attack=True),
        "byEnemyTownhallDef": _group_by_th_matchup(filtered_defenses, is_attack=False),
    }


def group_attacks_by_type(attacks, defenses, wars):
    grouped = {
        "all": {"attacks": [], "defenses": [], "missedAttacks": 0, "missedDefenses": 0, "warsCounts": 0},
        "random": {"attacks": [], "defenses": [], "missedAttacks": 0, "missedDefenses": 0, "warsCounts": 0},
        "cwl": {"attacks": [], "defenses": [], "missedAttacks": 0, "missedDefenses": 0, "warsCounts": 0},
        "friendly": {"attacks": [], "defenses": [], "missedAttacks": 0, "missedDefenses": 0, "warsCounts": 0},
    }

    for war in wars:
        war_type = war.get("war_data", {}).get("type", "all").lower()
        missed_attacks = war.get("missedAttacks", 0)
        missed_defenses = war.get("missedDefenses", 0)

        grouped["all"]["missedAttacks"] += missed_attacks
        grouped["all"]["missedDefenses"] += missed_defenses
        grouped["all"]["warsCounts"] += 1

        if war_type in grouped:
            grouped[war_type]["missedAttacks"] += missed_attacks
            grouped[war_type]["missedDefenses"] += missed_defenses
            grouped[war_type]["warsCounts"] += 1

    for atk in attacks:
        war_type = atk.get("war_type", "all").lower()
        grouped["all"]["attacks"].append(atk)
        if war_type in grouped:
            grouped[war_type]["attacks"].append(atk)

    for dfn in defenses:
        war_type = dfn.get("war_type", "all").lower()
        grouped["all"]["defenses"].append(dfn)
        if war_type in grouped:
            grouped[war_type]["defenses"].append(dfn)

    return grouped


def _check_attack_special_filters(atk, member, attack_filter):
    """Check special attack filters (same_th, fresh_only)."""
    if attack_filter.same_th and atk.defender.town_hall != member.town_hall:
        return False
    if attack_filter.fresh_only and not atk.is_fresh_attack:
        return False
    return True

def _check_stars_range(stars, min_stars, max_stars, specific_stars):
    """Check if stars value passes filter criteria."""
    if min_stars and stars < min_stars:
        return False
    if max_stars and stars > max_stars:
        return False
    if specific_stars is not None and stars not in specific_stars:
        return False
    return True

def _check_destruction_range(destruction, min_destruction, max_destruction):
    """Check if destruction value passes filter criteria."""
    if min_destruction and destruction < min_destruction:
        return False
    if max_destruction and destruction > max_destruction:
        return False
    return True

def _check_common_filters(enemy_th, member_th, stars, destruction, enemy_position, hit_filter):
    """Check common filters for both attacks and defenses."""
    if not _check_th_filter(enemy_th, hit_filter.enemy_th):
        return False
    if not _check_th_filter(member_th, hit_filter.own_th):
        return False
    if not _check_stars_range(stars, hit_filter.min_stars, hit_filter.max_stars, hit_filter.stars):
        return False
    if not _check_destruction_range(destruction, hit_filter.min_destruction, hit_filter.max_destruction):
        return False
    if not _check_position_filter(enemy_position, hit_filter.map_position_min, hit_filter.map_position_max):
        return False
    return True

def attack_passes_filters(atk, member, attack_filter):
    if not attack_filter:
        return True

    if not _check_attack_special_filters(atk, member, attack_filter):
        return False
    return _check_common_filters(
        atk.defender.town_hall, member.town_hall,
        atk.stars, atk.destruction, atk.defender.map_position, attack_filter
    )


def _check_defense_special_filters(dfn, member, defense_filter):
    """Check special defense filters (same_th, fresh_only)."""
    if defense_filter.same_th and dfn.defender.town_hall != member.town_hall:
        return False
    if defense_filter.fresh_only and not dfn.is_fresh_attack:
        return False
    return True

def defense_passes_filters(dfn, member, defense_filter):
    if not defense_filter:
        return True
    if not dfn.attacker:
        return False

    if not _check_defense_special_filters(dfn, member, defense_filter):
        return False
    return _check_common_filters(
        dfn.attacker.town_hall, member.town_hall,
        dfn.stars, dfn.destruction, dfn.attacker.map_position, defense_filter
    )

def _should_skip_war_by_type(war, hits_filter):
    """Check if war should be skipped based on type filter."""
    if not hits_filter or hits_filter.type == "all":
        return False
    if isinstance(hits_filter.type, list):
        return war.type.lower() not in [t.lower() for t in hits_filter.type]
    return war.type.lower() != hits_filter.type.lower()

def _should_skip_war_by_season(war, hits_filter):
    """Check if war should be skipped based on season filter."""
    if not hits_filter or not hits_filter.season:
        return False
    try:
        year = int(hits_filter.season[:4])
        month = int(hits_filter.season[-2:])
        season_start = coc.utils.get_season_start(month=month - 1, year=year)
        season_end = coc.utils.get_season_end(month=month - 1, year=year)

        if not war.preparation_start_time or not hasattr(war.preparation_start_time, 'time'):
            return True

        war_start_timestamp = war.preparation_start_time.time.timestamp()
        return war_start_timestamp < season_start.timestamp() or war_start_timestamp >= season_end.timestamp()
    except (ValueError, AttributeError):
        return False

def _get_raw_data(obj):
    """Safely access the raw data from a coc.py object.

    Note: _raw_data is part of coc.py's documented API for accessing JSON data.
    """
    return getattr(obj, '_raw_data', {}).copy()

def _prepare_war_data(war):
    """Prepare war data by removing unnecessary fields."""
    war_data = _get_raw_data(war)
    for field in ["status_code", "_response_retry", "timestamp"]:
        war_data.pop(field, None)
    war_data["type"] = war.type
    war_data["clan"].pop("members", None)
    war_data["opponent"].pop("members", None)
    return war_data

def _prepare_member_data(member):
    """Prepare member data by removing attack/defense details."""
    member_raw_data = _get_raw_data(member)
    member_raw_data.pop("attacks", None)
    member_raw_data.pop("bestOpponentAttack", None)
    member_raw_data["attacks"] = []
    member_raw_data["defenses"] = []
    return member_raw_data

def _create_attack_data(atk, member, war):
    """Create attack data dictionary from attack object."""
    atk_data = _get_raw_data(atk)
    defender_data = _get_raw_data(atk.defender)
    defender_data.pop("attacks", None)
    defender_data.pop("bestOpponentAttack", None)
    atk_data["defender"] = defender_data
    atk_data["attacker"] = {
        "tag": member.tag,
        "townhallLevel": member.town_hall,
        "name": member.name,
        "mapPosition": member.map_position
    }
    atk_data["attack_order"] = atk.order
    atk_data["fresh"] = atk.is_fresh_attack
    atk_data["war_type"] = war.type.lower()
    return atk_data

def _create_defense_data(dfn, member, war):
    """Create defense data dictionary from defense object."""
    def_data = _get_raw_data(dfn)
    def_data["attack_order"] = dfn.order
    def_data["fresh"] = dfn.is_fresh_attack

    if dfn.attacker:
        attacker_data = _get_raw_data(dfn.attacker)
        attacker_data.pop("attacks", None)
        attacker_data.pop("bestOpponentAttack", None)
        def_data["attacker"] = attacker_data

    def_data["defender"] = {
        "tag": member.tag,
        "townhallLevel": member.town_hall,
        "name": member.name,
        "mapPosition": member.map_position,
    }
    def_data["war_type"] = war.type.lower()
    return def_data

def _process_member_in_war(member, war, war_id, war_data, players_data, all_wars_dict, tags_to_include, hits_filter):
    """Process a single member's data in a war."""
    tag = member.tag
    if tags_to_include and tag not in tags_to_include:
        return

    player_data = players_data[tag]
    player_data["townhall"] = max(player_data["townhall"] or 0, member.town_hall)
    player_data["missedAttacks"] += war.attacks_per_member - len(member.attacks)
    player_data["missedDefenses"] += 1 if not member.best_opponent_attack else 0
    player_data["warsCount"] += 1

    member_raw_data = _prepare_member_data(member)
    war_info = {"war_data": war_data, "member_data": member_raw_data}

    for atk in member.attacks:
        if not attack_passes_filters(atk, member, hits_filter):
            continue
        atk_data = _create_attack_data(atk, member, war)
        player_data["attacks"].append(atk_data)
        member_raw_data["attacks"].append(atk_data)

    for dfn in member.defenses:
        if not defense_passes_filters(dfn, member, hits_filter):
            continue
        def_data = _create_defense_data(dfn, member, war)
        player_data["defenses"].append(def_data)
        member_raw_data["defenses"].append(def_data)

    member_raw_data["missedAttacks"] = war.attacks_per_member - len(member.attacks)
    member_raw_data["missedDefenses"] = 1 if not member.best_opponent_attack else 0

    if war_id not in all_wars_dict:
        all_wars_dict[war_id] = {"war_data": war_data, "members": []}

    all_wars_dict[war_id]["members"].append(member_raw_data)
    war_info["missedAttacks"] = war.attacks_per_member - len(member.attacks)
    war_info["missedDefenses"] = 1 if not member.best_opponent_attack else 0
    player_data["wars"].append(war_info)

def _set_war_type_on_hits(hits, war_type):
    """Set war type on a list of hits (attacks or defenses)."""
    for hit in hits:
        hit["war_type"] = war_type

def _assign_war_types_to_hits(data):
    """Assign war types to all attacks and defenses."""
    for war_info in data["wars"]:
        war_type = war_info["war_data"].get("type", "all").lower()
        _set_war_type_on_hits(war_info["member_data"].get("attacks", []), war_type)
        _set_war_type_on_hits(war_info["member_data"].get("defenses", []), war_type)

def _compute_stats_by_war_type(data, hits_filter):
    """Compute statistics grouped by war type."""
    grouped = group_attacks_by_type(data["attacks"], data["defenses"], data["wars"])
    stats = {}
    for war_type, d in grouped.items():
        stats[war_type] = compute_warhit_stats(
            attacks=d["attacks"],
            defenses=d["defenses"],
            warhit_filter=hits_filter,
            missed_attacks=d["missedAttacks"],
            missed_defenses=d["missedDefenses"],
            num_wars=d["warsCounts"],
        )
    return stats

def _get_player_name(data):
    """Extract player name from data."""
    if data["attacks"]:
        return data["attacks"][0]["attacker"]["name"]
    if data["defenses"]:
        return data["defenses"][0]["defender"]["name"]
    return None

def _build_player_results(players_data, hits_filter):
    """Build final results from collected player data."""
    results = []
    for tag, data in players_data.items():
        _assign_war_types_to_hits(data)
        stats = _compute_stats_by_war_type(data, hits_filter)

        results.append({
            "name": _get_player_name(data),
            "tag": tag,
            "townhallLevel": data["townhall"],
            "stats": stats,
            "timeRange": {
                "start": hits_filter.timestamp_start,
                "end": hits_filter.timestamp_end,
            },
            "warType": hits_filter.type,
        })
    return results

def _process_war_sides(war, war_id, war_data, clan_tags, players_data, all_wars_dict, tags_to_include, hits_filter):
    """Process both sides of a war."""
    for side in [war.clan, war.opponent]:
        if clan_tags and side.tag not in clan_tags:
            continue
        for member in side.members:
            _process_member_in_war(member, war, war_id, war_data, players_data, all_wars_dict, tags_to_include, hits_filter)

def _attach_wars_to_player_results(results, players_data):
    """Attach individual wars to each player's results."""
    for tag in players_data:
        player_data = players_data[tag]
        wars_per_player = [
            {
                "war_data": war_info["war_data"],
                "members": [war_info["member_data"]]
            }
            for war_info in player_data["wars"]
        ]
        for item in results:
            if item["tag"] == tag:
                item["wars"] = wars_per_player
                break

def collect_player_hits_from_wars(wars_docs, tags_to_include=None, clan_tags=None, hits_filter=None, client=None):
    """Collect player hits from wars with filtering and aggregation.

    Args:
        wars_docs: War documents from database
        tags_to_include: Optional set of player tags to include
        clan_tags: Optional set of clan tags to filter by
        hits_filter: Optional filter for attacks/defenses
        client: coc.py client instance

    Returns:
        Dictionary with player statistics and war data
    """
    players_data = defaultdict(lambda: {
        "attacks": [],
        "defenses": [],
        "townhall": None,
        "missedAttacks": 0,
        "missedDefenses": 0,
        "warsCount": 0,
        "wars": []
    })

    seen_wars = set()
    all_wars_dict = {}

    for war_doc in wars_docs:
        war_raw = war_doc["data"]
        try:
            war = coc.ClanWar(data=war_raw, client=client)
        except (ValueError, KeyError, TypeError):
            continue

        war_id = "-".join(sorted([war.clan_tag, war.opponent.tag])) + f"-{int(war.preparation_start_time.time.timestamp())}"
        if war_id in seen_wars:
            continue
        seen_wars.add(war_id)

        if _should_skip_war_by_type(war, hits_filter):
            continue
        if _should_skip_war_by_season(war, hits_filter):
            continue

        war_data = _prepare_war_data(war)
        _process_war_sides(war, war_id, war_data, clan_tags, players_data, all_wars_dict, tags_to_include, hits_filter)

    results = _build_player_results(players_data, hits_filter)

    if clan_tags:
        return {
            "items": results,
            "wars": list(all_wars_dict.values())
        }

    _attach_wars_to_player_results(results, players_data)
    return {"items": results}
