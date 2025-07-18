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
        "excludeBannedUsers": False
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as resp:
            if resp.status != 200:
                print(f"Failed request: {resp.status}")
                return False
            
            result = await resp.json()
            return len(result.get("data", [])) > 0

thread_cache = {}  # global cache: {thread_id (int): discord.Thread or discord.TextChannel}

# bot initialization

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

        for channel in guild.text_channels:
            thread_cache[channel.id] = channel

        for thread in threads:
            thread_cache[thread.id] = thread
        

    print(f"Cached {len(thread_cache)} possible pvp channels/threads")


# GLOBAL PVP THREAD RELAY
# Host sends a message in host thread which is forwarded to all relay threads
# If a player sends a message in a relay thread, it is forwarded to the host thread





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
    
    if message.author.bot:
        return
    
    channel_id = int(message.channel.id)
    user_id = int(message.author.id)
    
    print(f"rate limited users: {rate_limited_users}")
    

    if user_id in rate_limited_users and rate_limited_users[user_id] == 5:
        # reply to user that they are rate limited ephemeral 
        msg = await message.reply(f"message not published. Please wait {rate_limited_users[user_id]} seconds before sending another message.")
        await asyncio.sleep(2)
        await msg.delete()
        return

    else:
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
        for role in roles if not role.is_default()
    ]
    return options

async def convert_list_to_options(guild_id: int, list: list[str]) -> list[discord.SelectOption]:
    guild = await get_guild_from_id(guild_id)
    options = [
        discord.SelectOption(label=role.name, value=int(role.id))
        for role in guild.roles if role.name in list
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

class GlobalSettingsView(discord.ui.View):
    def __init__(self, channels: list[SelectOption], guild_id: int):
        super().__init__()
        self.regional_roles = "Not configured"  # default value
        self.add_item(GlobalChannelSelect(channels, self))
        self.guild_id = guild_id
        self.message = None  # Will be assigned after sending

    @discord.ui.button(label="Set Regional PVP Roles", style=discord.ButtonStyle.primary, row=1)
    async def set_regional_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=RegionButtons(self.guild_id, self))

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
            description="Use the buttons below to configure your preferences. As of now, anyone can ping for pvp. This will be changed in a future update",
            color=discord.Color.blue()
        )
        newembed.add_field(name="Global PVP Channel", value=global_pvp_channel.mention if global_pvp_channel else "None", inline=False)
        newembed.add_field(name="Regional PVP Roles", value=regional_roles if regional_roles else "North America: Not set \n Europe: Not set \n Asia: Not set", inline=False)
        if global_pvp_enabled:
            newembed.add_field(name=f"Global PVP?", value="✅ Enabled", inline=False)
        else:
            newembed.add_field(name=f"Global PVP?", value="❌ Disabled", inline=False)
        
        if self.message:
            
            await self.message.edit(embed=newembed, view=self)
async def location_autocomplete(interaction: discord.Interaction, current: str):
    locations = [
        "South of Caitara",
        "Elysium",
        "Munera Garden",
        "Mount Orthys",
        "Mount Enkav",
        "Pelion Rift",
        "North of Vareska",
        "Sunken Caverns",
        "Temple of Valor",
        "Aetherforge Bridge",
        "Cliffside Watchtower",
        "Ruins of Oryk",
        "Snowveil Summit",
        "Crimson Hollow",
        "Verdant Plains",
        "Whispering Grove",
        "Forgotten Spire",
        "Ironclad Barracks",
        "Duskmire Marshes",
        "Zephyr Expanse"
    ]

    matches = [loc for loc in locations if current.lower() in loc.lower()]
    
    return [
        app_commands.Choice(name=loc, value=loc)
        for loc in matches[:25]
    ]

async def get_muted_users(guild_id: int):
    cursor = db.mutes.find({"guild_id": guild_id})
    muted_users = await cursor.to_list(length=None)
    userlist = []

    now = datetime.datetime.now(datetime.timezone.utc)

    for user in muted_users:
        try:
            created_at = datetime.datetime.fromisoformat(user["created_at"])
            duration = user.get("duration", 0)

            if now - created_at > datetime.timedelta(days=duration):
                await db.mutes.delete_one({"username": user["username"], "guild_id": guild_id})
            else:
                userlist.append(user["username"])

        except KeyError as e:
            print(f"Missing expected key in mute record: {e}")

    return userlist


class GlobalPVPCommands(app_commands.Group):
    # show global settings command
    @app_commands.command(name="settings", description="show the current global settings.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def globals(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)  # <-- Respond immediately to avoid expiration

        embed = discord.Embed(
            title="Loading...",
            description="Use the buttons below to configure your preferences.",
            color=discord.Color.blue()
        )

        channels = await text_channel_options(interaction.guild.id)
        view = GlobalSettingsView(channels, interaction.guild_id)
        
        sent = await interaction.followup.send(embed=embed, view=view, ephemeral=True)  # <-- Follow up instead
        view.message = sent
        await view.update_embed()
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
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.cooldown(1, 900, key=None)
    async def ping(
        self,
        interaction: discord.Interaction,
        region: str,
        where: str,
        code: str,
        extra: str = None,
    ):
        
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
                muted_users = await get_muted_users(guild.id)

                if muted_users and interaction.user.name in muted_users:
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

    @app_commands.command(name="muteuser", description="Block a user’s global PvP pings in your server")
    @app_commands.describe(
        username="Discord username",
        duration="duration of the mute in days",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def muteuser(
        self,
        interaction: discord.Interaction,
        username: str,
        duration: int,
    ):
        db.mutes.insert_one({
            "username": str(username),
            "guild_id": int(interaction.guild.id),
            "duration": duration,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

        await interaction.response.send_message(f"✅ muted {username} for {duration} days", ephemeral=True)

    @app_commands.command(name="unmuteuser", description="Unblock a user’s global PvP pings in your server")
    @app_commands.describe(
        username="Discord username",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unmuteuser(
        self,
        interaction: discord.Interaction,
        username: str,
    ):
        db.mutes.delete_one({"username": str(username)})

        await interaction.response.send_message(f"✅ unmuted {username}", ephemeral=True)
    
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

        await interaction.edit_original_response(
            content="✅ Step 1: Do you want to enable Global PvP? This will allow your users to ping an entire region for pvp, and allow your server to receive pings (don't worry, region roles must be set first)",
            view=self
        )


    async def step_select_channel(self, interaction: Interaction):
        options = [
            SelectOption(label=channel.name, value=str(channel.id))
            for channel in self.guild.text_channels if channel.permissions_for(self.guild.me).send_messages
        ]

        select = Select(placeholder="Select a global PvP channel...", options=options, row=0)
        skip = Button(label="Skip", style=ButtonStyle.danger, custom_id="skip_channel", row=1)

        async def select_callback(i: Interaction):
            self.selected_channel = int(select.values[0])
            await set_setting(self.guild.id, "global_pvp_channel", self.selected_channel)
            await i.response.edit_message(
                content=f"✔️ Global PvP channel set to <#{self.selected_channel}>.\n\n➡️ Next: Assign regional roles.",
                view=None
            )
            await asyncio.sleep(3)
            await self.next_step(i)  # use i, not original interaction

        async def skip_callback(i: Interaction):
            await i.response.edit_message(
                content="⏭️ Skipped setting Global PvP channel.\n\n➡️ Next: Assign regional roles.",
                view=self
            )
            await asyncio.sleep(3)
            await self.next_step(i)

        # Assign callbacks
        select.callback = select_callback
        skip.callback = skip_callback

        self.add_item(select)
        self.add_item(skip)

        await interaction.edit_original_response(
            content="✅ Step 2: Select a text channel to use for Global PvP pings.\nIf your channel isn't listed, make sure the bot has the `Send Messages` permission and use `/globalpvp setchannel` later.",
            view=self
        )

    async def step_assign_roles(self, interaction: Interaction):
        await interaction.edit_original_response(content="✅ Step 3: Please type role mentions in this format:\n```\nNorth America: @na-role\nEurope: @eu-role\nAsia: @asia-role\n``` \n This can be changed later with `/globalpvp setregionalroles`", view=None)

        def check(m): return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await bot.wait_for("message", timeout=120, check=check)
            lines = msg.content.strip().splitlines()
            for line in lines:
                if ":" in line:
                    region, mention = line.split(":", 1)
                    region = region.strip()
                    role_id = int(mention.strip().strip("<@&>"))
                    self.regional_roles[region] = role_id

            await set_setting(self.guild.id, "regional_roles", self.regional_roles)
            
            await interaction.followup.send("✔️ Regional roles saved", ephemeral=True)
            await self.next_step(interaction)

        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout during role input. Run `/setup` again to restart.", ephemeral=True)


    async def finish(self, interaction: Interaction):
        summary = f"""🎉 Setup complete! Use `/setup` and `/globalpvp settings` to configure your preferences. Players can use `/findpvp` to find players to 1v1, or `/globalpvp ping` to ping an entire region for pvp.
\n\n
**Global PvP Enabled:** {await get_toggle(interaction.guild.id, "global_pvp_enabled")}
**Global PvP Channel:** <#{self.selected_channel}>
**Regional Roles:**\n""" + "\n".join(f"• {region}: <@&{rid}>" for region, rid in self.regional_roles.items())

        await interaction.followup.send(summary, ephemeral=True)


@bot.tree.command(name="setup", description="Step-by-step setup for AO Challenger")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    await interaction.response.send_message("🔧 Starting setup wizard...", ephemeral=True)
    view = SetupView(interaction.guild)
    await view.next_step(interaction)



@bot.tree.command(name="findpvp", description="Find a player to pvp")
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
        user_exists = await roblox_user_exists(username)
        if user_exists:
            if not searchingPlayer:
                await db.queue.insert_one({
                    "region": region,
                    "username": username,
                    "extra": extra,
                    "where": where,
                    "user_id": int(interaction.user.id),
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                })
                searchingPlayer = await db.queue.find_one({"region": region, "username": username})
                view = QueueView(searchingPlayer["_id"])
            else:
                await db.queue.update_one({"user_id": int(interaction.user.id)}, { # prevents players from editing others queue
                    "$set": {
                        "region": region,
                        "username": username,
                        "extra": extra,
                        "where": where,
                        "user_id": int(interaction.user.id),
                        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }
                })
                searchingPlayer = await db.queue.find_one({"region": region, "username": username})
                view = QueueView(searchingPlayer["_id"])
                await interaction.response.send_message(f"edited your queue for pvp")
            await interaction.response.send_message(f"✅ added `{username}` to the queue for pvp in {region}. Players you can be paired with will be limited to the region you selected.", ephemeral=True, view=view)
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
    searchingPlayer = None
    while True:
        foundPlayer = await db.queue.find_one({"region": region, "username": {"$ne": username}})

        if foundPlayer:
            foundPlayer_mention = f"<@{foundPlayer['user_id']}>"
            result = await interaction.followup.send(f"✅✅ found a player: [{foundPlayer_mention}] \n Roblox Username/Code is `{foundPlayer['username']}`\nRegion is `{foundPlayer['region']}`\nExtra info: `{foundPlayer['extra']}`")
            await db.queue.delete_one({"username": foundPlayer["username"]})
            await db.queue.delete_one({"username": searchingPlayer["username"]})
            break
        
        await asyncio.sleep(1)
        if searchingPlayer != None:
            if datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(searchingPlayer["created_at"]) > datetime.timedelta(minutes=5):
                result = await interaction.followup.send("❌ No player found in 5 minutes. Cancelling queue.", ephemeral=True)
                await msg.delete()
                await db.queue.delete_one({"username": searchingPlayer["username"]})
                break
            if db.queue.count_documents() == 0:
                result = await interaction.followup.send("The queue has been cleared. Cancelling queue.", ephemeral=True)
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
