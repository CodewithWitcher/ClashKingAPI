# ClashKingAPI Endpoints Analysis for Dashboard

## Server Settings Endpoints

### GET /v2/server/{server_id}/settings
Get all settings for a server including role configurations.

**Parameters:**
- `server_id: int` - Discord server ID
- `request: Request`
- `clan_settings: bool = False` - Include clan settings in response

**Returns:** Complete server settings with aggregated roles

---

### PATCH /v2/server/{server_id}/settings
Update server settings (unified endpoint for all server-level configurations).

**Parameters:**
- `server_id: int` - Discord server ID
- `settings: ServerSettingsUpdate` - Settings to update
- `user_id: str = None`
- `request: Request = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo_client: MongoClient` (injected)

**Settings fields (all optional):**
- `embed_color: int` - Embed color as integer
- `nickname_rule: str` - Family member nickname convention
- `non_family_nickname_rule: str` - Non-family nickname convention
- `change_nickname: bool` - Enable/disable nickname changes
- `flair_non_family: bool` - Enable/disable non-family flair
- `auto_eval_nickname: bool` - Enable/disable auto-eval for nicknames
- `autoeval_triggers: List[str]` - List of auto-eval triggers
- `autoeval_log: int` - Auto-eval log channel ID
- `autoeval: bool` - Enable/disable auto-eval
- `blacklisted_roles: List[int]` - List of blacklisted role IDs
- `role_treatment: List[str]` - Role treatment types
- `full_whitelist_role: int` - Full whitelist role ID
- `leadership_eval: bool` - Enable/disable leadership eval
- `autoboard_limit: int` - Autoboard limit
- `api_token: bool` - Enable/disable API token
- `tied: bool` - Enable/disable tied stats
- `banlist: int` - Banlist channel ID
- `strike_log: int` - Strike log channel ID
- `reddit_feed: int` - Reddit feed channel ID
- `family_label: str` - Family label text
- `greeting: str` - Server welcome message
- `link_parse: LinkParseSettings` - Link parsing configuration
  - `clan: bool`
  - `army: bool`
  - `player: bool`
  - `base: bool`
  - `show: bool`

**Returns:**
```json
{
  "message": "Server settings updated successfully",
  "server_id": 123,
  "updated_fields": 5
}
```

---

### PUT /v2/server/{server_id}/embed-color/{hex_code}
Update server Discord embed color (legacy endpoint).

**Parameters:**
- `server_id: int` - Discord server ID
- `hex_code: int` - Hex color code as integer
- `request: Request`

---

## Clan Settings Endpoints

### GET /v2/server/{server_id}/clan/{clan_tag}/settings
Get settings for a specific clan.

**Parameters:**
- `server_id: int` - Discord server ID
- `clan_tag: str` - Clan tag (with or without #)
- `request: Request`

---

### PATCH /v2/server/{server_id}/clan/{clan_tag}/settings
Update clan settings (unified endpoint for all clan-level configurations).

**Parameters:**
- `server_id: int` - Discord server ID
- `clan_tag: str` - Clan tag
- `settings: ClanSettingsUpdate` - Settings to update
- `user_id: str = None`
- `request: Request = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo_client: MongoClient` (injected)

**Settings fields (all optional):**
- `generalRole: int` (alias: `member_role`) - Member role ID
- `leaderRole: int` (alias: `leader_role`) - Leader role ID
- `clanChannel: int` (alias: `clan_channel`) - Clan channel ID
- `category: str` - Clan category
- `abbreviation: str` - Clan abbreviation for nicknames
- `greeting: str` - Clan welcome message
- `auto_greet_option: str` - Auto-greet option: Never/Always/On Join
- `leadership_eval: bool` - Enable/disable leadership eval
- `warCountdown: int` (alias: `war_countdown`) - War countdown channel ID
- `warTimerCountdown: int` (alias: `war_timer_countdown`) - War timer countdown channel ID
- `ban_alert_channel: int` - Ban alert channel ID
- `member_count_warning: MemberCountWarningUpdate`
  - `channel: int`
  - `above: int`
  - `below: int`
  - `role: int`
- `join_log_profile_button: bool` - Enable profile button on join logs
- `leave_log_strike_button: bool` - Enable strike button on leave logs
- `leave_log_ban_button: bool` - Enable ban button on leave logs

**Returns:**
```json
{
  "message": "Clan settings updated successfully",
  "server_id": 123,
  "clan_tag": "#2PP",
  "updated_fields": 8
}
```

---

## Clan Management Endpoints

### GET /v2/server/{server_id}/clans
Get all clans registered for a server.

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)
- `rest: hikari.RESTApp` (injected)

**Returns:** List of clans with tag and name

---

### POST /v2/server/{server_id}/clans
Add a clan to a server.

**Parameters:**
- `server_id: int` - Discord server ID
- `clan_request: AddClanRequest`
  - `tag: str` - Clan tag (with or without #)
  - `name: str = None` - Clan name (fetched from API if not provided)
- `user_id: str = None`
- `request: Request = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo_client: MongoClient` (injected)
- `coc_client: CustomClashClient` (injected)

**Returns:**
```json
{
  "message": "Clan added successfully",
  "server_id": 123,
  "clan_tag": "#2PP",
  "clan_name": "Clash King"
}
```

---

### DELETE /v2/server/{server_id}/clans/{clan_tag}
Remove a clan from a server.

**Parameters:**
- `server_id: int` - Discord server ID
- `clan_tag: str` - Clan tag
- `user_id: str = None`
- `request: Request = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo_client: MongoClient` (injected)

**Returns:**
```json
{
  "message": "Clan removed successfully",
  "server_id": 123,
  "clan_tag": "#2PP",
  "deleted_count": 1
}
```

---

## Logs Endpoints

### GET /v2/server/{server_id}/logs
Get complete logs configuration for a server (aggregated from all clans).

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)
- `rest: hikari.RESTApp` (injected)

**Returns:** ServerLogsConfig with all log types

---

### PUT /v2/server/{server_id}/logs
Update complete logs configuration for a server.

**Parameters:**
- `server_id: int` - Discord server ID
- `logs_config: ServerLogsConfig`
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)
- `rest: hikari.RESTApp` (injected)

**Returns:**
```json
{
  "message": "Logs configuration updated successfully",
  "server_id": 123,
  "updated_clans": 5
}
```

---

### PATCH /v2/server/{server_id}/logs/{log_type}
Update a specific log type configuration.

**Parameters:**
- `server_id: int` - Discord server ID
- `log_type: str` - Log type (join_leave_log, donation_log, war_log, etc.)
- `log_config: LogConfig`
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)
- `rest: hikari.RESTApp` (injected)

**Valid log types:**
- join_leave_log
- donation_log
- war_log
- capital_donation_log
- capital_raid_log
- player_upgrade_log
- legend_log
- ban_log
- strike_log

---

### GET /v2/server/{server_id}/clan-logs
Get logs configuration for all clans (not aggregated).

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)
- `rest: hikari.RESTApp` (injected)

**Returns:** List of ClanLogsConfig for each clan

---

### PUT /v2/server/{server_id}/clan/{clan_tag}/logs
Update logs configuration for a specific clan.

**Parameters:**
- `server_id: int` - Discord server ID
- `clan_tag: str` - Clan tag
- `request: UpdateClanLogRequest`
  - `channel_id: str | int = None`
  - `thread_id: str | int = None`
  - `log_types: List[str]` - List of log types to update
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)
- `rest: hikari.RESTApp` (injected)

**Returns:**
```json
{
  "message": "Clan logs updated successfully",
  "clan_tag": "#2PP",
  "updated_log_types": ["join_log", "leave_log"],
  "webhook_id": 123456789,
  "thread_id": 987654321
}
```

---

### DELETE /v2/server/{server_id}/clan/{clan_tag}/logs
Delete logs configuration for a specific clan.

**Parameters:**
- `server_id: int` - Discord server ID
- `clan_tag: str` - Clan tag
- `log_types: str` (Query parameter) - Comma-separated list of log types to delete
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)

**Example:** `?log_types=join_log,leave_log,donation_log`

**Returns:**
```json
{
  "message": "Clan logs deleted successfully",
  "clan_tag": "#2PP",
  "deleted_log_types": ["join_log", "leave_log", "donation_log"]
}
```

---

## Discord Channel/Thread Endpoints

### GET /v2/server/{server_id}/channels
Get all text channels for a Discord server.

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `rest: hikari.RESTApp` (injected)
- `mongo: MongoClient` (injected)

**Returns:** List of ChannelInfo
```json
[
  {
    "id": "123456789",
    "name": "general",
    "type": "text",
    "parent_id": "987654321",
    "parent_name": "CATEGORY NAME"
  }
]
```

---

### GET /v2/server/{server_id}/threads
Get all active threads for a Discord server.

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `rest: hikari.RESTApp` (injected)
- `mongo: MongoClient` (injected)

**Returns:** List of ThreadInfo
```json
[
  {
    "id": "123456789",
    "name": "Discussion Thread",
    "parent_channel_id": "987654321",
    "parent_channel_name": "general",
    "archived": false
  }
]
```

---

## Reminders Endpoints

### GET /v2/server/{server_id}/reminders
Get all reminders for a server (grouped by type).

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)

**Returns:** Reminders grouped by type (war, clan_capital, clan_games, inactivity, roster)

---

### POST /v2/server/{server_id}/reminders
Create a new reminder.

**Parameters:**
- `server_id: int` - Discord server ID
- `reminder: ClanReminderCreate | RosterReminderCreate`
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)

**Reminder types and fields:**
- **War:** clan, channel, time, types, roles, townhall_filter
- **Clan Games:** clan, channel, time, point_threshold, roles, townhalls
- **Clan Capital:** clan, channel, time, attack_threshold, roles, townhalls
- **Inactivity:** clan, channel, time, roles, townhall_filter
- **Roster:** roster, channel, time, ping_type

**Returns:**
```json
{
  "message": "Reminder created successfully",
  "reminder_id": "abc123",
  "server_id": 123
}
```

---

### PUT /v2/server/{server_id}/reminders/{reminder_id}
Update a reminder.

**Parameters:**
- `server_id: int` - Discord server ID
- `reminder_id: str` - Reminder ID
- `reminder: UpdateReminderRequest`
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)

---

### DELETE /v2/server/{server_id}/reminders/{reminder_id}
Delete a reminder.

**Parameters:**
- `server_id: int` - Discord server ID
- `reminder_id: str` - Reminder ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo: MongoClient` (injected)

---

## Role Management Endpoints

### GET /v2/server/{server_id}/roles/{role_type}
List all roles of a specific type.

**Parameters:**
- `server_id: int` - Discord server ID
- `role_type: RoleType` - Type of role
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo_client: MongoClient` (injected)

**Role types:**
- `townhall` - Townhall level roles
- `league` - League roles
- `builderhall` - Builder hall level roles
- `builder_league` - Builder league roles
- `achievement` - Achievement-based roles
- `status` - Discord tenure roles
- `family_position` - Family position roles

**Returns:**
```json
{
  "server_id": 123,
  "role_type": "townhall",
  "roles": [...],
  "count": 5
}
```

---

### POST /v2/server/{server_id}/roles/{role_type}
Create a new role.

**Parameters:**
- `server_id: int` - Discord server ID
- `role_type: RoleType` - Type of role
- `role_data: Union[TownhallRoleCreate, LeagueRoleCreate, ...]` - Role configuration
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo_client: MongoClient` (injected)

**Role creation models:**
- **TownhallRoleCreate:** role_id, th (1-17), toggle
- **LeagueRoleCreate:** role_id, league, toggle
- **BuilderHallRoleCreate:** role_id, bh (1-10), toggle
- **BuilderLeagueRoleCreate:** role_id, league, toggle
- **AchievementRoleCreate:** role_id, achievement, toggle
- **StatusRoleCreate:** role_id (or id), months
- **FamilyPositionRoleCreate:** role_id, type, toggle

**Returns:**
```json
{
  "message": "Townhall role created successfully",
  "server_id": 123,
  "role_type": "townhall",
  "role_id": 987654321
}
```

---

### DELETE /v2/server/{server_id}/roles/{role_type}/{role_id}
Delete a role by its Discord role ID.

**Parameters:**
- `server_id: int` - Discord server ID
- `role_type: RoleType` - Type of role
- `role_id: int` - Discord role ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`
- `mongo_client: MongoClient` (injected)

---

## Autoboards Endpoints

### GET /v2/server/{server_id}/autoboards
Get all autoboards for a server.

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`

---

### POST /v2/server/{server_id}/autoboards
Create a new autoboard.

**Parameters:**
- `server_id: int` - Discord server ID
- `autoboard: AutoboardCreate`
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`

---

### PATCH /v2/server/{server_id}/autoboards/{autoboard_id}
Update an autoboard.

**Parameters:**
- `server_id: int` - Discord server ID
- `autoboard_id: str` - Autoboard ID
- `autoboard: AutoboardUpdate`
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`

---

### DELETE /v2/server/{server_id}/autoboards/{autoboard_id}
Delete an autoboard.

**Parameters:**
- `server_id: int` - Discord server ID
- `autoboard_id: str` - Autoboard ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`

---

## Links Endpoints

### GET /v2/server/{server_id}/links
Get all member links for a server.

**Parameters:**
- `server_id: int` - Discord server ID
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`

---

### DELETE /v2/server/{server_id}/links/{user_discord_id}/{player_tag}
Unlink account from member.

**Parameters:**
- `server_id: int` - Discord server ID
- `user_discord_id: str` - Discord user ID
- `player_tag: str` - Player tag
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`

---

### POST /v2/server/{server_id}/links/bulk-unlink
Bulk unlink accounts from member.

**Parameters:**
- `server_id: int` - Discord server ID
- `unlink_request: BulkUnlinkRequest`
- `user_id: str = None`
- `credentials: HTTPAuthorizationCredentials = Depends(security)`

---

## Authentication

All endpoints use:
- `@check_authentication` decorator for security
- `@linkd.ext.fastapi.inject` for dependency injection
- `HTTPAuthorizationCredentials = Depends(security)` for Bearer token

## Common Injected Dependencies

- `mongo: MongoClient` or `mongo_client: MongoClient` - Database client
- `rest: hikari.RESTApp` - Discord REST API client (for channel/thread/webhook operations)
- `coc_client: CustomClashClient` - Clash of Clans API client (for clan operations)

## Response Format

All endpoints return consistent JSON responses:
```json
{
  "message": "Operation successful",
  "server_id": 123,
  // ... additional fields
}
```

## Error Codes

- **404** - Resource not found (server, clan, role, reminder)
- **400** - Bad request (missing fields, invalid format)
- **403** - Forbidden (bot lacks permissions)
- **409** - Conflict (duplicate resource)
- **500** - Server error (database issues)
