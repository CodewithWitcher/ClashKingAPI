from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.security import check_authentication
from utils.database import MongoClient
from .clan_models import ClanSettingsUpdate, ClanSettingsResponse
import linkd

security = HTTPBearer()
router = APIRouter(prefix="/v2/server", tags=["Clan Settings"], include_in_schema=True)


@router.patch("/{server_id}/clan/{clan_tag}/settings",
              name="Update clan settings",
              response_model=ClanSettingsResponse)
@linkd.ext.fastapi.inject
@check_authentication
async def update_clan_settings(
    server_id: int,
    clan_tag: str,
    settings: ClanSettingsUpdate,
    user_id: str = None,
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo_client: MongoClient
) -> ClanSettingsResponse:
    """
    Update clan settings. Only provided fields will be updated.

    This endpoint handles all clan-level settings including:
    - Basic settings (roles, channel, category, abbreviation, greeting)
    - War settings (countdown channels, ban alerts)
    - Member count warnings (thresholds, channel, role)
    - Log button configurations (profile, strike, ban buttons)
    """
    # Verify clan exists for this server
    existing = await mongo_client.clan_db.find_one({
        "$and": [{"tag": clan_tag}, {"server": server_id}]
    })
    if not existing:
        raise HTTPException(status_code=404, detail="Clan not found on this server")

    # Build update document with only provided fields
    update_doc = {}

    # Direct field mappings (using DB field names)
    direct_fields = [
        "generalRole", "leaderRole", "clanChannel", "category",
        "abbreviation", "greeting", "auto_greet_option", "leadership_eval",
        "warCountdown", "warTimerCountdown", "ban_alert_channel"
    ]

    for field in direct_fields:
        value = getattr(settings, field, None)
        if value is not None:
            update_doc[field] = value

    # Handle nested member_count_warning
    if settings.member_count_warning is not None:
        if settings.member_count_warning.channel is not None:
            update_doc["member_count_warning.channel"] = settings.member_count_warning.channel
        if settings.member_count_warning.above is not None:
            update_doc["member_count_warning.above"] = settings.member_count_warning.above
        if settings.member_count_warning.below is not None:
            update_doc["member_count_warning.below"] = settings.member_count_warning.below
        if settings.member_count_warning.role is not None:
            update_doc["member_count_warning.role"] = settings.member_count_warning.role

    # Handle log button settings
    if settings.join_log_profile_button is not None:
        update_doc["logs.join_log.profile_button"] = settings.join_log_profile_button
    if settings.leave_log_strike_button is not None:
        update_doc["logs.leave_log.strike_button"] = settings.leave_log_strike_button
    if settings.leave_log_ban_button is not None:
        update_doc["logs.leave_log.ban_button"] = settings.leave_log_ban_button

    if not update_doc:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Update the clan
    result = await mongo_client.clan_db.update_one(
        {"$and": [{"tag": clan_tag}, {"server": server_id}]},
        {"$set": update_doc}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Clan not found")

    return ClanSettingsResponse(
        message="Clan settings updated successfully",
        server_id=server_id,
        clan_tag=clan_tag,
        updated_fields=len(update_doc)
    )
