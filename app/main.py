import discord
from discord.ui import View, Select
import requests
import threading
import os
import sqlite3
import asyncio
import csv
import io
import datetime
import aiohttp
from discord.ext import commands
from discord import app_commands
from discord import Client, SelectOption
from discord.app_commands import checks
from discord import Interaction, SelectOption, TextChannel, ButtonStyle
from discord.ui import View, Select, Button
from dotenv import load_dotenv
from flask import Flask
from typing import List
from motor.motor_asyncio import AsyncIOMotorClient
import json

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))  # Render sets the PORT environment variable
    app.run(host='0.0.0.0', port=port)

# Start Flask in a separate thread so it doesn’t block the bot
threading.Thread(target=run_flask).start()

# SQLite data setup


from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI")
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["challenger"]

import pymongo
# The db variable will be set in on_ready
# ONLINE/OFFLINE STATUS LOGGING


# Init
bot = commands.Bot(command_prefix='?', intents=intents)
import discord

# roblox API

usersEndpoint = "https://users.roblox.com/v1/usernames/users"

async def roblox_user_exists(username: str) -> bool:
    url = "https://users.roblox.com/v1/usernames/users"
    data = {
        "usernames": [username],
        "excludeblockedUsers": False
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as resp:
            if resp.status != 200:
                print(f"Failed request: {resp.status}")
                return False
            
            result = await resp.json()
            ## return the username
            return result.get("data", [])[0].get("name")

async def get_roblox_user_id(username: str):
    url = "https://users.roblox.com/v1/usernames/users"
    data = {
        "usernames": [username],
        "excludeblockedUsers": False
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as resp:
            if resp.status != 200:
                print(f"Failed request: {resp.status}")
                return False
            
            result = await resp.json()
            ## return the id
            return result.get("data", [])[0].get("id")

async def get_roblox_headshot(user_id: int):
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
    params = {
        "userIds": str(user_id),
        "size": "150x150",
        "format": "Png",
        "isCircular": "false"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            data = await response.json()
            return data['data'][0]['imageUrl']
        


# bot initialization

# servers can block users from interacting with their server (such as /globalpvp ping), even if they are not in the server

@bot.event
async def on_ready():
    print(f'live on {bot.user.name} - {bot.user.id}')

    activity = discord.Activity(type=discord.ActivityType.listening, name="/findpvp /help")
    await bot.change_presence(activity=activity)

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    # Cache all text channels and threads from all guilds


    for guild in bot.guilds:
        # Await the coroutine properly to get the list of active threads
        threads = await guild.active_threads()

        for thread in threads:
            thread_cache[thread.id] = thread
        

    print(f"Cached {len(thread_cache)} possible pvp channels/threads")

    # remove all queue entries on start
    await db.queue.delete_many({})

# GLOBAL PVP THREAD RELAY
# Host sends a message in host thread which is forwarded to all relay threads
# If a player sends a message in a relay thread, it is forwarded to the host thread

thread_cache = {}  # global cache: {thread_id (int): discord.Thread or discord.TextChannel}

async def get_blocked_users(guild_id: int):
    cursor = db.blocks.find({"guild_id": guild_id})
    blocked_users = await cursor.to_list()
    userlist = []

    now = datetime.datetime.now(datetime.timezone.utc)

    for user in blocked_users:
        try:
            created_at = datetime.datetime.fromisoformat(user["created_at"])
            duration = user.get("duration", 0)

            if now - created_at > datetime.timedelta(days=duration):
                await db.blocks.delete_one({"username": user["username"], "guild_id": guild_id})
            else:
                userlist.append(user)

        except KeyError as e:
            print(f"Missing expected key in block record: {e}")

    return userlist

async def is_blocked_user(username: str, guild_id: int):
    blocked_users = await get_blocked_users(guild_id)
    print(blocked_users)
    print(username)
    for user in blocked_users: 
        if user["username"] == username:
            print(f"user {user} is blocked")
            return True
            break

    return False



async def get_relay_threads(host_id: int):
    config = await db.relay_threads.find_one({"host_id": int(host_id)})
    if not config:
        return None
    return config  # Return entire document

relay_threads = {}

@bot.event
async def get_channel_cached(channel_id: int):
    if channel_id in thread_cache:
        print(f"Returning cached channel {channel_id}")
        return thread_cache[channel_id]
    channel = bot.get_channel(channel_id)
    if channel:
        print(f"Returning channel {channel_id}")
        thread_cache[channel_id] = channel
        return channel
    # fallback to fetching from API
    try:
        print(f"Fetching channel {channel_id}")
        channel = await bot.fetch_channel(channel_id)
        thread_cache[channel_id] = channel
        return channel
    except discord.NotFound:
        print("Channel not found")
        return None


@bot.event
async def on_thread_create(thread):
    thread_cache[thread.id] = thread
    # set the message cooldown of the thread to 5 minutes
    await thread.edit(slowmode_delay=5) 
@bot.event
async def on_thread_delete(thread):
    thread_cache.pop(thread.id, None)

@bot.event
async def on_guild_channel_delete(channel):
    thread_cache.pop(channel.id, None)


rate_limited_users = {}

COOLDOWN_DURATION = 5  # in seconds

async def cooldown_timer(user_id):
    for i in range(COOLDOWN_DURATION, 0, -1):
        rate_limited_users[user_id] = i
        await asyncio.sleep(1)
    rate_limited_users.pop(user_id, None)

@bot.event
async def on_message(message: discord.Message):
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
        # ─── Check if message is from a HOST THREAD ─────────────────────────────
        rate_limited_users[user_id] = COOLDOWN_DURATION
        asyncio.create_task(cooldown_timer(user_id))

        relay_entry = await db.relay_threads.find_one({"relay_thread_id": channel_id})
        host_entry = await db.host_threads.find_one({"host_thread_id": channel_id})
        is_host_of_this_thread = host_entry and host_entry.get("host_id") == user_id

        if host_entry and is_host_of_this_thread:
            print("message is from a host thread")
            host_id = host_entry["host_id"]

            # Fetch all relay threads associated with this host_id and host_thread_id
            relay_entries = db.relay_threads.find({
                "host_id": host_id,
                "host_thread_id": channel_id  # relay threads linked to this host_thread
            })

            async for relay in relay_entries:
                relay_thread_id = int(relay["relay_thread_id"])
                host_thread_id = int(relay["host_thread_id"])
                print(f"Relay thread id: {relay_thread_id}")
                relay_thread = bot.get_channel(relay_thread_id)
                host_thread = bot.get_channel(host_thread_id)
                if relay_thread is None:
                    try:
                        relay_thread = await bot.fetch_channel(relay_thread_id)
                        print("Relay thread fetched")
                    except discord.NotFound:
                        print(f"Relay thread {relay_thread_id} not found (may be deleted)")
                    except discord.Forbidden:
                        print(f"No access to Relay thread {relay_thread_id}")
                    except discord.HTTPException as e:
                        print(f"Failed to fetch channel {relay_thread_id}: {e}")

                if relay_thread:
                    print("Relay thread found")

                    if message.channel.permissions_for(message.guild.me).manage_threads:
                        await asyncio.sleep(2)
                        is_blocked = await is_blocked_user(message.author.name, relay_thread.guild.id)
                        if is_blocked:
                            await relay_thread.send(f"This host `{message.author.name}` is blocked from interacting with your server" 
                                                    f"\n-# Please contact a server admin if you believe this is an error.")
                            return
                        await relay_thread.send(f"👑 Host: {message.content}")
                        await relay_thread.edit(slowmode_delay=5)
                        await host_thread.edit(slowmode_delay=5)

        # ─── Check if message is from a RELAY THREAD ────────────────────────────
        elif relay_entry and not is_host_of_this_thread:
            print("message is from a relay thread")
            host_id = relay_entry["host_id"]
            host_thread_id = relay_entry.get("host_thread_id")
            relay_thread_id = relay_entry.get("relay_thread_id")
            host_thread = bot.get_channel(int(host_thread_id))
            relay_thread = bot.get_channel(int(relay_thread_id))

            if host_thread_id:
                print("host thread id found")
                if host_thread and relay_thread_id != host_thread_id:
                    print("host channel found")
                    if message.channel.permissions_for(message.guild.me).manage_threads:
                        await asyncio.sleep(2)
                        is_blocked = await is_blocked_user(message.author.name, host_thread.guild.id)
                        if is_blocked:
                            await host_thread.send(f"blocked message from `{message.author.name}`" 
                                                   f"\n-# Please contact a server admin if you believe this is an error.")
                            return

                        await host_thread.send(f"`{message.guild.name}` {message.author}: {message.content}")
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




# MAIN BOT CODE





async def text_channel_options(guild_id: int):
    guild = bot.get_guild(guild_id)
    text_channel_list = []
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages :
            text_channel_list.append(SelectOption(label=channel.name, value=int(channel.id)))
    return text_channel_list

# configurations

async def get_setting(guild_id: int, name: str):
    config = await db.server_config.find_one({"guild_id": int(guild_id), "name": name})
    if not config:
        print(f"No {name} set for guild {guild_id}")
        return None
    return config["value"]

async def get_toggle(guild_id: int, name: str):
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

async def get_roles_as_options(guild_id: int) -> list[discord.SelectOption]:
    guild = await get_guild_from_id(guild_id)
    roles = guild.roles
    options = [
        discord.SelectOption(label=role.name, value=int(role.id))
        for role in roles
    ]
    return options

async def convert_list_to_options(guild_id: int, list: list[str]) -> list[discord.SelectOption]:
    guild = await get_guild_from_id(guild_id)
    items = list
    options = [
        discord.SelectOption(label=item.name, value=int(item.id))
        for item in items
    ]
    return options
    
async def get_regional_roles_dict(guild_id: int) -> dict:
    config = await db.server_config.find_one({"guild_id": int(guild_id), "name": "regional_roles"})
    
    if not config:
        print(f"No regional roles set for guild {guild_id}")
        return {}

    value = config.get("value", {})

    if not isinstance(value, dict):
        print(f"[WARN] Expected dict for regional_roles.value but got {type(value).__name__}")
        return {}

    return value

region_choices = [
    app_commands.Choice(name="🍔 North America", value="North America"),
    app_commands.Choice(name="🥖 Europe", value="Europe"),
    app_commands.Choice(name="🍚 Asia", value="Asia"),
]



class GlobalChannelSelect(Select):
    def __init__(self, channels: list[SelectOption], parentview: discord.ui.View):
        super().__init__(placeholder="Select a global PvP channel...", options=channels, row=0)
        self.parentview = parentview
        
    async def callback(self, interaction: discord.Interaction):
        # check if the bot has permission to create threads
        selected_value = self.values[0]
        
        selected_channel = discord.utils.get(interaction.guild.text_channels, id=int(selected_value))
        perms = selected_channel.permissions_for(interaction.guild.me)
        if not perms.create_public_threads and perms.send_messages_in_threads and perms.send_messages and perms.manage_threads: 
            await interaction.response.send_message(f"⚠️ please make sure i have the following permissions in {selected_channel.mention}: Create Public Threads, Send Messages in Threads, Send Messages, and Manage Threads. If I already have these permissions, try moving my role higher", ephemeral=True)

        await set_setting(interaction.guild.id, "global_pvp_channel", selected_value)

        await interaction.response.defer(ephemeral=True)  # prevent "interaction failed"
        await self.parentview.update_embed()


class HostRoleSelect(Select):
    def __init__(self, roleoptions: list[SelectOption], parentview: discord.ui.View):
        super().__init__(placeholder="Choose who can host pvp (everyone by default)", options=roleoptions, row=3)
        self.parentview = parentview
    
    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        if selected_value == "1393397825085374587":
            await set_setting(interaction.guild.id, "host_role", False)
        else:
            await set_setting(interaction.guild.id, "host_role", selected_value)

        await interaction.response.defer(ephemeral=True)  # prevent "interaction failed"
        await self.parentview.update_embed()
# user selects a region -> lets them choose from a list of roles to set for that region

class RegionalRolesSelect(Select):
    def __init__(self, roleoptions: list[SelectOption], parentview: discord.ui.View, region: str):
        super().__init__(placeholder=f"Select a role for {region}", options=roleoptions, row=1)
        self.parentview = parentview
        self.region = region

    async def callback(self, interaction: discord.Interaction):
        perms = interaction.channel.permissions_for(interaction.guild.me)

        # update server config, set na/eu/as config to the selected role. is a dictionary where key is region name and value is role id
      
        current_roles = await get_regional_roles_dict(self.parentview.guild_id)
        current_roles[str(self.region)] = self.values[0]
        await set_setting(self.parentview.guild_id, "regional_roles", current_roles)

        await interaction.response.defer(ephemeral=True)  # prevent "interaction failed"
        await self.parentview.update_embed()

class RegionButtons(discord.ui.View):
    def __init__(self, guild_id: str, parentview: discord.ui.View):
        super().__init__()
        self.guild_id = guild_id

        # Provide a dummy/placeholder option initially (not interactive)
        placeholder_option = [discord.SelectOption(label="Choose a region above", value="placeholder", description="No region selected yet")]
        self.select = RegionalRolesSelect(roleoptions=placeholder_option, parentview=parentview, region="None")
        self.select.disabled = True  # Disable it until a region is selected
        self.add_item(self.select)

    async def update_select_options(self, region: str):
        # Fetch roles as SelectOptions
        roles = await get_roles_as_options(self.guild_id)
        self.select.options = roles
        self.select.placeholder = f"Select a role for {region} "
        self.select.region = region  # store current region if you want

    @discord.ui.button(label="North America", style=discord.ButtonStyle.primary, row=0)
    async def na_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles = await get_roles_as_options(self.guild_id)
        self.select.options = roles
        self.select.disabled = False
        await self.update_select_options("North America")
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Europe", style=discord.ButtonStyle.primary, row=0)
    async def eu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles = await get_roles_as_options(self.guild_id)
        self.select.options = roles
        self.select.disabled = False
        await self.update_select_options("Europe")
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Asia", style=discord.ButtonStyle.primary, row=0)
    async def as_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles = await get_roles_as_options(self.guild_id)
        self.select.options = roles
        self.select.disabled = False
        await self.update_select_options("Asia")
        await interaction.response.edit_message(view=self)

# since we have to use commands for the best UX, we can't use a settings view. read more below
class GlobalSettingsView(discord.ui.View):
    # channel and role selections have been removed for optimization and ease of use
    ## discord only allows 25 options per select
    ## adding pagination to each select would lead to the code being too complex 
    ## until discord allows more than 25 options per select, this is staying

    def __init__(self, channels: list[SelectOption], roles: list[SelectOption], guild_id: int):
        super().__init__()
        self.regional_roles = "Not configured"  # default value
        self.host_role = "Not configured, everyone by default"
        # self.add_item(GlobalChannelSelect(channels, self))
        # self.add_item(HostRoleSelect(roles, self))
        self.guild_id = guild_id
        self.message = None  # Will be assigned after sending
        
    # @discord.ui.button(label="Set Regional PVP Roles", style=discord.ButtonStyle.primary, row=1)
    # async def set_regional_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     await interaction.response.edit_message(view=RegionButtons(self.guild_id, self))

    async def auto_update_embed(self):
        while True:
            await self.update_embed()
            await asyncio.sleep(5)
    
    asyncio.create_task(auto_update_embed())

    @discord.ui.button(label="Enable Global PVP", style=discord.ButtonStyle.green, row=2)
    async def enable_global_pvp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await set_setting(self.guild_id, "global_pvp_enabled", True)
        await interaction.response.defer(ephemeral=True)  # prevents double send
        await self.update_embed()


    @discord.ui.button(label="Disable Global PVP", style=discord.ButtonStyle.red, row=2)
    async def disable_global_pvp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await set_setting(self.guild_id, "global_pvp_enabled", False)
        await interaction.response.defer(ephemeral=True)  # prevents double send
        await self.update_embed()
    

    async def update_embed(self):
        guild = await get_guild_from_id(self.guild_id)
        global_pvp_channel_id = await get_setting(self.guild_id, "global_pvp_channel")
        global_pvp_channel = discord.utils.get(guild.text_channels, id=int(global_pvp_channel_id)) if global_pvp_channel_id else None
            
        global_pvp_enabled = await get_toggle(self.guild_id, "global_pvp_enabled")
        host_role = await get_setting(self.guild_id, "host_role")
        # formatted regional roles
        regional_roles = await get_regional_roles_dict(self.guild_id)
        regional_roles_list = []
        for region, role_id in regional_roles.items():
            role = discord.utils.get(guild.roles, id=int(role_id))
            regional_roles_list.append(f"{region}: {role.mention}")
        regional_roles = "\n".join(regional_roles_list)

        print(f"Global channel: {global_pvp_channel}, PVP enabled: {global_pvp_enabled}, regional roles: {regional_roles}")

        newembed = discord.Embed(
            title="⚙️ AO Challenger Settings",
            description="`/globalpvp setchannel` - set the global pvp channel \n `/globalpvp setregionalroles` - set the roles for each region to be pinged \n `/globalpvp sethostrole` - set who can host pvp (everyone by default) \n `/help` - all commmands and guide",
            color=discord.Color.blue()
        )
        newembed.add_field(name="Global PVP Channel", value=f"{global_pvp_channel.mention}" if global_pvp_channel else "None", inline=False)
        newembed.add_field(name="Regional PVP Roles", value=regional_roles if regional_roles else "North America: Not set \n Europe: Not set \n Asia: Not set", inline=False)
        if global_pvp_enabled:
            newembed.add_field(name=f"Global PVP?", value="✅ Enabled", inline=False)
        else:
            newembed.add_field(name=f"Global PVP?", value="❌ Disabled", inline=False)
        
        if host_role:
            newembed.add_field(name="Host Role", value=f"Users with role <@&{host_role}> can host public pvp", inline=False)
        else:
            newembed.add_field(name="Host Role", value="Anyone can host public pvp", inline=False)
        if self.message:
            
            await self.message.edit(embed=newembed, view=self)
async def location_autocomplete(interaction: discord.Interaction, current: str):
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




class GlobalPVPCommands(app_commands.Group):
    # show global settings command
    # # since we have to use commands for the best UX, we can't use a settings view. read more in the GlobalSettingsView class
    # @app_commands.command(name="settings", description="edit the current global settings.")
    # @app_commands.checks.has_permissions(manage_channels=True)
    # async def globals(self, interaction: discord.Interaction):
    #     await interaction.response.defer(ephemeral=True)  # <-- Respond immediately to avoid expiration
                
    #     if not interaction.guild.id:
    #         await interaction.response.send_message(f"❌ this command is not available in DMs", ephemeral=True)
    #         return
        
    #     embed = discord.Embed(
    #         title="Loading...",
    #         description="Use the buttons below to configure your preferences.",
    #         color=discord.Color.blue()
    #     )

    #     channels = await text_channel_options(interaction.guild.id)
    #     roles = await get_roles_as_options(interaction.guild.id)
    #     view = GlobalSettingsView(channels, roles, interaction.guild_id)
        
    #     sent = await interaction.followup.send(embed=embed, view=view, ephemeral=True)  # <-- Follow up instead
    #     view.message = sent
    #     await view.update_embed()


    # ping for global pvp
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
    @app_commands.checks.cooldown(1, 900, key=None)
    async def ping(
        self,
        interaction: discord.Interaction,
        region: str,
        where: str,
        code: str,
        extra: str = None,
    ):
        
        if not interaction.guild.id:
            await interaction.response.send_message(f"❌ this command is not available in DMs", ephemeral=True)
            return

        host_role = await get_setting(interaction.guild.id, "host_role")
        if host_role and not host_role in interaction.user.roles:
            await interaction.response.send_message(f"❌ you need the role <@&{host_role}> to ping for pvp", ephemeral=True)

        global_pvp_channel_id = await get_setting(interaction.guild.id, "global_pvp_channel")
        if not global_pvp_channel_id or not interaction.guild.get_channel(int(global_pvp_channel_id)):
            await interaction.response.send_message(f"❌ no global pvp channel set. Please tell an admin to set a global pvp channel with `/globalpvp setchannel`", ephemeral=True)
            return
        else:
            await interaction.response.send_message(f"✅ your pvp announcement is out! Publish extra announcements in your host thread in <#{global_pvp_channel_id}>", ephemeral=True)

        asyncio.create_task(self._handle_global_ping(interaction, region, where, code, extra))

    async def _handle_global_ping(self, interaction: discord.Interaction, region: str, where: str, code: str, extra: str = None):
        host_id = int(interaction.user.id)
        host_thread_id = None
        relay_entries = []
        for guild in bot.guilds:
            try:

                # check if global pvp is enabled for this guild
                global_pvp_enabled = await get_toggle(guild.id, "global_pvp_enabled")
                blocked_users = await get_blocked_users(guild.id)
                is_blocked = await is_blocked_user(interaction.user.name, guild.id)

                if is_blocked:
                    continue

                global_pvp_channel_id = await get_setting(guild.id, "global_pvp_channel")
                if not global_pvp_channel_id or not global_pvp_enabled:
                    continue

                channel = discord.utils.get(guild.text_channels, id=int(global_pvp_channel_id))
                if not channel:
                    continue

                # Get regional role config
                config = await db.server_config.find_one({"guild_id": int(guild.id), "name": "regional_roles"})
                regional_roles = config["value"] if config else {}
                regional_role = regional_roles.get(region)

                regional_role_mention = f"(<@&{regional_role}>)" if regional_role else f"({region})\n-# No regional role set for {region}. Please contact a server admin if this isn't intentional"
                extra_text = f"\nExtra info: {extra}" if extra else ""
                guild_count = len(bot.guilds)
                messagecontent = (
                    f"{interaction.user.mention} is pvping at {where}. User/code: `{code}` {regional_role_mention} "
                    f"{extra_text}"
                    f"\n-# TIP: Use `/globalpvp ping` to ping an entire region for pvp"
                )

                sent_msg = await channel.send(messagecontent)
                thread = await sent_msg.create_thread(
                    name=f"{interaction.user.name}'s announcements",
                    auto_archive_duration=60,
                    reason="pvp thread"
                )
                utc_now = datetime.datetime.now(datetime.timezone.utc)
                timestamp = int(utc_now.timestamp())

                
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
                        f"👑 {interaction.user.mention} this is your HOST thread. Use this channel for announcements to your guests. Created on <t:{timestamp}:f>. "
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
                print(f"Error in globalpvp: {e}")

    @ping.error
    async def ping_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.errors.CommandOnCooldown):
            await interaction.response.send_message(
                f"Someone already pinged for pvp in the last {error.cooldown.per} seconds. Please wait before pinging again.",
                ephemeral=True
            )

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
                await button_interaction.response.send_message(f"✅ {interaction.user.mention} blocked `{username}` for {duration} day(s)", ephemeral=True)
            elif button_interaction.data["custom_id"] == "cancel":
                await button_interaction.response.send_message(f"❌ Cancelled", ephemeral=True)

        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out, no action taken.", ephemeral=True)
        

    @app_commands.command(name="unblockuser", description="Unblock a user from interacting with your server")
    @app_commands.describe(
        username="Discord username",
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
        

    @app_commands.command(name="setchannel", description="set the global pvp channel")
    @app_commands.describe(
        channel="the channel to receive pings",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def setchannel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await set_setting(interaction.guild.id, "global_pvp_channel", channel.id)
        await interaction.response.send_message(f"✅ set global pvp channel to {channel.mention}. ", ephemeral=True)

    @app_commands.command(name="setregionalroles" , description="set the regional pvp roles")
    @app_commands.describe(
        region="the region",
        role="the role tied to the region",
    )
    @app_commands.choices(
        region=region_choices,
    )

    @app_commands.checks.has_permissions(manage_channels=True)
    async def setregionalroles(
        self,
        interaction: discord.Interaction,
        region: str,
        role: discord.Role,
    ):
        current_roles = await get_regional_roles_dict(interaction.guild.id)
        current_roles[region] = role.id
        await set_setting(interaction.guild.id, "regional_roles", current_roles)
        await interaction.response.send_message(f"✅ set regional role for {region} to {role.mention}", ephemeral=True)
    
    @app_commands.command(name="sethostrole", description="set the role that can host pvp (everyone by default)")
    @app_commands.describe(
        role="role that will be able to host pvp",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def sethostrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ):
        await set_setting(interaction.guild.id, "host_role", role.id)
        await interaction.response.send_message(f"✅ set host role to {role.mention}", ephemeral=True)

    @app_commands.command(name="clearhostrole", description="clear the host role")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def clearhostrole(
        self,
        interaction: discord.Interaction,
    ):
        await set_setting(interaction.guild.id, "host_role", False)
        await interaction.response.send_message(f"✅ cleared host role", ephemeral=True)
        
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




# SERVER SETUP

class SetupView(View):
    # this command uses self.guild instead of self.guild_id, be careful
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
            await self.step_select_channel(interaction)
        elif self.step == 3:
            await self.step_assign_roles(interaction)
        elif self.step == 4:
            await self.step_set_host_role(interaction)
        elif self.step == 5:
            await self.finish(interaction)

    async def step_enable_global_pvp(self, interaction: Interaction):

        async def toggle_callback(enable: bool):
            await set_setting(interaction.guild.id, "global_pvp_enabled", enable)

            # Confirm it's saved
            current = await get_setting(interaction.guild.id, "global_pvp_enabled")
            print(f"Saved value: {current}")  # Debug


            await interaction.edit_original_response(
                content=f"✔️ Global PvP {'enabled' if enable else 'disabled'}.\n\n➡️ Next: Select the global PvP channel.",
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
            content="✅ Step 1: Do you want to enable Global PvP? \n This will allow your users to ping an entire region for pvp, and allow your server to receive pings (don't worry, region roles must be set first) \n All settings can be changed later using `/help`",
            view=self,
            ephemeral=True
        )




    async def step_select_channel(self, interaction: Interaction):
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


        await interaction.edit_original_response(content="Step 2: Use `/globalpvp setchannel` to select a global PvP channel", view=self)

    async def step_assign_roles(self, interaction: Interaction):
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


        await interaction.edit_original_response(content="Step 3: Use `/globalpvp setregionalroles` to assign roles to regions", view=self)


    async def step_set_host_role(self, interaction: Interaction):
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


        await interaction.edit_original_response(content="Step 4: Use `/globalpvp sethostrole` to set who can host pvp (everyone by default)", view=self)

    async def finish(self, interaction: Interaction):
        regional_roles = await get_regional_roles_dict(interaction.guild.id)
        channel_mention = f"<#{self.selected_channel}>" if self.selected_channel else "*Not set*"
        summaryEmbed = discord.Embed(
            title="🎉 Setup complete!",
            description="For more important commands, use `/help`. Players can use `/findpvp` to find players to 1v1, or `/globalpvp ping` to ping an entire region for pvp.",
            color=discord.Color.blue()
        )
        summaryEmbed.add_field(name="Global PvP Enabled", value=await get_toggle(interaction.guild.id, "global_pvp_enabled"), inline=False)
        summaryEmbed.add_field(name="Global PvP Channel", value=channel_mention, inline=False)
        summaryEmbed.add_field(name="Regional Roles", value="\n".join(f"• {region}: <@&{rid}>" for region, rid in regional_roles.items()), inline=False)
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(embed=summaryEmbed, view=None) 


@bot.tree.command(name="setup", description="Step-by-step setup for AO Challenger")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction): 
    if not interaction.guild.id:
        await interaction.response.send_message(f"❌ this command is not available in DMs", ephemeral=True)
        return
    view = SetupView(interaction.guild)
    await view.next_step(interaction)

@bot.tree.command(name="help", description="How to use the bot and all commands")
async def help(interaction: discord.Interaction):
    await interaction.response.send_message(f"All commands and guide: https://ciabidev.github.io/challenger/",embed=None)

@bot.tree.command(name="invite", description="Invite the bot to your server")
async def invite(interaction: discord.Interaction):
    # get invite.txt
    with open("app/invite.txt", "r") as f:
        invite = f.read()
    await interaction.response.send_message(f"[invite me to your server]({invite})", embed=None)

@bot.tree.command(name="upvote", description="suport the bot for FREE by upvoting it on top.gg")
async def upvote(interaction: discord.Interaction):
    # get invite.txt
    with open("app/upvote.txt", "r") as f:
        upvote = f.read()
    await interaction.response.send_message(f"[upvote me on top.gg]({upvote})")
    
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
async def queue_command(interaction: discord.Interaction, username: str, region: str, extra: str = None, where: str = None):
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

            result = await interaction.followup.send(f"{interaction.user.mention} you've been paired with {foundPlayer_mention}", embed=resultEmbed, ephemeral=True)
            await db.queue.delete_one({"username": foundPlayer["username"]})
            await db.queue.delete_one({"username": searchingPlayer["username"]})
            break
        
        await asyncio.sleep(1)
        if searchingPlayer != None:
            if datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(searchingPlayer["created_at"]) > datetime.timedelta(minutes=5):
                result = await interaction.followup.send("{interaction.user.mention} ❌ No player found in 5 minutes. Cancelling queue.", ephemeral=True)
                await msg.delete()
                await db.queue.delete_one({"username": searchingPlayer["username"]})
                break
            if await db.queue.count_documents({}) == 0:
                result = await interaction.followup.send("{interaction.user.mention} The queue has been cleared. Cancelling queue.", ephemeral=True)
                await msg.delete()
                break

# register globalpvp class
bot.tree.add_command(GlobalPVPCommands(name="globalpvp", description="global/public pvp management"))

# Global Settings View - Manage all global settings in one place with simple buttons
## features:
## displays the current settings in an updating embed
## set the global pvp channel using a button and dropdown with pagination
## set the regional ping roles using the same dropdown structure
## disable/enable global pvp using a button
## choose who can ping globally for pvp (everyone by default)
# should be fully functional and senior developer tier quality
# ALL FUNCTIONS, VARIABLES, CLAsiaSES ETC. THAT YOU USE MUST BE DEFINED FIRST
# VALIDATE YOUR CODE FOR BEST PRACTICES AND NO ERRORS BEFORE ADDING
# Includes live settings via mongodb that save to database


bot.run(token) #
