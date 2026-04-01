from collections import defaultdict

import linkd

from fastapi import HTTPException, APIRouter
import coc
from coc.utils import correct_tag, get

from routers.v2.clan.clan_models import (
    ClanBoard, Location, Ranking, ClanBoardSeasonStats, TownhallComp
)
from utils.database import MongoClient
from utils.custom_coc import CustomClashClient
from utils.security import check_authentication
from utils.time import gen_season_date

router = APIRouter(prefix="/v2", tags=["Clan Endpoints"], include_in_schema=True)


@router.get("/clan/{tag}/board", name="Data for clan board endpoint")
@linkd.ext.fastapi.inject
async def clan_board(
        tag: str,
        *,
        coc_client: CustomClashClient,
        mongo: MongoClient
) -> ClanBoard:
    clan = await coc_client.get_clan(tag=correct_tag(tag))
    season_date: str = gen_season_date()
    pipeline = [
        {"$match": {"clan_tag": clan.tag, "season": season_date}},
        {
            "$group": {
                "_id": None,
                "clan_games": {"$sum": "$clan_games"},
                "donated": {"$sum": "$donated"},
                "received": {"$sum": "$received"},
                "attack_wins": {"$sum": "$attack_wins"},
            }
        }
    ]
    result = await mongo.player_stats.aggregate(pipeline=pipeline)
    season_stats = (await result.to_list())[0]
    print(season_stats)

    capital_hall = coc.utils.get(clan.capital_districts, id=70000000)

    townhall_count = defaultdict(int)

    for member in clan.members:
        townhall_count[member.town_hall] += 1
    townhall_comp = []
    for level, count in sorted(townhall_count.items(), reverse=True):
        townhall_comp.append(TownhallComp(level=level, count=count))

    return ClanBoard(
        tag=clan.tag,
        link=clan.share_link,
        badge=clan.badge.url,
        name=clan.name,
        trophies=clan.points,
        builder_trophies=clan.builder_base_points,
        required_townhall=clan.required_townhall,
        type=clan.type.in_game_name,
        location=Location(
            emoji="",
            name=""
        ),
        ranking=Ranking(
            world=3,
            country=3
        ),
        leader=get(clan.members, role=coc.Role.leader).name if clan.member_count > 0 else "No Leader",
        level=clan.level,
        member_count=clan.member_count,
        cwl_league=clan.war_league.name,
        war_wins=clan.war_wins,
        wars_lost=clan.war_losses if clan.war_losses >= 0 else None,
        win_streak=clan.war_win_streak if clan.war_win_streak >= 0 else None,
        win_ratio=round((clan.war_wins / abs(clan.war_losses)), 1),

        capital_league=clan.capital_league.name,
        capital_points=clan.capital_points,
        capital_hall=capital_hall.hall_level if capital_hall else 0,

        description=clan.description,

        season=ClanBoardSeasonStats(
            month=season_date,
            tracked=True,
            clan_games=season_stats.get("clan_games", 0),
            attack_wins=season_stats.get("attack_wins", 0),
            donations=season_stats.get("donated", 0),
            received=season_stats.get("received", 0),
            active_daily=season_stats.get("active_daily", 0)
        ),
        townhall_composition=townhall_comp,
        boosted_super_troops=[]
    )
