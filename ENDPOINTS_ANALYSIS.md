# ClashKingAPI vs ClashKingBot - Endpoints Analysis

## Date: 2025-01-16

This analysis compares ClashKingBot features (v2.0 branch) with available endpoints in ClashKingAPI (feat/dashboard branch) to identify what's missing or needs improvement.

---

## ✅ Already Implemented Endpoints

### Server Settings
- ✅ **GET** `/v2/server/{server_id}/settings` - Get all server settings
- ✅ **PUT** `/v2/server/{server_id}/embed-color/{hex_code}` - Update embed color
- ✅ **GET** `/v2/{server_id}/channels` - List Discord channels

### Clan Settings
- ✅ **GET** `/v2/server/{server_id}/clan/{clan_tag}/settings` - Get specific clan settings
- ✅ **GET** `/v2/{server_id}/clans` - List all server clans

### Logs Configuration
- ✅ **GET** `/v2/{server_id}/logs` - Get logs configuration
- ✅ **PUT** `/v2/{server_id}/logs` - Update logs configuration
- ✅ **PATCH** `/v2/{server_id}/logs/{log_type}` - Update specific log type

### Reminders
- ✅ **GET** `/v2/{server_id}/reminders` - List all reminders
- ✅ **POST** `/v2/{server_id}/reminders` - Create a reminder
- ✅ **PUT** `/v2/{server_id}/reminders/{reminder_id}` - Update a reminder
- ✅ **DELETE** `/v2/{server_id}/reminders/{reminder_id}` - Delete a reminder

### Autoboards
- ✅ **GET** `/v2/{server_id}/autoboards` - List autoboards
- ✅ **POST** `/v2/{server_id}/autoboards` - Create an autoboard
- ✅ **PATCH** `/v2/{server_id}/autoboards/{autoboard_id}` - Update an autoboard
- ✅ **DELETE** `/v2/{server_id}/autoboards/{autoboard_id}` - Delete an autoboard

### Links (Player Links)
- ✅ **GET** `/v2/{server_id}/links` - List all server links
- ✅ **DELETE** `/v2/{server_id}/links/{user_discord_id}/{player_tag}` - Delete a link
- ✅ **POST** `/v2/{server_id}/links/bulk-unlink` - Bulk delete links

---

## ❌ Missing Endpoints (by priority)

### 🔴 HIGH PRIORITY - Server Settings

#### Nickname & Eval Settings
- ❌ **PUT** `/v2/server/{server_id}/nickname/family-convention` - Family member nickname convention
- ❌ **PUT** `/v2/server/{server_id}/nickname/non-family-convention` - Non-family nickname convention
- ❌ **PUT** `/v2/server/{server_id}/nickname/auto-eval` - Enable/disable auto-eval
- ❌ **PUT** `/v2/server/{server_id}/nickname/change-nickname` - Enable/disable nickname changes
- ❌ **PUT** `/v2/server/{server_id}/nickname/flair-non-family` - Enable/disable non-family flair

**ClashKingBot fields:**
```python
self.family_nickname_convention = data.get('nickname_rule', '{discord_display_name}')
self.non_family_nickname_convention = data.get('non_family_nickname_rule', '{discord_display_name}')
self.change_nickname = data.get('change_nickname', True)
self.flair_non_family: bool = data.get('flair_non_family', True)
self.auto_eval_nickname: bool = data.get('auto_eval_nickname', False)
```

#### Auto-Eval Configuration
- ❌ **PUT** `/v2/server/{server_id}/autoeval/triggers` - Configure auto-eval triggers
- ❌ **PUT** `/v2/server/{server_id}/autoeval/log-channel` - Auto-eval log channel
- ❌ **PUT** `/v2/server/{server_id}/autoeval/status` - Enable/disable auto-eval

**ClashKingBot fields:**
```python
self.autoeval_triggers = set(data.get('autoeval_triggers', AUTOREFRESH_TRIGGERS))
self.auto_eval_log = data.get('autoeval_log')
self.auto_eval_status = data.get('autoeval', False)
```

#### Role Management
- ❌ **POST** `/v2/server/{server_id}/roles/blacklisted` - Add blacklisted role
- ❌ **DELETE** `/v2/server/{server_id}/roles/blacklisted/{role_id}` - Remove blacklisted role
- ❌ **PUT** `/v2/server/{server_id}/roles/treatment` - Update role treatment
- ❌ **PUT** `/v2/server/{server_id}/roles/full-whitelist` - Set full whitelist role

**ClashKingBot fields:**
```python
self.blacklisted_roles: List[int] = data.get('blacklisted_roles', [])
self.role_treatment: List[str] = data.get('role_treatment', ROLE_TREATMENT_TYPES)
```

#### Other Server Settings
- ❌ **PUT** `/v2/server/{server_id}/leadership-eval` - Enable/disable leadership eval
- ❌ **PUT** `/v2/server/{server_id}/autoboard-limit` - Autoboard limit
- ❌ **PUT** `/v2/server/{server_id}/api-token` - Enable/disable API token
- ❌ **PUT** `/v2/server/{server_id}/tied-stats` - Enable/disable tied stats
- ❌ **PUT** `/v2/server/{server_id}/banlist-channel` - Banlist channel
- ❌ **PUT** `/v2/server/{server_id}/strike-log-channel` - Strike log channel
- ❌ **PUT** `/v2/server/{server_id}/family-label` - Family label
- ❌ **PUT** `/v2/server/{server_id}/greeting` - Server welcome message
- ❌ **PUT** `/v2/server/{server_id}/reddit-feed` - Reddit feed channel

#### Link Parse Configuration
- ❌ **PUT** `/v2/server/{server_id}/link-parse` - Configure link parsing
  - Fields: `clan`, `army`, `player`, `base`, `show`

**ClashKingBot fields:**
```python
self.clan_link_parse = data.get('link_parse', {}).get('clan', True)
self.army_link_parse = data.get('link_parse', {}).get('army', True)
self.player_link_parse = data.get('link_parse', {}).get('player', True)
self.base_link_parse = data.get('link_parse', {}).get('base', True)
self.show_command_parse = data.get('link_parse', {}).get('show', True)
```

### 🔴 HIGH PRIORITY - Clan Settings

#### Basic Clan Settings
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-role` - Member role
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/leader-role` - Leader role
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/clan-channel` - Clan channel
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/category` - Clan category
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/abbreviation` - Clan abbreviation
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/greeting` - Clan welcome message
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/auto-greet` - Auto-greet option
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/leadership-eval` - Leadership eval

**ClashKingBot fields:**
```python
self.member_role = data.get('generalRole')
self.leader_role = data.get('leaderRole')
self.clan_channel = data.get('clanChannel')
self.category = data.get('category')
self.abbreviation = data.get('abbreviation', '')
self.greeting = data.get('greeting', '')
self.auto_greet_option = data.get('auto_greet_option', 'Never')
self.leadership_eval = data.get('leadership_eval')
```

#### War Settings
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/war-countdown` - War countdown channel
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/war-timer-countdown` - War timer channel
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/ban-alert-channel` - Ban alert channel

#### Member Count Warning
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/channel` - Alert channel
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/above` - Upper threshold
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/below` - Lower threshold
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/role` - Role to ping

**ClashKingBot fields:**
```python
class MemberCountWarning:
    self.channel = self.data.get('channel')
    self.above = self.data.get('above')
    self.below = self.data.get('below')
    self.role = self.data.get('role')
```

#### Log Buttons Configuration
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/logs/join/profile-button` - Profile button
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/logs/leave/strike-button` - Strike button
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/logs/leave/ban-button` - Ban button

#### Server Events
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/events/{type}` - Enable/disable Discord events

### 🟡 MEDIUM PRIORITY - Roles

#### Townhall Roles
- ❌ **GET** `/v2/server/{server_id}/roles/townhall` - List TH roles
- ❌ **POST** `/v2/server/{server_id}/roles/townhall` - Create TH role
- ❌ **DELETE** `/v2/server/{server_id}/roles/townhall/{role_id}` - Delete TH role

#### League Roles
- ❌ **GET** `/v2/server/{server_id}/roles/league` - List league roles
- ❌ **POST** `/v2/server/{server_id}/roles/league` - Create league role
- ❌ **DELETE** `/v2/server/{server_id}/roles/league/{role_id}` - Delete league role

#### Builder Hall/League Roles
- ❌ **GET** `/v2/server/{server_id}/roles/builderhall` - List BH roles
- ❌ **POST** `/v2/server/{server_id}/roles/builderhall` - Create BH role
- ❌ **DELETE** `/v2/server/{server_id}/roles/builderhall/{role_id}` - Delete BH role

#### Achievement Roles
- ❌ **GET** `/v2/server/{server_id}/roles/achievement` - List achievement roles
- ❌ **POST** `/v2/server/{server_id}/roles/achievement` - Create achievement role
- ❌ **DELETE** `/v2/server/{server_id}/roles/achievement/{role_id}` - Delete achievement role

#### Status Roles (Discord tenure)
- ❌ **GET** `/v2/server/{server_id}/roles/status` - List status roles
- ❌ **POST** `/v2/server/{server_id}/roles/status` - Create status role
- ❌ **DELETE** `/v2/server/{server_id}/roles/status/{role_id}` - Delete status role

#### Family Position Roles
- ❌ **GET** `/v2/server/{server_id}/roles/family-position` - List position roles
- ❌ **POST** `/v2/server/{server_id}/roles/family-position` - Create position role
- ❌ **DELETE** `/v2/server/{server_id}/roles/family-position/{role_id}` - Delete position role

**ClashKingBot fields:**
```python
self.townhall_roles = [TownhallRole(...) for d in data.get('eval', {}).get('townhall_roles', [])]
self.league_roles = [MultiTypeRole(...) for d in data.get('eval', {}).get('league_roles', [])]
self.builderhall_roles = [BuilderHallRole(...)]
self.builder_league_roles = [MultiTypeRole(...)]
self.achievement_roles = [AchievementRole(data=d) for d in data.get('achievement_roles', [])]
self.status_roles = [StatusRole(data=d) for d in data.get('status_roles', {}).get('discord', [])]
self.family_elder_roles, self.family_coleader_roles, self.family_leader_roles
```

### 🟡 MEDIUM PRIORITY - Clan Management

#### Add/Remove Clans
- ❌ **POST** `/v2/server/{server_id}/clans` - Add clan to server
- ❌ **DELETE** `/v2/server/{server_id}/clans/{clan_tag}` - Remove clan from server

---

## ⚠️ Schema Compatibility Issues Detected

### 1. Reminders - Townhall fields
**Status:** ✅ Already fixed
- Clan Capital and Clan Games use `townhalls`
- War and Inactivity use `townhall_filter`

### 2. Logs Configuration
**To verify:** Supported log types
ClashKingBot handles these log types:
- `join_log`, `leave_log`
- `capital_donations`, `capital_attacks`, `raid_map`, `capital_weekly_summary`
- `donation_log`, `clan_achievement_log`, `clan_requirements_log`, `clan_description_log`
- `cwl_lineup_change`, `super_troop_boost`, `role_change`
- `troop_upgrade`, `th_upgrade`, `league_change`, `spell_upgrade`, `hero_upgrade`, `hero_equipment_upgrade`
- `name_change`, `war_log`, `legend_log_attacks`, `legend_log_defenses`
- `war_panel`, `raid_panel` (panels with message tracking)

**Action:** Verify all these types are supported in the API

### 3. Panels (War Panel, Raid Panel)
**Special structure:**
```python
class WarPanel(ClanLog):
    self.war_id = self.data.get('war_id')
    self.message_id = self.data.get('war_message')
    self.channel_id = self.data.get('war_channel')

class CapitalPanel(ClanLog):
    self.raid_id = self.data.get('raid_id')
    self.message_id = self.data.get('raid_message')
```

These panels have specific message IDs and may need dedicated endpoints.

---

## 📊 Missing Endpoints Summary

| Category | Missing Endpoints | Priority |
|----------|------------------|----------|
| Server Settings (general) | ~15 | 🔴 High |
| Server Settings (nickname/eval) | ~5 | 🔴 High |
| Server Settings (roles) | ~4 | 🔴 High |
| Clan Settings (basic) | ~8 | 🔴 High |
| Clan Settings (war) | ~3 | 🔴 High |
| Clan Settings (member warning) | ~4 | 🔴 High |
| Clan Settings (log buttons) | ~3 | 🔴 High |
| Role Management (all types) | ~18 | 🟡 Medium |
| Clan Management | ~2 | 🟡 Medium |
| **TOTAL** | **~62 endpoints** | |

---

## 🎯 Recommendations

### Phased Approach

#### Phase 1 - Basic Settings (2-3 days)
1. Create PUT endpoints for basic server settings
2. Create PUT endpoints for basic clan settings
3. Test compatibility with ClashKingBot

#### Phase 2 - Advanced Settings (2-3 days)
1. Endpoints for nickname/eval configuration
2. Endpoints for member warning
3. Endpoints for war settings

#### Phase 3 - Role Management (3-4 days)
1. CRUD endpoints for each role type
2. Role rule validation
3. Integration testing

#### Phase 4 - Clan Management (1-2 days)
1. Add/Remove clans
2. Permission validation

### Recommended Structure

```
routers/v2/server/
├── server.py (general server settings)
├── server_models.py
├── clans.py (clan settings)
├── clan_models.py
├── roles.py (role management)
├── roles_models.py
├── logs.py (already exists)
├── reminders.py (already exists)
├── autoboards.py (already exists)
└── links.py (already exists)
```

### Conventions to Follow

1. **Authentication:** Use `@check_authentication` on all endpoints
2. **Injection:** Use `@linkd.ext.fastapi.inject` for MongoClient
3. **Validation:** Pydantic models for all requests
4. **Responses:** Standardized format `{"message": "...", "data": {...}}`
5. **Errors:** HTTPException with appropriate codes (404, 400, 403)

---

## 🔍 Key Considerations

1. **Separate MongoDB Collections**
   - ClashKingBot uses separate collections for certain roles (townhallroles, legendleagueroles, etc.)
   - API will need to do lookups or aggregations to retrieve all data

2. **Data Formats**
   - Ensure input/output formats are consistent
   - ObjectId ↔ string conversion
   - int ↔ string conversion for Discord IDs

3. **Permissions**
   - Verify user has rights on the server
   - Verify channels/roles exist in Discord server

4. **Validation**
   - Validate clan tags (format #XXXXXXXX)
   - Validate Discord IDs (snowflakes)
   - Validate hex codes for colors

---

## ✅ Suggested Next Steps

1. **Create missing priority endpoints** (server settings, clan settings)
2. **Create Pydantic models** for each setting type
3. **Test compatibility** with existing ClashKingBot data
4. **Document** each endpoint with examples
5. **Create unit tests** to verify logic
