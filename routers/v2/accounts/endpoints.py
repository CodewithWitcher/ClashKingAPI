import pendulum as pend
import linkd
from fastapi import HTTPException, APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from routers.v2.accounts.utils import fetch_coc_account_data, is_coc_account_linked, verify_coc_ownership, \
    validate_coc_tag, reorder_user_accounts
from routers.v2.auth.models import CocAccountRequest
from utils.utils import generate_custom_id, fix_tag, remove_id_fields
from pymongo import UpdateOne
from utils.database import MongoClient
from utils.security import check_authentication
from utils.sentry_utils import capture_endpoint_errors

router = APIRouter(prefix="/v2", tags=["Coc Accounts"], include_in_schema=True)
security = HTTPBearer()


@router.post("/users/coc-accounts", name="Link a Clash of Clans account to a user")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def add_coc_account(request: CocAccountRequest, user_id: str = None,
                          _credentials: HTTPAuthorizationCredentials = Depends(security), *, mongo: MongoClient):
    """Associate a Clash of Clans account (tag) with a user WITHOUT ownership verification.

    Args:
        request: CocAccountRequest containing player_tag
        user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        dict: Success message with account details (tag, name, townHallLevel, is_verified)

    Raises:
        HTTPException: 400 if tag format is invalid
        HTTPException: 404 if account does not exist
        HTTPException: 409 if account is already linked to another user
    """
    # Normalize the tag (converts lowercase to uppercase and fixes format)
    player_tag = fix_tag(request.player_tag)
    validate_coc_tag(player_tag)

    # Fetch account details from the API
    coc_account_data = fetch_coc_account_data(player_tag)

    if await is_coc_account_linked(player_tag, mongo):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This Clash of Clans account is already linked to another user",
                "account": {
                    "tag": coc_account_data["tag"],
                    "name": coc_account_data["name"],
                    "townHallLevel": coc_account_data["townHallLevel"]
                }
            }
        )

    # Get the order index for the new account
    existing_accounts = await mongo.coc_accounts.count_documents({"user_id": user_id})
    order_index = existing_accounts  # The new account will be added at the end

    # Store in the database
    await mongo.coc_accounts.insert_one({
        "user_id": user_id,
        "player_tag": coc_account_data["tag"],
        "order_index": order_index,
        "is_verified": False,
        "added_at": pend.now(tz=pend.UTC)
    })

    # Return account details to the front-end
    return {
        "message": "Clash of Clans account linked successfully",
        "account": {
            "tag": coc_account_data["tag"],
            "name": coc_account_data["name"],
            "townHallLevel": coc_account_data["townHallLevel"],
            "is_verified": False  # Account is not verified when added without token
        }
    }


@router.post("/users/coc-accounts/verified",
             name="Link a Clash of Clans account to a user with a token verification")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def add_coc_account_with_verification(request: CocAccountRequest, user_id: str = None,
                                            _credentials: HTTPAuthorizationCredentials = Depends(security), *,
                                            mongo: MongoClient):
    """Associate a Clash of Clans account with a user WITH ownership verification.

    Args:
        request: CocAccountRequest containing player_tag and player_token
        user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        dict: Success message with account details (tag, name, townHallLevel, is_verified=True)

    Raises:
        HTTPException: 400 if tag format is invalid
        HTTPException: 403 if player token is invalid
        HTTPException: 404 if account does not exist
    """
    # Normalize the tag (converts lowercase to uppercase and fixes format)
    player_tag = fix_tag(request.player_tag)
    player_token = request.player_token
    validate_coc_tag(player_tag)

    if not verify_coc_ownership(player_tag, player_token):
        raise HTTPException(status_code=403,
                            detail="Invalid player token. Check your Clash of Clans account settings and try again.")

    # Fetch account details from the API
    coc_account_data = fetch_coc_account_data(player_tag)

    # Remove the link to the other user if it exists
    old_account = await mongo.coc_accounts.find_one({"player_tag": player_tag})
    if old_account:
        old_user_id = old_account["user_id"]

        # Delete the old account link
        await mongo.coc_accounts.delete_one({"player_tag": player_tag})

        # Update the order index for the remaining accounts
        await reorder_user_accounts(old_user_id, mongo)

    # Get the order index for the new account
    existing_accounts = await mongo.coc_accounts.count_documents({"user_id": user_id})
    order_index = existing_accounts  # The new account will be added at the end

    # Store in the database - only use custom _id if user_id is numeric
    doc = {
        "user_id": user_id,
        "player_tag": coc_account_data["tag"],
        "order_index": order_index,
        "is_verified": True,  # Verified during account addition
        "added_at": pend.now(tz=pend.UTC)
    }

    # Only add custom _id if user_id is numeric (not for "server:123" format)
    if user_id.isdigit():
        doc["_id"] = generate_custom_id(int(user_id))

    await mongo.coc_accounts.insert_one(doc)

    # Return account details to the front-end
    return {
        "message": "Clash of Clans account linked successfully with ownership verification",
        "account": {
            "tag": coc_account_data["tag"],
            "name": coc_account_data["name"],
            "townHallLevel": coc_account_data["townHallLevel"],
            "is_verified": True  # Account is verified when added with token
        }
    }


@router.get("/users/coc-accounts", name="Get all Clash of Clans accounts linked to a user")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_coc_accounts(user_id: str = None, _credentials: HTTPAuthorizationCredentials = Depends(security), *,
                           mongo: MongoClient):
    """Retrieve all Clash of Clans accounts linked to a user.

    Args:
        user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        dict: {'coc_accounts': [list of account objects sorted by order_index]}
    """

    accounts = await mongo.coc_accounts.find({"user_id": user_id}).sort("order_index", 1).to_list(length=None)

    return remove_id_fields({"coc_accounts": accounts})


@router.delete("/users/coc-accounts/{player_tag}", name="Remove a Clash of Clans account linked to a user")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def remove_coc_account(player_tag: str, user_id: str = None,
                             _credentials: HTTPAuthorizationCredentials = Depends(security), *, mongo: MongoClient):
    """Remove a specific Clash of Clans account linked to a user.

    Args:
        player_tag: Clash of Clans player tag (path parameter)
        user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        dict: Success message

    Raises:
        HTTPException: 404 if account not found or not linked to user
    """
    # Normalize the tag (converts lowercase to uppercase and fixes format)
    player_tag = fix_tag(player_tag)

    result = await mongo.coc_accounts.delete_one({"user_id": user_id, "player_tag": player_tag})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Clash of Clans account not found or not linked to your profile")

    # Reorder the remaining accounts using bulk operations
    await reorder_user_accounts(user_id, mongo)

    return {"message": "Clash of Clans account unlinked successfully"}


@router.get("/users/coc-accounts/{player_tag}/status", name="Check if a Clash of Clans account is linked to any user")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def check_coc_account(player_tag: str, user_id: str = None,
                            _credentials: HTTPAuthorizationCredentials = Depends(security), *, mongo: MongoClient):
    """Check if a Clash of Clans account is linked to any user.

    Args:
        player_tag: Clash of Clans player tag (path parameter)
        user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        dict: {'linked': bool, 'is_own_account': bool (if linked), 'message': str}
    """

    # Normalize the tag (converts lowercase to uppercase and fixes format)
    player_tag = fix_tag(player_tag)

    existing_account = await mongo.coc_accounts.find_one({"player_tag": player_tag})

    if not existing_account:
        return {"linked": False, "message": "This Clash of Clans account is not linked to any user."}

    # Only return user_id if it's the same as the authenticated user (privacy)
    is_own_account = existing_account["user_id"] == user_id

    return {
        "linked": True,
        "is_own_account": is_own_account,
        "message": "This Clash of Clans account is already linked to a user."
    }


@router.put("/users/coc-accounts/order", name="Reorder linked Clash of Clans accounts")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def reorder_coc_accounts(request: dict, user_id: str = None,
                               _credentials: HTTPAuthorizationCredentials = Depends(security), *, mongo: MongoClient):
    """Reorder Clash of Clans accounts based on user preferences.

    Args:
        request: dict with 'ordered_tags' key containing list of player tags in desired order
        user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        dict: Success message

    Raises:
        HTTPException: 400 if ordered_tags is empty or contains invalid tags
    """

    new_order = request.get("ordered_tags", [])
    if not new_order:
        raise HTTPException(status_code=400, detail="Ordered tags list cannot be empty")

    # Validate all tags belong to user using only the tags (no need to fetch full docs)
    user_tags_count = await mongo.coc_accounts.count_documents({
        "user_id": user_id,
        "player_tag": {"$in": new_order}
    })

    if user_tags_count != len(new_order):
        raise HTTPException(status_code=400, detail="Invalid account tags provided")

    # Update the order index for each account using bulk operations
    updates = [
        UpdateOne(
            {"user_id": user_id, "player_tag": tag},
            {"$set": {"order_index": index}}
        )
        for index, tag in enumerate(new_order)
    ]

    await mongo.coc_accounts.bulk_write(updates, ordered=False)

    return {"message": "Accounts reordered successfully"}


@router.post("/users/coc-accounts/{player_tag}/verify", name="Verify ownership of an existing linked Clash of Clans account")
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def verify_coc_account(player_tag: str, request: dict, user_id: str = None,
                             _credentials: HTTPAuthorizationCredentials = Depends(security), *, mongo: MongoClient):
    """Verify ownership of an existing linked Clash of Clans account using API token.

    Args:
        player_tag: Clash of Clans player tag (path parameter)
        request: dict containing player_token
        user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        dict: {'message': str, 'verified': True}

    Raises:
        HTTPException: 400 if tag format is invalid or token is missing
        HTTPException: 403 if player token is invalid
        HTTPException: 404 if account not found or not linked to user
    """
    # Normalize the tag (converts lowercase to uppercase and fixes format)
    player_tag = fix_tag(player_tag)
    player_token = request.get("player_token")
    validate_coc_tag(player_tag)

    if not player_token:
        raise HTTPException(status_code=400, detail="Player token is required for verification")

    # Check if the account is linked to this user
    existing_account = await mongo.coc_accounts.find_one({"user_id": user_id, "player_tag": player_tag})
    if not existing_account:
        raise HTTPException(status_code=404, detail="Clash of Clans account not found or not linked to your profile")

    # Check if already verified
    if existing_account.get("is_verified", False):
        return {"message": "Account is already verified", "verified": True}

    # Verify ownership using the token
    if not verify_coc_ownership(player_tag, player_token):
        raise HTTPException(status_code=403,
                            detail="Invalid player token. Check your Clash of Clans account settings and try again.")

    # Update verification status in database
    await mongo.coc_accounts.update_one(
        {"user_id": user_id, "player_tag": player_tag},
        {"$set": {"is_verified": True, "verified_at": pend.now(tz=pend.UTC)}}
    )

    return {"message": "Account verified successfully", "verified": True}
