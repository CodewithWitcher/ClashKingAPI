from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.security import check_authentication
from utils.database import MongoClient
from utils.config import Config
from utils.sentry_utils import capture_endpoint_errors
from utils.cache_decorator import cache_endpoint
from .models import (
    RoleType,
    TownhallRoleCreate,
    LeagueRoleCreate,
    BuilderHallRoleCreate,
    BuilderLeagueRoleCreate,
    AchievementRoleCreate,
    StatusRoleCreate,
    FamilyPositionRoleCreate,
    RoleResponse,
    RolesListResponse,
    DiscordRole,
    DiscordRolesResponse,
    RoleSettingsResponse,
    RoleSettingsUpdate,
    AllRolesResponse,
)
from typing import Union
import linkd
import hikari
import json
import os

security = HTTPBearer()
config = Config()
router = APIRouter(prefix="/v2/server", tags=["Role Management"], include_in_schema=True)

# Constants
SERVER_NOT_FOUND = "Server not found"


def load_league_data() -> tuple[dict, dict]:
    """
    Load league tier names and translations for validation.

    Returns:
        Tuple of (translations_dict, tid_to_english_name_map)
    """
    import coc
    coc_path = os.path.dirname(coc.__file__)

    # Load static data
    static_data_path = os.path.join(coc_path, "static", "static_data.json")
    with open(static_data_path, 'r', encoding='utf-8') as f:
        static_data = json.load(f)

    # Load translations
    translations_path = os.path.join(coc_path, "static", "translations.json")
    with open(translations_path, 'r', encoding='utf-8') as f:
        translations = json.load(f)

    # Build TID -> English name mapping
    tid_to_english = {}
    league_tiers = static_data.get("league_tiers", [])
    for tier in league_tiers:
        tid = tier.get("TID", {}).get("name")
        if tid and tid in translations:
            english_name = translations[tid].get("EN")
            if english_name:
                tid_to_english[tid] = english_name

    return translations, tid_to_english


def convert_to_english_league_name(name: str, translations: dict, tid_to_english: dict) -> str:
    """
    Convert a league name in any language to its English equivalent.

    Args:
        name: League name in any language (e.g., "Ligue Légende", "Legend League")
        translations: Full translations dictionary
        tid_to_english: Mapping from TID to English name

    Returns:
        English league name

    Raises:
        HTTPException: If the league name is not found in any language
    """
    # Check if it's already in English
    if name in tid_to_english.values():
        return name

    # Search through all translations to find the TID
    for tid, lang_map in translations.items():
        if name in lang_map.values():
            # Found it! Return the English name
            english_name = tid_to_english.get(tid)
            if english_name:
                return english_name

    # Not found in any language
    raise HTTPException(
        status_code=400,
        detail=f"Invalid league type: '{name}'. Must be a valid Clash of Clans league in any supported language."
    )


def normalize_league_name(name: str) -> str:
    """
    Normalize league name to snake_case for database storage.
    Example: "Legend League" -> "legend_league"
             "Titan League I" -> "titan_league_i"
    """
    return name.lower().replace(" ", "_")


# Load league data at startup
LEAGUE_TRANSLATIONS, TID_TO_ENGLISH = load_league_data()


# Mapping of role types to Pydantic models
ROLE_MODELS = {
    "townhall": TownhallRoleCreate,
    "league": LeagueRoleCreate,
    "builderhall": BuilderHallRoleCreate,
    "builder_league": BuilderLeagueRoleCreate,
    "achievement": AchievementRoleCreate,
    "status": StatusRoleCreate,
    "family_position": FamilyPositionRoleCreate,
}


def get_role_collection(mongo: MongoClient, role_type: str):
    """Get the collection object for a given role type."""
    collection_map = {
        "townhall": mongo.townhall_roles,
        "league": mongo.legend_league_roles,
        "builderhall": mongo.builderhall_roles,
        "builder_league": mongo.builder_league_roles,
        "achievement": mongo.achievement_roles,
        "family_position": mongo.family_roles,
    }
    return collection_map.get(role_type)


def build_duplicate_query(server_id: int, role_type: str, role_data) -> dict:
    """Build query to check for duplicate roles based on role type."""
    query = {"server": server_id}

    if role_type == "townhall":
        # MongoDB stores as "th10" string format
        query["th"] = f"th{role_data.th}"
    elif role_type in ["league", "builder_league"]:
        query["type"] = role_data.type
    elif role_type == "builderhall":
        # MongoDB stores as "bh3" string format
        query["bh"] = f"bh{role_data.bh}"
    elif role_type == "achievement":
        query["type"] = role_data.type
        query["season"] = role_data.season
        query["amount"] = role_data.amount
    elif role_type == "family_position":
        query["type"] = role_data.type

    return query


async def create_status_role(mongo: MongoClient, server_id: int, server: dict, role_data, role_doc: dict) -> int:
    """Handle creation/update of status roles."""
    existing_roles = server.get("status_roles", {}).get("discord", [])
    if any(r.get("months") == role_data.months for r in existing_roles):
        # Update existing
        await mongo.server_db.update_one(
            {"server": server_id, "status_roles.discord.months": role_data.months},
            {"$set": {"status_roles.discord.$.id": role_data.id}}
        )
    else:
        # Add new
        await mongo.server_db.update_one(
            {"server": server_id},
            {"$addToSet": {"status_roles.discord": role_doc}}
        )
    return role_data.id


async def create_standard_role(collection, query: dict, role_type: str, role_data, role_doc: dict) -> int:
    """Handle creation/update of standard roles (non-status)."""
    existing = await collection.find_one(query)

    if existing:
        # Update existing role
        if role_type == "achievement":
            await collection.update_one(query, {"$set": {"id": role_data.id}})
            return role_data.id
        else:
            await collection.update_one(query, {"$set": {"role": role_data.role}})
            return role_data.role
    else:
        # Insert new role
        await collection.insert_one(role_doc)
        return role_data.id if role_type == "achievement" else role_data.role


async def fetch_roles_by_type(mongo: MongoClient, server_id: int, role_type: str, server: dict) -> list:
    """Fetch roles for a specific role type."""
    if role_type == "status":
        # Status roles are in server_db
        status_roles_data = server.get("status_roles")
        if status_roles_data and isinstance(status_roles_data, dict):
            return status_roles_data.get("discord", [])
        return []
    else:
        collection = get_role_collection(mongo, role_type)
        if collection is not None:
            return await collection.find({"server": server_id}).to_list(length=None)
        return []


def sanitize_role_data(role_list: list) -> None:
    """Remove internal fields and convert Discord IDs to strings for JSON compatibility."""
    for role in role_list:
        if isinstance(role, dict):
            role.pop("_id", None)
            role.pop("toggle", None)

            # Convert Discord Snowflake IDs to strings
            # JavaScript can't handle 64-bit integers without precision loss
            if "role" in role and isinstance(role["role"], int):
                role["role"] = str(role["role"])
            # Status roles use "id" instead of "role"
            if "id" in role and isinstance(role["id"], int):
                role["id"] = str(role["id"])


@router.get("/{server_id}/roles/{role_type}",
            name="List roles by type",
            response_model=RolesListResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def list_roles(
    server_id: int,
    role_type: RoleType,
    _user_id: str = None,
    _request: Request = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> RolesListResponse:
    """
    List all roles of a specific type for a server.

    Role types:
    - townhall: Townhall level roles
    - league: League roles (Legend, Titan, etc.)
    - builderhall: Builder hall level roles
    - builder_league: Builder league roles
    - achievement: Achievement-based roles
    - status: Discord tenure/status roles
    - family_position: Family position roles (elder, co-leader, leader)
    """
    # Status roles are in server_db, not a separate collection
    if role_type == "status":
        server = await mongo.server_db.find_one({"server": server_id})
        if not server:
            raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

        status_roles_data = server.get("status_roles")
        if status_roles_data and isinstance(status_roles_data, dict):
            role_list = status_roles_data.get("discord", [])
        else:
            role_list = []
    else:
        # Get collection
        collection = get_role_collection(mongo, role_type)
        if not collection:
            raise HTTPException(status_code=400, detail=f"Invalid role type: {role_type}")

        roles = await collection.find({"server": server_id}).to_list(length=None)
        role_list = roles

    # Remove _id and toggle fields for JSON serialization
    for role in role_list:
        if isinstance(role, dict):
            role.pop("_id", None)
            role.pop("toggle", None)

    return RolesListResponse(
        server_id=server_id,
        role_type=role_type,
        roles=role_list,
        count=len(role_list)
    )


@router.post("/{server_id}/roles/{role_type}",
             name="Create a role",
             response_model=RoleResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def create_role(
    server_id: int,
    role_type: RoleType,
    role_data: Union[
        TownhallRoleCreate,
        LeagueRoleCreate,
        BuilderHallRoleCreate,
        BuilderLeagueRoleCreate,
        AchievementRoleCreate,
        StatusRoleCreate,
        FamilyPositionRoleCreate,
    ],
    _user_id: str = None,
    _request: Request = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> RoleResponse:
    """
    Create a new role for a server.

    The request body should match the role type:
    - townhall: {role, th}
    - league: {role, type}
    - builderhall: {role, bh}
    - builder_league: {role, type}
    - achievement: {id, type, season, amount}
    - status: {id, months}
    - family_position: {role, type}
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Validate and normalize league types
    if role_type == "league":
        # Convert from any language to English (validates in the process)
        english_name = convert_to_english_league_name(role_data.type, LEAGUE_TRANSLATIONS, TID_TO_ENGLISH)
        # Normalize to snake_case for database storage
        role_data.type = normalize_league_name(english_name)
    elif role_type == "builder_league":
        # TODO: Add builder league validation and translation once we have it
        role_data.type = normalize_league_name(role_data.type)

    role_doc = role_data.model_dump()

    # Status roles don't need server field (they're stored in server_db subdocument)
    if role_type != "status":
        role_doc["server"] = server_id

    # Convert townhall and builderhall levels to string format for MongoDB
    if role_type == "townhall" and "th" in role_doc:
        role_doc["th"] = f"th{role_doc['th']}"
    elif role_type == "builderhall" and "bh" in role_doc:
        role_doc["bh"] = f"bh{role_doc['bh']}"

    # Handle status roles differently (stored in server_db)
    if role_type == "status":
        role_id = await create_status_role(mongo, server_id, server, role_data, role_doc)
    else:
        # Get collection for other role types
        collection = get_role_collection(mongo, role_type)
        query = build_duplicate_query(server_id, role_type, role_data)
        role_id = await create_standard_role(collection, query, role_type, role_data, role_doc)

    return RoleResponse(
        message=f"{role_type.replace('_', ' ').title()} role created successfully",
        server_id=server_id,
        role_type=role_type,
        role_id=role_id
    )


@router.delete("/{server_id}/roles/{role_type}/{role_id}",
               name="Delete a role",
               response_model=RoleResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def delete_role(
    server_id: int,
    role_type: RoleType,
    role_id: int,
    _user_id: str = None,
    _request: Request = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> RoleResponse:
    """
    Delete a role by its Discord role ID.

    This will remove the role configuration from the server.
    """
    # Special handling for status roles (stored in server_db)
    if role_type == "status":
        result = await mongo.server_db.update_one(
            {"server": server_id},
            {"$pull": {"status_roles.discord": {"id": role_id}}}
        )
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Role not found")
    else:
        # Get collection
        collection = get_role_collection(mongo, role_type)

        # Delete based on role or id field
        field_name = "id" if role_type == "achievement" else "role"
        result = await collection.delete_one({
            "server": server_id,
            field_name: role_id
        })
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Role not found")

    return RoleResponse(
        message=f"{role_type.replace('_', ' ').title()} role deleted successfully",
        server_id=server_id,
        role_type=role_type,
        role_id=role_id
    )


@router.get("/{server_id}/discord-roles",
            name="Get Discord roles",
            response_model=DiscordRolesResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
@cache_endpoint(ttl=30, key_prefix="discord-roles")
async def get_discord_roles(
    server_id: int,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    rest: hikari.RESTApp
) -> DiscordRolesResponse:
    """
    Get all Discord roles available on the server.

    Returns a list of all roles with their properties (name, color, position, etc.)
    that can be used for role management configuration.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Fetch roles from Discord API
    try:
        async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
            roles = await client.fetch_roles(server_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Discord roles: {str(e)}")

    # Format roles
    role_list = []
    for role in roles:
        role_list.append(DiscordRole(
            id=str(role.id),
            name=role.name,
            color=int(role.color) if role.color else 0,
            position=role.position,
            managed=role.is_managed,
            mentionable=role.is_mentionable
        ))

    # Sort by position (highest first)
    role_list.sort(key=lambda r: r.position, reverse=True)

    return DiscordRolesResponse(
        server_id=server_id,
        roles=role_list,
        count=len(role_list)
    )


@router.get("/{server_id}/role-settings",
            name="Get role settings",
            response_model=RoleSettingsResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_role_settings(
    server_id: int,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> RoleSettingsResponse:
    """
    Get global role management settings for a server.

    Returns configuration for auto-eval, blacklisted roles, and role treatment rules.
    """
    # Fetch server settings
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    return RoleSettingsResponse(
        server_id=server_id,
        auto_eval_status=server.get("autoeval"),
        auto_eval_nickname=server.get("auto_eval_nickname"),
        autoeval_triggers=server.get("autoeval_triggers", []),
        autoeval_log=server.get("autoeval_log"),
        blacklisted_roles=server.get("blacklisted_roles", []),
        role_treatment=server.get("role_treatment", []),
        category_roles=server.get("category_roles", {})
    )


@router.patch("/{server_id}/role-settings",
              name="Update role settings",
              response_model=RoleResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_role_settings(
    server_id: int,
    settings: RoleSettingsUpdate,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> RoleResponse:
    """
    Update global role management settings for a server.

    Only provided fields will be updated. All fields are optional.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Build update document
    update_doc = {}

    if settings.auto_eval_status is not None:
        update_doc["autoeval"] = settings.auto_eval_status
    if settings.auto_eval_nickname is not None:
        update_doc["auto_eval_nickname"] = settings.auto_eval_nickname
    if settings.autoeval_triggers is not None:
        update_doc["autoeval_triggers"] = settings.autoeval_triggers
    if settings.autoeval_log is not None:
        update_doc["autoeval_log"] = settings.autoeval_log
    if settings.blacklisted_roles is not None:
        update_doc["blacklisted_roles"] = settings.blacklisted_roles
    if settings.role_treatment is not None:
        update_doc["role_treatment"] = settings.role_treatment

    if not update_doc:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Update server settings
    await mongo.server_db.update_one(
        {"server": server_id},
        {"$set": update_doc}
    )

    return RoleResponse(
        message="Role settings updated successfully",
        server_id=server_id,
        role_type="settings",
        role_id=None
    )


@router.get("/{server_id}/all-roles",
            name="Get all roles",
            response_model=AllRolesResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_all_roles(
        server_id: int,
        _user_id: str = None,
        _credentials: HTTPAuthorizationCredentials = Depends(security),
        *,
        mongo: MongoClient
) -> AllRolesResponse:
    """
    Get all configured roles of all types in a single request.

    Returns a complete overview of all role configurations for the server.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    all_roles = {}
    total_count = 0

    # Fetch roles for each type
    role_types = ["townhall", "league", "builderhall", "builder_league", "achievement", "status", "family_position"]

    for role_type in role_types:
        role_list = await fetch_roles_by_type(mongo, server_id, role_type, server)
        sanitize_role_data(role_list)

        all_roles[role_type] = role_list
        total_count += len(role_list)

    return AllRolesResponse(
        server_id=server_id,
        roles=all_roles,
        total_count=total_count
    )