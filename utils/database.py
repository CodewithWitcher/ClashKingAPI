import pymongo
from pymongo.asynchronous.collection import AsyncCollection

from utils.config import Config

config = Config()

from pymongo import AsyncMongoClient
from redis import asyncio as redis


class MongoClient(AsyncMongoClient):
    # ClashKing database collections
    button_store: AsyncCollection
    coc_accounts: AsyncCollection
    rosters: AsyncCollection
    roster_groups: AsyncCollection
    roster_signup_categories: AsyncCollection
    roster_automation: AsyncCollection
    tokens: AsyncCollection
    autoboards: AsyncCollection
    bot_sync: AsyncCollection
    giveaways : AsyncCollection
    link_shortner: AsyncCollection

    # Settings database collections
    clans: AsyncCollection

    # Auth database collections
    users: AsyncCollection
    auth_discord_tokens: AsyncCollection
    auth_refresh_tokens: AsyncCollection
    auth_email_verifications: AsyncCollection
    auth_password_reset_tokens: AsyncCollection

    # New Looper database collections
    player_stats: AsyncCollection
    leaderboard_db: AsyncCollection
    clan_leaderboard_db: AsyncCollection
    clan_stats: AsyncCollection
    legend_rankings: AsyncCollection
    player_history: AsyncCollection
    player_stats: AsyncCollection

    # Cache database collections
    capital_cache: AsyncCollection
    capital: AsyncCollection

    # Looper database collections
    history_db: AsyncCollection
    clan_wars: AsyncCollection
    clan_join_leave: AsyncCollection
    join_leave_history: AsyncCollection
    war_timer: AsyncCollection
    new_player_stats: AsyncCollection
    raid_weekend_db: AsyncCollection
    cwl_db: AsyncCollection
    cwl_groups: AsyncCollection
    war_elo: AsyncCollection
    warhits: AsyncCollection
    basic_clan: AsyncCollection
    legend_history: AsyncCollection

    # Ranking history
    player_leaderboard: AsyncCollection
    player_trophies: AsyncCollection
    player_versus_trophies: AsyncCollection
    clan_versus_trophies: AsyncCollection
    clan_trophies: AsyncCollection
    capital_trophies: AsyncCollection

    # Bot settings & usafam database collections
    server_db: AsyncCollection
    clan_db: AsyncCollection
    reminders: AsyncCollection
    banlist: AsyncCollection
    strike_list: AsyncCollection
    townhall_roles: AsyncCollection
    legend_league_roles: AsyncCollection
    builderhall_roles: AsyncCollection
    builder_league_roles: AsyncCollection
    achievement_roles: AsyncCollection
    family_roles: AsyncCollection
    general_family_roles: AsyncCollection
    not_family_roles: AsyncCollection
    family_exclusive_roles: AsyncCollection
    ignored_roles: AsyncCollection
    bot_settings: AsyncCollection
    ticketing: AsyncCollection
    embeds: AsyncCollection
    open_tickets: AsyncCollection
    user_settings: AsyncCollection

    def __init__(self, uri: str, **kwargs):
        super().__init__(host=uri, **kwargs)

        # ClashKing database
        self.__clashking = self.get_database('clashking')
        self.button_store = self.__clashking.get_collection('button_store')
        self.coc_accounts = self.__clashking.get_collection('coc_accounts')
        self.rosters = self.__clashking.get_collection('rosters')
        self.roster_groups = self.__clashking.get_collection('roster_groups')
        self.roster_signup_categories = self.__clashking.get_collection('roster_signup_categories')
        self.roster_automation = self.__clashking.get_collection('roster_automation')
        self.tokens = self.__clashking.get_collection('tokens')
        self.autoboards = self.__clashking.get_collection('autoboards')
        self.bot_sync = self.__clashking.get_collection('bot_sync')
        self.giveaways = self.__clashking.get_collection('giveaways')
        self.link_shortner = self.__clashking.get_collection('short_links')

        # Settings database
        self.__settings = self.get_database('settings')
        self.clans = self.__settings.get_collection('clans')
        self.__auth = self.get_database('auth')
        self.users = self.__auth.get_collection('users')
        self.auth_discord_tokens = self.__auth.get_collection('discord_tokens')
        self.auth_refresh_tokens = self.__auth.get_collection('refresh_tokens')
        self.auth_email_verifications = self.__auth.get_collection('email_verifications')
        self.auth_password_reset_tokens = self.__auth.get_collection('password_reset_tokens')

        # New Looper database
        self.__new_looper = self.get_database('new_looper')
        self.player_stats = self.__new_looper.get_collection('player_stats')
        self.leaderboard_db = self.__new_looper.get_collection('leaderboard_db')
        self.clan_leaderboard_db = self.__new_looper.get_collection('clan_leaderboard_db')
        self.clan_stats = self.__new_looper.get_collection('clan_stats')
        self.legend_rankings = self.__new_looper.get_collection('legend_rankings')
        self.player_history = self.__new_looper.get_collection('player_history')

        # Cache database
        self.__cache = self.get_database('cache')
        self.capital_cache = self.__cache.get_collection('capital_raids')
        self.capital = self.__cache.get_collection('capital_raids')  # Alias for v1 compatibility

        # Looper database
        self.__looper = self.get_database('looper')
        self.history_db = self.__looper.get_collection('legend_history')
        self.clan_wars = self.__looper.get_collection('clan_war')
        self.clan_join_leave = self.__looper.get_collection('join_leave_history')
        self.join_leave_history = self.__looper.get_collection('join_leave_history')  # Alias for v1 compatibility
        self.war_timer = self.__looper.get_collection('war_timer')
        self.new_player_stats = self.__looper.get_collection('player_stats')
        self.raid_weekend_db = self.__looper.get_collection('raid_weekends')
        self.cwl_db = self.__looper.get_collection('cwl_db')
        self.cwl_groups = self.__looper.get_collection('cwl_group')
        self.war_elo = self.__looper.get_collection('war_elo')
        self.warhits = self.__looper.get_collection('warhits')
        self.basic_clan = self.__looper.get_collection('clan_tags')
        self.legend_history = self.__looper.get_collection('legend_history')

        # Ranking history database
        self.__ranking_history = self.get_database('ranking_history')
        self.player_leaderboard = self.__ranking_history.get_collection('player_leaderboard')
        self.player_trophies = self.__ranking_history.get_collection('player_trophies')
        self.player_versus_trophies = self.__ranking_history.get_collection('player_versus_trophies')
        self.clan_versus_trophies = self.__ranking_history.get_collection('clan_versus_trophies')
        self.clan_trophies = self.__ranking_history.get_collection('clan_trophies')
        self.capital_trophies = self.__ranking_history.get_collection('capital')  # Alias for v1 compatibility

        # Second connection for static_mongodb (bot settings)
        self.__static_client = pymongo.AsyncMongoClient(
            config.static_mongodb, compressors=['snappy', 'zlib']
        )

        # Usafam database
        self.__bot_usafam = self.__static_client.get_database('usafam')
        self.server_db = self.__bot_usafam.get_collection('server')
        self.clan_db = self.__bot_usafam.get_collection('clans')
        self.reminders = self.__bot_usafam.get_collection('reminders')
        self.banlist = self.__bot_usafam.get_collection('banlist')
        self.strike_list = self.__bot_usafam.get_collection('strikes')
        self.townhall_roles = self.__bot_usafam.get_collection('townhallroles')
        self.legend_league_roles = self.__bot_usafam.get_collection('legendleagueroles')
        self.builderhall_roles = self.__bot_usafam.get_collection('builderhallroles')
        self.builder_league_roles = self.__bot_usafam.get_collection('builderleagueroles')
        self.achievement_roles = self.__bot_usafam.get_collection('achievementroles')
        self.family_roles = self.__bot_usafam.get_collection('family_roles')
        self.general_family_roles = self.__bot_usafam.get_collection('generalrole')
        self.not_family_roles = self.__bot_usafam.get_collection('linkrole')
        self.family_exclusive_roles = self.__bot_usafam.get_collection('familyexclusiveroles')
        self.ignored_roles = self.__bot_usafam.get_collection('evalignore')
        self.ticketing = self.__bot_usafam.get_collection('tickets')
        self.embeds = self.__bot_usafam.get_collection('custom_embeds')
        self.open_tickets = self.__bot_usafam.get_collection('open_tickets')
        self.user_settings = self.__bot_usafam.get_collection('user_settings')

        # Bot settings database
        self.__bot = self.__static_client.get_database('bot')
        self.bot_settings = self.__bot.get_collection('settings')


class OldMongoClient:
    looper_db = pymongo.AsyncMongoClient(
        config.stats_mongodb, compressors=['snappy', 'zlib']
    )
    db_client = pymongo.AsyncMongoClient(
        config.static_mongodb, compressors=['snappy', 'zlib']
    )

    # Databases
    new_looper = looper_db.get_database('new_looper')
    stats = looper_db.get_database('stats')
    cache = looper_db.get_database('cache')
    looper = looper_db.get_database('looper')
    clashking = looper_db.get_database('clashking')
    auth = looper_db.get_database('auth')
    bot_settings = db_client.get_database('usafam')

    # Collections (Looper)
    history_db = looper.get_collection('legend_history')
    warhits = looper.get_collection('warhits')
    webhook_message_db = looper.get_collection('webhook_messages')
    cwl_db = looper.get_collection('cwl_db')
    clan_wars = looper.get_collection('clan_war')
    command_stats = new_looper.get_collection('command_stats')
    player_history = new_looper.get_collection('player_history')
    clan_history = new_looper.get_collection('clan_history')
    clan_cache = new_looper.get_collection('clan_cache')
    war_elo = looper.get_collection('war_elo')
    raid_weekend_db = looper.get_collection('raid_weekends')
    clan_join_leave = looper.get_collection('join_leave_history')
    base_stats = looper.get_collection('base_stats')
    cwl_groups = looper.get_collection('cwl_group')
    basic_clan = looper.get_collection('clan_tags')
    war_timer = looper.get_collection('war_timer')
    new_player_stats = looper.get_collection('player_stats')

    # Collections (ClashKing)
    excel_templates = clashking.get_collection('excel_templates')
    giveaways = clashking.get_collection('giveaways')
    tokens_db = clashking.get_collection('tokens')
    lineups = clashking.get_collection('lineups')
    bot_stats = clashking.get_collection('bot_stats')
    autoboards = clashking.get_collection('autoboards')
    number_emojis = clashking.get_collection('number_emojis')
    groups = clashking.get_collection('groups')
    coc_accounts = clashking.get_collection('coc_accounts')

    # Collections (Auth)
    app_users = auth.get_collection('users')

    # Collections (Stats & New Looper)
    base_player = stats.get_collection('base_player')
    legends_stats = stats.get_collection('legends_stats')
    season_stats = stats.get_collection('season_stats')
    capital_cache = cache.get_collection('capital_raids')
    player_stats = new_looper.get_collection('player_stats')
    leaderboard_db = new_looper.get_collection('leaderboard_db')
    clan_leaderboard_db = new_looper.get_collection('clan_leaderboard_db')
    clan_stats = new_looper.get_collection('clan_stats')
    legend_rankings = new_looper.get_collection('legend_rankings')

    # Collections (Bot Settings)
    clan_db = bot_settings.get_collection('clans')
    banlist = bot_settings.get_collection('banlist')
    server_db = bot_settings.get_collection('server')
    profile_db = bot_settings.get_collection('profile_db')
    ignored_roles = bot_settings.get_collection('evalignore')
    general_family_roles = bot_settings.get_collection('generalrole')
    family_exclusive_roles = bot_settings.get_collection(
        'familyexclusiveroles'
    )
    family_position_roles = bot_settings.get_collection('family_roles')
    not_family_roles = bot_settings.get_collection('linkrole')
    townhall_roles = bot_settings.get_collection('townhallroles')
    builderhall_roles = bot_settings.get_collection('builderhallroles')
    legendleague_roles = bot_settings.get_collection('legendleagueroles')
    builderleague_roles = bot_settings.get_collection('builderleagueroles')
    donation_roles = bot_settings.get_collection('donationroles')
    achievement_roles = bot_settings.get_collection('achievementroles')
    status_roles = bot_settings.get_collection('statusroles')
    welcome = bot_settings.get_collection('welcome')
    button_db = bot_settings.get_collection('button_db')
    legend_profile = bot_settings.get_collection('legend_profile')
    youtube_channels = bot_settings.get_collection('youtube_channels')
    reminders = bot_settings.get_collection('reminders')
    whitelist = bot_settings.get_collection('whitelist')
    rosters = bot_settings.get_collection('rosters')
    credentials = bot_settings.get_collection('credentials')
    global_chat_db = bot_settings.get_collection('global_chats')
    global_reports = bot_settings.get_collection('reports')
    strike_list = bot_settings.get_collection('strikes')

    custom_bots = bot_settings.get_collection('custom_bots')
    suggestions = bot_settings.get_collection('suggestions')

    personal_reminders = bot_settings.get_collection('personal_reminders')
    tickets = bot_settings.get_collection('tickets')
    open_tickets = bot_settings.get_collection('open_tickets')
    custom_embeds = bot_settings.get_collection('custom_embeds')
    custom_commands = bot_settings.get_collection('custom_commands')
    bases = bot_settings.get_collection('bases')
    colors = bot_settings.get_collection('colors')
    level_cards = bot_settings.get_collection('level_cards')
    autostrikes = bot_settings.get_collection('autostrikes')
    user_settings = bot_settings.get_collection('user_settings')
    custom_boards = bot_settings.get_collection('custom_boards')
    trials = bot_settings.get_collection('trials')
    autoboard_db = bot_settings.get_collection('autoboard_db')
    player_search = bot_settings.get_collection('player_search')

cache = redis.Redis(
    host=config.redis_ip,
    port=6379,
    db=0,
    password=config.redis_pw,
    decode_responses=False,
    max_connections=50,
    health_check_interval=10,
    socket_connect_timeout=5,
    retry_on_timeout=True,
    socket_keepalive=True,
)
