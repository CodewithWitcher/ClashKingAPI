import coc
import hikari
import logging
import pendulum as pend
from bson import ObjectId
from coc.utils import correct_tag

from utils.cache_decorator import cache_endpoint
from utils.config import Config
from utils.database import MongoClient

logger = logging.getLogger(__name__)

# Constants
DATA_PREP_START_TIME = 'data.preparationStartTime'
NO_USER = 'No User'
MATCH_STAGE = '$match'
CLAN_NOT_LINKED_ERROR = "Selected clan is not linked to this server"


def parse_th_restriction(th_restriction: str) -> tuple:
    """Parse townhall restriction string to separate min and max values.

    Formats handled:
    - "12+" -> min_th=12, max_th=None (TH12 and above)
    - "12-15" -> min_th=12, max_th=15 (TH12 to TH15)
    - "1-15" -> min_th=None, max_th=15 (up to TH15, treating 1 as no minimum)
    - "12" -> min_th=12, max_th=12 (exactly TH12)

    Args:
        th_restriction: Townhall restriction string

    Returns:
        Tuple of (min_th, max_th)
    """
    if not th_restriction:
        return None, None

    th_restriction = th_restriction.strip()

    if th_restriction.endswith('+'):
        # Format: "12+" indicates minimum TH level with no upper limit
        min_th = int(th_restriction[:-1])
        return min_th, None
    elif '-' in th_restriction:
        # Format: "12-15" indicates TH range
        parts = th_restriction.split('-')
        # Don't show min_th if it's 1 (effectively no minimum restriction)
        min_th = int(parts[0]) if parts[0] != '1' else None
        max_th = int(parts[1])
        return min_th, max_th
    else:
        # Format: "12" indicates exact TH level required
        th = int(th_restriction)
        return th, th


def count_player_attacks(war_data: dict, player_tag: str) -> tuple[int, int]:
    """Count total attacks and three-star attacks for a player in a war.

    Args:
        war_data: War data dictionary
        player_tag: Player tag to search for

    Returns:
        Tuple of (total_attacks, three_star_attacks)
    """
    total = 0
    three_stars = 0

    for side in ['clan', 'opponent']:
        for member in war_data[side].get('members', []):
            if member['tag'] == player_tag:
                for attack in member.get('attacks', []):
                    total += 1
                    if attack['stars'] == 3:
                        three_stars += 1

    return total, three_stars


async def calculate_player_hitrate(player_tag: str, days: int = 30, mongo: MongoClient = None) -> float:
    """Calculate player's hitrate over the last X days."""
    import logging
    logger = logging.getLogger(__name__)

    # Debug: Check if mongo is None
    if mongo is None:
        logger.warning(f"[HITRATE DEBUG] mongo is None for player {player_tag}")
        return 0.0

    # Calculate time range
    end_time = pend.now(tz=pend.UTC)
    start_time = end_time.subtract(days=days)

    start_time_str = start_time.strftime('%Y%m%dT%H%M%S.000Z')
    end_time_str = end_time.strftime('%Y%m%dT%H%M%S.000Z')

    player_tag = correct_tag(player_tag)

    logger.info(f"[HITRATE DEBUG] Calculating hitrate for {player_tag}, range: {start_time_str} to {end_time_str}")

    pipeline = [
        {
            MATCH_STAGE: {
                '$and': [
                    {
                        '$or': [
                            {'data.clan.members.tag': player_tag},
                            {'data.opponent.members.tag': player_tag},
                        ]
                    },
                    {DATA_PREP_START_TIME: {'$gte': start_time_str}},
                    {DATA_PREP_START_TIME: {'$lte': end_time_str}},
                ]
            }
        },
        {'$sort': {DATA_PREP_START_TIME: -1}},
        {'$project': {'data': '$data'}},
    ]

    try:
        cursor = await mongo.clan_wars.aggregate(
            pipeline, allowDiskUse=True
        )
        wars_docs = await cursor.to_list(length=None)

        logger.info(f"[HITRATE DEBUG] Found {len(wars_docs)} wars for player {player_tag}")

        total_attacks = 0
        three_star_attacks = 0

        for war_doc in wars_docs:
            war_data = war_doc['data']
            attacks, three_stars = count_player_attacks(war_data, player_tag)
            total_attacks += attacks
            three_star_attacks += three_stars

        logger.info(f"[HITRATE DEBUG] Player {player_tag}: {three_star_attacks}/{total_attacks} attacks")

        if total_attacks == 0:
            return 0.0

        hitrate = round((three_star_attacks / total_attacks) * 100, 2)
        logger.info(f"[HITRATE DEBUG] Player {player_tag} hitrate: {hitrate}%")
        return hitrate
    except Exception as e:
        logger.error(f"[HITRATE DEBUG] Exception for {player_tag}: {type(e).__name__}: {e}")
        return 0.0


async def get_player_last_online(player_tag: str, mongo: MongoClient = None) -> int:
    """Get player's last online timestamp from player_stats database."""
    try:
        player_tag = correct_tag(player_tag)
        result = await mongo.player_stats.find_one(
            {'tag': player_tag}, {'last_online': 1}
        )
        return result.get('last_online', 0) if result else 0
    except (KeyError, TypeError):
        return 0


async def calculate_player_activity(player_tag: str, days: int = 30, mongo: MongoClient = None) -> int:
    """Calculate player's activity based on player_history collection."""
    try:
        player_tag = correct_tag(player_tag)

        # Calculate timestamp X days ago
        days_ago = int(pend.now('UTC').subtract(days=days).timestamp())

        # Count distinct days the player had activity in player_history
        pipeline = [
            {MATCH_STAGE: {'tag': player_tag, 'time': {'$gte': days_ago}}},
            {
                '$group': {
                    '_id': {
                        '$dateToString': {
                            'format': '%Y-%m-%d',
                            'date': {
                                '$toDate': {'$multiply': ['$time', 1000]}
                            },
                        }
                    },
                    'count': {'$sum': 1},
                }
            },
            {'$count': 'total_days'},
        ]

        cursor = await mongo.player_history.aggregate(pipeline)
        result = await cursor.to_list(length=1)
        return result[0]['total_days'] if result else 0
    except (KeyError, TypeError, IndexError):
        return 0


async def calculate_bulk_stats(player_tags: list[str], mongo: MongoClient = None) -> dict:
    """Calculate hitrate, last_online, and activity for multiple players efficiently."""
    stats = {}

    for tag in player_tags:
        stats[tag] = {
            'hitrate': await calculate_player_hitrate(tag, mongo=mongo),
            'last_online': await get_player_last_online(tag, mongo=mongo),
            'activity': await calculate_player_activity(tag, mongo=mongo),
        }

    return stats


def extract_discord_user_id(discord_mention: str) -> str:
    """Extract Discord user ID from mention format or raw ID.

    Args:
        discord_mention: Discord mention like <@123456> or raw ID

    Returns:
        Extracted user ID as string, or empty string if invalid
    """
    if not discord_mention or discord_mention == NO_USER:
        return ""

    # Handle mention format <@123456> or <@!123456>
    if discord_mention.startswith('<@') and discord_mention.endswith('>'):
        user_id = discord_mention[2:-1]
        if user_id.startswith('!'):
            user_id = user_id[1:]
        return user_id

    return discord_mention  # Already just an ID or custom format


async def check_user_account_limit(
    roster_id: str, discord_user: str, exclude_tag: str = None, mongo: MongoClient = None
) -> tuple[bool, int, int]:
    """
    Check if adding this member would exceed the roster's account limit per user.
    Returns: (is_valid, current_count, max_allowed)
    """
    try:
        _id = ObjectId(roster_id)
    except (ValueError, TypeError):
        return True, 0, 0  # Invalid ID, let other validation handle it

    roster = await mongo.rosters.find_one({'_id': _id})
    if not roster:
        return True, 0, 0  # Roster not found, let other validation handle it

    max_accounts = roster.get('max_accounts_per_user')
    if max_accounts is None:
        return True, 0, 0  # No limit set

    discord_user_id = extract_discord_user_id(discord_user)
    if not discord_user_id:
        return True, 0, max_accounts  # No Discord user, no limit

    # Count current accounts for this Discord user
    members = roster.get('members', [])
    current_count = 0

    for member in members:
        if exclude_tag and member.get('tag') == exclude_tag:
            continue  # Don't count the member we're potentially replacing

        member_discord_id = extract_discord_user_id(
            member.get('discord', NO_USER)
        )
        if member_discord_id == discord_user_id:
            current_count += 1

    is_valid = current_count < max_accounts
    return is_valid, current_count, max_accounts


async def refresh_member_data(
    member: dict, coc_client: coc.Client, mongo: MongoClient = None
) -> tuple[dict, str]:
    """
    Refresh a single member's data from CoC API.
    Returns: (updated_member_dict, action)
    Actions: 'updated', 'remove', 'no_change'
    """
    try:
        player_tag = member['tag']
        player = await coc_client.get_player(player_tag)

        # Calculate hero levels sum
        hero_lvs = sum(hero.level for hero in player.heroes)

        # Get current clan info
        current_clan = player.clan.name if player.clan else 'No Clan'
        current_clan_tag = player.clan.tag if player.clan else '#'

        # Calculate stats for enhanced member data
        hitrate = await calculate_player_hitrate(player.tag, mongo=mongo)
        last_online = await get_player_last_online(player.tag, mongo=mongo)

        # Get league name
        current_league = player.league.name if player.league else 'Unranked'

        # Update member data with enhanced fields
        member.update(
            {
                'name': player.name,
                'hero_lvs': hero_lvs,
                'townhall': player.town_hall,
                'current_clan': current_clan,
                'current_clan_tag': current_clan_tag,
                'war_pref': player.war_opted_in,
                'trophies': player.trophies,
                'hitrate': hitrate,
                'last_online': last_online,
                'current_league': current_league,
                'last_updated': int(pend.now('UTC').timestamp()),
                'member_status': 'active',
                'error_details': None,
            }
        )

        return member, 'updated'

    except coc.NotFound:
        # Player doesn't exist anymore - mark for removal
        return member, 'remove'

    except Exception as e:
        # API error - keep existing data, just update tracking fields
        member.update(
            {
                'last_updated': int(pend.now('UTC').timestamp()),
                'member_status': 'api_error',
                'error_details': str(e),
            }
        )
        return member, 'no_change'


async def validate_clan_for_roster(
    roster_type: str, clan_tag: str, server_id: int, mongo, coc_client
):
    """
    Validate and fetch clan data for roster creation.
    Returns: (clan_object, error_message)
    """
    if roster_type == 'clan':
        if not clan_tag:
            return None, "Clan tag is required for clan-specific rosters"

        server_clan = await mongo.clan_db.find_one({
            'tag': clan_tag,
            'server': server_id
        })
        if not server_clan:
            return None, CLAN_NOT_LINKED_ERROR

        clan = await coc_client.get_clan(tag=clan_tag)
        return clan, None

    elif roster_type == 'family':
        if clan_tag:
            server_clan = await mongo.clan_db.find_one({
                'tag': clan_tag,
                'server': server_id
            })
            if not server_clan:
                return None, CLAN_NOT_LINKED_ERROR

            clan = await coc_client.get_clan(tag=clan_tag)
            return clan, None
        return None, None

    return None, None


def build_roster_metadata(clan, roster_data, server_id: int) -> dict:
    """Build roster document metadata including clan info."""
    ext_data = {
        'server_id': server_id,
        'custom_id': None,  # Will be set by caller
        'members': [],
        'columns': ['Townhall Level', 'Name', '30 Day Hitrate', 'Clan Tag'],
        'sort': [],
        'created_at': pend.now(tz=pend.UTC),
        'updated_at': pend.now(tz=pend.UTC),
    }

    if clan:
        ext_data.update({
            'clan_name': clan.name,
            'clan_tag': clan.tag,
            'clan_badge': clan.badge.large,
        })
    elif roster_data.get('roster_type') == 'family':
        ext_data.update({
            'clan_name': f"{roster_data.get('alias', 'Family')} Family",
            'clan_tag': None,
            'clan_badge': None,
        })

    return ext_data


def convert_th_range_to_restriction(min_th: int = None, max_th: int = None) -> str | None:
    """Convert min_th and max_th values to th_restriction string format."""
    if min_th is not None and max_th is not None:
        if min_th == max_th:
            return str(min_th)
        else:
            return f"{min_th}-{max_th}"
    elif min_th is not None:
        return f"{min_th}+"
    elif max_th is not None:
        return f"1-{max_th}"
    else:
        return None


async def validate_and_update_clan_info(
    roster_type: str, clan_tag: str, server_id: int, mongo, coc_client
) -> dict:
    """
    Validate clan and return clan info updates for roster.
    Returns dict with clan_name, clan_tag, clan_badge fields.
    """
    if roster_type == 'clan':
        if not clan_tag:
            return {'error': "Clan tag is required for clan type rosters"}

        server_clan = await mongo.clan_db.find_one({
            'tag': clan_tag,
            'server': server_id
        })
        if not server_clan:
            return {'error': CLAN_NOT_LINKED_ERROR}

        clan = await coc_client.get_clan(tag=clan_tag)
        return {
            'clan_name': clan.name,
            'clan_tag': clan.tag,
            'clan_badge': clan.badge.large
        }

    elif roster_type == 'family':
        if clan_tag:
            return {'error': "Family type rosters should not have a specific clan"}
        return {
            'clan_tag': None,
            'clan_badge': None
        }

    return {}


async def validate_signup_groups(
    add_members: list, server_id: int, roster: dict, mongo
) -> None:
    """Validate signup groups for members being added. Raises HTTPException on error."""
    from fastapi import HTTPException

    signup_group_to_validate = set()
    for member in add_members:
        if member.signup_group:
            signup_group_to_validate.add(member.signup_group)

    if not signup_group_to_validate:
        return

    # Verify all specified signup groups exist on this server
    existing_categories = await mongo.roster_signup_categories.find(
        {
            'server_id': server_id,
            'custom_id': {'$in': list(signup_group_to_validate)},
        }
    ).to_list(length=None)
    existing_category_ids = {
        category['custom_id'] for category in existing_categories
    }

    # Check for invalid/non-existent signup groups
    invalid_groups = signup_group_to_validate - existing_category_ids
    if invalid_groups:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid signup_group(s): {', '.join(invalid_groups)}",
        )

    # Validate signup groups are allowed for this specific roster
    allowed_groups = set(roster.get('allowed_signup_categories', []))
    if allowed_groups:
        unauthorized_groups = signup_group_to_validate - allowed_groups
        if unauthorized_groups:
            raise HTTPException(
                status_code=400,
                detail=f"Signup_group(s) not allowed for this roster: {', '.join(unauthorized_groups)}",
            )


async def get_discord_user_mappings(add_tags: list, mongo) -> dict:
    """Get Discord user ID mappings for player tags."""
    cursor = mongo.coc_accounts.find({'player_tag': {'$in': add_tags}})
    tag_to_user_id = {
        doc['player_tag']: doc['user_id']
        for doc in await cursor.to_list(length=None)
    }
    return tag_to_user_id


async def get_user_account_counts(roster_id: str, mongo) -> dict:
    """Get current account counts per Discord user for a roster."""
    pipeline = [
        {MATCH_STAGE: {'custom_id': roster_id}},
        {'$unwind': '$members'},
        {'$group': {'_id': '$members.discord', 'count': {'$sum': 1}}},
    ]
    cursor = await mongo.rosters.aggregate(pipeline)
    user_to_count = {
        doc['_id']: doc['count']
        for doc in await cursor.to_list(length=None)
    }
    return user_to_count


def build_member_data(player, user_id: str, signup_group: str, hitrate: float, last_online: int) -> dict:
    """Build member data dictionary from player object and stats."""
    hero_lvs = sum(hero.level for hero in player.heroes if hero.is_home_base)
    current_clan = player.clan.name if player.clan else 'No Clan'
    current_clan_tag = player.clan.tag if player.clan else '#'
    current_league = player.league.name if player.league else 'Unranked'

    return {
        'name': player.name,
        'tag': player.tag,
        'hero_lvs': hero_lvs,
        'townhall': player.town_hall,
        'discord': user_id,
        'current_clan': current_clan,
        'current_clan_tag': current_clan_tag,
        'war_pref': player.war_opted_in,
        'trophies': player.trophies,
        'signup_group': signup_group,
        'hitrate': hitrate,
        'last_online': last_online,
        'current_league': current_league,
        'last_updated': pend.now(tz=pend.UTC).int_timestamp,
        'added_at': pend.now(tz=pend.UTC).int_timestamp,
        'member_status': 'active',
    }


async def process_player_additions(
    coc_client,
    add_tags: list,
    roster: dict,
    payload_add: list,
    tag_to_user_id: dict,
    user_to_count: dict,
    mongo: MongoClient = None,
) -> tuple[list, int, int]:
    """
    Process player additions and return added members list with counts.
    Returns: (added_members, success_count, error_count)
    """
    import coc

    added_members = []
    success_count = 0
    error_count = 0
    max_accounts = roster.get('max_accounts_per_user')

    async for player in coc_client.get_players(player_tags=add_tags):
        if isinstance(player, coc.errors.NotFound):
            error_count += 1
            continue
        elif isinstance(player, coc.Maintenance):
            raise player

        user_id = tag_to_user_id.get(player.tag, NO_USER)
        current_count = user_to_count.get(user_id, 0)

        # Skip if account limit exceeded
        if (
            max_accounts
            and current_count >= max_accounts
            and user_id != NO_USER
        ):
            error_count += 1
            continue

        # Find signup group from original request
        original_member = next(
            (m for m in payload_add if correct_tag(m.tag) == player.tag),
            None,
        )
        signup_group = original_member.signup_group if original_member else None

        # Fetch player stats
        hitrate = await calculate_player_hitrate(player.tag, mongo=mongo)
        last_online = await get_player_last_online(player.tag, mongo=mongo)

        # Build member data
        member_data = build_member_data(
            player, user_id, signup_group, hitrate, last_online
        )

        added_members.append(member_data)

        if user_id != NO_USER:
            user_to_count[user_id] = user_to_count.get(user_id, 0) + 1

        success_count += 1

    return added_members, success_count, error_count


async def handle_clan_updates_for_roster(
    body: dict, roster_id: str, server_id: int, mongo, coc_client
) -> None:
    """Handle clan_tag and roster_type updates. Modifies body in place."""
    if 'roster_type' not in body and 'clan_tag' not in body:
        return

    current_roster = await mongo.rosters.find_one({
        'custom_id': roster_id,
        'server_id': server_id
    })

    new_roster_type = body.get('roster_type', current_roster.get('roster_type', 'clan'))
    new_clan_tag = body.get('clan_tag', current_roster.get('clan_tag'))

    clan_updates = await validate_and_update_clan_info(
        new_roster_type, new_clan_tag, server_id, mongo, coc_client
    )

    if 'error' in clan_updates:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=clan_updates['error'])

    if new_roster_type == 'family':
        clan_updates['clan_name'] = f"{current_roster.get('alias', 'Family')} Family"

    body.update(clan_updates)


async def validate_automation_targets(payload, mongo) -> None:
    """Validate roster and group targets for automation. Raises HTTPException on error."""
    from fastapi import HTTPException

    if not payload.roster_id and not payload.group_id:
        raise HTTPException(
            status_code=400, detail='Must specify either roster_id or group_id'
        )

    if payload.roster_id:
        roster = await mongo.rosters.find_one({'custom_id': payload.roster_id})
        if not roster:
            raise HTTPException(status_code=404, detail='Roster not found')

    if payload.group_id:
        group = await mongo.roster_groups.find_one({'group_id': payload.group_id})
        if not group:
            raise HTTPException(status_code=404, detail='Roster group not found')


def build_missing_member_info(member) -> dict:
    """Build missing member info dictionary from clan member."""
    return {
        'tag': member.tag,
        'name': member.name,
        'townhall': member.town_hall,
        'role': member.role.name if member.role else 'Member',
        'trophies': member.trophies,
        'discord': NO_USER,
    }


def build_roster_info_dict(roster: dict, registered_count: int) -> dict:
    """Build roster info dictionary for missing members response."""
    return {
        'roster_id': roster['custom_id'],
        'alias': roster['alias'],
        'clan_tag': roster['clan_tag'],
        'clan_name': roster.get('clan_name', 'Unknown'),
        'group_id': roster.get('group_id'),
        'registered_count': registered_count,
    }


def calculate_coverage_stats(registered_count: int, total_clan_members: int, missing_count: int) -> dict:
    """Calculate coverage statistics for roster."""
    coverage_percentage = round(
        (registered_count / max(total_clan_members, 1)) * 100,
        2,
    )
    return {
        'total_missing': missing_count,
        'total_clan_members': total_clan_members,
        'coverage_percentage': coverage_percentage,
    }


async def analyze_roster_missing_members(roster: dict, coc_client) -> dict:
    """Analyze a single roster for missing members. Returns result dict with state."""
    registered_tags = {member['tag'] for member in roster.get('members', [])}

    if not roster.get('clan_tag'):
        return {
            'state': 'error',
            'error_message': 'No clan assigned to this roster',
            'roster_info': build_roster_info_dict(roster, len(registered_tags)),
            'missing_members': [],
            'summary': {'total_missing': 0, 'total_clan_members': 0, 'coverage_percentage': 0},
        }

    try:
        clan = await coc_client.get_clan(roster['clan_tag'])
        missing_members = []

        for member in clan.members:
            if member.tag not in registered_tags:
                missing_members.append(build_missing_member_info(member))

        summary = calculate_coverage_stats(
            len(registered_tags),
            len(clan.members),
            len(missing_members)
        )

        return {
            'state': 'ok',
            'roster_info': build_roster_info_dict(roster, len(registered_tags)),
            'missing_members': missing_members,
            'summary': summary,
        }

    except Exception as e:
        return {
            'state': 'error',
            'error_message': f'Error fetching clan data: {str(e)}',
            'roster_info': build_roster_info_dict(roster, len(registered_tags)),
            'missing_members': [],
            'summary': {
                'total_missing': 0,
                'total_clan_members': 0,
                'coverage_percentage': 0,
            },
        }


def build_refresh_query_filter(roster_id: str, group_id: str, server_id: int) -> dict:
    """Build MongoDB query filter for refresh operation.

    Args:
        roster_id: Specific roster ID to refresh
        group_id: Group ID to refresh all rosters in group
        server_id: Server ID to refresh all rosters on server

    Returns:
        MongoDB query filter dict

    Raises:
        ValueError: If no filter parameters provided
    """
    query_filter = {}
    if roster_id:
        query_filter['custom_id'] = roster_id
    elif group_id:
        query_filter['group_id'] = group_id
    elif server_id:
        query_filter['server_id'] = server_id
    else:
        raise ValueError('Must provide server_id, group_id, or roster_id')

    return query_filter


async def refresh_single_roster(roster: dict, mongo, coc_client) -> dict:
    """Refresh a single roster and return summary.

    Args:
        roster: Roster document to refresh
        mongo: MongoDB client instance
        coc_client: Clash of Clans API client

    Returns:
        Dict with roster_id, alias, message, updated count, and removed count
    """
    import pendulum as pend

    members = roster.get('members', [])
    if not members:
        return {
            'roster_id': roster['custom_id'],
            'alias': roster.get('alias', 'Unknown'),
            'message': 'No members to refresh',
            'updated': 0,
            'removed': 0,
        }

    updated_members = []
    updated_count = 0
    removed_count = 0

    for member in members:
        updated_member, action = await refresh_member_data(member, coc_client, mongo=mongo)

        if action == 'remove':
            removed_count += 1
        elif action == 'updated':
            updated_members.append(updated_member)
            updated_count += 1
        else:  # no_change
            updated_members.append(updated_member)

    # Save refreshed members
    await mongo.rosters.update_one(
        {'custom_id': roster['custom_id']},
        {
            '$set': {
                'members': updated_members,
                'updated_at': pend.now(tz=pend.UTC),
            }
        },
    )

    return {
        'roster_id': roster['custom_id'],
        'alias': roster.get('alias', 'Unknown'),
        'message': f'Refreshed: {updated_count} updated, {removed_count} removed',
        'updated': updated_count,
        'removed': removed_count,
    }


@cache_endpoint(ttl=120, key_prefix="roster_server_members")
async def get_server_members_with_cache(rest: hikari.RESTApp, server_id: int, bot_token: str) -> dict:
    """Fetch all members for a Discord server with caching.

    Args:
        rest: Hikari REST client
        server_id: Discord server ID
        bot_token: Bot authentication token

    Returns:
        Dictionary mapping user_id (str) to member object with username and avatar
    """
    members_dict = {}
    if not bot_token:
        return members_dict

    try:
        async with rest.acquire(token=bot_token, token_type=hikari.TokenType.BOT) as client:
            async for member in client.fetch_members(server_id):
                user_id = str(member.user.id)
                display_name = member.nickname or member.user.username
                avatar_url = str(member.user.make_avatar_url()) if member.user.avatar_hash else None

                members_dict[user_id] = {
                    'username': display_name,
                    'avatar_url': avatar_url
                }
    except Exception as e:
        logger.warning(f"Error fetching server members for {server_id}: {e}")

    return members_dict


def enrich_members_with_discord_info(members: list, members_dict: dict) -> list:
    """Enrich roster members with Discord username and avatar.

    Args:
        members: List of roster member dicts
        members_dict: Dict mapping user_id to {username, avatar_url}

    Returns:
        Members list with discord_username and discord_avatar_url added
    """
    if not members:
        return members

    for member in members:
        discord_value = member.get('discord', '')
        user_id = extract_discord_user_id(discord_value)

        if user_id and user_id in members_dict:
            member['discord_username'] = members_dict[user_id].get('username')
            member['discord_avatar_url'] = members_dict[user_id].get('avatar_url')
        else:
            member['discord_username'] = None
            member['discord_avatar_url'] = None

    return members
