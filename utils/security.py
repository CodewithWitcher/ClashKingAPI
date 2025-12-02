import jwt
import os
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from functools import wraps
import hikari
from utils.config import Config
import pendulum as pend
import inspect

config = Config()


def _set_user_id_in_kwargs(func, kwargs, user_id):
    """Helper to set user_id in kwargs if function expects it."""
    sig = inspect.signature(func)
    if "user_id" in sig.parameters or "_user_id" in sig.parameters:
        user_id_key = "user_id" if "user_id" in sig.parameters else "_user_id"
        kwargs[user_id_key] = user_id


async def _handle_local_dev_mode(func, args, kwargs):
    """Handle local development mode authentication bypass."""
    _set_user_id_in_kwargs(func, kwargs, os.getenv("DEV_USER_ID"))
    return await func(*args, **kwargs)


def _extract_token(credentials):
    """Extract token from authorization credentials."""
    if not credentials:
        return None
    auth_header = credentials.credentials
    if not auth_header:
        return None
    return auth_header.split(" ")[1] if " " in auth_header else auth_header


async def _try_static_token(token, func, args, kwargs):
    """Check if token matches static expected token."""
    expected_token = os.getenv("AUTH_TOKEN")
    if token == expected_token:
        return await func(*args, **kwargs)
    return None


async def _try_db_token(token, mongo, func, args, kwargs):
    """Check if token exists in database (rosters, giveaways)."""
    token_doc = await mongo.tokens_db.find_one({"token": token})
    if not token_doc:
        return None

    if token_doc["expires_at"] < pend.now():
        raise HTTPException(status_code=401, detail="Access token expired")

    # Set user_id to server-based ID
    _set_user_id_in_kwargs(func, kwargs, f"server:{token_doc['server_id']}")

    # Set server_id if function expects it
    sig = inspect.signature(func)
    if "server_id" in sig.parameters and "server_id" not in kwargs:
        kwargs["server_id"] = token_doc["server_id"]

    return await func(*args, **kwargs)


async def _find_user_by_id(mongo, user_id):
    """Find user in database, trying both string and int versions."""
    user = await mongo.users.find_one({"user_id": user_id})
    if not user:
        try:
            user_id_int = int(user_id)
            user = await mongo.users.find_one({"user_id": user_id_int})
        except (ValueError, TypeError):
            pass
    return user


async def _verify_server_membership(rest, server_id, user_id):
    """Verify that user is a member of the specified server."""
    if not rest:
        return
    async with rest.acquire(token=config.bot_token, token_type=hikari.TokenType.BOT) as client:
        try:
            await client.fetch_member(server_id, user_id)
        except hikari.errors.NotFoundError:
            raise HTTPException(status_code=401, detail="This user is not a member of this guild")


async def _try_jwt_token(token, mongo, rest, func, args, kwargs):
    """Decode and validate JWT token."""
    try:
        decoded_token = jwt.decode(token, config.secret_key, algorithms=config.algorithm)
        user_id = decoded_token["sub"]
        device_id = decoded_token.get("device")
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authentication token: " + str(e))

    # Find user in database (only if mongo is available)
    if mongo:
        user = await _find_user_by_id(mongo, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
    else:
        # If no mongo connection, we cannot verify user existence
        raise HTTPException(status_code=500, detail="An error occurred while connecting to the database")

    # Verify server membership if needed
    if "server_id" in kwargs:
        await _verify_server_membership(rest, kwargs["server_id"], user_id)

    # Set user_id and device_id in kwargs
    _set_user_id_in_kwargs(func, kwargs, user_id)
    sig = inspect.signature(func)
    if "device_id" in sig.parameters and device_id:
        kwargs["device_id"] = device_id

    return await func(*args, **kwargs)


def check_authentication(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        mongo = kwargs.get('mongo') or kwargs.get('_mongo')
        rest = kwargs.get('rest') or kwargs.get('_rest')

        credentials: HTTPAuthorizationCredentials = kwargs.get("credentials") or kwargs.get("_credentials")

        # Handle missing credentials
        if not credentials:
            if config.is_local:
                return await _handle_local_dev_mode(func, args, kwargs)
            raise HTTPException(status_code=403, detail="Authentication token missing")

        # Extract token
        token = _extract_token(credentials)
        if not token:
            raise HTTPException(status_code=403, detail="Authentication token missing")

        # Try authentication methods in order
        # Option 1: Static token
        result = await _try_static_token(token, func, args, kwargs)
        if result is not None:
            return result

        # Option 2: Database token (rosters, giveaways) - only if mongo is available
        if mongo:
            result = await _try_db_token(token, mongo, func, args, kwargs)
            if result is not None:
                return result

        # Option 3: JWT token
        return await _try_jwt_token(token, mongo, rest, func, args, kwargs)

    return wrapper