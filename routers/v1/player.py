import aiohttp
import coc
import pendulum as pend
import re
import copy
import linkd

from collections import defaultdict
from fastapi import HTTPException, Query, APIRouter
from fastapi_cache.decorator import cache
from typing import List, Annotated
from utils.utils import fix_tag, gen_legend_date, gen_games_season
from utils.database import MongoClient


router = APIRouter(tags=["Player Endpoints"])

# MongoDB aggregation pipeline constants
MATCH_STAGE = "$match"
PROJECT_STAGE = "$project"
LIMIT_STAGE = "$limit"
PREPARATION_START_TIME_FIELD = "data.preparationStartTime"


def get_raw_data(obj):
    """
    Safely access _raw_data attribute from coc.py objects.
    Note: This is intentional access to a protected member, as coc.py library
    exposes this attribute for accessing underlying API data.
    """
    return obj._raw_data  # noqa: SLF001


def generate_war_unique_id(war: coc.ClanWar) -> str:
    """Generate a unique identifier for a war based on clan tags and preparation start time."""
    return "-".join(sorted([war.clan_tag, war.opponent.tag])) + f"-{int(war.preparation_start_time.time.timestamp())}"


def clean_member_raw_data(member_data: dict) -> dict:
    """Clean member raw data by removing unnecessary fields."""
    member_data.pop("attacks", None)
    member_data.pop("bestOpponentAttack", None)
    return member_data


async def fetch_player_clan_tag(player_tag: str) -> str | None:
    """Fetch the current clan tag for a player. Returns None if player is not in a clan or request fails."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://proxy.clashk.ing/v1/players/{player_tag.replace('#', '%23')}") as response:
            if response.status == 200:
                player_json = await response.json()
                return player_json.get("clan", {}).get("tag")
    return None


async def fetch_raid_data(player_tag: str, player_clan_tag: str) -> dict:
    """Fetch raid data for a player."""
    if not player_clan_tag:
        return {}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://proxy.clashk.ing/v1/clans/{player_clan_tag.replace('#', '%23')}/capitalraidseasons?limit=1") as response:
            if response.status == 200:
                data = await response.json()
                if data.get("items"):
                    raid_weekend_entry = coc.RaidLogEntry(data=data.get("items")[0], client=None, clan_tag=player_clan_tag)
                    if raid_weekend_entry.end_time.seconds_until >= 0:
                        raid_member = raid_weekend_entry.get_member(tag=player_tag)
                        if raid_member:
                            return {
                                "attacks_done": raid_member.attack_count,
                                "attack_limit": raid_member.attack_limit + raid_member.bonus_attack_limit,
                            }
    return {}


async def fetch_cwl_war(player_clan_tag: str, war_tag: str) -> coc.ClanWar | None:
    """Fetch a CWL war by war tag. Returns None if war is not found or doesn't involve the player's clan."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://proxy.clashk.ing/v1/clanwarleagues/wars/{war_tag.replace('#', '%23')}") as response:
            if response.status == 200:
                war_json = await response.json()
                war = coc.ClanWar(data=war_json, client=None)
                if player_clan_tag in [war.clan.tag, war.opponent.tag]:
                    return war
    return None


async def fetch_cwl_data(player_tag: str, player_clan_tag: str) -> dict:
    """Fetch CWL data for a player."""
    if not player_clan_tag:
        return {}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://proxy.clashk.ing/v1/clans/{player_clan_tag.replace('#', '%23')}/currentwar/leaguegroup") as response:
            if response.status != 200:
                return {}
            group_data = await response.json()

    if not group_data or group_data.get("season") != gen_games_season():
        return {}

    cwl_group = coc.ClanWarLeagueGroup(data=group_data, client=None)
    last_round = cwl_group.rounds[-1] if len(cwl_group.rounds) == 1 or len(cwl_group.rounds) == cwl_group.number_of_rounds else cwl_group.rounds[-2]

    for war_tag in last_round:
        our_war = await fetch_cwl_war(player_clan_tag, war_tag)
        if our_war:
            war_member = our_war.get_member(tag=player_tag)
            if war_member:
                return {
                    "attack_limit": our_war.attacks_per_member,
                    "attacks_done": len(war_member.attacks)
                }

    return {}


def _correct_event_sequence(events_copy: list) -> list:
    """Correct the event sequence to ensure 'leave' events precede 'join' events for the same clan."""
    corrected_events = []

    while events_copy:
        event = events_copy.pop(0)

        if event.get("type") == "leave":
            corrected_events.append(event)
            continue

        if event.get("type") == "join":
            corrected_events.append(event)
            clan_tag = event.get("tag")
            clan_id = event.get("clan")

            # Find the corresponding 'leave' event
            leave_index = next(
                (i for i, e in enumerate(events_copy)
                 if e.get("type") == "leave" and e.get("tag") == clan_tag and e.get("clan") == clan_id),
                None
            )

            if leave_index is not None:
                leave_event = events_copy.pop(leave_index)

                # Find the time of the next 'join' event
                next_join = next(
                    (e for e in events_copy if e.get("type") == "join"),
                    None
                )
                next_join_time = next_join["time"] if next_join else leave_event["time"]

                # Adjust the 'leave' event's time to match the next 'join' event's time
                leave_event["time"] = next_join_time
                corrected_events.append(leave_event)

    return corrected_events


def _remove_redundant_leave_events(corrected_events_sorted: list) -> list:
    """Remove redundant 'leave' events that do not have a preceding 'join' event."""
    cleaned_events = []
    active_clans = set()

    for event in corrected_events_sorted:
        clan_id = event.get("clan")

        if event.get("type") == "join":
            active_clans.add(clan_id)
            cleaned_events.append(event)
        elif event.get("type") == "leave":
            if clan_id in active_clans:
                active_clans.remove(clan_id)
                cleaned_events.append(event)
            else:
                # Redundant leave; optionally log or handle as needed
                cleaned_events.append(event)

    return cleaned_events


def _process_clan_events(events: list) -> list:
    """
    Processes and cleans a list of clan events by:
    1. Correcting the event sequence to ensure 'leave' events precede 'join' events for the same clan.
    2. Sorting the events chronologically, prioritizing 'leave' events when times are equal.
    3. Removing redundant 'leave' events that do not have a preceding 'join' event.

    Args:
        events (list): A list of event dictionaries. Each event should have at least the following keys:
                       - 'type': 'join' or 'leave'
                       - 'clan': Clan identifier
                       - 'time': ISO 8601 timestamp string
                       - 'tag': Player's tag
                       - 'clan_name': Name of the clan

    Returns:
        list: A cleaned and sorted list of event dictionaries.
    """
    # Make a deep copy to avoid mutating the original list
    events_copy = copy.deepcopy(events)

    # Step 1: Correct the event sequence
    corrected_events = _correct_event_sequence(events_copy)

    # Step 2: Sort the corrected events
    corrected_events_sorted = sorted(
        corrected_events,
        key=lambda e: (
            e["time"],
            0 if e["type"] == "leave" else 1  # Prioritize 'leave' over 'join' if times are equal
        )
    )

    # Step 3: Remove redundant 'leave' events
    return _remove_redundant_leave_events(corrected_events_sorted)


@router.get("/player/{player_tag}/stats",
         name="All collected Stats for a player (clan games, looted, activity, etc)")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_stat(player_tag: str, *, mongo: MongoClient):
    player_tag = player_tag and "#" + re.sub(r"[^A-Z0-9]+", "", player_tag.upper()).replace("O", "0")
    result = await mongo.player_stats.find_one({"tag": player_tag})
    lb_spot = await mongo.player_leaderboard.find_one({"tag": player_tag})

    if result is None:
        raise HTTPException(status_code=404, detail="No player found")
    try:
        del result["legends"]["streak"]
    except (KeyError, TypeError):
        pass
    result = {
        "name" : result.get("name"),
        "tag" : result.get("tag"),
        "townhall" : result.get("townhall"),
        "legends" : result.get("legends", {}),
        "last_online" : result.get("last_online"),
        "looted" : {"gold": result.get("gold", {}), "elixir": result.get("elixir", {}), "dark_elixir": result.get("dark_elixir", {})},
        "trophies" : result.get("trophies", 0),
        "warStars" : result.get("warStars"),
        "clanCapitalContributions" : result.get("aggressive_capitalism"),
        "donations": result.get("donations", {}),
        "capital" : result.get("capital_gold", {}),
        "clan_games" : result.get("clan_games", {}),
        "season_pass" : result.get("season_pass", {}),
        "attack_wins" : result.get("attack_wins", {}),
        "activity" : result.get("activity", {}),
        "clan_tag" : result.get("clan_tag"),
        "league" : result.get("league")
    }

    if lb_spot is not None:
        try:
            result["legends"]["global_rank"] = lb_spot["global_rank"]
            result["legends"]["local_rank"] = lb_spot["local_rank"]
        except (KeyError, TypeError):
            pass
        try:
            result["location"] = lb_spot["country_name"]
        except (KeyError, TypeError):
            pass

    return result


@router.get("/player/{player_tag}/legends",
         name="Legend stats for a player")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_legend(player_tag: str, season: str = None, *, mongo: MongoClient):
    player_tag = fix_tag(player_tag)
    result = await mongo.player_stats.find_one({"tag": player_tag}, projection={"name" : 1, "townhall" : 1, "legends" : 1, "tag" : 1})
    if result is None:
        raise HTTPException(status_code=404, detail="No player found")
    ranking_data = await mongo.player_leaderboard.find_one({"tag": player_tag}, projection={"_id" : 0})

    default = {"country_code": None,
               "country_name": None,
               "local_rank": None,
               "global_rank": None}
    if ranking_data is None:
        ranking_data = default
    if ranking_data.get("global_rank") is None:
        self_global_ranking = await mongo.legend_rankings.find_one({"tag": player_tag})
        if self_global_ranking:
            ranking_data["global_rank"] = self_global_ranking.get("rank")

    legend_data = result.get('legends', {})
    if season and legend_data != {}:
        year, month = map(int, season.split("-"))
        previous_month = pend.date(year, month, 1).subtract(months=1)
        prev_year, prev_month = previous_month.year, previous_month.month

        season_start = pend.instance(coc.utils.get_season_start(month=prev_month, year=prev_year))
        season_end = pend.instance(coc.utils.get_season_end(month=prev_month, year=prev_year))

        days = [season_start.add(days=i).to_date_string() for i in range((season_end - season_start).days)]

        _holder = {}
        for day in days:
            _holder[day] = legend_data.get(day, {})
        legend_data = _holder

    # Clean up legend_data before returning
    legend_data.pop("global_rank", None)
    legend_data.pop("local_rank", None)
    streak = legend_data.pop("streak", 0)

    result = {
        "name" : result.get("name"),
        "tag" : result.get("tag"),
        "townhall" : result.get("townhall"),
        "legends" : legend_data,
        "rankings" : ranking_data,
        "streak": streak
    }

    return result


@router.get("/player/{player_tag}/historical/{season}",
         name="Historical data for player events")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_historical(player_tag: str, season: str, *, mongo: MongoClient):
    player_tag = player_tag and "#" + re.sub(r"[^A-Z0-9]+", "", player_tag.upper()).replace("O", "0")
    year = season[:4]
    month = season[-2:]
    season_start = coc.utils.get_season_start(month=int(month) - 1, year=int(year))
    season_end = coc.utils.get_season_end(month=int(month) - 1, year=int(year))
    historical_data = await mongo.player_history.find({"$and" : [{"tag": player_tag}, {"time" : {"$gte" : season_start.timestamp()}}, {"time" : {"$lte" : season_end.timestamp()}}]}).sort("time", 1).to_list(length=25000)
    breakdown = defaultdict(list)
    for data in historical_data:
        del data["_id"]
        breakdown[data["type"]].append(data)

    result = {}
    for key, item in breakdown.items():
        result[key] = item

    return dict(result)


@router.get("/player/{player_tag}/warhits",
         name="War attacks done/defended by a player")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_warhits(player_tag: str, timestamp_start: int = 0, timestamp_end: int = 2527625513, limit: int = 50, *, mongo: MongoClient):
    client = coc.Client(raw_attribute=True)
    player_tag = fix_tag(player_tag)
    start = pend.from_timestamp(timestamp_start, tz=pend.UTC).strftime('%Y%m%dT%H%M%S.000Z')
    end = pend.from_timestamp(timestamp_end, tz=pend.UTC).strftime('%Y%m%dT%H%M%S.000Z')
    pipeline = [
        {MATCH_STAGE: {"$or": [{"data.clan.members.tag": player_tag}, {"data.opponent.members.tag": player_tag}]}},
        {MATCH_STAGE: {"$and": [{PREPARATION_START_TIME_FIELD: {"$gte": start}}, {PREPARATION_START_TIME_FIELD: {"$lte": end}}]}},
        {"$unset": ["_id"]},
        {PROJECT_STAGE: {"data": "$data"}},
        {"$sort": {PREPARATION_START_TIME_FIELD: -1}}
    ]
    wars = await mongo.clan_wars.aggregate(pipeline, allowDiskUse=True).to_list(length=None)
    found_wars = set()
    stats = {"items" : []}
    local_limit = 0
    for war in wars:
        war = war.get("data")
        war = coc.ClanWar(data=war, client=client)
        war_unique_id = generate_war_unique_id(war)
        if war_unique_id in found_wars:
            continue
        found_wars.add(war_unique_id)
        if limit == local_limit:
            break
        local_limit += 1

        war_member = war.get_member(player_tag)

        war_data: dict = get_raw_data(war)
        war_data.pop("status_code", None)
        war_data.pop("_response_retry", None)
        war_data.pop("timestamp", None)
        del war_data["clan"]["members"]
        del war_data["opponent"]["members"]
        war_data["type"] = war.type

        member_raw_data = clean_member_raw_data(get_raw_data(war_member))

        done_holder = {
            "war_data": war_data,
            "member_data" : member_raw_data,
            "attacks": [],
            "defenses" : []
        }
        for attack in war_member.attacks:
            raw_attack: dict = get_raw_data(attack)
            raw_attack["fresh"] = attack.is_fresh_attack
            raw_attack["defender"] = clean_member_raw_data(get_raw_data(attack.defender))
            raw_attack["attack_order"] = attack.order
            done_holder["attacks"].append(raw_attack)

        for defense in war_member.defenses:
            raw_defense: dict = get_raw_data(defense)
            raw_defense["fresh"] = defense.is_fresh_attack
            raw_defense["attacker"] = clean_member_raw_data(get_raw_data(defense.attacker))
            raw_defense["attack_order"] = defense.order
            done_holder["defenses"].append(raw_defense)

        stats["items"].append(done_holder)
    return stats


@router.get(
    path="/player/{player_tag}/raids",
    name="Raids participated in by a player"
)
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_raids(player_tag: str, limit: int = 1, *, mongo: MongoClient):
    results = await mongo.capital.find({"data.members.tag" : player_tag}).sort({"data.endTime" : -1}).limit(limit=limit).to_list(length=None)
    results = [r.get("data") for r in results]
    return {"items" : results}


@router.get("/player/to-do",
         name="List of in-game items to complete (legends, war, raids, etc)")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_to_do(player_tags: Annotated[List[str], Query(min_length=1, max_length=50)], *, mongo: MongoClient):
    return_data = {"items" : []}
    for player_tag in player_tags:
        player_tag = fix_tag(player_tag)

        player_data = await mongo.player_stats.find_one({"tag" : player_tag},
                                                               {"legends" : 1, "clan_games" : 1, "season_pass" : 1, "last_online" : 1})
        player_data = player_data or {}

        legends_data = player_data.get("legends", {}).get(gen_legend_date(), {})
        games_data = player_data.get("clan_games", {}).get(gen_games_season(), {})
        pass_data = player_data.get("season_pass", {}).get(gen_games_season(), {})
        last_active_data = player_data.get("last_online")

        player_clan_tag = await fetch_player_clan_tag(player_tag)
        raid_data = await fetch_raid_data(player_tag, player_clan_tag)
        war_data = await mongo.war_timer.find_one({"_id" : player_tag}, {"_id" : 0}) or {}
        cwl_data = await fetch_cwl_data(player_tag, player_clan_tag)

        return_data["items"].append({
            "player_tag" : player_tag,
            "current_clan" : player_clan_tag,
            "legends" : legends_data,
            "clan_games" : games_data,
            "season_pass" : pass_data,
            "last_active" : last_active_data,
            "raids" : raid_data,
            "war" : war_data,
            "cwl" : cwl_data
        })

    return return_data



@router.get("/player/{player_tag}/legend_rankings",
         name="Previous player legend rankings")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_legend_rankings(player_tag: str, limit:int = 10, *, mongo: MongoClient):

    player_tag = fix_tag(player_tag)
    results = await mongo.legend_history.find({"tag": player_tag}).sort("season", -1).limit(limit).to_list(length=None)
    for result in results:
        del result["_id"]

    return results


@router.get("/player/{player_tag}/wartimer",
         name="Get the war timer for a player")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_wartimer(player_tag: str, *, mongo: MongoClient):
    player_tag = fix_tag(player_tag)
    result = await mongo.war_timer.find_one({"_id" : player_tag})
    if result is None:
        return result
    result["tag"] = result.pop("_id")
    time = result["time"]
    time = time.replace(tzinfo=pend.UTC)
    result["unix_time"] = time.timestamp()
    result["time"] = time.isoformat()
    return result


@router.get("/player/search/{name}",
         name="Search for players by name")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def search_players(name: str, *, mongo: MongoClient):
    pipeline = [
        {
            "$search": {
                "index": "player_search",
                "autocomplete": {
                    "query": name,
                    "path": "name",
                },
            }
        },
        {LIMIT_STAGE: 25}
    ]
    results = await mongo.player_search.aggregate(pipeline=pipeline).to_list(length=None)
    for result in results:
        del result["_id"]
    return {"items" : results}


@router.get("/player/full-search/{name}",
         name="Search for players by name")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def full_search_players(name: str,
                        role:str =Query(default=None, description='An in-game player role, uses API values like admin however'),
                        league:str =Query(default=None, description='An in-game player league'),
                        townhall: str = Query(default=None, description='A comma seperated value of low, high values like: 1,16'),
                        exp:str =Query(default=None, description='A comma seperated value of low, high values like: 0,500'),
                        trophies:str =Query(default=None, description='A comma seperated value of low, high values like: 0,6000'),
                        donations:str =Query(default=None, description='A comma seperated value of low, high values like: 0,90000'),
                        limit: int = 25,
                        *,
                        mongo: MongoClient):
    conditions = [
        {"$regexMatch": {"input": "$$member.name", "regex": name, "options": "i"}},
    ]

    if role is not None:
        conditions.append({"$eq": ["$$member.role", role]})

    if exp is not None:
        exp = exp.split(',')
        conditions.extend([
            {"$gte": ["$$member.expLevel", int(exp[0])]},
            {"$lte": ["$$member.expLevel", int(exp[1])]}
        ])
    if townhall is not None:
        townhall = townhall.split(',')
        conditions.extend([
            {"$gte": ["$$member.townhall", int(townhall[0])]},
            {"$lte": ["$$member.townhall", int(townhall[1])]}
        ])
    if trophies is not None:
        trophies = trophies.split(',')
        conditions.extend([
            {"$gte": ["$$member.trophies", int(trophies[0])]},
            {"$lte": ["$$member.trophies", int(trophies[1])]}
        ])
    if league is not None:
        conditions.append({"$eq": ["$$member.league", league]})
    if donations is not None:
        donations = donations.split(',')
        conditions.extend([
            {"$gte": ["$$member.donations", int(donations[0])]},
            {"$lte": ["$$member.donations", int(donations[1])]}
        ])

    pipeline =[
        {
            MATCH_STAGE: {"$text": {"$search": name}}
        },
        {
            PROJECT_STAGE: {
                '_id' : 0,
                'clan_name' : '$name',
                'clan_tag' : '$tag',
                "memberList": {
                    "$filter": {
                        "input": "$memberList",
                        "as": "member",
                        "cond": {
                            "$and": conditions
                        }
                    }
                }
            }
        },
        {
            MATCH_STAGE: {"memberList.0": {"$exists": True}}
        },
        {LIMIT_STAGE: min(limit, 1000)}
    ]

    results = await mongo.basic_clan.aggregate(pipeline=pipeline).to_list(length=None)
    return {"items" : [member | {'clan_name' : doc['clan_name'], 'clan_tag' : doc['clan_tag']} for doc in results for member in doc['memberList']]}


@router.get("/player/{player_tag}/join-leave",
            name="Get join leave history for a player")
@cache(expire=300)
@linkd.ext.fastapi.inject
async def player_join_leave(player_tag: str, timestamp_start: int = 0, time_stamp_end: int = 9999999999, limit: int = 250, *, mongo: MongoClient):
    player_tag = fix_tag(player_tag)

    pipeline = [
        {
            MATCH_STAGE: {
                "$and": [
                    {"tag": player_tag},
                    {"time": {"$gte": pend.from_timestamp(timestamp_start, tz='UTC')}},
                    {"time": {"$lte": pend.from_timestamp(time_stamp_end, tz='UTC')}}
                ]
            }
        },
        {
            "$lookup": {
                "from": "clan_tags",
                "localField": "clan",
                "foreignField": "tag",
                "as": "clan_info"
            }
        },
        {
            "$unwind": "$clan_info"
        },
        {
            PROJECT_STAGE: {
                "_id": 0,
                "type": 1,
                "clan": 1,
                "clan_name": "$clan_info.name",
                "time": 1,
                "tag": 1,
                "name": 1,
                "th": 1
            }
        },
        {
            "$sort": {"time": 1}
        },
        {
            LIMIT_STAGE: limit
        }
    ]
    result = await mongo.join_leave_history.aggregate(pipeline).to_list(length=None)
    processed_events = _process_clan_events(result)
    processed_events.reverse()
    return {"items": processed_events}



