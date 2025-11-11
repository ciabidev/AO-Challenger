import discord
from discord.ui import View
import threading
import os
import asyncio
import datetime
import math
import aiohttp
from discord.ext import commands
from discord import app_commands
from discord import Interaction, ButtonStyle
from discord.ui import View, Button
from dotenv import load_dotenv
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
import logging
# Set up logging configuration for the bot


        

"""
# GLOBAL PVP THREAD RELAY SYSTEM
# Definitions:

# - Global PVP: The region-based pvp ping system. Will soon change to Regional PVP. Only pings the server the command was used in, unless Cross Server PVP is enabled.
# - Cross Server PVP: When enabled, the global pvp ping will be sent to other servers.

# - Host Server: The server that hosts the global pvp ping
# - Relay Server: The server that recieves the global pvp ping. Includes the host server.
# - Host Thread: Thread where the host can announce stuff to the relay server
# - Relay Thread: Thread where the relay server can send messages to the host server

# - When a host sends a message in their thread, it's forwarded to all relay threads
# - When a player sends a message in a relay thread, it's forwarded to the host thread

# - Cross Server are rate-limited, but not moderated. To block a user from pinging, use `/globalpvp blockuser`.
"""

"""
Bot Initialization
This section handles the bot's startup sequence including:
- Syncing commands
- Setting up presence/activity
- Caching channels and threads
- Clearing old queue entries
"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Development mode flag - affects token and database selection
load_dotenv()  # Load environment variables first before checking DEV_MODE

dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"  # Default to false if not set

# Load environment variables and get Discord bot token

if dev_mode:
    token = os.getenv("TESTING_TOKEN")
else:
    token = os.getenv("DISCORD_TOKEN")

# Configure Discord bot intents
# These determine what events and data the bot can access
intents = discord.Intents.default()
intents.message_content = True  # Allow reading message content
intents.members = True  # Allow accessing member information

# Flask app for web server functionality
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8000))  # Render sets the PORT environment variable
    app.run(host='0.0.0.0', port=port)

# Start Flask in a separate thread so it doesn’t block the bot
threading.Thread(target=run_flask).start()



# MongoDB Database Configuration
# Using motor for asynchronous MongoDB operations
from motor.motor_asyncio import AsyncIOMotorClient

# Set up MongoDB connection and database
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["challenger"]  # Main database for production

if dev_mode:
    db = mongo_client["challenger-testing"]

bot = commands.Bot(command_prefix='?', intents=intents)
import discord
@bot.event
async def on_ready():
    """
    Bot initialization
    """
    logging.info(f"dev mode: {dev_mode}")
    logging.info(f'live on {bot.user.name} - {bot.user.id}') 

    activity = discord.Activity(type=discord.ActivityType.listening, name="/findpvp /globalpvp /help") # display useful commands in bot activity. 
    await bot.change_presence(activity=activity)

    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logging.info(f"Error syncing commands: {e}")

    # Cache all text channels and threads from all guilds

    for guild in bot.guilds:
        # Await the coroutine properly to get the list of active threads
        threads = await guild.active_threads()

        for thread in threads:
            if thread.owner_id == bot.user.id:
                thread_cache[thread.id] = thread
        

    logging.info(f"Cached {len(thread_cache)} possible pvp channels/threads")

    # remove all queue entries on start
    await db.queue.delete_many({})

"""

MAIN BOT CODE

"""

"""
Roblox API Functions
"""
    


# Roblox API Integration
# This section handles all Roblox-related functionality including user verification
# and profile image fetching. The functions were moved into the `RobloxAPI` class
# to group related behavior and make testing/maintenance easier.

class RobloxAPI:
    """
    Helper class for Roblox API operations.

    Methods are async and create short-lived aiohttp sessions per call (same behavior
    as the previous standalone functions). This keeps the refactor minimal and
    backwards-compatible via the wrapper functions defined below.
    """

    def __init__(self):
        # Endpoint for username -> id/metadata lookup
        self.users_endpoint = "https://users.roblox.com/v1/usernames/users"
        # Endpoint for fetching headshot thumbnails
        self.headshot_url = "https://thumbnails.roblox.com/v1/users/avatar-headshot"

    async def user_exists(self, username: str) -> str | None:
        """
        Check whether a Roblox user exists by username.

        Args:
            username (str): Roblox username to check

        Returns:
            str | None: The canonical username if found, otherwise None
        """
        data = {
            "usernames": [username],
            "excludeblockedUsers": False
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.users_endpoint, json=data) as resp:
                if resp.status != 200:
                    logging.error(f"Roblox user lookup failed with status {resp.status}")
                    return None
                result = await resp.json()
                return result.get("data", [])[0].get("name")

    async def get_user_id(self, username: str) -> int | None:
        """
        Retrieve the Roblox user id for a given username.

        Args:
            username (str): Roblox username

        Returns:
            int | None: The numeric user id if found, otherwise None
        """
        data = {
            "usernames": [username],
            "excludeblockedUsers": False
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.users_endpoint, json=data) as resp:
                if resp.status != 200:
                    logging.error(f"Roblox user id lookup failed with status {resp.status}")
                    return None
                result = await resp.json()
                return result.get("data", [])[0].get("id")

    async def get_headshot(self, user_id: int) -> str | None:
        """
        Retrieve a PNG headshot URL for a Roblox user id.

        Args:
            user_id (int): Roblox user id

        Returns:
            str | None: URL to the headshot image if available, otherwise None
        """
        params = {
            "userIds": str(user_id),
            "size": "150x150",
            "format": "Png",
            "isCircular": "false"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(self.headshot_url, params=params) as response:
                if response.status != 200:
                    logging.error(f"Roblox headshot request failed with status {response.status}")
                    return None
                data = await response.json()
                return data.get('data', [])[0].get('imageUrl')

# Instantiate a module-level client for convenience
roblox_api = RobloxAPI()

# Backwards-compatible wrapper functions (preserve original names used elsewhere)
async def roblox_user_exists(username: str) -> bool:
    """
    Wrapper that calls RobloxAPI.user_exists. Returns the username string
    if found, otherwise None. Kept for compatibility with existing call sites.
    """
    return await roblox_api.user_exists(username)


async def get_roblox_user_id(username: str):
    """Wrapper that returns the numeric Roblox user id for a username."""
    return await roblox_api.get_user_id(username)


async def get_roblox_headshot(user_id: int):
    """Wrapper that returns the headshot image URL for a Roblox user id."""
    return await roblox_api.get_headshot(user_id)

# whenever someone uses a command, print the user's id and name
@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command: discord.app_commands.Command):
    """
    Event handler for when a slash command is completed. Logs the user and command information.

    Args:
        interaction (discord.Interaction): The interaction that triggered the command
        command (discord.app_commands.Command): The command that was executed
    """
    user = interaction.user
    logger.info(f"User {user.id} ({user.name}) used slash command '/{command.name}'")


thread_cache = {}

# User management functions for blocking and banning
async def get_blocked_users(guild_id: int):
    """
    Gets a list of blocked users from the database for a given guild

    Args:
        guild_id (int): The ID of the guild to get the blocked users for

    Returns:
        list: A list of blocked users
    """

    # get all blocked users from the database
    cursor = db.blocks.find({"guild_id": guild_id})
    blocked_users = await cursor.to_list()
    userlist = []

    now = datetime.datetime.now(datetime.timezone.utc)

    # iterate through blocked users and check if they are still blocked
    for user in blocked_users:
        try:
            created_at = datetime.datetime.fromisoformat(user["created_at"])
            duration = user.get("duration", 0)

            if now - created_at > datetime.timedelta(days=duration): # check if the user is still blocked
                await db.blocks.delete_one({"username": user["username"], "guild_id": guild_id})
            else:
                userlist.append(user) # add the user to the list if they are still blocked

        except KeyError as e:
            continue
    return userlist
async def is_blocked_user(username: str, guild_id: int):
    """
    Checks if a user is blocked from interacting with a guild through AO Challenger

    Args:
        username (str): The username of the user to check
        guild_id (int): The ID of the guild to check

    Returns:
        bool: true if the user is blocked, false otherwise
    """
    blocked_users = await get_blocked_users(guild_id) # get all blocked users from the database
    for user in blocked_users: # iterate through blocked users and check if the username matches
        if user["username"] == username:
            logging.info(f"user {user} is blocked")
            return True

    return False

async def get_banned_users():
    """
    Gets a list of users banned from using AO Challenger from the database

    Returns:
        list: A list of banned users
    """
    cursor = db.bans.find({})
    banned_users = await cursor.to_list()
    userlist = []

    now = datetime.datetime.now(datetime.timezone.utc)

    for user in banned_users:
        try:
            created_at = datetime.datetime.fromisoformat(user["created_at"])
            userlist.append(user)

        except KeyError as e:
            continue

    return userlist


async def is_banned_user(user_id):
    banned_users = await get_banned_users()
    for user in banned_users: 
        if user["user_id"] == int(user_id):
            logging.info(f"user {user} is banned")
            return True
            break

async def ban_check(interaction: discord.Interaction) -> bool:
    """
    Custom check for every command if the user is banned. Must be used at the top of every command
    """
    if await is_banned_user(interaction.user.id):  # make sure this is an async function if needed
        await interaction.response.send_message(
            "❌ You are banned from using the bot. Appeal here: https://tally.so/r/3X6yqV", # i need to add a "Reason: " section to this so the user knows why they were banned. will probably be in the bannned users db
            ephemeral=True
        )
        return True  # block the command
    return False  # allow command

async def get_relay_threads(host_id: int):
    """
    Gets the relay threads for a host thread

    Args:
        host_id (int): The ID of the host thread

    Returns:
        dict: A dictionary of relay threads
    """
    config = await db.relay_threads.find_one({"host_id": int(host_id)})
    if not config:
        return None
    return config  # Return entire document

relay_threads = {}

@bot.event
async def get_channel_cached(channel_id: int):
    """
    Gets a channel from the cache, or fetches it from Discord if not cached.
    Improves performance by avoiding unnecessary API calls.

    Args:
        channel_id (int): The ID of the channel to get

    Returns:
        discord.TextChannel or None: The channel if found, None if not found
    """
    if channel_id in thread_cache:
        logging.info(f"Returning cached channel {channel_id}")
        return thread_cache[channel_id]
    channel = bot.get_channel(channel_id)
    if channel:
        logging.info(f"Returning channel {channel_id}")
        thread_cache[channel_id] = channel
        return channel
    # fallback to fetching from API
    try:
        logging.info(f"Fetching channel {channel_id}")
        channel = await bot.fetch_channel(channel_id)
        thread_cache[channel_id] = channel
        return channel
    except discord.NotFound:
        logging.error("Channel not found")
        return None


 
@bot.event
async def on_thread_delete(thread):
    """
    Event handler for when a thread is deleted.
    Removes the thread from the cache.

    Args:
        thread (discord.Thread): The thread that was deleted
    """
    thread_cache.pop(thread.id, None)

@bot.event
async def on_guild_channel_delete(channel):
    thread_cache.pop(channel.id, None)

"""
RATE LIMITING
Prevents users from overloading the bot with requests
"""
rate_limited_users = {}

# Duration of cooldown in seconds for rate-limited users
COOLDOWN_DURATION = 5  # in seconds

async def cooldown_timer(user_id):
    for i in range(COOLDOWN_DURATION, 0, -1):
        rate_limited_users[user_id] = i
        await asyncio.sleep(1)
    rate_limited_users.pop(user_id, None)

allowed_mentions = discord.AllowedMentions(everyone=False, roles=False, users=True)

@bot.event
async def on_message(message: discord.Message):
    slurs = ["clanker", "clanka", "wireback", "tinskin", "cogsucker", "clank er", "clank a", "wire back", "tin skin", "404er", "404 er"]
    # if the message has any of the above slurs add reaction
    if any(slur in message.content.lower() for slur in slurs):
        await message.add_reaction("😡")
        


    if message.guild == None:
        return
    
    await get_blocked_users(message.guild.id) # user activity automatically updates blocked users
    if message.author.bot:
        return
    

    
    channel_id = int(message.channel.id)
    user_id = int(message.author.id)    

    if user_id in rate_limited_users and rate_limited_users[user_id] == 5 and message.channel.id in thread_cache:
        # reply to user that they are rate limited ephemeral 
        msg = await message.reply(f"message not published. Please wait {rate_limited_users[user_id]} seconds before sending another message.")
        await asyncio.sleep(2)
        await msg.delete()
        return

    elif message.channel.id in thread_cache:
        if await is_banned_user(message.author.id):
            await message.delete()
            return
        
        # ─── Check if message is from a HOST THREAD ─────────────────────────────
        rate_limited_users[user_id] = COOLDOWN_DURATION
        asyncio.create_task(cooldown_timer(user_id))

        relay_entry = await db.relay_threads.find_one({"relay_thread_id": channel_id})
        host_entry = await db.host_threads.find_one({"host_thread_id": channel_id})
        is_host_of_this_thread = host_entry and host_entry.get("host_id") == user_id

        if host_entry and is_host_of_this_thread:
            logging.info("message is from a host thread")
            host_id = host_entry["host_id"]

            # Fetch all relay threads associated with this host_id and host_thread_id
            relay_entries = db.relay_threads.find({
                "host_id": host_id,
                "host_thread_id": channel_id  # relay threads linked to this host_thread
            })

            async for relay in relay_entries:
                relay_thread_id = int(relay["relay_thread_id"])
                host_thread_id = int(relay["host_thread_id"])
                logging.info(f"Relay thread id: {relay_thread_id}")
                relay_thread = bot.get_channel(relay_thread_id)
                host_thread = bot.get_channel(host_thread_id)
                if relay_thread is None:
                    try:
                        relay_thread = await bot.fetch_channel(relay_thread_id)
                        logger.info("Relay thread fetched")
                    except discord.NotFound:
                        logger.warning(f"Relay thread {relay_thread_id} not found (may be deleted)")
                    except discord.Forbidden:
                        logger.error(f"No access to Relay thread {relay_thread_id}")
                    except discord.HTTPException as e:
                        logger.error(f"Failed to fetch channel {relay_thread_id}: {e}")

                if relay_thread:
                    logging.info("Relay thread found")

                    if message.channel.permissions_for(message.guild.me).manage_threads:
                        await asyncio.sleep(2)
                        is_blocked = await is_blocked_user(message.author.name, relay_thread.guild.id)
                        if is_blocked:
                            await relay_thread.send(f"This host `{message.author.name}` is blocked from interacting with your server" 
                                                    f"\n-# Please contact a server admin if you believe this is an error.")
                            return
                        await relay_thread.send(f"👑 Host: {message.content}", allowed_mentions=allowed_mentions )
                        await relay_thread.edit(slowmode_delay=5)
                        await host_thread.edit(slowmode_delay=5)

        # ─── Check if message is from a RELAY THREAD ────────────────────────────
        elif relay_entry and not is_host_of_this_thread:
            logger.info("message is from a relay thread")
            host_id = relay_entry["host_id"]
            host_thread_id = relay_entry.get("host_thread_id")
            relay_thread_id = relay_entry.get("relay_thread_id")
            host_thread = bot.get_channel(int(host_thread_id))
            relay_thread = bot.get_channel(int(relay_thread_id))

            if host_thread_id:
                logger.info("host thread id found")
                if host_thread and relay_thread_id != host_thread_id:
                    logger.info("host channel found")
                    if message.channel.permissions_for(message.guild.me).manage_threads:
                        await asyncio.sleep(2)
                        is_blocked = await is_blocked_user(message.author.name, host_thread.guild.id)
                        if is_blocked:
                            await host_thread.send(f"blocked message from `{message.author.name}`" 
                                                   f"\n-# Please contact a server admin if you believe this is an error.")
                            return

                        await host_thread.send(f"`{message.guild.name}` `{message.author}`: {message.content}", allowed_mentions=allowed_mentions )
                        await relay_thread.edit(slowmode_delay=5)
                        await host_thread.edit(slowmode_delay=5)

        # append the user to the rate limited users list if they are not already there
        

        # ─── Continue with normal command processing ────────────────────────────
        await bot.process_commands(message)



@bot.command()
async def debug_relays(ctx):
    host_id = str(ctx.author.id)

    host_thread = await db.host_threads.find_one({"host_id": host_id})
    if not host_thread:
        await ctx.send("❌ No host thread found for you.")
        return

    host_thread_id = host_thread["host_thread_id"]

    relays = db.relay_threads.find({"host_id": host_id})
    relay_list = []
    async for relay in relays:
        relay_list.append(f"- Guild ID: `{relay['guild_id']}` | Relay Thread: `{relay['relay_thread_id']}`")

    if not relay_list:
        await ctx.send("⚠️ No relay threads found for your host thread.")
    else:
        await ctx.send(
            f"🧪 Relay Threads for Host Thread `{host_thread_id}`:\n" +
            "\n".join(relay_list)
        )

async def get_setting(guild_id: int, name: str):
    """
    Retrieves a specific setting for a guild from the database.

    Args:
        guild_id (int): The ID of the guild to get the setting for
        name (str): The name of the setting to retrieve

    Returns:
        Any: The value of the setting, or None if not found
    """
    config = await db.server_config.find_one({"guild_id": int(guild_id), "name": name})
    if not config:
        return None
    return config["value"]

async def get_toggle(guild_id: int, name: str):
    """
    Retrieves a boolean toggle setting for a guild.

    Args:
        guild_id (int): The ID of the guild to get the toggle for
        name (str): The name of the toggle setting

    Returns:
        bool: True if the setting exists and is enabled, False otherwise
    """
    config = await db.server_config.find_one({"guild_id": int(guild_id), "name": name})
    if not config or config["value"] is False:
        return False
    return True

async def set_setting(guild_id: int, name: str, value):
    await db.server_config.update_one(
        {"guild_id": guild_id, "name": name},
        {"$set": {"value": value}},
        upsert=True
    )

async def get_guild_from_id(guild_id: int):
    guild = bot.get_guild(int(guild_id))  # ✅ no await here
    if guild is None:
        guild = await bot.fetch_guild(int(guild_id))  # ✅ this is awaitable
    return guild

# List of supported regions for PVP matchmaking
regions = ["North America", "Europe", "Asia"]

# Helper function to format region settings for display
async def get_regions_formatted(guild_id: int) -> dict:
    formatted_regions = ""
    for region in regions:
        role_id = await get_setting(guild_id, f"{region} Role")
        channel_id = await get_setting(guild_id, f"{region} Channel")
        if role_id and channel_id:
            formatted_regions += f"{region}: <@&{role_id}> in <#{channel_id}> \n"
            
    return formatted_regions

async def get_host_roles_formatted(guild_id: int) -> dict:
    host_roles = await get_setting(guild_id, "host_roles")
    formatted_host_roles = ""
    if host_roles:
        for host_role in host_roles:
            host_role = "<@&" + str(host_role) + ">"
            # role1, role2, role3
            formatted_host_roles += f"{host_role}, "
        formatted_host_roles = formatted_host_roles[:-2] # remove last comma

    return formatted_host_roles

region_choices = [app_commands.Choice(name=region, value=region) for region in regions]
"""        
Global Settings View - Manage all global settings in one place with simple buttons
Features:
- Displays the current settings in an updating embed
- Toggle global PVP using buttons
- Toggle cross-server PVP
- Toggle global PVP threads
- View and manage host roles
- View regional settings
"""
class GlobalSettingsView(discord.ui.View):
    # Note: Channel and role selections have been removed for optimization and ease of use
    # Discord only allows 25 options per select menu, and adding pagination would increase complexity
    # This limitation will be revisited when Discord increases the option limit

    def __init__(self, guild_id: int):
        super().__init__()
        self.regional_roles = "Not configured"  # default value
        self.host_roles = "Not configured, everyone by default"

        self.guild_id = guild_id
        self.message = None  
        asyncio.create_task(self.auto_reload())


    async def auto_reload(self):
        while True:
            await asyncio.sleep(10)
            await self.update_embed()
            # stop if command timed out
            if self.message is None:
                break

    @discord.ui.button(label="Toggle Global PVP", style=discord.ButtonStyle.primary, row=2)  # toggle global pvp
    async def toggle_global_pvp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global_pvp_enabled = await get_toggle(self.guild_id, "global_pvp_enabled")
        await set_setting(self.guild_id, "global_pvp_enabled", not global_pvp_enabled)
        await interaction.response.defer(ephemeral=True)  # prevents double send
        await self.update_embed()
    
    @discord.ui.button(label="Toggle Cross Server PVP", style=discord.ButtonStyle.primary, row=3)  # toggle cross server pvp
    async def toggle_cross_server_pvp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cross_server_pvp_enabled = await get_toggle(self.guild_id, "cross_server_pvp_enabled")
        await set_setting(self.guild_id, "cross_server_pvp_enabled", not cross_server_pvp_enabled)
        await interaction.response.defer(ephemeral=True)  # prevents double send
        await self.update_embed()

    @discord.ui.button(label="Toggle Global PVP Threads", style=discord.ButtonStyle.primary, row=4)  # toggle global pvp threads
    async def toggle_global_pvp_threads_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global_pvp_threads_enabled = await get_toggle(self.guild_id, "global_pvp_threads_enabled")
        await set_setting(self.guild_id, "global_pvp_threads_enabled", not global_pvp_threads_enabled)
        await interaction.response.defer(ephemeral=True)  # prevents double send
        await self.update_embed()

    async def update_embed(self):
        guild = await get_guild_from_id(self.guild_id)
            
        cross_server_pvp_enabled = await get_toggle(self.guild_id, "cross_server_pvp_enabled") 
        global_pvp_enabled = await get_toggle(self.guild_id, "global_pvp_enabled")
        global_pvp_threads_enabled = await get_toggle(self.guild_id, "global_pvp_threads_enabled")

        host_roles = await get_setting(self.guild_id, "host_roles")
        # formatted regional roles

        regions_formatted = await get_regions_formatted(self.guild_id)
        host_roles_formatted = await get_host_roles_formatted(self.guild_id)

        newembed = discord.Embed(
            title="⚙️ AO Challenger Settings",
            description="`/help` - all commmands and guide",
            color=discord.Color.blue()
        )

        newembed.set_footer(text="Updates every 10 seconds. If settings dont update, try using the command again")
        newembed.add_field(name="Regions", value=regions_formatted if regions_formatted else "North America: Not set \n Europe: Not set \n Asia: Not set", inline=False)

        newembed.add_field(name=f"Global PVP?", value=f"Allows your server members to ping an entire region for pvp\n{"✅ Enabled" if global_pvp_enabled else "❌ Disabled"}", inline=False)

        newembed.add_field(name=f"Cross Server PVP?", value=f"Allows your server members to send and recieve pvp pings from other servers. Same with messages in Global PVP Threads\n{"✅ Enabled" if cross_server_pvp_enabled else "❌ Disabled"}", inline=False)
        
        newembed.add_field(name=f"Global PVP Threads?", value=f"Adds a thread below each pvp ping for host announcements\n{"✅ Enabled" if global_pvp_threads_enabled else "❌ Disabled"}", inline=False)
            

        if host_roles:
            newembed.add_field(name="Host Roles", value=f"Users with any of the following roles can host public pvp: {host_roles_formatted}", inline=False)
        else:
            newembed.add_field(name="Host Roles", value="Anyone can host public pvp", inline=False)
        
        if self.message:
            try:
                await self.message.edit(embed=newembed, view=self)
            except discord.HTTPException as e:
                logger.error(f"Failed to edit settings message: {e}")
            except Exception as e:
                logger.error(f"Unexpected error editing settings message: {e}")
            
async def location_autocomplete(interaction: discord.Interaction, current: str):
    """
    Autocomplete for in game locations
    """
    locations = [
        "South of Caitara",
        "Elysium",
        "Munera Garden",
        "Mount Orthys",
        "Mount Enkav",
        "Pelion Rift"
    ]

    matches = [loc for loc in locations if current.lower() in loc.lower()]
    
    return [
        app_commands.Choice(name=loc, value=loc)
        for loc in matches[:25]
    ]



# Track the last time each user sent a global PVP ping
# Format: {user_id (int): datetime.datetime}
# This enforces per-user cooldowns, not global cooldowns
global_pvp_ping_last_run = {}

class GlobalPVPCommands(app_commands.Group):
    
    # show global settings command

    """
    Settings command
    Allows users to edit the current global PVP settings.
    """
    @app_commands.command(name="settings", description="edit the current global settings.")
    
    @app_commands.checks.has_permissions(manage_channels=True)
    async def globalpvpsettings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)  # <-- Respond immediately to avoid expiration
        
        # check if the user is in a guild
        if not interaction.guild.id:
            await interaction.response.send_message(f"❌ this command is not available in DMs", ephemeral=True)
            return
        
        # create the settings view
        embed = discord.Embed(
            title="Loading...",
            description="Use the buttons below to configure your preferences.",
            color=discord.Color.blue()
        )
        view = GlobalSettingsView( interaction.guild_id)
        
        sent = await interaction.followup.send(embed=embed, view=view, ephemeral=True)  # <-- Follow up instead
        view.message = sent
        await view.update_embed()


    """"
    PING COMMAND
    Allows users to ping an entire region for pvp/elysium
    """

    @app_commands.command(name="ping", description="ping an entire region for pvp/elysium")
    
    @app_commands.describe(
        region="the region to ping for pvp",
        where="where are you pvping?",
        code="Roblox username or Elysium code",
        extra="Any extra information you want to add to the ping message"
    )

    @app_commands.choices(
        region=region_choices,
    )
    @app_commands.autocomplete(where=location_autocomplete)
    async def ping(
        self,
        interaction: discord.Interaction,
        region: str,
        where: str,
        code: str,
        extra: str = None,
    ):
        if await ban_check(interaction):
            return
        
        if not interaction.guild.id:
            await interaction.response.send_message(f"❌ this command is not available in DMs", ephemeral=True)
            return

        host_roles = await get_setting(interaction.guild.id, "host_roles")
        host_roles_formatted = await get_host_roles_formatted(interaction.guild.id)

        # check if the user has any of the host roles
        if host_roles and not any(role.id in host_roles for role in interaction.user.roles):
            await interaction.response.send_message(f"❌ you need one of the following to ping for pvp: {host_roles_formatted}", ephemeral=True)
            return 
        
        # check if the user has a global pvp channel set for the region and check permissions
        user_id = interaction.user.id
        if user_id in global_pvp_ping_last_run and datetime.datetime.now(datetime.timezone.utc) - global_pvp_ping_last_run[user_id] < datetime.timedelta(minutes=20):
            time_elapsed = datetime.datetime.now(datetime.timezone.utc) - global_pvp_ping_last_run[user_id]
            remaining_seconds = (datetime.timedelta(minutes=20) - time_elapsed).total_seconds()
            remaining_minutes = math.ceil(remaining_seconds / 20)
            await interaction.response.send_message(f"❌ Please wait {remaining_minutes} minutes before pinging again.", ephemeral=True)
            return
        global_pvp_channel_id = await get_setting(interaction.guild.id, f"{region} Channel")

        global_pvp_channel = interaction.guild.get_channel(int(global_pvp_channel_id))

        if not global_pvp_channel_id or not interaction.guild.get_channel(int(global_pvp_channel_id)):
            await interaction.response.send_message(f"❌ no global pvp channel set for the region [{region}]. Please tell an admin to assign a channel with `/globalpvp assignregions`", ephemeral=True)
            return
        
        if not global_pvp_channel.permissions_for(interaction.guild.me).send_messages or not global_pvp_channel.permissions_for(interaction.guild.me).read_message_history or not global_pvp_channel.permissions_for(interaction.guild.me).send_messages_in_threads or not global_pvp_channel.permissions_for(interaction.guild.me).manage_threads or not global_pvp_channel.permissions_for(interaction.guild.me).manage_roles:
            await interaction.response.send_message(f"I am missing one or more of the following permissions in <#{global_pvp_channel_id}> \n\n `Send Messages`, \n `Read Message History` - read GlobalPVP announcement threads, \n `Send Messages in Threads` - publish GlobalPVP announcement threads, \n `Manage Threads` - create GlobalPVP announcement threads, \n `Manage Roles` - Allows me to ping a region role. \n\n Please contact a server admin if this isn't intentional", ephemeral=True)
            return

        
        asyncio.create_task(self._handle_global_ping(interaction, region, where, code, extra))


    async def _handle_global_ping(self, interaction: discord.Interaction, region: str, where: str, code: str, extra: str = None):
        global global_pvp_ping_last_run
        
        if await ban_check(interaction):
            return
        host_id = int(interaction.user.id)
        host_thread_id = None
        relay_entries = []
        for guild in bot.guilds:
            try:
                # check if Cross Server PVP is disbaled for the host guild
                host_cross_server_pvp_enabled = await get_toggle(interaction.guild.id, "cross_server_pvp_enabled")
                relay_cross_server_pvp_enabled = await get_toggle(guild.id, "cross_server_pvp_enabled")

                if not host_cross_server_pvp_enabled and guild.id != interaction.guild_id:
                    continue
                

                # check if global pvp is enabled for this guild
                global_pvp_enabled = await get_toggle(guild.id, "global_pvp_enabled")
                is_blocked = await is_blocked_user(interaction.user.name, guild.id)
                
                if is_blocked:
                    continue

                global_pvp_channel_id = await get_setting(guild.id, f"{region} Channel")
                if not global_pvp_channel_id or not global_pvp_enabled:
                    continue

                channel = discord.utils.get(guild.text_channels, id=int(global_pvp_channel_id))
                if not channel:
                    continue
                
                # check if global pvp threads are enabled for both the host and relay guilds
                host_global_pvp_threads_enabled = await get_toggle(interaction.guild.id, "global_pvp_threads_enabled")
                relay_global_pvp_threads_enabled = await get_toggle(guild.id, "global_pvp_threads_enabled")

                # Get regional role config
                regional_role_id = await get_setting(guild.id, f"{region} Role")

                regional_role_mention = f"(<@&{regional_role_id}>)" if regional_role_id else f"({region})\n-# No regional role set for {region}. Please contact a server admin if this isn't intentional"
                extra_text = f"\nExtra info: {extra}" if extra else ""
                guild_count = len(bot.guilds)
                messagecontent = (
                    f"{interaction.user.mention} is pvping at {where}. User/code: {code} {regional_role_mention} "
                    f"{extra_text}"
                    f"\n-# TIP: Use `/globalpvp ping` to ping an entire region for pvp"
                )
                sent_msg = None
                
                # cross server check
                
                
                if relay_cross_server_pvp_enabled:
                    sent_msg = await channel.send(messagecontent, allowed_mentions=allowed_mentions )                        
                elif guild.id == interaction.guild.id: # relay servers includes the host server so we have to check for this. If we don't check for this, the message wont be announced at all if cross_server_pvp is disabled on the host's server.
                    sent_msg = await channel.send(messagecontent, allowed_mentions=allowed_mentions )
                
                # also Auto Publish the sent message if the channel is a Discord Announcement Channel
                if host_cross_server_pvp_enabled:
                    if sent_msg and isinstance(channel, discord.TextChannel) and channel.is_news():
                        try: 
                            await sent_msg.publish()
                        except Exception as e:
                            logger.error(f"Error publishing message: {e}")

                # check if global pvp threads are enabled for this guild
                if host_global_pvp_threads_enabled and relay_global_pvp_threads_enabled:
                    thread = await sent_msg.create_thread(
                        name=f"{interaction.user.name}'s announcements",
                        auto_archive_duration=60,
                        reason="pvp thread"
                    )
                    utc_now = datetime.datetime.now(datetime.timezone.utc)
                    timestamp = int(utc_now.timestamp())
                    
                    # add the thread to thread_cache
                    thread_cache[thread.id] = thread
                    # set the message cooldown of the thread to 5 seconds
                    await thread.edit(slowmode_delay=5) 
                    
                    thread_id = int(thread.id)
                    guild_id = int(guild.id)

                    

                    member = guild.get_member(interaction.user.id)
                    if member:
                        try:
                            await thread.add_user(member)
                        except discord.Forbidden:
                            pass

                    if guild.id == interaction.guild_id:
                        host_thread_id = thread_id
                        await thread.send(
                            f"👑 <@{interaction.user.id}> this is your HOST thread. Use this channel for announcements to your guests (and guests in other servers if Cross Server PVP is enabled). Created on <t:{timestamp}:f>. "
                        )
                        await db.host_threads.insert_one({
                            "host_id": int(interaction.user.id),
                            "host_thread_id": host_thread_id,
                            "guild_id": guild_id,
                        })
                    else:
                        # Only save relay threads from other guilds
                        await thread.send(
                            f"📥 Through this thread you can read announcements or message the host. Created on <t:{timestamp}:f>"
                        )
                        relay_entries.append({
                            "host_id": int(interaction.user.id),
                            "guild_id": guild_id,
                            "relay_thread_id": thread_id,
                        })

                    # Insert into relay_threads now that we have the host_thread_id
                    if host_thread_id:
                        for entry in relay_entries:
                            entry["host_thread_id"] = host_thread_id
                            await db.relay_threads.insert_one(entry)

            
            except Exception as e:
                logger.error(f"Error in globalpvp: {e}")
        await interaction.response.send_message(f"✅ your pvp announcement is out! Publish extra announcements in your host thread in <#{global_pvp_channel_id}>", ephemeral=True) # todo: improve this system. even if theres an error sending out the announcement it still shows this message (look below)  
        global_pvp_ping_last_run[int(interaction.user.id)] = datetime.datetime.now(datetime.timezone.utc)

            
    @ping.error
    async def ping_error(self, interaction: discord.Interaction, error):
        await interaction.response.send_message(f"error: {error}", ephemeral=True)

    @app_commands.command(name="blockuser", description="Block a user from interacting with your server")
    @app_commands.describe(
        username="Discord Username, NOT Display Name",
        duration="duration of the block in days",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def blockuser(
        self,
        interaction: discord.Interaction,
        username: str,
        duration: int,
    ):
        confirmView = View()

        confirmButton = Button(label="Yes", style=ButtonStyle.success, custom_id="confirm")
        cancelButton = Button(label="No", style=ButtonStyle.danger, custom_id="cancel")

        # Add buttons to view
        confirmView.add_item(confirmButton)
        confirmView.add_item(cancelButton)

        confirmEmbed = discord.Embed(
            title="⚠️ Block User",
            description=f"Are you sure you want to block `{username}` for {duration} day(s)? This will prevent them from \n - sending messages to your hosts \n - pinging your server for pvp \n - announcing to your guests \n - any more Challenger-Related interactions with your server",
            color=discord.Color.blue()
        )
        confirmEmbed.add_field(name="Username", value=username, inline=False)
        confirmEmbed.add_field(name="Duration", value=f"{duration} day(s)", inline=False)
        
        # Send the message with buttons
        # check if the user is already blocked
        is_blocked = await is_blocked_user(username, interaction.guild.id)
        if is_blocked:
            await interaction.response.send_message(f"❌ User `{username}` is already blocked", ephemeral=True)
            return
        else:
            await interaction.response.send_message(embed=confirmEmbed, view=confirmView, ephemeral=True)

        # Wait for button interaction
        def check(i: Interaction):
            return i.user.id == interaction.user.id and i.data["custom_id"] in ["confirm", "cancel"]

        try:
            button_interaction = await interaction.client.wait_for("interaction", check=check, timeout=60)

            if button_interaction.data["custom_id"] == "confirm":
                await db.blocks.insert_one({
                    "username": str(username),
                    "guild_id": int(interaction.guild.id),
                    "duration": duration,
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                })
                await button_interaction.response.send_message(f"✅ <@{interaction.user.id}> blocked `{username}` for {duration} day(s)", ephemeral=True)
            elif button_interaction.data["custom_id"] == "cancel":
                await button_interaction.response.send_message(f"❌ Cancelled", ephemeral=True)

        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out, no action taken.", ephemeral=True)
        

    @app_commands.command(name="unblockuser", description="Unblock a user from interacting with your server")
    @app_commands.describe(
        username="Discord username, NOT Display Name",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unblockuser(
        self,
        interaction: discord.Interaction,
        username: str,
    ):
        
        # check if the user is already blocked
        is_blocked = await is_blocked_user(username, interaction.guild.id)
        if not is_blocked:
            await interaction.response.send_message(f"❌ User `{username}` is not blocked", ephemeral=True)
            return
        else:
            db.blocks.delete_one({"username": str(username)})
            await interaction.response.send_message(f"✅ unblocked `{username}`")
    
    @app_commands.command(name="listblocked", description="List all blocked users")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def listblocked(
        self,
        interaction: discord.Interaction,
    ):
        blocked_users = await get_blocked_users(interaction.guild.id)
        if not blocked_users:
            await interaction.response.send_message(f"❌ No blocked users found", ephemeral=True)
            return
        
        # list blocked users in an embed field table, with fields for username, duration, days left, created_at
        blocked_users_embed = discord.Embed(
            title="🔒 Blocked Users",
            description=f"Use `/unblockuser` to unblock a user",
            color=discord.Color.blue()
        )
        
        for user in blocked_users:
            created_dt = datetime.datetime.fromisoformat(user['created_at'])
            unblock_dt = created_dt + datetime.timedelta(days=int(user['duration']))
            unblock_ts = int(unblock_dt.timestamp())

            info = (
                f"- Duration: {user['duration']} day(s)\n"
                f"- Blocked at: <t:{int(created_dt.timestamp())}:f>\n"
                f"- 🔓 Unblocked: <t:{unblock_ts}:R>"
            )


            blocked_users_embed.add_field(name=user["username"], value=info, inline=False)
        await interaction.response.send_message(embed=blocked_users_embed, ephemeral=True)

    @app_commands.command(name="assignregions" , description="assign regions to channels and ping roles")
    @app_commands.describe(
        region="the region",
        role="the role tied to the region",
        channel="the channel tied to the region",
    )
    @app_commands.choices(
        region=region_choices,
    )

    @app_commands.checks.has_permissions(manage_channels=True)
    async def assignregions(
        self,
        interaction: discord.Interaction,
        region: str,
        role: discord.Role,
        channel: discord.TextChannel,
    ):
        
        await set_setting(interaction.guild.id, f"{region} Role", role.id)
        await set_setting(interaction.guild.id, f"{region} Channel", channel.id)
        await interaction.response.send_message(f"✅ assigned `{region}` to <@&{role.id}> in <#{channel.id}>", ephemeral=True)
    
    @app_commands.command(name="addhostrole", description="add a role that can host pvp (everyone by default)")
    @app_commands.describe(
        role="role that will be able to host pvp",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def addhostrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ):
        host_roles = await get_setting(interaction.guild.id, "host_roles")
        if not host_roles:
            host_roles = []
        host_roles.append(role.id)
        await set_setting(interaction.guild.id, "host_roles", host_roles)
        await interaction.response.send_message(f"✅ added host role <@&{role.id}>", ephemeral=True)

    @app_commands.command(name="clearhostroles", description="remove all host roles")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def clearhostrole(
        self,
        interaction: discord.Interaction,
    ):
        await set_setting(interaction.guild.id, "host_roles", False)
        await interaction.response.send_message(f"✅ cleared host roles", ephemeral=True)
class QueueView(discord.ui.View):
    def __init__(self, searchingPlayer_id: str):  
        super().__init__(timeout=300)
        self.searchingPlayer_id = searchingPlayer_id    
        self.message = None  # message that was sent

    @discord.ui.button(label="cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        await db.queue.delete_one({"_id": self.searchingPlayer_id})

        await interaction.response.send_message("❌ queue cancelled", ephemeral=True)

        if self.message:
            await self.message.delete()



"""
Easy server setup for admins
"""
class SetupView(View):
    # this class uses "guild" instead of "guild.id"
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild
        self.step = 0
        self.selected_channel = None
        self.regional_roles = {}
        self.latest_interaction: Interaction | None = None  # Add this line

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.guild_permissions.administrator

    async def next_step(self, interaction: Interaction):
        self.clear_items()
        self.step += 1

        if self.step == 1:
            await self.step_enable_global_pvp(interaction)
        elif self.step == 2:
            await self.step_assign_regions(interaction)
        elif self.step == 3:
            await self.step_add_host_roles(interaction)
        elif self.step == 4:
            await self.step_enable_cross_server_pvp(interaction)
        elif self.step == 5:
            await self.finish(interaction)

    async def step_enable_global_pvp(self, interaction: Interaction):

        async def toggle_callback(enable: bool):
            await set_setting(interaction.guild.id, "global_pvp_enabled", enable)

            # Confirm it's saved
            current = await get_setting(interaction.guild.id, "global_pvp_enabled")


            await interaction.edit_original_response(
                content=f"✔️ Global PvP {'enabled' if enable else 'disabled'}",
                view=None
            )
            await asyncio.sleep(3)
            await self.next_step(interaction)

        async def handle_button(i: Interaction):
            await i.response.defer(ephemeral=True)
            if i.data["custom_id"] == "enable_pvp":
                await toggle_callback(True)
            elif i.data["custom_id"] == "disable_pvp":
                await toggle_callback(False)

        # Define buttons and attach callback BEFORE adding to view
        enable_button = Button(label="Enable", style=ButtonStyle.success, custom_id="enable_pvp")
        disable_button = Button(label="Disable", style=ButtonStyle.danger, custom_id="disable_pvp")

        enable_button.callback = handle_button
        disable_button.callback = handle_button

        self.clear_items()
        self.add_item(enable_button)
        self.add_item(disable_button)

        await interaction.response.send_message(
            content="Step 1: Do you want to enable Global PvP? \n This will allow your users to ping an entire region for pvp",
            view=self,
            ephemeral=True
        )




    async def step_assign_regions(self, interaction: Interaction):
        self.latest_interaction = interaction

        async def on_done(i: Interaction):
            self.latest_interaction = i
            await self.next_step(i)

        done = Button(label="Done/Skip", style=ButtonStyle.success, row=1)
        done.callback = on_done
        self.clear_items()
        self.add_item(done)

        # 🛠 FIX: Defer the response so followup works
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)


        await interaction.edit_original_response(content="Step 2: Use `/globalpvp assignregions` to assign regions to channels and roles", view=self)

    async def step_add_host_roles(self, interaction: Interaction):
        self.latest_interaction = interaction

        async def on_done(i: Interaction):
            self.latest_interaction = i
            await self.next_step(i)

        done = Button(label="Done/Skip", style=ButtonStyle.success, row=1)
        done.callback = on_done
        self.clear_items()
        self.add_item(done)

        # 🛠 FIX: Defer the response so followup works
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)


        await interaction.edit_original_response(content="Step 3: Choose who can host pvp via `/globalpvp addhostroles`. Users with any of the roles can host pvp", view=self)


    async def step_enable_cross_server_pvp(self, interaction: Interaction):

        async def toggle_callback(enable: bool):
            await set_setting(interaction.guild.id, "cross_server_pvp_enabled", enable)

            # Confirm it's saved
            current = await get_setting(interaction.guild.id, "cross_server_pvp_enabled")   


            await interaction.edit_original_response(
                content=f"✔️ Cross Server PvP {'enabled' if enable else 'disabled'}.",
                view=None
            )
            await asyncio.sleep(3)
            await self.next_step(interaction)

        async def handle_button(i: Interaction):
            await i.response.defer(ephemeral=True)
            if i.data["custom_id"] == "enable_cross_server":
                await toggle_callback(True)
            elif i.data["custom_id"] == "disable_cross_server":
                await toggle_callback(False)

        # Define buttons and attach callback BEFORE adding to view
        enable_button = Button(label="Enable", style=ButtonStyle.success, custom_id="enable_cross_server")
        disable_button = Button(label="Disable", style=ButtonStyle.danger, custom_id="disable_cross_server")

        enable_button.callback = handle_button
        disable_button.callback = handle_button

        self.clear_items()
        self.add_item(enable_button)
        self.add_item(disable_button)

        await interaction.response.send_message(
            content="Step 4: Do you want to enable Cross Server PvP? \n This will enable your server to receive pvp pings from *other servers* and vice versa",
            view=self,
            ephemeral=True
        )

    
    async def finish(self, interaction: Interaction):
        
        regions_formatted = await get_regions_formatted(interaction.guild.id)
        host_roles_formatted = await get_host_roles_formatted(interaction.guild.id)
        global_pvp_enabled = await get_toggle(interaction.guild.id, "global_pvp_enabled")
        cross_server_pvp_enabled = await get_toggle(interaction.guild.id, "cross_server_pvp_enabled")
        summaryEmbed = discord.Embed(
            title="🎉 Setup complete!",
            description="Wanna change these later? use `/globalpvp settings` or `/setup` again. For more important commands, use `/help`. Players can use `/findpvp` to find players to 1v1, or `/globalpvp ping` to ping an entire region for pvp.",
            color=discord.Color.blue()
        )
        summaryEmbed.add_field(name="Global PvP Enabled", value=global_pvp_enabled, inline=False)
        summaryEmbed.add_field(name="Cross Server PvP Enabled", value=cross_server_pvp_enabled, inline=False)
        summaryEmbed.add_field(name="Host Roles", value=host_roles_formatted if host_roles_formatted else "Anyone can host pvp", inline=False)
        summaryEmbed.add_field(name="Assigned Regions", value=regions_formatted if regions_formatted else "North America: Not set \n Europe: Not set \n Asia: Not set", inline=False)
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content="Done", embed=summaryEmbed, view=None) 


@bot.tree.command(name="setup", description="Step-by-step setup for AO Challenger")

@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction): 
    if await ban_check(interaction):
        return
    
    if not interaction.guild.id:
        await interaction.response.send_message(f"❌ this command is not available in DMs", ephemeral=True)
        return
    view = SetupView(interaction.guild)
    await view.next_step(interaction)

@bot.tree.command(name="help", description="How to use the bot and all commands")
async def help(interaction: discord.Interaction):
    await interaction.response.send_message(f"\n `/findpvp` - find a 1v1 \n `/globalpvp ping` - ping an entire region for pvp \n\n [All commands and guide](https://github.com/ciabidev/AO-Challenger/blob/main/README.md) ",embed=None)

@bot.tree.command(name="invite", description="Invite the bot to your server")

async def invite(interaction: discord.Interaction):
    # get invite.txt
    with open("app/invite.txt", "r") as f:
        invite = f.read()
    await interaction.response.send_message(f"[invite me to your server]({invite})", embed=None)

# support command
@bot.tree.command(name="support", description="ask for help or suggest something")
async def support(interaction: discord.Interaction):
    await interaction.response.send_message(f"[Support and Suggestions](https://tally.so/r/3X6yqV)", ephemeral=True)

# upvote command
@bot.tree.command(name="upvote", description="suport the bot for FREE by upvoting it on top.gg")
async def upvote(interaction: discord.Interaction):
    # get invite.txt
    with open("app/upvote.txt", "r") as f:
        upvote = f.read()
    await interaction.response.send_message(f"[upvote me on top.gg]({upvote})")

# findpvp command
@bot.tree.command(name="findpvp", description="Join a queue to find a player to pvp")

@app_commands.describe(
    region="the region to queue for pvp",
    username="Roblox username",
    extra="Any extra information you want to add to the queue message"
)
@app_commands.choices(
    region=region_choices,
)

@app_commands.autocomplete(where=location_autocomplete)
async def findpvp(interaction: discord.Interaction, username: str, region: str, extra: str = None, where: str = None):
    if await ban_check(interaction):
        return
    
    
    searchingPlayer = await db.queue.find_one({"username": username})        
    
    view = None

    # using roblox api, check if the user exists
    msg = None

    try:
        roblox_username = await roblox_user_exists(username)
        discord_user_already_in_queue = await db.queue.find_one({"user_id": int(interaction.user.id)})
        if roblox_username:
            if not searchingPlayer and not discord_user_already_in_queue:
                await db.queue.insert_one({
                    "region": region,
                    "username": roblox_username,
                    "extra": extra,
                    "where": where,
                    "user_id": int(interaction.user.id),
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                })
                searchingPlayer = await db.queue.find_one({"region": region, "username": roblox_username})
                view = QueueView(searchingPlayer["_id"])
                
                addedEmbed = discord.Embed(
                    title="✅ Joined queue",
                    description=f"Players you can be paired with will be limited to the region you selected.",
                    color=discord.Color.blue(),
                )

                addedEmbed.add_field(name="Region", value=region, inline=False)
                addedEmbed.add_field(name="Username", value=roblox_username, inline=False)
                addedEmbed.add_field(name="Extra", value=extra, inline=False)
                addedEmbed.add_field(name="Where", value=where, inline=False)
                await interaction.response.send_message(embed=addedEmbed, view=view, ephemeral=True)
            else:
                await db.queue.update_one({"user_id": int(interaction.user.id)}, { # prevents players from editing others queue
                    "$set": {
                        "region": region,
                        "username": roblox_username,
                        "extra": extra,
                        "where": where,
                        "user_id": int(interaction.user.id),
                        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }
                })
                searchingPlayer = await db.queue.find_one({"region": region, "username": roblox_username})
                view = QueueView(searchingPlayer["_id"])

                changesEmbed = discord.Embed(
                    title="☑️ Edited your user",
                    description=f"Players you can be paired with will be limited to the region you selected.",
                    color=discord.Color.blue(),
                )

                changesEmbed.add_field(name="Region", value=region, inline=False)
                changesEmbed.add_field(name="Username", value=roblox_username, inline=False)
                changesEmbed.add_field(name="Extra", value=extra, inline=False)
                changesEmbed.add_field(name="Where", value=where, inline=False)
                await interaction.response.send_message(embed=changesEmbed, view=view, ephemeral=True)
            msg = await interaction.original_response()
            view.message = msg  
        else:
            msg = await interaction.response.send_message(f"❌ user `{username}` not found.", ephemeral=True)
    except Exception as e:
        if not searchingPlayer:
            msg = await interaction.response.send_message(f"❌ error: {e}", ephemeral=True)
        else:
            msg = await interaction.response.send_message(f"❌ error: You do not have permission to edit this person's queue", ephemeral=True, view=view)


        
    
    # wait until another player with same region is in queue. times out after 5 minutes

    foundPlayer = None
    while True:
        foundPlayer = await db.queue.find_one({"region": region, "username": {"$ne": roblox_username}})
        if foundPlayer and foundPlayer["user_id"] != int(interaction.user.id):
            foundPlayer_mention = f"<@{foundPlayer['user_id']}>"
            foundPlayer_id = await get_roblox_user_id(foundPlayer["username"])
            foundPlayer_headshot = await get_roblox_headshot(foundPlayer_id)
            resultEmbed = discord.Embed(
                title="🎉 Found a player",
                description=f" ",
                color=discord.Color.blue(),
            )
            resultEmbed.set_thumbnail(url=foundPlayer_headshot)

            resultEmbed.add_field(name="Region", value=foundPlayer["region"], inline=False)
            resultEmbed.add_field(name="Roblox Username", value=foundPlayer["username"], inline=False)
            resultEmbed.add_field(name="Extra", value=foundPlayer["extra"], inline=False)
            resultEmbed.add_field(name="Where", value=foundPlayer["where"], inline=False)

            result = await interaction.followup.send(f"<@{interaction.user.id}> you've been paired with {foundPlayer_mention}", embed=resultEmbed, ephemeral=True)
            await db.queue.delete_one({"username": foundPlayer["username"]})
            await db.queue.delete_one({"username": searchingPlayer["username"]})
            break
        
        await asyncio.sleep(1)
        if searchingPlayer != None:
            if datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(searchingPlayer["created_at"]) > datetime.timedelta(minutes=5):
                result = await interaction.followup.send(f"<@{interaction.user.id}> ❌ No player found in 5 minutes. Cancelling queue.", ephemeral=True)
                await msg.delete()
                await db.queue.delete_one({"username": searchingPlayer["username"]})
                break
            if await db.queue.count_documents({}) == 0:
                result = await interaction.followup.send(f"<@{interaction.user.id}> The queue has been cleared. Cancelling queue.", ephemeral=True)
                await msg.delete()
                break

# banuser command
@bot.tree.command(name="banuser", description="Ban a user from using the bot")
@app_commands.describe(
    user_id="Discord User ID",
)
async def banuser(
    interaction: discord.Interaction,
    user_id: str,
):
    if interaction.user.id == 968622168302833735:
        await db.bans.insert_one({
            "user_id": int(user_id),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
        await interaction.response.send_message(f"✅ <@{user_id}> banned", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ you don't have permission to ban users from using the bot. to block users from interacting with your server, use `/globalpvp blockuser`", ephemeral=True)

@bot.tree.command(name="unbanuser", description="Unban a user from using the bot")
@app_commands.describe(
    user_id="Discord User ID",
)
async def unbanuser(
    interaction: discord.Interaction,
    user_id: str,
):
    if interaction.user.id == 968622168302833735:
        db.bans.delete_one({"user_id": int(user_id)})
        await interaction.response.send_message(f"✅ unbanned <@{user_id}>", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ you don't have permission to unban users from using the bot. to unblock users from interacting with your server, use `/globalpvp unblockuser`", ephemeral=True)



@bot.tree.command(name="listbanned", description="List all banned users")
async def listbanned(
    interaction: discord.Interaction,
):
    if interaction.user.id != 968622168302833735:
        await interaction.response.send_message(f"❌ you don't have permission to list users banned from using the bot. to list blocked users, use `/globalpvp listblocked`", ephemeral=True)
        return
    banned_users = await get_banned_users()
    if not banned_users:
        await interaction.response.send_message(f"❌ No banned users found", ephemeral=True)
        return
    
    # list banned users in an embed field table, with fields for username, duration, days left, created_at
    banned_users_embed = discord.Embed(
        title="🔒 Banned Users",
        description=f"Use `/unban` to unban a user",
        color=discord.Color.blue()
    )

    # no duration for bans
    for user in banned_users:
        created_dt = datetime.datetime.fromisoformat(user['created_at'])

        info = (
            f"- Banned at: <t:{int(created_dt.timestamp())}:f>\n"
        )


        banned_users_embed.add_field(name=user["user_id"], value=info, inline=False)
    await interaction.response.send_message(embed=banned_users_embed, ephemeral=True)
    

# register globalpvp class
bot.tree.add_command(GlobalPVPCommands(name="globalpvp", description="global/public pvp management"))
def run_bot():
    bot.run(token) 

run_bot()