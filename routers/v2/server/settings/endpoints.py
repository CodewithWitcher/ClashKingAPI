from utils.utils import remove_id_fields
from utils.database import MongoClient
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.security import check_authentication
from utils.config import Config
from utils.sentry_utils import capture_endpoint_errors
from .models import ServerSettingsUpdate, ServerSettingsResponse
import linkd

config = Config()
security = HTTPBearer()
router = APIRouter(prefix="/v2", tags=["Server Settings"], include_in_schema=True)

# Constants
LOOKUP_OPERATOR = "$lookup"
SERVER_NOT_FOUND = "Server not found"


def _build_server_aggregation_pipeline(server_id: int, include_clans: bool = True) -> list:
    """
    Build MongoDB aggregation pipeline for fetching server settings with role lookups.

    Args:
        server_id: The Discord server ID
        include_clans: Whether to include clan data in the pipeline

    Returns:
        List of aggregation pipeline stages
    """
    pipeline = [
        {"$match": {"server": server_id}},
        {LOOKUP_OPERATOR: {"from": "legendleagueroles", "localField": "server", "foreignField": "server",
                     "as": "eval.league_roles"}},
        {LOOKUP_OPERATOR: {"from": "evalignore", "localField": "server", "foreignField": "server",
                     "as": "eval.ignored_roles"}},
        {LOOKUP_OPERATOR: {"from": "generalrole", "localField": "server", "foreignField": "server",
                     "as": "eval.family_roles"}},
        {LOOKUP_OPERATOR: {"from": "linkrole", "localField": "server", "foreignField": "server",
                     "as": "eval.not_family_roles"}},
        {LOOKUP_OPERATOR: {"from": "familyexclusiveroles", "localField": "server", "foreignField": "server",
                     "as": "eval.only_family_roles"}},
        {LOOKUP_OPERATOR: {"from": "family_roles", "localField": "server", "foreignField": "server",
                     "as": "eval.family_position_roles"}},
        {LOOKUP_OPERATOR: {"from": "townhallroles", "localField": "server", "foreignField": "server",
                     "as": "eval.townhall_roles"}},
        {LOOKUP_OPERATOR: {"from": "builderhallroles", "localField": "server", "foreignField": "server",
                     "as": "eval.builderhall_roles"}},
        {LOOKUP_OPERATOR: {"from": "achievementroles", "localField": "server", "foreignField": "server",
                     "as": "eval.achievement_roles"}},
        {LOOKUP_OPERATOR: {"from": "statusroles", "localField": "server", "foreignField": "server",
                     "as": "eval.status_roles"}},
        {LOOKUP_OPERATOR: {"from": "builderleagueroles", "localField": "server", "foreignField": "server",
                     "as": "eval.builder_league_roles"}},
    ]

    if include_clans:
        pipeline.append({LOOKUP_OPERATOR: {"from": "clans", "localField": "server", "foreignField": "server", "as": "clans"}})

    return pipeline


def _build_link_parse_updates(link_parse) -> dict:
    """
    Build link_parse field updates from the link_parse settings object.

    Args:
        link_parse: LinkParseSettings object with nested settings

    Returns:
        Dictionary with dotted field names for MongoDB update
    """
    link_parse_updates = {}
    if link_parse.clan is not None:
        link_parse_updates["link_parse.clan"] = link_parse.clan
    if link_parse.army is not None:
        link_parse_updates["link_parse.army"] = link_parse.army
    if link_parse.player is not None:
        link_parse_updates["link_parse.player"] = link_parse.player
    if link_parse.base is not None:
        link_parse_updates["link_parse.base"] = link_parse.base
    if link_parse.show is not None:
        link_parse_updates["link_parse.show"] = link_parse.show
    return link_parse_updates


@router.get("/server/{server_id}/settings",
             name="Get settings for a server")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def server_settings(
    server_id: int,
    clan_settings: bool = False,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
):
    pipeline = _build_server_aggregation_pipeline(server_id, include_clans=clan_settings)
    cursor = await mongo.server_db.aggregate(pipeline)
    results = await cursor.to_list(length=1)
    if not results:
        raise HTTPException(status_code=404, detail="Server Not Found")
    return remove_id_fields(results[0])


@router.get("/server/{server_id}/clan/{clan_tag}/settings",
            name="Get clan settings for a server")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def server_clan_settings(
    server_id: int,
    clan_tag: str,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
):
    result = await mongo.clan_db.find_one({'$and': [{'tag': clan_tag}, {'server': server_id}]})
    if not result:
        raise HTTPException(status_code=404, detail="Server or clan not found")
    return remove_id_fields(result)


@router.put("/server/{server_id}/embed-color/{hex_code}",
            name="Update server discord embed color")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def set_server_embed_color(
    server_id: int,
    hex_code: int,
    _user_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
):
    result = await mongo.server_db.find_one_and_update(
        {"server": server_id},
        {"$set": {"embed_color": hex_code}},
        return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)
    return {"message": "Embed color updated", "server_id": server_id, "embed_color": hex_code}


@router.patch("/server/{server_id}/settings",
              name="Update server settings",
              response_model=ServerSettingsResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_server_settings(
    server_id: int,
    settings: ServerSettingsUpdate,
    _user_id: str = None,
    _request: Request = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> ServerSettingsResponse:
    """
    Update server settings. Only provided fields will be updated.

    This endpoint handles all server-level settings including:
    - Nickname conventions and auto-eval
    - Role management (blacklist, treatment)
    - Channel configurations (banlist, strike log, reddit feed)
    - Link parsing settings
    - General settings (leadership eval, tied stats, etc.)
    """
    # Verify server exists
    existing = await mongo.server_db.find_one({"server": server_id})
    if not existing:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Build update document with only provided fields
    update_doc = {}

    # Direct field mappings
    field_mappings = {
        "embed_color": "embed_color",
        "nickname_rule": "nickname_rule",
        "non_family_nickname_rule": "non_family_nickname_rule",
        "change_nickname": "change_nickname",
        "flair_non_family": "flair_non_family",
        "auto_eval_nickname": "auto_eval_nickname",
        "autoeval_triggers": "autoeval_triggers",
        "autoeval_log": "autoeval_log",
        "autoeval": "autoeval",
        "blacklisted_roles": "blacklisted_roles",
        "role_treatment": "role_treatment",
        "full_whitelist_role": "full_whitelist_role",
        "leadership_eval": "leadership_eval",
        "autoboard_limit": "autoboard_limit",
        "api_token": "api_token",
        "tied": "tied",
        "banlist": "banlist",
        "strike_log": "strike_log",
        "reddit_feed": "reddit_feed",
        "family_label": "family_label",
        "greeting": "greeting",
    }

    for pydantic_field, db_field in field_mappings.items():
        value = getattr(settings, pydantic_field, None)
        if value is not None:
            update_doc[db_field] = value

    # Handle nested link_parse settings
    if settings.link_parse is not None:
        link_parse_updates = _build_link_parse_updates(settings.link_parse)
        update_doc.update(link_parse_updates)

    if not update_doc:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Update the server
    result = await mongo.server_db.update_one(
        {"server": server_id},
        {"$set": update_doc}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    return ServerSettingsResponse(
        message="Server settings updated successfully",
        server_id=server_id,
        updated_fields=len(update_doc)
    )