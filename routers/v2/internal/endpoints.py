import json

import linkd
import sys
import platform
import psutil
from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException
from utils.database import MongoClient
from utils.security import check_authentication

router = APIRouter(tags=["Internal"], prefix="/v2/internal")


@router.get("/bot/info", include_in_schema=False)
@linkd.ext.fastapi.inject
@check_authentication
async def bot_info(*, mongo: MongoClient):
    """
    Get comprehensive bot/API information including uptime, system metrics, and database statistics.

    Requires authentication via JWT token.

    Returns detailed information about:
        - Bot Discord statistics (shards, clusters, servers, members)
        - System resource usage (CPU, memory, disk)
        - Python and OS environment
        - Database statistics (clans, players, tickets, etc.)
    """

    # Get bot shard data from MongoDB (filter for main bot only)
    main_bot_id = 824653933347209227
    shard_data = await mongo.bot_sync.find({"bot_id": main_bot_id}).to_list(length=None)

    # Calculate totals from shard data
    total_servers = sum(d.get('server_count', 0) for d in shard_data)
    total_members = sum(d.get('member_count', 0) for d in shard_data)
    total_clans = sum(d.get('clan_count', 0) for d in shard_data)

    # Format cluster stats
    cluster_stats = []
    for d in sorted(shard_data, key=lambda x: x.get('cluster_id', 0)):
        shards = d.get('shards', []) or []
        cluster_stats.append({
            "cluster_id": d.get('cluster_id', 0),
            "server_count": d.get('server_count', 0),
            "member_count": d.get('member_count', 0),
            "clan_count": d.get('clan_count', 0),
            "shards": shards
        })

    # System metrics
    process = psutil.Process()
    memory_info = process.memory_info()
    system_memory = psutil.virtual_memory()

    system_metrics = {
        "python_version": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "cpu_percent": psutil.cpu_percent(interval=0.1),  # System CPU instead of process CPU
        "memory_used_mb": round(memory_info.rss / (1024 * 1024), 2),
        "memory_total_gb": round(system_memory.total / (1024 ** 3), 2),
        "memory_percent": system_memory.percent,
        "disk_usage_percent": psutil.disk_usage('/').percent
    }

    # Database statistics (using estimated counts for performance)
    db_stats = {
        "clans_tracked": await mongo.clan_db.estimated_document_count(),
        "players_tracked": await mongo.player_stats.estimated_document_count(),
        "wars_stored": await mongo.clan_wars.estimated_document_count(),
        "tickets_open": await mongo.banlist.estimated_document_count(),
        "capital_raids": await mongo.raid_weekend_db.estimated_document_count(),
    }

    info = {
        "bot": {
            "total_servers": total_servers,
            "total_members": total_members,
            "total_clans": total_clans,
            "total_shards": sum(len(d.get('shards') or []) for d in shard_data),
            "clusters": cluster_stats
        },
        "system": system_metrics,
        "database": db_stats
    }

    print(json.dumps(info, indent=4))
    return info
