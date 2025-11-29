import re
import requests
from fastapi import HTTPException
from pymongo import UpdateOne
from utils.database import MongoClient

def fetch_coc_account_data(coc_tag: str) -> dict:
    """Retrieve Clash of Clans account details using the API.

    Args:
        coc_tag: Clash of Clans player tag (e.g., "#ABC123")

    Returns:
        dict: Account data including 'tag', 'name', 'townHallLevel', etc.

    Raises:
        HTTPException: 404 if account does not exist
    """
    coc_tag = coc_tag.replace("#", "%23")
    url = f"https://proxy.clashk.ing/v1/players/{coc_tag}"
    response = requests.get(url)

    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Clash of Clans account does not exist")

    return response.json()  # Return the account data

def verify_coc_ownership(coc_tag: str, player_token: str) -> bool:
    """Verify if the provided player token matches the given Clash of Clans account.

    Args:
        coc_tag: Clash of Clans player tag (e.g., "#ABC123")
        player_token: API token from in-game settings

    Returns:
        bool: True if token is valid and matches the account, False otherwise
    """
    coc_tag = coc_tag.replace("#", "%23")
    url = f"https://proxy.clashk.ing/v1/players/{coc_tag}/verifytoken"
    response = requests.post(url, json={"token": player_token})

    if response.status_code != 200:
        return False  # API error, consider it invalid

    try:
        data = response.json()
        return data.get("status") == "ok"
    except ValueError:
        return False  # If JSON parsing fails, assume invalid


async def is_coc_account_linked(coc_tag: str, mongo: MongoClient) -> bool:
    """Check if the Clash of Clans account is already linked to another user.

    Args:
        coc_tag: Clash of Clans player tag (e.g., "#ABC123")
        mongo: MongoDB client instance

    Returns:
        bool: True if account is already linked, False otherwise
    """
    existing_account = await mongo.coc_accounts.find_one({"player_tag": coc_tag})
    return existing_account is not None


def validate_coc_tag(player_tag: str) -> None:
    """Validate Clash of Clans tag format.

    Args:
        player_tag: Clash of Clans player tag (e.g., "#ABC123")

    Returns:
        None

    Raises:
        HTTPException: 400 if tag format is invalid (must be #[A-Z0-9]{5,12})
    """
    if not re.match(r"^#[A-Z0-9]{5,12}$", player_tag):
        raise HTTPException(status_code=400, detail="Invalid Clash of Clans tag format")


async def reorder_user_accounts(user_id: str, mongo: MongoClient) -> None:
    """Reorder all accounts for a user sequentially (0, 1, 2, ...) using bulk operations.

    Args:
        user_id: Discord user ID or server identifier
        mongo: MongoDB client instance

    Returns:
        None
    """
    remaining_accounts = await mongo.coc_accounts.find({"user_id": user_id}).sort("order_index", 1).to_list(length=None)

    if not remaining_accounts:
        return

    updates = [
        UpdateOne(
            {"_id": account["_id"]},
            {"$set": {"order_index": index}}
        )
        for index, account in enumerate(remaining_accounts)
    ]

    await mongo.coc_accounts.bulk_write(updates, ordered=False)

