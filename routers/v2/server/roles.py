from fastapi import APIRouter, HTTPException, Request, Depends, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.security import check_authentication
from utils.database import MongoClient
from .roles_models import (
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
)
from typing import Union
import linkd

security = HTTPBearer()
router = APIRouter(prefix="/v2/server", tags=["Role Management"], include_in_schema=True)


# Mapping of role types to MongoDB collections
ROLE_COLLECTIONS = {
    "townhall": "townhallroles",
    "league": "legendleagueroles",
    "builderhall": "builderhallroles",
    "builder_league": "builderleagueroles",
    "achievement": "achievementroles",
    "status": "statusroles",
    "family_position": "family_roles",
}


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


@router.get("/{server_id}/roles/{role_type}",
            name="List roles by type",
            response_model=RolesListResponse)
@linkd.ext.fastapi.inject
@check_authentication
async def list_roles(
    server_id: int,
    role_type: RoleType,
    user_id: str = None,
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
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
    # Get collection name
    collection_name = ROLE_COLLECTIONS.get(role_type)
    if not collection_name:
        raise HTTPException(status_code=400, detail=f"Invalid role type: {role_type}")

    # Get collection from the __bot_settings database
    collection = mongo._MongoClient__static_client.get_database('usafam').get_collection(collection_name)

    # Query roles for this server
    if role_type == "status":
        # Status roles are stored differently
        roles = await collection.find({"server": server_id}).to_list(length=None)
        # Extract from nested structure
        role_list = []
        for doc in roles:
            if "discord" in doc:
                role_list.extend(doc.get("discord", []))
    else:
        roles = await collection.find({"server": server_id}).to_list(length=None)
        role_list = roles

    # Remove _id fields for JSON serialization
    for role in role_list:
        if "_id" in role:
            role.pop("_id")

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
    user_id: str = None,
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> RoleResponse:
    """
    Create a new role for a server.

    The request body should match the role type:
    - townhall: {role_id, th, toggle}
    - league: {role_id, league, toggle}
    - builderhall: {role_id, bh, toggle}
    - builder_league: {role_id, league, toggle}
    - achievement: {role_id, achievement, toggle}
    - status: {role_id (or id), months}
    - family_position: {role_id, type, toggle}
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Get collection
    collection_name = ROLE_COLLECTIONS.get(role_type)
    collection = mongo._MongoClient__static_client.get_database('usafam').get_collection(collection_name)

    # Build role document
    role_doc = role_data.model_dump(by_alias=True)
    role_doc["server"] = server_id

    # Special handling for status roles
    if role_type == "status":
        # Status roles are stored in a nested structure
        existing = await collection.find_one({"server": server_id})
        if existing:
            # Add to existing discord array
            await collection.update_one(
                {"server": server_id},
                {"$push": {"discord": role_doc}}
            )
        else:
            # Create new document
            await collection.insert_one({
                "server": server_id,
                "discord": [role_doc]
            })
    else:
        # Check for duplicates
        query = {"server": server_id}
        if role_type == "townhall":
            query["th"] = role_data.th
        elif role_type in ["league", "builder_league"]:
            query["league"] = role_data.league
        elif role_type == "builderhall":
            query["bh"] = role_data.bh
        elif role_type == "achievement":
            query["achievement"] = role_data.achievement
        elif role_type == "family_position":
            query["type"] = role_data.type

        existing = await collection.find_one(query)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"A {role_type} role with these parameters already exists"
            )

        # Insert role
        await collection.insert_one(role_doc)

    return RoleResponse(
        message=f"{role_type.replace('_', ' ').title()} role created successfully",
        server_id=server_id,
        role_type=role_type,
        role_id=role_data.role_id if hasattr(role_data, 'role_id') else getattr(role_data, 'id', None)
    )


@router.delete("/{server_id}/roles/{role_type}/{role_id}",
               name="Delete a role",
               response_model=RoleResponse)
@linkd.ext.fastapi.inject
@check_authentication
async def delete_role(
    server_id: int,
    role_type: RoleType,
    role_id: int,
    user_id: str = None,
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> RoleResponse:
    """
    Delete a role by its Discord role ID.

    This will remove the role configuration from the server.
    """
    # Get collection
    collection_name = ROLE_COLLECTIONS.get(role_type)
    collection = mongo._MongoClient__static_client.get_database('usafam').get_collection(collection_name)

    # Special handling for status roles
    if role_type == "status":
        result = await collection.update_one(
            {"server": server_id},
            {"$pull": {"discord": {"id": role_id}}}
        )
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Role not found")
    else:
        # Delete based on role_id field
        result = await collection.delete_one({
            "server": server_id,
            "role_id": role_id
        })
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Role not found")

    return RoleResponse(
        message=f"{role_type.replace('_', ' ').title()} role deleted successfully",
        server_id=server_id,
        role_type=role_type,
        role_id=role_id
    )
