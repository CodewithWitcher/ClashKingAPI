from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.security import check_authentication
from utils.database import MongoClient
from utils.config import Config
from utils.sentry_utils import capture_endpoint_errors
from .models import (
    FamilyRoleAdd,
    FamilyRoleRemove,
    FamilyRolesResponse,
    FamilyRoleOperationResponse,
    FamilyRoleType,
)
import linkd

security = HTTPBearer()
config = Config()
router = APIRouter(prefix="/v2/server", tags=["Family Roles"], include_in_schema=True)

# Constants
SERVER_NOT_FOUND = "Server not found"

# Mapping of role types to collections
FAMILY_ROLE_COLLECTIONS = {
    "family": "generalrole",
    "not_family": "linkrole",
    "only_family": "familyexclusiveroles",
    "ignored": "evalignore",
}

# Position roles are stored in family_roles collection with a 'type' field
FAMILY_POSITION_TYPES = {
    "family_member": "family_member_roles",
    "family_elder": "family_elder_roles",
    "family_coleader": "family_co-leader_roles",
    "family_leader": "family_leader_roles",
}


@router.get("/{server_id}/family-roles",
           name="Get all family roles for a server",
           response_model=FamilyRolesResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_family_roles(
    server_id: int,
    _user_id: str = None,
    _request: Request = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> FamilyRolesResponse:
    """
    Get all family roles configured for a server.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Fetch general family roles (family, not_family, only_family, ignored)
    family_roles_docs = await mongo.general_family_roles.find({"server": server_id}).to_list(length=None)
    not_family_roles_docs = await mongo.not_family_roles.find({"server": server_id}).to_list(length=None)
    only_family_roles_docs = await mongo.family_exclusive_roles.find({"server": server_id}).to_list(length=None)
    ignored_roles_docs = await mongo.ignored_roles.find({"server": server_id}).to_list(length=None)

    # Fetch position roles (member, elder, coleader, leader)
    position_roles_docs = await mongo.family_roles.find({"server": server_id}).to_list(length=None)

    # Organize position roles by type
    family_member_roles = [doc["role"] for doc in position_roles_docs if doc.get("type") == "family_member_roles"]
    family_elder_roles = [doc["role"] for doc in position_roles_docs if doc.get("type") == "family_elder_roles"]
    family_coleader_roles = [doc["role"] for doc in position_roles_docs if doc.get("type") == "family_co-leader_roles"]
    family_leader_roles = [doc["role"] for doc in position_roles_docs if doc.get("type") == "family_leader_roles"]

    return FamilyRolesResponse(
        server_id=server_id,
        family_roles=[str(doc["role"]) for doc in family_roles_docs],
        not_family_roles=[str(doc["role"]) for doc in not_family_roles_docs],
        only_family_roles=[str(doc["role"]) for doc in only_family_roles_docs],
        family_member_roles=[str(r) for r in family_member_roles],
        family_elder_roles=[str(r) for r in family_elder_roles],
        family_coleader_roles=[str(r) for r in family_coleader_roles],
        family_leader_roles=[str(r) for r in family_leader_roles],
        ignored_roles=[str(doc["role"]) for doc in ignored_roles_docs],
    )


@router.post("/{server_id}/family-roles",
            name="Add a family role",
            response_model=FamilyRoleOperationResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def add_family_role(
    server_id: int,
    role_data: FamilyRoleAdd,
    _user_id: str = None,
    _request: Request = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> FamilyRoleOperationResponse:
    """
    Add a family role to the server.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Determine which collection to use
    role_type_str = role_data.type

    if role_type_str in FAMILY_POSITION_TYPES:
        # Position role - stored in family_roles collection with type field
        collection = mongo.family_roles
        internal_type = FAMILY_POSITION_TYPES[role_type_str]

        # Check for duplicate
        existing = await collection.find_one({
            "server": server_id,
            "role": role_data.role,
            "type": internal_type
        })

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Role {role_data.role} is already added as {role_type_str}"
            )

        # Insert new role
        await collection.insert_one({
            "server": server_id,
            "role": role_data.role,
            "type": internal_type
        })

    elif role_type_str in FAMILY_ROLE_COLLECTIONS:
        # General role - stored in separate collections
        collection_name = FAMILY_ROLE_COLLECTIONS[role_type_str]

        if collection_name == "generalrole":
            collection = mongo.general_family_roles
        elif collection_name == "linkrole":
            collection = mongo.not_family_roles
        elif collection_name == "familyexclusiveroles":
            collection = mongo.family_exclusive_roles
        elif collection_name == "evalignore":
            collection = mongo.ignored_roles
        else:
            raise HTTPException(status_code=400, detail="Invalid role type")

        # Check for duplicate
        existing = await collection.find_one({
            "server": server_id,
            "role": role_data.role
        })

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Role {role_data.role} is already added as {role_type_str}"
            )

        # Insert new role
        await collection.insert_one({
            "server": server_id,
            "role": role_data.role
        })
    else:
        raise HTTPException(status_code=400, detail="Invalid role type")

    return FamilyRoleOperationResponse(
        message=f"Family role added successfully",
        server_id=server_id,
        role_type=role_type_str,
        role_id=str(role_data.role)
    )


@router.delete("/{server_id}/family-roles/{role_type}/{role_id}",
              name="Remove a family role",
              response_model=FamilyRoleOperationResponse)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def remove_family_role(
    server_id: int,
    role_type: FamilyRoleType,
    role_id: int,
    _user_id: str = None,
    _request: Request = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient
) -> FamilyRoleOperationResponse:
    """
    Remove a family role from the server.
    """
    # Verify server exists
    server = await mongo.server_db.find_one({"server": server_id})
    if not server:
        raise HTTPException(status_code=404, detail=SERVER_NOT_FOUND)

    # Determine which collection to use
    if role_type in FAMILY_POSITION_TYPES:
        # Position role
        collection = mongo.family_roles
        internal_type = FAMILY_POSITION_TYPES[role_type]

        result = await collection.delete_one({
            "server": server_id,
            "role": role_id,
            "type": internal_type
        })

        if result.deleted_count == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Role {role_id} not found as {role_type}"
            )

    elif role_type in FAMILY_ROLE_COLLECTIONS:
        # General role
        collection_name = FAMILY_ROLE_COLLECTIONS[role_type]

        if collection_name == "generalrole":
            collection = mongo.general_family_roles
        elif collection_name == "linkrole":
            collection = mongo.not_family_roles
        elif collection_name == "familyexclusiveroles":
            collection = mongo.family_exclusive_roles
        elif collection_name == "evalignore":
            collection = mongo.ignored_roles
        else:
            raise HTTPException(status_code=400, detail="Invalid role type")

        result = await collection.delete_one({
            "server": server_id,
            "role": role_id
        })

        if result.deleted_count == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Role {role_id} not found as {role_type}"
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid role type")

    return FamilyRoleOperationResponse(
        message=f"Family role removed successfully",
        server_id=server_id,
        role_type=role_type,
        role_id=str(role_id)
    )
