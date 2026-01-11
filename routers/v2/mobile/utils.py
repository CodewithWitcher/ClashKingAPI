"""Helper functions for mobile app bulk endpoints."""
import asyncio
import logging
from typing import Any, Dict, List

import aiohttp
import pendulum as pend
from fastapi import HTTPException, Request

from routers.v2.clan.endpoints import get_clans_stats, get_clans_capital_raids, get_multiple_clan_join_leave
from routers.v2.clan.models import ClanTagsRequest, RaidsRequest
from routers.v2.player.models import PlayerTagsRequest
from routers.v2.player.utils import (
    get_legend_stats_common,
    assemble_full_player_data,
    fetch_full_player_data,
    fetch_player_api_data,
)
from routers.v2.war.endpoints import get_multiple_clan_war_summary, clan_warhits_stats, players_warhits_stats
from routers.v2.war.models import ClanWarHitsFilter, PlayerWarhitsFilter
from utils.utils import remove_id_fields
from utils.database import MongoClient

logger = logging.getLogger(__name__)


async def fetch_clan_war_logs(clan_tags: List[str]) -> List[Dict[str, Any]]:
    """Fetch war logs for multiple clans in parallel.

    Args:
        clan_tags: List of clan tags to fetch war logs for

    Returns:
        List[Dict]: List of war log data per clan with structure:
            {'clan_tag': str, 'items': List[Dict]}
    """
    async def fetch_single_war_log(
        session: aiohttp.ClientSession, clan_tag: str
    ) -> Dict[str, Any]:
        """Fetch war log for a single clan."""
        url = f"https://proxy.clashk.ing/v1/clans/{clan_tag.replace('#', '%23')}/warlog"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {'clan_tag': clan_tag, 'items': data.get('items', [])}
                return {'clan_tag': clan_tag, 'items': []}
        except Exception as e:
            logger.error(f"Error fetching war log for {clan_tag}: {e}", exc_info=True)
            return {'clan_tag': clan_tag, 'items': []}

    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(
            *(fetch_single_war_log(session, tag) for tag in clan_tags)
        )


async def fetch_players_basic_data(player_tags: List[str]) -> List[Dict[str, Any]]:
    """Fetch basic player data from CoC API.

    Args:
        player_tags: List of player tags

    Returns:
        List[Dict]: Basic player data from API
    """
    async with aiohttp.ClientSession() as session:
        fetch_tasks = [fetch_player_api_data(session, tag) for tag in player_tags]
        api_results = await asyncio.gather(*fetch_tasks)

    basic_result = []
    for tag, data in zip(player_tags, api_results):
        if isinstance(data, HTTPException):
            if data.status_code in (503, 500):
                raise data
            continue
        if data:
            basic_result.append({'tag': tag, **data})

    return basic_result


async def fetch_players_extended_data(
    player_tags: List[str],
    mongo: MongoClient
) -> List[Dict[str, Any]]:
    """Fetch extended player data with MongoDB tracking stats and legends data.

    Args:
        player_tags: List of player tags
        mongo: MongoDB client instance

    Returns:
        List[Dict]: Extended player data with tracking stats
    """
    # Fetch MongoDB player_stats in bulk
    players_info = await mongo.player_stats.find(
        {'tag': {'$in': player_tags}},
        {
            '_id': 0,
            'tag': 1,
            'donations': 1,
            'clan_games': 1,
            'season_pass': 1,
            'activity': 1,
            'last_online': 1,
            'last_online_time': 1,
            'attack_wins': 1,
            'dark_elixir': 1,
            'gold': 1,
            'capital_gold': 1,
            'season_trophies': 1,
            'last_updated': 1,
        },
    ).to_list(length=None)

    mongo_data_dict = {player['tag']: player for player in players_info}

    # Load legends data in bulk
    legends_data = await get_legend_stats_common(player_tags)
    tag_to_legends = {
        entry['tag']: entry['legends_by_season'] for entry in legends_data
    }

    # Fetch extended data per player in parallel
    async with aiohttp.ClientSession() as session:
        fetch_tasks = [
            fetch_full_player_data(
                session, tag, mongo_data_dict.get(tag, {}), None
            )
            for tag in player_tags
        ]
        player_results = await asyncio.gather(*fetch_tasks)

    # Assemble enriched player data in parallel
    extended_results = await asyncio.gather(
        *[
            assemble_full_player_data(tag, raid_data, war_data, mongo_data, tag_to_legends)
            for tag, raid_data, war_data, mongo_data in player_results
        ]
    )

    # Remove MongoDB _id fields
    return remove_id_fields(extended_results)


async def fetch_all_clan_data(
    clan_tags: List[str], request: Request, mongo: MongoClient
) -> Dict[str, Any]:
    """Fetch all clan-related data in parallel.

    Args:
        clan_tags: List of clan tags
        request: FastAPI request object
        mongo: MongoDB client instance

    Returns:
        Dict with all clan data:
            - clan_details: Dict[str, Any]
            - join_leave_data: Dict[str, Any]
            - capital_data: List[Any]
            - war_log_data: List[Any]
            - war_data: List[Any]
            - clan_war_stats: List[Any]
    """
    clan_request = ClanTagsRequest(clan_tags=clan_tags)
    raids_request = RaidsRequest(clan_tags=clan_tags, limit=10)

    async def fetch_clan_war_stats() -> Dict[str, Any]:
        """Fetch clan war stats."""
        mongo_filter = ClanWarHitsFilter(
            clan_tags=clan_tags,
            timestamp_start=int(pend.now(tz=pend.UTC).subtract(months=6).timestamp()),
            timestamp_end=int(pend.now(tz=pend.UTC).timestamp()),
            limit=50,
        )
        return await clan_warhits_stats(mongo_filter, mongo=mongo)

    async def fetch_join_leave_data() -> Dict[str, Any]:
        """Fetch join/leave data."""
        return await get_multiple_clan_join_leave(
            clan_tags=clan_tags, request=request, programmatic_filters=None
        )

    # Execute all API calls in parallel
    (
        clan_details_result,
        clan_join_leave_result,
        clan_capital_result,
        war_summary_result_raw,
        clan_war_stats_result,
        clan_war_log_result,
    ) = await asyncio.gather(
        get_clans_stats(request, clan_request),
        fetch_join_leave_data(),
        get_clans_capital_raids(request, raids_request),
        get_multiple_clan_war_summary(clan_request, request),
        fetch_clan_war_stats(),
        fetch_clan_war_logs(clan_tags),
    )

    # Extract content from JSONResponse if needed
    from fastapi.responses import JSONResponse
    import json

    if isinstance(war_summary_result_raw, JSONResponse):
        war_summary_result = json.loads(war_summary_result_raw.body.decode())
    else:
        war_summary_result = war_summary_result_raw

    return {
        'clan_details': {
            item.get('tag', ''): item
            for item in clan_details_result.get('items', [])
            if item
        },
        'join_leave_data': {
            item.get('clan_tag', ''): item
            for item in clan_join_leave_result.get('items', [])
        },
        'capital_data': clan_capital_result.get('items', []),
        'war_log_data': clan_war_log_result,
        'war_data': war_summary_result.get('items', []),
        'clan_war_stats': clan_war_stats_result.get('items', []),
    }


def extract_clan_tags_from_players(players_basic: List[Dict[str, Any]]) -> List[str]:
    """Extract unique clan tags from basic player data.

    Args:
        players_basic: List of basic player data

    Returns:
        List[str]: List of unique clan tags
    """
    clan_tags = set()
    for player in players_basic:
        if player and player.get('clan') and player['clan'].get('tag'):
            clan_tag = str(player['clan']['tag'])
            if clan_tag:
                clan_tags.add(clan_tag)
    return list(clan_tags)


async def fetch_player_war_stats(body: PlayerTagsRequest, mongo: MongoClient) -> Dict[str, Any]:
    """Fetch player war stats with mobile app defaults (last 6 months, limit 50).

    Args:
        body: Request containing player tags
        mongo: MongoDB client instance

    Returns:
        Dict: War statistics for players

    Raises:
        HTTPException: 400 if player_tags is empty
    """
    if not body.player_tags:
        raise HTTPException(status_code=400, detail='player_tags cannot be empty')

    mongo_filter = PlayerWarhitsFilter(
        player_tags=body.player_tags,
        timestamp_start=int(pend.now(tz=pend.UTC).subtract(months=6).timestamp()),
        timestamp_end=int(pend.now(tz=pend.UTC).timestamp()),
        limit=50,
    )

    return await players_warhits_stats(mongo_filter, mongo=mongo)
