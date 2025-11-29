import aiohttp
import linkd
import logging
import pendulum as pend
import pymongo
from coc.utils import correct_tag
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from routers.v2.rosters.models import (CreateRosterAutomationModel,
                                       CreateRosterGroupModel,
                                       CreateRosterModel,
                                       CreateRosterSignupCategoryModel,
                                       RosterCloneModel,
                                       RosterMemberBulkOperationModel,
                                       RosterUpdateModel,
                                       UpdateRosterAutomationModel,
                                       UpdateRosterGroupModel,
                                       UpdateRosterSignupCategoryModel, UpdateMemberModel)
from routers.v2.rosters.utils import (refresh_member_data,
                                      parse_th_restriction,
                                      validate_clan_for_roster,
                                      build_roster_metadata,
                                      convert_th_range_to_restriction,
                                      validate_signup_groups,
                                      get_discord_user_mappings,
                                      get_user_account_counts,
                                      process_player_additions,
                                      handle_clan_updates_for_roster,
                                      validate_automation_targets,
                                      analyze_roster_missing_members,
                                      build_refresh_query_filter,
                                      refresh_single_roster)
from utils.custom_coc import CustomClashClient
from utils.database import MongoClient
from utils.discord_api import get_discord_channels
from utils.security import check_authentication
from utils.sentry_utils import capture_endpoint_errors
from utils.utils import gen_clean_custom_id, generate_access_token

router = APIRouter(prefix='/v2', tags=['Rosters'], include_in_schema=True)
security = HTTPBearer()
logger = logging.getLogger(__name__)

# Constants
CLAN_NOT_LINKED = "Selected clan is not linked to this server"
NOTHING_TO_UPDATE = "Nothing to update"
ROSTER_NOT_FOUND = "Roster not found"
ROSTER_GROUP_NOT_FOUND = "Roster group not found"
ROSTER_SIGNUP_CATEGORY_NOT_FOUND = "Roster signup category not found"
MEMBER_NOT_FOUND_IN_ROSTER = "Member not found in roster"
AUTOMATION_RULE_NOT_FOUND = "Automation rule not found"
NO_USER = "No User"


@router.post('/roster', name='Create a roster')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def create_roster(
    server_id: int,
    roster_data: CreateRosterModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    coc_client: CustomClashClient,
):
    """
    Create a new roster for a Discord server.

    Input:
        - server_id: Discord server ID where the roster will be created
        - roster_data: Roster configuration (name, type, clan_tag, etc.)
        - credentials: JWT authentication token

    Output:
        - Success message with roster ID
        - HTTP 400 if validation fails
        - HTTP 401 if unauthorized
    """
    # Validate clan selection and fetch clan data
    clan, error = await validate_clan_for_roster(
        roster_data.roster_type,
        roster_data.clan_tag,
        server_id,
        mongo,
        coc_client
    )

    if error:
        raise HTTPException(status_code=400, detail=error)

    # Build roster document with metadata
    roster_doc = roster_data.model_dump()
    ext_data = build_roster_metadata(clan, roster_data.model_dump(), server_id)
    ext_data['custom_id'] = gen_clean_custom_id()

    if not clan and roster_data.roster_type not in ['family']:
        raise HTTPException(status_code=400, detail="Invalid roster configuration")

    roster_doc.update(ext_data)
    await mongo.rosters.insert_one(roster_doc)

    return {
        'message': 'Roster created successfully',
        'roster_id': ext_data.get('custom_id'),
    }



@router.patch('/roster/{roster_id}', name='Update a Roster')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_roster(
    server_id: int,
    roster_id: str,
    payload: RosterUpdateModel,
    group_id: str = None,  # For group updates
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    coc_client: CustomClashClient,
):
    """
    Update roster settings including name, clan assignment, and townhall restrictions.

    Input:
        - server_id: Discord server ID for authorization
        - roster_id: Unique roster identifier OR group_id for batch updates
        - payload: Updated roster settings (alias, roster_type, min_th, max_th, etc.)
        - group_id: Optional group ID for updating all rosters in a group

    Output:
        - Updated roster document OR batch update summary
        - HTTP 404 if roster/group not found
        - HTTP 400 if validation fails
    """
    body = payload.model_dump(exclude_none=True)
    if not body:
        return {'message': NOTHING_TO_UPDATE}

    # Convert min_th/max_th to th_restriction format
    if 'min_th' in body or 'max_th' in body:
        min_th = body.pop('min_th', None)
        max_th = body.pop('max_th', None)

        if min_th is not None and max_th is not None and min_th > max_th:
            raise HTTPException(status_code=400, detail='Minimum TH cannot be greater than Maximum TH')

        body['th_restriction'] = convert_th_range_to_restriction(min_th, max_th)

    # Map event_start_time to time field
    if 'event_start_time' in body:
        body['time'] = body['event_start_time']

    # Handle clan updates
    await handle_clan_updates_for_roster(body, roster_id, server_id, mongo, coc_client)

    body['updated_at'] = pend.now(tz=pend.UTC)

    if roster_id and not group_id:
        result = await mongo.rosters.find_one_and_update(
            {'custom_id': roster_id, 'server_id': server_id},
            {'$set': body},
            projection={'_id': 0},
            return_document=pymongo.ReturnDocument.AFTER,
        )

        if not result:
            raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

        return {'message': 'Roster updated', 'roster': result}

    elif group_id:
        group = await mongo.roster_groups.find_one({'group_id': group_id})
        if not group:
            raise HTTPException(status_code=404, detail='Roster group not found')

        body.pop('group_id', None)

        result = await mongo.rosters.update_many(
            {'group_id': group_id}, {'$set': body}
        )

        return {
            'message': f'Updated {result.modified_count} rosters in group',
            'updated_count': result.modified_count,
            'group_id': group_id,
        }

    else:
        raise HTTPException(
            status_code=400, detail='Must provide roster_id or group_id'
        )

@router.get('/roster/{roster_id}', name='Get a Roster')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_roster(
    server_id: int,
    roster_id: str,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Retrieve a specific roster by its ID for display in the dashboard.

    Input:
        - server_id: Discord server ID for authorization
        - roster_id: Unique roster identifier
        - credentials: JWT authentication token

    Output:
        - Complete roster document with parsed townhall restrictions
        - HTTP 404 if roster not found
        - HTTP 401 if unauthorized
    """
    # Fetch roster from database with server ownership validation
    doc = await mongo.rosters.find_one({'custom_id': roster_id, 'server_id': server_id}, {'_id': 0})
    if not doc:
        raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

    # Add parsed townhall restriction values to response for easier UI consumption
    doc['min_th'], doc['max_th'] = parse_th_restriction(doc.get('th_restriction'))

    # Map time field to event_start_time for frontend compatibility
    if doc.get('time'):
        doc['event_start_time'] = doc['time']

    return {'roster': doc}


@router.delete('/roster/{roster_id}', name='Delete a Roster')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def delete_roster(
    server_id: int,
    roster_id: str,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Permanently delete a roster and all its member data.

    Input:
        - server_id: Discord server ID for authorization
        - roster_id: Unique roster identifier to delete
        - credentials: JWT authentication token

    Output:
        - Success message confirming deletion
        - HTTP 404 if roster not found
        - HTTP 401 if unauthorized

    Note: This operation is irreversible and will remove all member data
    """
    # Attempt to delete roster with server ownership validation
    res = await mongo.rosters.delete_one({'custom_id': roster_id, 'server_id': server_id})

    # Check if any document was actually deleted
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

    return {'message': 'Roster deleted successfully'}



@router.delete(
    '/roster/{roster_id}/members/{player_tag}',
    name='Remove Member from Roster',
)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def remove_member_from_roster(
    roster_id: str,
    player_tag: str,
    _server_id: int,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Remove a specific player from a roster by their player tag.

    Input:
        - roster_id: Unique roster identifier
        - player_tag: Clash of Clans player tag to remove (with or without #)
        - server_id: Discord server ID for authorization
        - credentials: JWT authentication token

    Output:
        - Success message confirming member removal
        - HTTP 404 if roster not found
        - HTTP 401 if unauthorized

    Note: Member is removed even if player tag doesn't exist in roster
    """
    # Standardize player tag format (ensures proper # prefix)
    player_tag = correct_tag(player_tag)

    # Remove member from roster's members array using MongoDB $pull operator
    res = await mongo.rosters.update_one(
        {'custom_id': roster_id},
        {
            '$pull': {'members': {'tag': player_tag}},  # Remove member with matching tag
            '$set': {'updated_at': pend.now(tz=pend.UTC)},    # Update roster timestamp
        },
    )

    # Check if roster was found (matched_count > 0 even if no member was removed)
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

    return {'message': 'Member removed from roster'}


@router.post('/roster/refresh', name='General Refresh Rosters')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def general_refresh_rosters(
    server_id: int = Query(
        None, description='Refresh all rosters for this server'
    ),
    group_id: str = Query(
        None, description='Refresh all rosters in this group'
    ),
    roster_id: str = Query(None, description='Refresh specific roster'),
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    coc_client: CustomClashClient,
):
    """
    Refresh member data for rosters by updating player stats from Clash of Clans API.

    Input:
        - server_id: Refresh all rosters on this Discord server (optional)
        - group_id: Refresh all rosters in this group (optional)
        - roster_id: Refresh only this specific roster (optional)
        - credentials: JWT authentication token

    Output:
        - Summary of refresh operation with counts of updated/removed members
        - List of all refreshed rosters with individual results
        - HTTP 400 if no filter parameters provided
        - HTTP 401 if unauthorized

    Note: Exactly one of server_id, group_id, or roster_id must be provided
    """
    # Build query filter and validate parameters
    try:
        query_filter = build_refresh_query_filter(roster_id, group_id, server_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Find all rosters matching the filter criteria
    rosters = await mongo.rosters.find(query_filter, {'_id': 0}).to_list(length=None)
    if not rosters:
        return {
            'message': 'No rosters found to refresh',
            'refreshed_rosters': [],
        }

    # Refresh each roster and collect results
    refreshed_rosters = []
    for roster in rosters:
        result = await refresh_single_roster(roster, mongo, coc_client)
        refreshed_rosters.append(result)

    return {
        'message': f'Refreshed {len(refreshed_rosters)} roster(s)',
        'refreshed_rosters': refreshed_rosters,
    }


@router.post('/roster/{roster_id}/clone', name='Clone Roster')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def clone_roster(
    server_id: int,  # Target server ID (destination)
    roster_id: str,  # Source roster ID
    payload: RosterCloneModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    _coc_client: CustomClashClient,
):
    """
    Create a copy of an existing roster, supporting both same-server and cross-server cloning.

    Input:
        - server_id: Target Discord server ID where the clone will be created
        - roster_id: Source roster ID to clone from
        - payload: Clone configuration (new_alias, copy_members, group_id)
        - credentials: JWT authentication token

    Output:
        - Details of the newly created roster clone
        - Information about source and target servers
        - Count of members copied (if copy_members=true)
        - HTTP 404 if source roster not found
        - HTTP 401 if unauthorized

    Note: Cross-server clones cannot be added to groups automatically
    """

    # Fetch the source roster that will be cloned
    source_roster = await mongo.rosters.find_one(
        {'custom_id': roster_id}, {'_id': 0}
    )
    if not source_roster:
        raise HTTPException(status_code=404, detail='Source roster not found')

    # Determine if this is a cross-server operation (import) or same-server (clone)
    is_cross_server = source_roster['server_id'] != server_id

    # Generate appropriate alias based on operation type
    if is_cross_server:
        # Cross-server clone: use import-style naming to indicate origin
        new_alias = payload.new_alias or f'Import {roster_id}'
    else:
        # Same-server clone: use clone-style naming to indicate duplication
        new_alias = payload.new_alias or f"{source_roster['alias']} (Clone)"

    # Ensure the new alias is unique on the target server to avoid conflicts
    base_alias = new_alias
    counter = 1
    while await mongo.rosters.find_one(
        {'server_id': server_id, 'alias': new_alias}
    ):
        # Append incrementing number to make alias unique
        new_alias = f'{base_alias} ({counter})'
        counter += 1

    # Create the cloned roster document with updated metadata
    cloned_roster = source_roster.copy()
    cloned_roster.update(
        {
            'custom_id': gen_clean_custom_id(),  # Generate new unique ID
            'server_id': server_id,  # Assign to target server from URL parameter
            'alias': new_alias,  # Use the validated unique alias
            'created_at': pend.now(tz=pend.UTC),  # Set current creation time
            'updated_at': pend.now(tz=pend.UTC),  # Set current update time
            # Conditionally copy members based on user preference
            'members': source_roster.get('members', []).copy()
            if payload.copy_members
            else [],  # Empty members array if not copying
        }
    )

    # Handle group assignment (only possible for same-server clones)
    if payload.group_id and not is_cross_server:
        # Verify the target group exists on the destination server
        group = await mongo.roster_groups.find_one(
            {'group_id': payload.group_id, 'server_id': server_id}
        )
        if group:
            cloned_roster['group_id'] = payload.group_id
        # Note: If group doesn't exist, we silently ignore rather than error

    # Save the new cloned roster to the database
    await mongo.rosters.insert_one(cloned_roster)

    # Determine user-friendly operation name for response
    operation_type = 'imported' if is_cross_server else 'cloned'

    return {
        'message': f'Roster {operation_type} successfully',
        'new_roster_id': cloned_roster['custom_id'],
        'new_alias': new_alias,
        'target_server_id': server_id,
        'source_server_id': source_roster['server_id'],
        'is_cross_server': is_cross_server,
        'members_copied': len(cloned_roster['members'])
        if payload.copy_members
        else 0,
    }


@router.get('/roster/{server_id}/list', name='List Rosters')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def list_rosters(
    server_id: int,
    group_id: str = None,
    clan_tag: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Retrieve a list of rosters for a Discord server with optional filtering.

    Input:
        - server_id: Discord server ID to list rosters for
        - group_id: Optional filter to show only rosters in specific group
        - clan_tag: Optional filter to show only rosters for specific clan
        - credentials: JWT authentication token

    Output:
        - List of rosters with group information enriched
        - Applied filter parameters echoed back
        - Rosters sorted by most recently updated first
        - HTTP 401 if unauthorized

    Note: Returns empty list if no rosters match the criteria
    """

    # Build MongoDB query dynamically based on provided filters
    query = {'server_id': server_id}  # Always filter by server for security

    # Apply optional filters to narrow down results
    if group_id:
        # Filter by roster group (e.g., "CWL Season 12", "War Roster")
        query['group_id'] = group_id
    if clan_tag:
        # Filter by specific clan tag (e.g., show only rosters for one clan)
        query['clan_tag'] = clan_tag

    # Execute query with sorting by most recently updated first
    cursor = mongo.rosters.find(query, {'_id': 0}).sort('updated_at', -1)
    rosters = await cursor.to_list(length=None)

    # Enrich each roster with additional group information for display
    for roster in rosters:
        if roster.get('group_id'):
            # Fetch group details to show group name alongside group_id
            group = await mongo.roster_groups.find_one(
                {'group_id': roster['group_id']},
                {'_id': 0, 'alias': 1, 'group_id': 1},  # Only get needed fields
            )
            roster['group_info'] = group  # Add group details to roster object

    return {
        'items': rosters,
        'server_id': server_id,
        'group_id': group_id,  # Echo back applied filters for client reference
        'clan_tag': clan_tag,
    }


@router.delete('/roster/{roster_id}', name='Delete Roster')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def delete_roster_or_members(
    server_id: int,
    roster_id: str,
    members_only: bool = False,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Delete an entire roster or clear only its member list.

    Input:
        - server_id: Discord server ID for authorization
        - roster_id: Unique roster identifier
        - members_only: If true, clear members but keep roster structure
        - credentials: JWT authentication token

    Output:
        - Success message indicating operation performed
        - HTTP 404 if roster not found
        - HTTP 401 if unauthorized

    Note: When members_only=true, roster settings and structure are preserved
    """

    if members_only:
        # Clear all members but preserve roster structure and settings
        result = await mongo.rosters.update_one(
            {'custom_id': roster_id, 'server_id': server_id},
            {
                '$set': {
                    'members': [],  # Empty the members array
                    'updated_at': pend.now(tz=pend.UTC)  # Update timestamp
                }
            },
        )

        # Verify roster exists on this server
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

        return {'message': 'Roster members cleared'}

    else:
        # Perform complete roster deletion (irreversible)
        result = await mongo.rosters.delete_one({
            'custom_id': roster_id,
            'server_id': server_id  # Ensure server ownership
        })

        # Check if any roster was actually deleted
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

        return {'message': 'Roster deleted successfully'}


# ======================== ROSTER GROUPS ENDPOINTS ========================


@router.post('/roster-group', name='Create Roster Group')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def create_roster_group(
    server_id: int,
    payload: CreateRosterGroupModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Create a new roster group to organize multiple rosters together.

    Input:
        - server_id: Discord server ID where the group will be created
        - payload: Group configuration (alias, description, etc.)
        - credentials: JWT authentication token

    Output:
        - Success message with generated group_id
        - HTTP 401 if unauthorized

    Note: Groups help organize rosters for events like CWL seasons or tournaments
    """
    # Convert payload to database document format
    group_doc = payload.model_dump()

    # Add system-generated fields and metadata
    group_doc.update(
        {
            'group_id': gen_clean_custom_id(),  # Generate unique group identifier
            'server_id': server_id,  # Associate with Discord server
            'created_at': pend.now(tz=pend.UTC),  # Track creation time
            'updated_at': pend.now(tz=pend.UTC),  # Track last modification
        }
    )

    # Save the new group to the database
    await mongo.roster_groups.insert_one(group_doc)

    return {
        'message': 'Roster group created successfully',
        'group_id': group_doc['group_id'],
    }


@router.get('/roster-group/{group_id}', name='Get Roster Group')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_roster_group(
    server_id: int,
    group_id: str,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Retrieve detailed information about a specific roster group including associated rosters.

    Input:
        - server_id: Discord server ID for authorization
        - group_id: Unique group identifier
        - credentials: JWT authentication token

    Output:
        - Complete group document with list of associated rosters
        - HTTP 404 if group not found
        - HTTP 401 if unauthorized

    Note: Includes summary information for each roster in the group
    """
    # Fetch group with server ownership validation
    group = await mongo.roster_groups.find_one(
        {'group_id': group_id, 'server_id': server_id}, {'_id': 0}
    )
    if not group:
        raise HTTPException(status_code=404, detail=ROSTER_GROUP_NOT_FOUND)

    # Get all rosters that belong to this group for display
    cursor = mongo.rosters.find(
        {'group_id': group_id},
        {
            '_id': 0,
            'custom_id': 1,  # Roster identifier
            'alias': 1,      # Roster display name
            'clan_name': 1,  # Associated clan name
            'updated_at': 1, # Last modification time
        },
    )
    rosters = await cursor.to_list(length=None)

    # Add roster list to group data for comprehensive view
    group['rosters'] = rosters
    return {'group': group}


@router.patch('/roster-group/{group_id}', name='Update Roster Group')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_roster_group(
    server_id: int,
    group_id: str,
    payload: UpdateRosterGroupModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Update roster group settings such as alias, description, or other metadata.

    Input:
        - server_id: Discord server ID for authorization
        - group_id: Unique group identifier to update
        - payload: Updated group settings (only provided fields will be changed)
        - credentials: JWT authentication token

    Output:
        - Updated group document
        - HTTP 404 if group not found
        - HTTP 400 if no fields to update
        - HTTP 401 if unauthorized
    """
    # Extract only the fields that were actually provided in the request
    body = payload.model_dump(exclude_none=True)
    if not body:
        return {'message': NOTHING_TO_UPDATE}

    # Add timestamp to track when the update occurred
    body['updated_at'] = pend.now(tz=pend.UTC)

    # Update group and return the modified document
    result = await mongo.roster_groups.find_one_and_update(
        {'group_id': group_id, 'server_id': server_id},  # Filter with server validation
        {'$set': body},  # Apply the updates
        projection={'_id': 0},  # Exclude MongoDB internal ID
        return_document=pymongo.ReturnDocument.AFTER,  # Return updated document
    )

    # Check if group was found and updated
    if not result:
        raise HTTPException(status_code=404, detail=ROSTER_GROUP_NOT_FOUND)

    return {'message': 'Roster group updated', 'group': result}


@router.get('/roster-group/list', name='List Roster Groups')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def list_roster_groups(
    server_id: int,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Retrieve all roster groups for a Discord server with roster counts.

    Input:
        - server_id: Discord server ID to list groups for
        - credentials: JWT authentication token

    Output:
        - List of groups sorted by most recently updated
        - Each group includes count of associated rosters
        - HTTP 401 if unauthorized

    Note: Returns empty list if server has no roster groups
    """
    # Fetch all groups for the server, sorted by most recent activity
    cursor = mongo.roster_groups.find(
        {'server_id': server_id}, {'_id': 0}
    ).sort('updated_at', -1)
    groups = await cursor.to_list(length=None)

    # Enrich each group with roster count for better overview
    for group in groups:
        # Count how many rosters are currently assigned to this group
        roster_count = await mongo.rosters.count_documents(
            {'group_id': group['group_id']}
        )
        group['roster_count'] = roster_count  # Add count to group data

    return {'items': groups, 'server_id': server_id}


@router.delete('/roster-group/{group_id}', name='Delete Roster Group')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def delete_roster_group(
    _server_id: int,
    group_id: str,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Delete a roster group while preserving associated rosters.

    Input:
        - server_id: Discord server ID for authorization
        - group_id: Unique group identifier to delete
        - credentials: JWT authentication token

    Output:
        - Success message with count of rosters that were ungrouped
        - HTTP 404 if group not found
        - HTTP 401 if unauthorized

    Note: Rosters in the group remain but lose their group association
    """
    # Verify group exists before attempting deletion
    group = await mongo.roster_groups.find_one({'group_id': group_id})
    if not group:
        raise HTTPException(status_code=404, detail=ROSTER_GROUP_NOT_FOUND)

    # Remove group association from all rosters in this group
    result = await mongo.rosters.update_many(
        {'group_id': group_id},  # Find all rosters in this group
        {
            '$unset': {'group_id': ''},  # Remove the group_id field
            '$set': {'updated_at': pend.now(tz=pend.UTC)},  # Update timestamp
        },
    )
    affected_rosters = result.modified_count

    # Delete the group document itself
    await mongo.roster_groups.delete_one({'group_id': group_id})

    return {
        'message': 'Roster group deleted successfully',
        'affected_rosters': affected_rosters,  # How many rosters were ungrouped
    }


# ======================== ROSTER PLACEMENTS ENDPOINTS ========================


@router.post('/roster-signup-category', name='Create Roster Signup Category')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def create_roster_signup_category(
    payload: CreateRosterSignupCategoryModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Create a new signup category for organizing roster members by role or skill level.

    Input:
        - payload: Category configuration (alias, server_id, description, etc.)
        - credentials: JWT authentication token

    Output:
        - Success message confirming category creation
        - HTTP 400 if custom_id already exists or validation fails
        - HTTP 401 if unauthorized

    Note: Categories help organize members (e.g., "Leaders", "TH14+", "War Specialists")
    """

    # Ensure server_id is always an integer for database consistency
    server_id = int(payload.server_id)

    # Generate custom_id automatically if not provided by user
    if not payload.custom_id:
        # Create URL-friendly ID based on category alias
        import re
        base_id = re.sub(r'[^a-z0-9]', '-', payload.alias.lower()).strip('-')
        base_id = re.sub(r'-+', '-', base_id)  # Remove multiple consecutive dashes

        # Ensure uniqueness by checking against existing categories
        counter = 1
        custom_id = base_id
        while True:
            existing = await mongo.roster_signup_categories.find_one(
                {'server_id': server_id, 'custom_id': custom_id}
            )
            if not existing:
                break  # Found unique ID
            counter += 1
            custom_id = f"{base_id}-{counter}"  # Append number to make unique

        payload.custom_id = custom_id
    else:
        # Validate that user-provided custom_id doesn't already exist
        existing = await mongo.roster_signup_categories.find_one(
            {'server_id': server_id, 'custom_id': payload.custom_id}
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail='Signup category with this custom_id already exists',
            )

    # Convert payload to database document and add metadata
    category_doc = payload.model_dump()
    category_doc['server_id'] = server_id  # Use the validated integer
    category_doc.update(
        {
            'created_at': pend.now(tz=pend.UTC),  # Track creation time
            'updated_at': pend.now(tz=pend.UTC),  # Track last modification
        }
    )

    # Save the new category to the database
    await mongo.roster_signup_categories.insert_one(category_doc)
    return {'message': 'Roster signup category created successfully'}


@router.get(
    '/roster-signup-category/list', name='List Roster Signup Categories'
)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def list_roster_signup_categories(
    server_id: int,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Retrieve all signup categories for a Discord server.

    Input:
        - server_id: Discord server ID to list categories for
        - credentials: JWT authentication token

    Output:
        - List of categories sorted by custom_id alphabetically
        - HTTP 401 if unauthorized

    Note: Categories are used to organize members when adding them to rosters
    """
    # Fetch all signup categories for the server, sorted alphabetically
    categories = await mongo.roster_signup_categories.find(
        {'server_id': server_id}, {'_id': 0}
    ).sort({'custom_id': 1}).to_list(length=None)

    return {'items': categories, 'server_id': server_id}


@router.patch(
    '/roster-signup-category/{custom_id}', name='Update Roster Signup Category'
)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_roster_signup_category(
    server_id: int,
    custom_id: str,
    payload: UpdateRosterSignupCategoryModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Update settings for an existing roster signup category.

    Input:
        - server_id: Discord server ID for authorization
        - custom_id: Category identifier to update
        - payload: Updated category settings (only provided fields will be changed)
        - credentials: JWT authentication token

    Output:
        - Success message confirming update
        - HTTP 404 if category not found
        - HTTP 400 if no fields to update
        - HTTP 401 if unauthorized
    """
    # Extract only the fields that were actually provided in the request
    body = payload.model_dump(exclude_none=True)
    if not body:
        return {'message': NOTHING_TO_UPDATE}

    # Add timestamp to track when the update occurred
    body['updated_at'] = pend.now(tz=pend.UTC)

    # Update the category with server ownership validation
    result = await mongo.roster_signup_categories.update_one(
        {'server_id': server_id, 'custom_id': custom_id}, {'$set': body}
    )

    # Check if category was found and updated
    if result.matched_count == 0:
        raise HTTPException(
            status_code=404, detail=ROSTER_SIGNUP_CATEGORY_NOT_FOUND
        )

    return {'message': 'Roster signup category updated'}


@router.delete(
    '/roster-signup-category/{custom_id}', name='Delete Roster Signup Category'
)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def delete_roster_signup_category(
    server_id: int,
    custom_id: str,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Delete a roster signup category and remove it from all associated members.

    Input:
        - server_id: Discord server ID for authorization
        - custom_id: Category identifier to delete
        - credentials: JWT authentication token

    Output:
        - Success message confirming deletion and member updates
        - HTTP 404 if category not found
        - HTTP 401 if unauthorized

    Note: Members using this category will have their group field set to null
    """

    # First, remove this category from all roster members who are using it
    await mongo.rosters.update_many(
        {'server_id': server_id, 'members.group': custom_id},  # Find rosters with members in this category
        {
            '$set': {
                'members.$[elem].group': None,  # Clear the group assignment
                'updated_at': pend.now(tz=pend.UTC),  # Update roster timestamp
            }
        },
        array_filters=[{'elem.group': custom_id}],  # Target only members with this category
    )

    # Delete the category document itself
    result = await mongo.roster_signup_categories.delete_one(
        {'server_id': server_id, 'custom_id': custom_id}
    )

    # Check if category was found and deleted
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404, detail=ROSTER_SIGNUP_CATEGORY_NOT_FOUND
        )

    return {'message': 'Roster signup category deleted and member groups updated'}


# ======================== ROSTER MEMBER MANAGEMENT ========================


@router.post('/roster/{roster_id}/members', name='Manage Roster Members')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def manage_roster_members(
    server_id: int,
    roster_id: str,
    payload: RosterMemberBulkOperationModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    coc_client: CustomClashClient,
):
    """
    Perform bulk operations to add and/or remove members from a roster.

    Input:
        - server_id: Discord server ID for authorization
        - roster_id: Unique roster identifier to modify
        - payload: Bulk operation data (lists of player tags to add/remove)
        - credentials: JWT authentication token

    Output:
        - Summary of operation with counts and details of added/removed members
        - List of successfully added members with full player data
        - Count of errors encountered during processing
        - HTTP 404 if roster not found
        - HTTP 400 if validation fails (invalid signup groups, account limits)
        - HTTP 401 if unauthorized

    Note: Fetches fresh player data from Clash of Clans API for all additions
    """

    # Fetch target roster and validate it exists
    roster = await mongo.rosters.find_one({'custom_id': roster_id})
    if not roster:
        raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

    # Initialize tracking variables for operation results
    added_members = []
    removed_tags = []
    success_count = 0
    error_count = 0

    # Process member removals first (simpler operation)
    if payload.remove:
        # Standardize all player tags to ensure proper format
        remove_tags = [correct_tag(tag) for tag in payload.remove]

        # Remove members from roster using MongoDB pull operation
        await mongo.rosters.update_one(
            {'custom_id': roster_id},
            {
                '$pull': {'members': {'tag': {'$in': remove_tags}}},  # Remove matching members
                '$set': {'updated_at': pend.now(tz=pend.UTC)},         # Update timestamp
            },
        )
        removed_tags = remove_tags

    # Process member additions
    if payload.add:
        existing_members = roster.get('members', [])
        existing_tags = {member['tag'] for member in existing_members}

        # Validate signup groups
        await validate_signup_groups(payload.add, server_id, roster, mongo)

        # Filter out duplicates
        add_tags = [
            member.tag
            for member in payload.add
            if correct_tag(member.tag) not in existing_tags
        ]

        if add_tags:
            # Get Discord user mappings and account counts
            tag_to_user_id = await get_discord_user_mappings(add_tags, mongo)
            user_to_count = await get_user_account_counts(roster_id, mongo)

            # Process player additions
            added_members, success_count, error_count = await process_player_additions(
                coc_client,
                add_tags,
                roster,
                payload.add,
                tag_to_user_id,
                user_to_count,
            )

            # Bulk add members to roster
            if added_members:
                await mongo.rosters.update_one(
                    {'custom_id': roster_id},
                    {
                        '$push': {'members': {'$each': added_members}},
                        '$set': {'updated_at': pend.now(tz=pend.UTC)},
                    },
                )

    return {
        'message': f'Added {success_count} members, removed {len(removed_tags)} members',
        'added': added_members,
        'removed': removed_tags,
        'success_count': success_count,
        'error_count': error_count,
    }


@router.patch('/roster/{roster_id}/members/{member_tag}', name='Update Individual Member')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_roster_member(
    server_id: int,
    roster_id: str,
    member_tag: str,
    payload: UpdateMemberModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Update specific properties of an individual roster member.

    Input:
        - server_id: Discord server ID for authorization
        - roster_id: Unique roster identifier
        - member_tag: Clash of Clans player tag of member to update
        - payload: Updated member properties (signup_group, member_status, etc.)
        - credentials: JWT authentication token

    Output:
        - Success message confirming member update
        - HTTP 404 if roster or member not found
        - HTTP 400 if validation fails (invalid signup group)
        - HTTP 401 if unauthorized

    Note: Allows updating signup category assignment and member status flags
    """

    # Validate roster exists and belongs to this server
    roster = await mongo.rosters.find_one({
        'custom_id': roster_id,
        'server_id': server_id
    })
    if not roster:
        raise HTTPException(status_code=404, detail=ROSTER_NOT_FOUND)

    # Validate signup group if being updated
    if payload.signup_group:
        # Check signup category exists on this server
        category_exists = await mongo.roster_signup_categories.find_one({
            'server_id': server_id,
            'custom_id': payload.signup_group
        })
        if not category_exists:
            raise HTTPException(status_code=400, detail='Invalid signup group')

        # Verify signup group is allowed for this specific roster
        allowed_groups = set(roster.get('allowed_signup_categories', []))
        if allowed_groups and payload.signup_group not in allowed_groups:
            raise HTTPException(
                status_code=400,
                detail='Signup group not allowed for this roster'
            )

    # Build update data from provided fields only
    update_data = payload.model_dump(exclude_none=True)

    # Special handling for signup_group to allow explicit None (removes category)
    if hasattr(payload, 'signup_group') and 'signup_group' in payload.model_fields_set:
        update_data['signup_group'] = payload.signup_group

    # Ensure there's actually something to update
    if not update_data:
        return {'message': NOTHING_TO_UPDATE}

    # Update the specific member using MongoDB positional operator ($)
    result = await mongo.rosters.update_one(
        {
            'custom_id': roster_id,
            'server_id': server_id,
            'members.tag': member_tag  # Find roster containing this member
        },
        {
            '$set': {f'members.$.{k}': v for k, v in update_data.items()}  # Update matched member
        }
    )

    # Check if member was found and updated
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=MEMBER_NOT_FOUND_IN_ROSTER)

    return {'message': 'Member updated successfully'}


# ======================== ROSTER AUTOMATION ENDPOINTS ========================


@router.post('/roster-automation', name='Create Roster Automation')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def create_roster_automation(
    payload: CreateRosterAutomationModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Create a scheduled automation rule for roster operations.

    Input:
        - payload: Automation configuration (action, schedule, target roster/group)
        - credentials: JWT authentication token

    Output:
        - Success message with generated automation_id
        - HTTP 404 if target roster or group not found
        - HTTP 400 if neither roster_id nor group_id provided
        - HTTP 401 if unauthorized

    Note: Automations can target individual rosters or entire groups
    """
    # Validate targets
    await validate_automation_targets(payload, mongo)

    # Create automation document with system-generated fields
    automation_doc = payload.model_dump()
    automation_doc.update(
        {
            'automation_id': gen_clean_custom_id(),
            'active': True,
            'executed': False,
            'created_at': pend.now(tz=pend.UTC),
            'updated_at': pend.now(tz=pend.UTC),
        }
    )

    await mongo.roster_automation.insert_one(automation_doc)
    return {
        'message': 'Roster automation created successfully',
        'automation_id': automation_doc['automation_id'],
    }


@router.get('/roster-automation/list', name='List Roster Automation Rules')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def list_roster_automation(
    server_id: int,
    roster_id: str = None,
    group_id: str = None,
    active_only: bool = True,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Retrieve automation rules with optional filtering by roster or group.

    Input:
        - server_id: Discord server ID to list automations for
        - roster_id: Optional filter for specific roster automations
        - group_id: Optional filter for specific group automations
        - active_only: If true, only show pending/active automations
        - credentials: JWT authentication token

    Output:
        - List of automation rules sorted by scheduled execution time
        - Applied filter parameters echoed back
        - HTTP 401 if unauthorized

    Note: Active_only=true excludes completed and disabled automations
    """
    # Build query filter starting with server scope
    query = {'server_id': server_id}

    # Apply optional target filters
    if roster_id:
        query['roster_id'] = roster_id  # Filter to specific roster
    if group_id:
        query['group_id'] = group_id    # Filter to specific group

    # Filter by execution status if requested
    if active_only:
        query['active'] = True      # Only enabled rules
        query['executed'] = False   # Only unexecuted rules

    # Fetch automations sorted by scheduled execution time (earliest first)
    cursor = mongo.roster_automation.find(query, {'_id': 0}).sort(
        {'scheduled_time': 1}
    )
    automations = await cursor.to_list(length=None)

    return {
        'items': automations,
        'server_id': server_id,
        'roster_id': roster_id,   # Echo back applied filters
        'group_id': group_id,
    }


@router.patch(
    '/roster-automation/{automation_id}', name='Update Roster Automation'
)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def update_roster_automation(
    server_id: int,
    automation_id: str,
    payload: UpdateRosterAutomationModel,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Update settings for an existing automation rule.

    Input:
        - server_id: Discord server ID for authorization
        - automation_id: Unique automation identifier to update
        - payload: Updated automation settings (schedule, action, active status)
        - credentials: JWT authentication token

    Output:
        - Success message confirming update
        - HTTP 404 if automation rule not found
        - HTTP 400 if no fields to update
        - HTTP 401 if unauthorized

    Note: Can update schedule, action parameters, or enable/disable rules
    """
    # Extract only the fields that were actually provided in the request
    body = payload.model_dump(exclude_none=True)
    if not body:
        return {'message': NOTHING_TO_UPDATE}

    # Add timestamp to track when the update occurred
    body['updated_at'] = pend.now(tz=pend.UTC)

    # Update automation rule with server ownership validation
    result = await mongo.roster_automation.update_one(
        {'automation_id': automation_id, 'server_id': server_id},
        {'$set': body},
    )

    # Check if automation rule was found and updated
    if result.matched_count == 0:
        raise HTTPException(
            status_code=404, detail=AUTOMATION_RULE_NOT_FOUND
        )

    return {'message': 'Automation rule updated'}


@router.delete(
    '/roster-automation/{automation_id}', name='Delete Roster Automation'
)
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def delete_roster_automation(
    server_id: int,
    automation_id: str,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Permanently delete an automation rule.

    Input:
        - server_id: Discord server ID for authorization
        - automation_id: Unique automation identifier to delete
        - credentials: JWT authentication token

    Output:
        - Success message confirming deletion
        - HTTP 404 if automation rule not found
        - HTTP 401 if unauthorized

    Note: This operation is irreversible and cancels any pending scheduled actions
    """
    # Delete automation rule with server ownership validation
    result = await mongo.roster_automation.delete_one(
        {'automation_id': automation_id, 'server_id': server_id}
    )

    # Check if automation rule was found and deleted
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404, detail=AUTOMATION_RULE_NOT_FOUND
        )

    return {'message': 'Automation rule deleted'}


@router.get('/roster/missing-members', name='Get Missing Members')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_missing_members(
    server_id: int,
    roster_id: str = Query(
        None, description='Get missing members for specific roster'
    ),
    group_id: str = Query(
        None, description='Get missing members for all rosters in group'
    ),
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    coc_client: CustomClashClient,
):
    """
    Identify clan members who are not yet registered in roster(s) for recruitment analysis.

    Input:
        - server_id: Discord server ID for authorization
        - roster_id: Check missing members for specific roster (optional)
        - group_id: Check missing members for all rosters in group (optional)
        - credentials: JWT authentication token

    Output:
        - Analysis results for each roster showing missing clan members
        - Coverage percentage and recruitment opportunities
        - Member details for easy roster addition
        - HTTP 404 if no rosters found
        - HTTP 400 if neither roster_id nor group_id provided
        - HTTP 401 if unauthorized

    Note: Helps identify recruitment gaps by comparing clan membership to roster registration
    """

    if not roster_id and not group_id:
        raise HTTPException(
            status_code=400, detail='Must provide roster_id or group_id'
        )

    # Build query filter and fetch rosters
    query_filter = {'server_id': server_id}
    if roster_id:
        query_filter['custom_id'] = roster_id
    elif group_id:
        query_filter['group_id'] = group_id

    rosters = await mongo.rosters.find(query_filter, {'_id': 0}).to_list(length=None)
    if not rosters:
        raise HTTPException(status_code=404, detail='No rosters found')

    # Analyze each roster for missing members
    results = []
    for roster in rosters:
        result = await analyze_roster_missing_members(roster, coc_client)
        results.append(result)

    return {
        'query_type': 'roster' if roster_id else 'group',
        'query_value': roster_id or group_id,
        'server_id': server_id,
        'results': results,
        'total_rosters_checked': len(results),
    }


@router.get('/roster/server/{server_id}/members', name='Get Server Clan Members')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_server_clan_members(
    server_id: int,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    coc_client: CustomClashClient,
):
    """
    Retrieve all members from clans linked to a Discord server for roster management.
    
    Input:
        - server_id: Discord server ID to get clan members for
        - credentials: JWT authentication token
        
    Output:
        - List of all clan members from server-linked clans
        - Member details including name, tag, townhall, and clan info
        - Sorted alphabetically by player name
        - HTTP 401 if unauthorized
        
    Note: Used for autocomplete and bulk member selection in roster interfaces
    """
    
    # Fetch all clans that are linked to this Discord server
    server_clans = await mongo.clan_db.find({
        'server': server_id
    }).to_list(length=None)
    
    # Return empty result if no clans are linked to this server
    if not server_clans:
        return {'members': []}
    
    all_members = []
    
    # Fetch member lists from each linked clan via Clash of Clans API
    for server_clan in server_clans:
        try:
            clan = await coc_client.get_clan(tag=server_clan['tag'])
            
            # Add each clan member to the combined list with full details
            for member in clan.members:
                all_members.append({
                    'name': member.name,
                    'tag': member.tag,
                    'townhall': member.town_hall,
                    'clan_name': clan.name,      # Which clan they belong to
                    'clan_tag': clan.tag,
                    'role': member.role.name if member.role else 'Member'
                })
                
        except Exception as e:
            # Log error but continue with other clans to avoid total failure
            logger.error(f"Error fetching clan {server_clan['tag']}: {e}")
            continue
    
    # Sort members alphabetically by name for easier browsing
    all_members.sort(key=lambda x: x['name'].lower())
    
    return {'members': all_members}


@router.post('/roster-token', name='Generate Server Roster Access Token')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def generate_server_roster_token(
    server_id: int,
    roster_id: str = None,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
):
    """
    Generate a temporary access token for roster dashboard access without requiring full authentication.
    
    Input:
        - server_id: Discord server ID to generate token for
        - roster_id: Optional specific roster to focus dashboard on
        - credentials: JWT authentication token (for initial authorization)
        
    Output:
        - Temporary access token valid for 1 hour
        - Dashboard URL with embedded token and parameters
        - Server information including roster count
        - Token expiration timestamp
        - HTTP 401 if unauthorized
        
    Note: Allows sharing roster management access without full bot permissions
    """

    # Get roster count for server information display
    roster_count = await mongo.rosters.count_documents({'server_id': server_id})
    
    # Generate time-limited access token for roster operations
    token_info = await generate_access_token(
        server_id=server_id,
        token_type='roster',      # Token type for roster dashboard access
        expires_hours=1,         # 1 hour expiration for security
        mongo_client=mongo,
    )

    # Build dashboard URL with appropriate parameters
    if roster_id:
        # Focus on specific roster if provided
        dashboard_url = f"{token_info['dashboard_url']}&server_id={server_id}&roster_id={roster_id}"
    else:
        # General server roster dashboard
        dashboard_url = f"{token_info['dashboard_url']}&server_id={server_id}"

    return {
        'message': 'Server roster access token generated successfully',
        'server_info': {
            'server_id': server_id,
            'roster_count': roster_count,  # How many rosters exist on this server
        },
        'access_url': dashboard_url,                           # Ready-to-use dashboard URL
        'token': token_info['token'],                          # Raw token for API access
        'expires_at': token_info['expires_at'].isoformat(),   # When token expires
    }


@router.get('/server/{server_id}/discord-channels', name='Get Discord Channels')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def get_server_discord_channels(
    server_id: int,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    _mongo: MongoClient,
):
    """
    Retrieve Discord channels for a server with write permissions, filtered and sorted for automation use.

    Input:
        - server_id: Discord server ID to get channels for
        - credentials: JWT authentication token

    Output:
        - List of channels suitable for automation (text channels with write permissions)
        - Channels are categorized and sorted by relevance for automation
        - HTTP 401 if unauthorized

    Note: Filters for channels likely to be used for announcements, events, or notifications
    """

    try:
        # Import here to ensure fresh config
        from utils.discord_api import discord_api

        # Check if bot token is configured
        if not discord_api.config.bot_token:
            raise HTTPException(
                status_code=503,
                detail='Discord bot token not configured'
            )

        result = await get_discord_channels(server_id)
        return result

    except aiohttp.ClientError as e:
        # Discord API specific errors
        if 'Unauthorized' in str(e) or '401' in str(e):
            raise HTTPException(
                status_code=401,
                detail='Discord bot token is invalid or expired'
            )
        elif 'Forbidden' in str(e) or '403' in str(e):
            raise HTTPException(
                status_code=403,
                detail='Discord bot does not have access to this server'
            )
        else:
            raise HTTPException(
                status_code=503,
                detail=f'Discord API error: {str(e)}'
            )
    except Exception as e:
        import traceback
        error_details = f'Error fetching Discord channels: {str(e)}\n{traceback.format_exc()}'
        logger.error(f"DEBUG: {error_details}")
        raise HTTPException(
            status_code=500,
            detail=f'Internal server error: {str(e)}'
        )


@router.get('/server/{server_id}/discord-test', name='Test Discord API Access')
@linkd.ext.fastapi.inject
@check_authentication
@capture_endpoint_errors
async def test_discord_api_access(
    server_id: int,
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    _mongo: MongoClient,
):
    """Test endpoint to verify Discord API configuration."""
    try:
        from utils.discord_api import discord_api

        # Check bot token
        if not discord_api.config.bot_token:
            return {
                'status': 'error',
                'message': 'Bot token not configured',
                'bot_token_present': False
            }

        # Test a simple Discord API call
        url = f'https://discord.com/api/v10/guilds/{server_id}'
        headers = {
            'Authorization': f'Bot {discord_api.config.bot_token}',
            'Content-Type': 'application/json'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                status_code = response.status

                if status_code == 200:
                    guild_data = await response.json()
                    return {
                        'status': 'success',
                        'message': 'Discord API access working',
                        'bot_token_present': True,
                        'guild_name': guild_data.get('name', 'Unknown'),
                        'status_code': status_code
                    }
                else:
                    error_text = await response.text()
                    return {
                        'status': 'error',
                        'message': f'Discord API error: {error_text}',
                        'bot_token_present': True,
                        'status_code': status_code
                    }

    except Exception as e:
        import traceback
        return {
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }
