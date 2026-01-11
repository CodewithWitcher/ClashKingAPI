import hikari
import jwt
import logging
import pendulum as pend
import hashlib
import secrets
from fastapi import HTTPException
from typing import Dict, Any, Optional, Union
import base64
from pydantic import EmailStr
from utils.config import Config
from utils.database import MongoClient

logger = logging.getLogger(__name__)
config = Config()

# Constants
DEFAULT_AVATAR_URL = "https://clashkingfiles.b-cdn.net/stickers/Troop_HV_Goblin.png"
INTERNAL_SERVER_ERROR = "Internal server error"
USER_NOT_FOUND = "User not found"

############################
# Utility functions
############################

# Encrypt data using Fernet
def encrypt_data(data: str) -> str:
    """Encrypt data using Fernet."""
    encrypted = config.cipher.encrypt(data.encode("utf-8"))  # Returns bytes
    return base64.urlsafe_b64encode(encrypted).decode("utf-8")  # Convert to str for storage

# Decrypt data using Fernet
def decrypt_data(data: str) -> str:
    """Decrypt data using Fernet."""
    try:
        data_bytes = base64.urlsafe_b64decode(data.encode("utf-8"))  # Convert back to bytes
        decrypted = config.cipher.decrypt(data_bytes).decode("utf-8")  # Decrypt and decode
        return decrypted
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt data: {str(e)}")

# Hash email for lookup purposes (one-way, deterministic)
def hash_email(email: Union[str, EmailStr]) -> str:
    """Create a deterministic hash of email for database lookups."""
    email_normalized = str(email).lower().strip()
    return hashlib.sha256(f"{email_normalized}{config.secret_key}".encode()).hexdigest()

# Encrypt and prepare email data for storage
def prepare_email_for_storage(email: Union[str, EmailStr]) -> dict:
    """Encrypt email and create lookup hash."""
    email_normalized = str(email).lower().strip()
    return {
        "email_encrypted": encrypt_data(email_normalized),
        "email_hash": hash_email(email_normalized)
    }

def add_email_to_data(data_dict: dict, user_email: Optional[str]) -> None:
    """Add email data to dictionary if email is provided.

    Args:
        data_dict: Dictionary to update with email data
        user_email: User email (optional)
    """
    if user_email:
        email_data = prepare_email_for_storage(user_email)
        data_dict.update(email_data)


def generate_jwt(user_id: str, device_id: str) -> str:
    """Generate a JWT token for the user."""
    payload = {
        "sub": user_id,
        "device": device_id,
        "iat": pend.now(tz=pend.UTC).int_timestamp,
        "exp": pend.now(tz=pend.UTC).add(hours=24).int_timestamp
    }
    return jwt.encode(payload, config.secret_key, algorithm=config.algorithm)


def decode_jwt(token: str) -> dict:
    """Decode the JWT access token and return the payload."""
    try:
        decoded_token = jwt.decode(token, config.secret_key, algorithms=[config.algorithm])
        return decoded_token
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Expired token. Please refresh.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token. Please login again.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error decoding token: {str(e)}")

def decode_refresh_token(token: str) -> dict:
    """Decode the JWT refresh token and return the payload."""
    try:
        decoded_token = jwt.decode(token, config.refresh_secret, algorithms=[config.algorithm])
        return decoded_token
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Expired refresh token. Please login again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token. Please login again.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error decoding refresh token: {str(e)}")

# Verify a plaintext password against a hashed one
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return config.pwd_context.verify(plain_password, hashed_password)


# Generate a long-lived refresh token (90 days)
def generate_clashking_access_token(user_id: str, device_id: str):
    payload = {
        "sub": user_id,
        "device": device_id,
        "exp": pend.now(tz=pend.UTC).add(days=90).int_timestamp
    }
    return jwt.encode(payload, config.refresh_secret, algorithm=config.algorithm)

def hash_password(password: str) -> str:
    return config.pwd_context.hash(password)

async def refresh_discord_access_token(
        encrypted_refresh_token: str,
        rest: hikari.RESTApp
) -> hikari.OAuth2AuthorizationToken:
    """
    Refreshes the Discord access token using the stored refresh token.
    """
    try:
        refresh_token = decrypt_data(encrypted_refresh_token)
    except HTTPException as e:
        # Token decryption failed - likely corrupted or wrong format
        logger.error(f"Failed to decrypt Discord refresh token: {e.detail}")
        raise HTTPException(
            status_code=401,
            detail="Stored Discord token is invalid. Please re-authenticate with Discord."
        )
    except Exception as e:
        logger.error(f"Unexpected error decrypting Discord refresh token: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Stored Discord token is invalid. Please re-authenticate with Discord."
        )

    try:
        async with rest.acquire() as client:
            auth = await client.refresh_access_token(
                client=config.discord_client_id,
                client_secret=config.discord_client_secret,
                refresh_token=refresh_token,
            )
        return auth
    except hikari.UnauthorizedError:
        logger.warning("Discord refresh token was rejected by Discord API (401)")
        raise HTTPException(
            status_code=401,
            detail="Discord refresh token expired. Please re-authenticate with Discord."
        )
    except hikari.BadRequestError as e:
        # Handle 400 errors (invalid_grant, etc.)
        logger.warning(f"Discord refresh token invalid (400): {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Discord refresh token invalid or expired. Please re-authenticate with Discord."
        )
    except Exception as e:
        logger.error(f"Error refreshing Discord token: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error refreshing Discord token: {str(e)}")

async def get_valid_discord_access_token(
        user_id: str,
        rest: hikari.RESTApp,
        mongo: MongoClient,
        device_id: Optional[str] = None,
) -> str:
    """
    Verifies if the Discord access token is still valid and refreshes it if needed.
    """
    try:
        query = {"user_id": user_id}
        if device_id:
            query["device_id"] = device_id
        discord_token = await mongo.auth_discord_tokens.find_one(query)

        if not discord_token:
            raise HTTPException(status_code=401, detail="Missing Discord refresh token")

        # Decrypt the access and refresh tokens
        encrypted_access_token = discord_token.get("discord_access_token")
        encrypted_refresh_token = discord_token.get("discord_refresh_token")

        if not encrypted_access_token or not encrypted_refresh_token:
            raise HTTPException(status_code=401, detail="Invalid stored tokens")

        access_token = decrypt_data(encrypted_access_token)

        # Check if the access token is still valid (add a buffer of 60s to prevent expiration race condition)
        if pend.now(tz=pend.UTC).int_timestamp < discord_token["expires_at"].timestamp() - 60:
            return access_token

        # Refresh the access token (pass encrypted token)
        auth = await refresh_discord_access_token(encrypted_refresh_token, rest)

        # Encrypt and store the new access token with updated expiration time
        new_encrypted_access = encrypt_data(auth.access_token)
        new_expires_in = int(auth.expires_in.total_seconds())  # Default: 7 days (7 * 24 * 60 * 60)

        await mongo.auth_discord_tokens.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "discord_access_token": new_encrypted_access,
                    "expires_at": pend.now(tz=pend.UTC).add(seconds=new_expires_in)
                }
            }
        )

        return auth.access_token

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting valid Discord access token: {str(e)}")


def generate_refresh_token(user_id: str) -> str:
    """Generate a refresh token for the user."""
    payload = {
        "sub": user_id,
        "iat": pend.now(tz=pend.UTC).int_timestamp,
        "exp": pend.now(tz=pend.UTC).add(days=30).int_timestamp
    }
    return jwt.encode(payload, config.refresh_secret, algorithm=config.algorithm)


def generate_email_verification_token() -> str:
    """Generate a secure random token for email verification."""
    return secrets.token_urlsafe(32)


def generate_verification_code() -> str:
    """Generate a 6-digit verification code."""
    return f"{secrets.randbelow(900000) + 100000:06d}"

def generate_reset_token() -> str:
    """Generate a secure password reset token."""
    return secrets.token_urlsafe(32)

def safe_email_log(email: Union[str, EmailStr]) -> str:
    """Safely format email for logging to prevent crashes.

    Args:
        email: Email address to format

    Returns:
        str: Safely formatted email for logging
    """
    if not email:
        return "unknown"
    email_str = str(email)
    if len(email_str) < 3:
        return "short"
    return email_str[:min(10, len(email_str))] + "***"


def validate_expires_at(expires_at: Any) -> pend.DateTime:
    """Validate and normalize expires_at timestamp to timezone-aware pendulum DateTime.

    Args:
        expires_at: Timestamp to validate (can be str, datetime, or pendulum DateTime)

    Returns:
        pend.DateTime: Timezone-aware pendulum DateTime

    Raises:
        ValueError: If timestamp format is invalid
    """
    # Handle string datetime format
    if isinstance(expires_at, str):
        try:
            expires_at = pend.parse(expires_at)
        except Exception as e:
            raise ValueError(f"Invalid datetime format: {e}")

    # Ensure timezone info exists
    if hasattr(expires_at, 'tzinfo') and expires_at.tzinfo is None:
        # expires_at is naive, make it UTC aware
        expires_at = pend.instance(expires_at, tz='UTC')
    elif not hasattr(expires_at, 'tzinfo'):
        # Handle case where expires_at might be a different type
        expires_at = pend.parse(str(expires_at)).in_timezone('UTC')

    return expires_at


async def store_refresh_token(user_id: str, refresh_token: str, mongo: MongoClient) -> None:
    """Store or update refresh token for a user.

    Args:
        user_id: User ID
        refresh_token: JWT refresh token to store
        mongo: MongoDB client instance

    Raises:
        HTTPException: 500 if database operation fails
    """
    try:
        await mongo.auth_refresh_tokens.update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "refresh_token": refresh_token,
                    "expires_at": pend.now(tz=pend.UTC).add(days=30)
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Failed to store refresh token for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to store authentication tokens")


def create_auth_response(
    user_id: str,
    username: str,
    device_id: str,
    avatar_url: str = DEFAULT_AVATAR_URL
) -> Dict[str, Any]:
    """Create a standard authentication response with tokens and user info.

    Args:
        user_id: User ID
        username: User's display name
        device_id: Device ID for JWT
        avatar_url: User's avatar URL (default: goblin)

    Returns:
        Dict with access_token, refresh_token, and user info ready for AuthResponse model
    """
    access_token = generate_jwt(str(user_id), device_id)
    refresh_token = generate_refresh_token(str(user_id))

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "user_id": str(user_id),
            "username": username,
            "avatar_url": avatar_url
        }
    }


def validate_verification_record(
    pending_verification: Dict[str, Any],
    email: str
) -> Dict[str, Any]:
    """Validate verification record has all required fields.

    Args:
        pending_verification: Verification record from database
        email: Email address for logging

    Returns:
        Dict: user_data from verification record

    Raises:
        HTTPException: 500 if validation fails
    """
    import sentry_sdk
    from fastapi import HTTPException

    # Get the pending user data
    user_data = pending_verification.get("user_data")
    if not user_data:
        sentry_sdk.capture_message(
            f"Missing user_data in verification record for email: {safe_email_log(email)}",
            level="error"
        )
        raise HTTPException(status_code=500, detail="Invalid verification record")

    # Validate required fields in user_data
    required_fields = ["email_encrypted", "email_hash", "username", "password", "device_id"]
    missing_fields = [field for field in required_fields if not user_data.get(field)]
    if missing_fields:
        sentry_sdk.capture_message(
            f"Missing user_data fields: {missing_fields} for email: {safe_email_log(email)}",
            level="error"
        )
        raise HTTPException(status_code=500, detail="Invalid verification record")

    return user_data


async def handle_existing_user_email_verification(
    existing_user: Dict[str, Any],
    user_data: Dict[str, Any],
    mongo: MongoClient
) -> str:
    """Handle email verification for existing Discord user.

    Args:
        existing_user: Existing user record
        user_data: User data from verification
        mongo: MongoDB client

    Returns:
        str: User ID

    Raises:
        HTTPException: 400 if email already verified for email auth
    """
    import sentry_sdk
    from fastapi import HTTPException

    # Check if it's a Discord user trying to add email auth
    if "discord" in existing_user.get("auth_methods", []) and "email" not in existing_user.get("auth_methods", []):
        # Update existing Discord user with email auth
        auth_methods = set(existing_user.get("auth_methods", []))
        auth_methods.add("email")

        await mongo.users.update_one(
            {"user_id": existing_user["user_id"]},
            {"$set": {
                "auth_methods": list(auth_methods),
                "username": user_data["username"],
                "password": user_data["password"],
                "email_encrypted": user_data["email_encrypted"],
                "email_hash": user_data["email_hash"]
            }}
        )

        user_id = existing_user["user_id"]
        sentry_sdk.capture_message(f"Email auth added to existing Discord user: {user_id}", level="info")
        return str(user_id)
    else:
        # Email already registered for email auth
        raise HTTPException(
            status_code=400,
            detail="This email has already been verified. Please try logging in instead."
        )


async def create_new_user_from_verification(
    user_data: Dict[str, Any],
    mongo: MongoClient
) -> str:
    """Create a new user from email verification data.

    Args:
        user_data: User data from verification
        mongo: MongoDB client

    Returns:
        str: User ID

    Raises:
        HTTPException: 500 if user creation fails
    """
    import sentry_sdk
    from fastapi import HTTPException
    from utils.utils import generate_custom_id

    user_id_raw = generate_custom_id()
    user_id = str(user_id_raw)

    try:
        await mongo.users.insert_one({
            "user_id": user_id,
            "email_encrypted": user_data["email_encrypted"],
            "email_hash": user_data["email_hash"],
            "username": user_data["username"],
            "password": user_data["password"],
            "auth_methods": ["email"],
            "created_at": pend.now(tz=pend.UTC)
        })
        return user_id
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"endpoint": "/auth/verify-email-code", "user_id": user_id})
        raise HTTPException(status_code=500, detail="Failed to create account. Please try again.")


async def create_password_reset_token(
    user: Dict[str, Any],
    email_hash: str,
    mongo: MongoClient
) -> Dict[str, Any]:
    """Create and store password reset token.

    Args:
        user: User record
        email_hash: Hashed email
        mongo: MongoDB client

    Returns:
        Dict: Reset record with _id and reset_code

    Raises:
        HTTPException: 500 if token creation fails
    """
    import sentry_sdk
    from fastapi import HTTPException

    # Check for existing unused reset token
    current_time = pend.now(tz=pend.UTC)
    existing_reset = await mongo.auth_password_reset_tokens.find_one({
        "email_hash": email_hash,
        "used": False,
        "expires_at": {"$gt": current_time}
    })

    if existing_reset:
        # Clean up old token
        await mongo.auth_password_reset_tokens.delete_one({"_id": existing_reset["_id"]})

    # Generate 6-digit password reset code
    reset_code = generate_verification_code()

    reset_record = {
        "user_id": user["user_id"],
        "email_hash": email_hash,
        "reset_code": reset_code,
        "expires_at": pend.now(tz=pend.UTC).add(hours=1),
        "created_at": pend.now(tz=pend.UTC),
        "used": False
    }

    try:
        result = await mongo.auth_password_reset_tokens.insert_one(reset_record)
        reset_record["_id"] = result.inserted_id
        return reset_record
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"function": "password_reset_token_insert", "user_id": user["user_id"]})
        raise HTTPException(status_code=500, detail="Failed to create password reset request")


async def send_password_reset_with_cleanup(
    user: Dict[str, Any],
    reset_record: Dict[str, Any],
    reset_code: str,
    mongo: MongoClient
) -> None:
    """Decrypt email and send password reset, with cleanup on failure.

    Args:
        user: User record
        reset_record: Reset token record (with _id for cleanup)
        reset_code: Reset code to send
        mongo: MongoDB client

    Raises:
        HTTPException: 500 if email decryption or sending fails
    """
    import sentry_sdk
    from fastapi import HTTPException
    from utils.email_service import send_password_reset_email_with_code

    # Decrypt email
    try:
        decrypted_email = decrypt_data(user["email_encrypted"])
        if not decrypted_email:
            raise ValueError("Decrypted email is empty")
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"function": "decrypt_email_for_password_reset", "user_id": user["user_id"]})
        await mongo.auth_password_reset_tokens.delete_one({"_id": reset_record["_id"]})
        raise HTTPException(status_code=500, detail="Failed to process password reset request")

    # Send email
    try:
        username = user.get("username", "User")
        await send_password_reset_email_with_code(decrypted_email, username, reset_code)
    except Exception as e:
        await mongo.auth_password_reset_tokens.delete_one({"_id": reset_record["_id"]})
        sentry_sdk.capture_exception(e, tags={"endpoint": "/auth/forgot-password", "decrypted_email": safe_email_log(decrypted_email)})
        raise HTTPException(status_code=500, detail="Failed to send password reset email")


############################
# Helper functions for auth endpoints
############################

async def exchange_discord_code_for_token(
    code: str,
    code_verifier: str,
    redirect_uri: str,
    rest: hikari.RESTApp
) -> hikari.OAuth2AuthorizationToken:
    """Exchange Discord OAuth code for access token.

    Args:
        code: OAuth authorization code
        code_verifier: PKCE code verifier
        redirect_uri: OAuth redirect URI
        rest: Hikari REST client

    Returns:
        OAuth2 authorization token

    Raises:
        HTTPException: If token exchange fails
    """
    import sentry_sdk
    from fastapi import HTTPException

    async with rest.acquire(None) as client:
        try:
            logger.debug(f"Exchanging Discord code for token with redirect_uri={redirect_uri}")
            auth = await client.authorize_access_token(
                client=config.discord_client_id,
                client_secret=config.discord_client_secret,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier
            )
            logger.debug(f"Got Discord auth token, type={type(auth).__name__}, scopes={getattr(auth, 'scopes', 'N/A')}")
            return auth
        except hikari.errors.UnauthorizedError:
            sentry_sdk.capture_message("Incorrect client or client secret passed", level="error")
            raise HTTPException(
                status_code=500,
                detail="Discord token error: Incorrect client or client secret passed"
            )
        except hikari.errors.BadRequestError:
            sentry_sdk.capture_message("Invalid redirect uri or code passed", level="error")
            raise HTTPException(
                status_code=500,
                detail="Discord token error: Invalid redirect uri or code passed"
            )


async def test_discord_token(access_token: str, rest: hikari.RESTApp) -> None:
    """Test Discord token by fetching guilds.

    Args:
        access_token: Discord access token
        rest: Hikari REST client
    """
    logger.debug("Testing Discord token by fetching guilds...")
    async with rest.acquire(token=access_token, token_type=hikari.TokenType.BEARER) as client:
        guilds = await client.fetch_my_guilds()
        logger.debug(f"Test fetch returned {len(guilds)} guilds")
        if guilds:
            logger.debug(f"First guild: {guilds[0].name}, permissions={getattr(guilds[0], 'permissions', 'N/A')}")


async def store_discord_tokens(
    user_id: int,
    device_id: str,
    device_name: str,
    auth: hikari.OAuth2AuthorizationToken,
    mongo: MongoClient
) -> None:
    """Store encrypted Discord tokens in database.

    Args:
        user_id: User ID
        device_id: Device identifier
        device_name: Device name
        auth: Discord OAuth token
        mongo: MongoDB client
    """
    if not auth.refresh_token:
        raise HTTPException(status_code=500, detail="Discord did not provide a refresh token")

    encrypted_access = encrypt_data(auth.access_token)
    encrypted_refresh = encrypt_data(auth.refresh_token)

    await mongo.auth_discord_tokens.update_one(
        {"user_id": user_id, "device_id": device_id, "device_name": device_name},
        {
            "$set": {
                "discord_access_token": encrypted_access,
                "discord_refresh_token": encrypted_refresh,
                "expires_at": pend.now(tz=pend.UTC).add(seconds=int(auth.expires_in.total_seconds()))
            }
        },
        upsert=True
    )


async def upsert_discord_user(
    discord_user: hikari.User,
    mongo: MongoClient
) -> int:
    """Create or update user from Discord account.

    Args:
        discord_user: Discord user object
        mongo: MongoDB client

    Returns:
        User ID
    """
    email_conditions = [{"user_id": discord_user.id}]
    user_email = getattr(discord_user, 'email', None)
    if user_email:
        email_hash = hash_email(user_email)
        email_conditions.append({"email_hash": email_hash})

    existing_user = await mongo.users.find_one({"$or": email_conditions})

    if existing_user:
        user_id = existing_user["user_id"]
        auth_methods = set(existing_user.get("auth_methods", []))
        auth_methods.add("discord")

        update_data = {
            "auth_methods": list(auth_methods),
            "username": discord_user.username
        }

        add_email_to_data(update_data, user_email)

        await mongo.users.update_one(
            {"user_id": user_id},
            {"$set": update_data}
        )
    else:
        user_id = discord_user.id
        insert_data = {
            "user_id": user_id,
            "auth_methods": ["discord"],
            "username": discord_user.username,
            "created_at": pend.now(tz=pend.UTC)
        }

        add_email_to_data(insert_data, user_email)

        await mongo.users.insert_one(insert_data)

    return user_id


async def find_user_by_id(user_id: str, mongo: MongoClient) -> Optional[dict]:
    """
    Find user by ID, trying both string and int formats.

    Args:
        user_id: User ID (string or int)
        mongo: MongoDB client

    Returns:
        User document or None
    """
    user = await mongo.users.find_one({"user_id": user_id})
    if not user:
        try:
            user_id_int = int(user_id)
            user = await mongo.users.find_one({"user_id": user_id_int})
        except (ValueError, TypeError):
            pass
    return user


async def get_user_info_from_discord(
    user_id: int,
    rest: hikari.RESTApp,
    mongo: MongoClient
) -> tuple[Optional[str], Optional[str]]:
    """Fetch username and avatar from Discord API.

    Args:
        user_id: Discord user ID
        rest: Hikari REST client
        mongo: MongoDB client

    Returns:
        Tuple of (username, avatar_url) or (None, None) if fails
    """
    import sentry_sdk

    try:
        discord_access = await get_valid_discord_access_token(str(user_id), rest, mongo)
        async with rest.acquire(token=discord_access, token_type=hikari.TokenType.BEARER) as client:
            try:
                user = await client.fetch_my_user()
                username = user.global_name or user.username
                avatar_url = str(user.make_avatar_url()) if user.avatar_hash else None
                return username, avatar_url
            except hikari.UnauthorizedError:
                sentry_sdk.capture_message("Discord API error: Invalid Token", level="warning")
                return None, None
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"function": "get_user_info_from_discord", "user_id": user_id})
        return None, None


async def find_verification_with_code(
    email_hash: str,
    code: str,
    mongo: MongoClient
) -> Optional[dict]:
    """Find pending verification by email hash and code.

    Handles backwards compatibility with old token-based records.

    Args:
        email_hash: Hashed email
        code: Verification code
        mongo: MongoDB client

    Returns:
        Verification document or None

    Raises:
        HTTPException: If old record format is found
    """
    from fastapi import HTTPException

    pending = await mongo.auth_email_verifications.find_one({
        "email_hash": email_hash,
        "verification_code": code
    })

    if not pending:
        # Check for old records with verification_token field (backwards compatibility)
        old_record = await mongo.auth_email_verifications.find_one({"email_hash": email_hash})
        if old_record and old_record.get("verification_token"):
            raise HTTPException(status_code=401, detail="Please request a new verification code")
        return None

    return pending