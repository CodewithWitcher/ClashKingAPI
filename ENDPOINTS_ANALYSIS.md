# ClashKingAPI vs ClashKingBot - Endpoints Analysis

## Date: 2025-01-16

Cette analyse compare les fonctionnalités de ClashKingBot (branche v2.0) avec les endpoints disponibles dans ClashKingAPI (branche feat/dashboard) pour identifier ce qui manque ou doit être amélioré.

---

## ✅ Endpoints déjà implémentés

### Server Settings
- ✅ **GET** `/v2/server/{server_id}/settings` - Récupère tous les settings serveur
- ✅ **PUT** `/v2/server/{server_id}/embed-color/{hex_code}` - Met à jour la couleur d'embed
- ✅ **GET** `/v2/{server_id}/channels` - Liste les channels Discord

### Clan Settings
- ✅ **GET** `/v2/server/{server_id}/clan/{clan_tag}/settings` - Settings d'un clan spécifique
- ✅ **GET** `/v2/{server_id}/clans` - Liste tous les clans du serveur

### Logs Configuration
- ✅ **GET** `/v2/{server_id}/logs` - Récupère la configuration des logs
- ✅ **PUT** `/v2/{server_id}/logs` - Met à jour la configuration des logs
- ✅ **PATCH** `/v2/{server_id}/logs/{log_type}` - Met à jour un type de log spécifique

### Reminders
- ✅ **GET** `/v2/{server_id}/reminders` - Liste tous les reminders
- ✅ **POST** `/v2/{server_id}/reminders` - Crée un reminder
- ✅ **PUT** `/v2/{server_id}/reminders/{reminder_id}` - Met à jour un reminder
- ✅ **DELETE** `/v2/{server_id}/reminders/{reminder_id}` - Supprime un reminder

### Autoboards
- ✅ **GET** `/v2/{server_id}/autoboards` - Liste les autoboards
- ✅ **POST** `/v2/{server_id}/autoboards` - Crée un autoboard
- ✅ **PATCH** `/v2/{server_id}/autoboards/{autoboard_id}` - Met à jour un autoboard
- ✅ **DELETE** `/v2/{server_id}/autoboards/{autoboard_id}` - Supprime un autoboard

### Links (Liens joueurs)
- ✅ **GET** `/v2/{server_id}/links` - Liste tous les liens serveur
- ✅ **DELETE** `/v2/{server_id}/links/{user_discord_id}/{player_tag}` - Supprime un lien
- ✅ **POST** `/v2/{server_id}/links/bulk-unlink` - Supprime plusieurs liens

---

## ❌ Endpoints manquants (par priorité)

### 🔴 PRIORITÉ HAUTE - Settings Serveur

#### Nickname & Eval Settings
- ❌ **PUT** `/v2/server/{server_id}/nickname/family-convention` - Convention de surnom pour membres famille
- ❌ **PUT** `/v2/server/{server_id}/nickname/non-family-convention` - Convention de surnom pour non-famille
- ❌ **PUT** `/v2/server/{server_id}/nickname/auto-eval` - Active/désactive l'auto-eval
- ❌ **PUT** `/v2/server/{server_id}/nickname/change-nickname` - Active/désactive le changement de surnom
- ❌ **PUT** `/v2/server/{server_id}/nickname/flair-non-family` - Active/désactive le flair pour non-famille

**ClashKingBot fields:**
```python
self.family_nickname_convention = data.get('nickname_rule', '{discord_display_name}')
self.non_family_nickname_convention = data.get('non_family_nickname_rule', '{discord_display_name}')
self.change_nickname = data.get('change_nickname', True)
self.flair_non_family: bool = data.get('flair_non_family', True)
self.auto_eval_nickname: bool = data.get('auto_eval_nickname', False)
```

#### Auto-Eval Configuration
- ❌ **PUT** `/v2/server/{server_id}/autoeval/triggers` - Configure les triggers d'auto-eval
- ❌ **PUT** `/v2/server/{server_id}/autoeval/log-channel` - Channel de log pour auto-eval
- ❌ **PUT** `/v2/server/{server_id}/autoeval/status` - Active/désactive auto-eval

**ClashKingBot fields:**
```python
self.autoeval_triggers = set(data.get('autoeval_triggers', AUTOREFRESH_TRIGGERS))
self.auto_eval_log = data.get('autoeval_log')
self.auto_eval_status = data.get('autoeval', False)
```

#### Role Management
- ❌ **POST** `/v2/server/{server_id}/roles/blacklisted` - Ajoute un rôle blacklisté
- ❌ **DELETE** `/v2/server/{server_id}/roles/blacklisted/{role_id}` - Retire un rôle blacklisté
- ❌ **PUT** `/v2/server/{server_id}/roles/treatment` - Met à jour le traitement des rôles
- ❌ **PUT** `/v2/server/{server_id}/roles/full-whitelist` - Définit le rôle whitelist complet

**ClashKingBot fields:**
```python
self.blacklisted_roles: List[int] = data.get('blacklisted_roles', [])
self.role_treatment: List[str] = data.get('role_treatment', ROLE_TREATMENT_TYPES)
```

#### Other Server Settings
- ❌ **PUT** `/v2/server/{server_id}/leadership-eval` - Active/désactive l'eval leadership
- ❌ **PUT** `/v2/server/{server_id}/autoboard-limit` - Limite d'autoboards
- ❌ **PUT** `/v2/server/{server_id}/api-token` - Active/désactive l'API token
- ❌ **PUT** `/v2/server/{server_id}/tied-stats` - Active/désactive les stats liées
- ❌ **PUT** `/v2/server/{server_id}/banlist-channel` - Channel de banlist
- ❌ **PUT** `/v2/server/{server_id}/strike-log-channel` - Channel de log des strikes
- ❌ **PUT** `/v2/server/{server_id}/family-label` - Label de la famille
- ❌ **PUT** `/v2/server/{server_id}/greeting` - Message de bienvenue serveur
- ❌ **PUT** `/v2/server/{server_id}/reddit-feed` - Channel du feed Reddit

#### Link Parse Configuration
- ❌ **PUT** `/v2/server/{server_id}/link-parse` - Configure le parsing des liens
  - Champs: `clan`, `army`, `player`, `base`, `show`

**ClashKingBot fields:**
```python
self.clan_link_parse = data.get('link_parse', {}).get('clan', True)
self.army_link_parse = data.get('link_parse', {}).get('army', True)
self.player_link_parse = data.get('link_parse', {}).get('player', True)
self.base_link_parse = data.get('link_parse', {}).get('base', True)
self.show_command_parse = data.get('link_parse', {}).get('show', True)
```

### 🔴 PRIORITÉ HAUTE - Settings Clan

#### Basic Clan Settings
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-role` - Rôle des membres
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/leader-role` - Rôle des leaders
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/clan-channel` - Channel du clan
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/category` - Catégorie du clan
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/abbreviation` - Abréviation du clan
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/greeting` - Message de bienvenue clan
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/auto-greet` - Option d'auto-greet
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/leadership-eval` - Eval des leaders

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
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/war-countdown` - Channel countdown de guerre
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/war-timer-countdown` - Channel timer de guerre
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/ban-alert-channel` - Channel d'alerte ban

#### Member Count Warning
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/channel` - Channel d'alerte
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/above` - Seuil haut
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/below` - Seuil bas
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/member-warning/role` - Rôle à ping

**ClashKingBot fields:**
```python
class MemberCountWarning:
    self.channel = self.data.get('channel')
    self.above = self.data.get('above')
    self.below = self.data.get('below')
    self.role = self.data.get('role')
```

#### Log Buttons Configuration
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/logs/join/profile-button` - Bouton profil
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/logs/leave/strike-button` - Bouton strike
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/logs/leave/ban-button` - Bouton ban

#### Server Events
- ❌ **PUT** `/v2/server/{server_id}/clan/{clan_tag}/events/{type}` - Active/désactive événements Discord

### 🟡 PRIORITÉ MOYENNE - Roles

#### Townhall Roles
- ❌ **GET** `/v2/server/{server_id}/roles/townhall` - Liste les rôles TH
- ❌ **POST** `/v2/server/{server_id}/roles/townhall` - Crée un rôle TH
- ❌ **DELETE** `/v2/server/{server_id}/roles/townhall/{role_id}` - Supprime un rôle TH

#### League Roles
- ❌ **GET** `/v2/server/{server_id}/roles/league` - Liste les rôles de ligue
- ❌ **POST** `/v2/server/{server_id}/roles/league` - Crée un rôle de ligue
- ❌ **DELETE** `/v2/server/{server_id}/roles/league/{role_id}` - Supprime un rôle de ligue

#### Builder Hall/League Roles
- ❌ **GET** `/v2/server/{server_id}/roles/builderhall` - Liste les rôles BH
- ❌ **POST** `/v2/server/{server_id}/roles/builderhall` - Crée un rôle BH
- ❌ **DELETE** `/v2/server/{server_id}/roles/builderhall/{role_id}` - Supprime un rôle BH

#### Achievement Roles
- ❌ **GET** `/v2/server/{server_id}/roles/achievement` - Liste les rôles d'achievement
- ❌ **POST** `/v2/server/{server_id}/roles/achievement` - Crée un rôle d'achievement
- ❌ **DELETE** `/v2/server/{server_id}/roles/achievement/{role_id}` - Supprime un rôle d'achievement

#### Status Roles (Discord tenure)
- ❌ **GET** `/v2/server/{server_id}/roles/status` - Liste les rôles de statut
- ❌ **POST** `/v2/server/{server_id}/roles/status` - Crée un rôle de statut
- ❌ **DELETE** `/v2/server/{server_id}/roles/status/{role_id}` - Supprime un rôle de statut

#### Family Position Roles
- ❌ **GET** `/v2/server/{server_id}/roles/family-position` - Liste les rôles de position
- ❌ **POST** `/v2/server/{server_id}/roles/family-position` - Crée un rôle de position
- ❌ **DELETE** `/v2/server/{server_id}/roles/family-position/{role_id}` - Supprime un rôle de position

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

### 🟡 PRIORITÉ MOYENNE - Clan Management

#### Add/Remove Clans
- ❌ **POST** `/v2/server/{server_id}/clans` - Ajoute un clan au serveur
- ❌ **DELETE** `/v2/server/{server_id}/clans/{clan_tag}` - Retire un clan du serveur

---

## ⚠️ Incohérences de schéma détectées

### 1. Reminders - Champs townhall
**Problème:** ✅ Déjà corrigé
- Clan Capital et Clan Games utilisent `townhalls`
- War et Inactivity utilisent `townhall_filter`

### 2. Logs Configuration
**À vérifier:** Les types de logs supportés
ClashKingBot gère ces types de logs:
- `join_log`, `leave_log`
- `capital_donations`, `capital_attacks`, `raid_map`, `capital_weekly_summary`
- `donation_log`, `clan_achievement_log`, `clan_requirements_log`, `clan_description_log`
- `cwl_lineup_change`, `super_troop_boost`, `role_change`
- `troop_upgrade`, `th_upgrade`, `league_change`, `spell_upgrade`, `hero_upgrade`, `hero_equipment_upgrade`
- `name_change`, `war_log`, `legend_log_attacks`, `legend_log_defenses`
- `war_panel`, `raid_panel` (panels avec message tracking)

**Action:** Vérifier que tous ces types sont supportés dans l'API

### 3. Panels (War Panel, Raid Panel)
**Structure spéciale:**
```python
class WarPanel(ClanLog):
    self.war_id = self.data.get('war_id')
    self.message_id = self.data.get('war_message')
    self.channel_id = self.data.get('war_channel')

class CapitalPanel(ClanLog):
    self.raid_id = self.data.get('raid_id')
    self.message_id = self.data.get('raid_message')
```

Ces panels ont des IDs de message spécifiques et nécessitent peut-être des endpoints dédiés.

---

## 📊 Résumé des manques

| Catégorie | Endpoints manquants | Priorité |
|-----------|-------------------|----------|
| Server Settings (général) | ~15 | 🔴 Haute |
| Server Settings (nickname/eval) | ~5 | 🔴 Haute |
| Server Settings (roles) | ~4 | 🔴 Haute |
| Clan Settings (basic) | ~8 | 🔴 Haute |
| Clan Settings (war) | ~3 | 🔴 Haute |
| Clan Settings (member warning) | ~4 | 🔴 Haute |
| Clan Settings (log buttons) | ~3 | 🔴 Haute |
| Role Management (all types) | ~18 | 🟡 Moyenne |
| Clan Management | ~2 | 🟡 Moyenne |
| **TOTAL** | **~62 endpoints** | |

---

## 🎯 Recommandations

### Approche par phase

#### Phase 1 - Settings de base (2-3 jours)
1. Créer endpoints PUT pour les settings serveur de base
2. Créer endpoints PUT pour les settings clan de base
3. Tester la compatibilité avec ClashKingBot

#### Phase 2 - Settings avancés (2-3 jours)
1. Endpoints pour nickname/eval configuration
2. Endpoints pour member warning
3. Endpoints pour war settings

#### Phase 3 - Gestion des rôles (3-4 jours)
1. Endpoints CRUD pour chaque type de rôle
2. Validation des règles de rôles
3. Tests d'intégration

#### Phase 4 - Clan Management (1-2 jours)
1. Add/Remove clans
2. Validation des permissions

### Structure recommandée

```
routers/v2/server/
├── server.py (settings généraux serveur)
├── server_models.py
├── clans.py (settings de clans)
├── clan_models.py
├── roles.py (gestion des rôles)
├── roles_models.py
├── logs.py (déjà existant)
├── reminders.py (déjà existant)
├── autoboards.py (déjà existant)
└── links.py (déjà existant)
```

### Conventions à suivre

1. **Authentification:** Utiliser `@check_authentication` sur tous les endpoints
2. **Injection:** Utiliser `@linkd.ext.fastapi.inject` pour MongoClient
3. **Validation:** Pydantic models pour toutes les requêtes
4. **Réponses:** Format standardisé `{"message": "...", "data": {...}}`
5. **Erreurs:** HTTPException avec codes appropriés (404, 400, 403)

---

## 🔍 Points d'attention

1. **Collections MongoDB séparées**
   - ClashKingBot utilise des collections séparées pour certains rôles (townhallroles, legendleagueroles, etc.)
   - L'API devra faire des lookups ou agrégations pour récupérer toutes les données

2. **Format des données**
   - S'assurer que les formats d'input/output sont cohérents
   - Conversion ObjectId ↔ string
   - Conversion int ↔ string pour les IDs Discord

3. **Permissions**
   - Vérifier que l'utilisateur a les droits sur le serveur
   - Vérifier que les channels/rôles existent dans le serveur Discord

4. **Validation**
   - Valider les clan tags (format #XXXXXXXX)
   - Valider les IDs Discord (snowflakes)
   - Valider les hex codes pour les couleurs

---

## ✅ Prochaines étapes suggérées

1. **Créer les endpoints manquants prioritaires** (server settings, clan settings)
2. **Créer les modèles Pydantic** pour chaque type de setting
3. **Tester la compatibilité** avec les données existantes de ClashKingBot
4. **Documenter** chaque endpoint avec exemples
5. **Créer tests unitaires** pour vérifier la logique
