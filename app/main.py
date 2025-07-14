import discord
from discord.ui import View, Select
import requests
import threading
import os
import sqlite3
import asyncio
import csv
import io
from discord.ext import commands
from discord import app_commands
from discord.app_commands import checks
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

MONGO_URI = os.getenv("MONGO_URI")  # or hardcode for now

mongo_client = None
_db = None

import pymongo
# The db variable will be set in on_ready
# ONLINE/OFFLINE STATUS LOGGING
url = "https://users.roblox.com/v1/usernames/users"


# Init
bot = commands.Bot(command_prefix='?', intents=intents)
import discord




@bot.event
async def on_ready():
    global mongo_client, _db, db
    if mongo_client is None:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        _db = mongo_client["warden"]
        db = _db
    print(f'live on {bot.user.name} - {bot.user.id}')

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    bot.loop.create_task(log_player_status())
    bot.logging_started = True

async def get_log_channel(guild_id: str):
    config = await db.server_config.find_one({"guild_id": str(guild_id), "name": "log_channel"})
    if not config:
        print(f"No log channel set for guild {guild_id}")
        return None
    channel_id = int(config["value"])
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            channel = await bot.fetch_channel(channel_id)
        print(f"Log channel set to: {channel.name} ({channel.id})")
        return channel
    except Exception as e:
        print(f"Failed to get log channel for guild {guild_id}: {e}")
        return None

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, discord.Forbidden):
        await interaction.response.send_message("❌ I don’t have permission to do that.", ephemeral=True)
    else:
        print(f"[Slash Command Error] {error}")
        try:
            await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)
        except:
            pass

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    print(f"Received message: {message.content}")

    await bot.process_commands(message)



#  functions for commands

def chunk_list(lst, n):
    """Helper to chunk list into pieces of size n."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

async def username_autocomplete(interaction: discord.Interaction, current: str):
    # Extract the last partial username after the last comma
    last_input = current.split(",")[-1].strip()

    usernames_cursor = db.players.find({"guild_id": str(interaction.guild.id)})
    usernames = [row["username"] async for row in usernames_cursor]

    # Filter usernames based on the last partial input
    suggestions = [
        app_commands.Choice(name=u, value=u)
        for u in usernames if last_input.lower() in u.lower()
    ][:25]  # Max 25 suggestions by Discord

    return suggestions

async def clan_autocomplete(interaction: discord.Interaction, current: str):
    clans_cursor = db.players.find({"guild_id": str(interaction.guild.id), "clan": {"$ne": None, "$ne": ""}})
    clans = set()
    async for row in clans_cursor:
        if row.get("clan"):
            clans.add(row["clan"])
    return [
        app_commands.Choice(name=c, value=c)
        for c in clans if current.lower() in c.lower()
    ][:25]

renown_choices = [
    app_commands.Choice(name="🥰 POSITIVE", value="🥰 POSITIVE"),
    app_commands.Choice(name="😈 NEGATIVE", value="😈 NEGATIVE"),
    app_commands.Choice(name="🩶 NEUTRAL", value="🩶 NEUTRAL"),
]

async def get_similar_usernames(username: str):
    # get guild id
    guild_id = str(username.guild.id) if hasattr(username, 'guild') else '0'  # Default to '0' if no guild context
    regex = {"$regex": username, "$options": "i"}
    usernames_cursor = db.players.find({"username": regex, "guild_id": str(guild_id)})
    usernames = [row["username"] async for row in usernames_cursor]
    return ', '.join(usernames)

from discord.ui import View, Select
import discord

# ping command

@bot.hybrid_command()
async def ping(ctx):
    await ctx.send('pong')

# WELCOME MESSAGE


welcome_embed = discord.Embed(title="welcome to lumi", color=0x7289DA)

welcome_embed.add_field(
    name="what is lumi",
    value=(
        "made by wheatwhole\n"
        "an open-source bot for tracking roblox player status, renown, and clans. you can set renown and clan for each player manually. it can't track the specific game a player is in, but we're always improving!\n\npro-tip: add an emoji to your clan name to make it stand out! 🏴‍☠️\n\nheavily inspired by imput and their projects. check them out!"
    ),
    inline=False
)

welcome_embed.add_field(
    name="terms and privacy",
    value=(
        "updated terms? you can always find them at https://rentry.co/lumibot"
    ),
    inline=False
)

welcome_embed.add_field(
    name="support me!",
    value=(
        "if you like lumi, consider supporting or checking out my other projects! it helps me keep things running and add new features.\n\ncheck out my profile:\nhttps://wheatwhole.github.io/\n\nor buy me a coffee?\nhttps://ko-fi.com/wheatwhole"
    ),
    inline=False
)


# if its the first time running the bot, send a welcome message
@bot.event
async def on_guild_join(guild: discord.Guild):
    target_channel = guild.system_channel or next(
        (channel for channel in guild.text_channels if channel.permissions_for(guild.me).send_messages),
        None
    )

    if target_channel is None:
        return  # No suitable channel to send message
    # ping and mention the user who added the bot
    owner = guild.owner
    await target_channel.send(f"{owner.mention}")
    await target_channel.send(embed=welcome_embed)


# add a command to display this welcome message
@bot.hybrid_command(name="welcome", description="show the welcome message for new servers.")
async def welcome(ctx):
    await ctx.send(embed=welcome_embed)




# PLAYER COMMANDS

# Ignore previous player_manager_role_check function, it was not complete and had issues. Add a player manager role check decorator that checks if the user has the player management role. Should be the built in administrator by default
async def check_player_manager_role(interaction: discord.Interaction):
    # Get the guild ID
    guild_id = str(interaction.guild.id)
    # Fetch the player management role ID from the database
    config = await db.server_config.find_one({"guild_id": guild_id, "name": "player_management_role_id"})
    if not config:
        # If no role is set, allow the command to be used by anyone with manage roles permission
        return interaction.user.guild_permissions.manage_roles
    role_id = int(config["value"])
    # Check if the user has the player management role
    role = discord.utils.get(interaction.guild.roles, id=role_id)
    if not role:
        # If the role does not exist, allow the command to be used by anyone with manage roles permission
        return interaction.user.guild_permissions.manage_roles
    if role not in interaction.user.roles:
        # If the user does not have the role, deny access
        await interaction.response.send_message(
            "❌ You do not have permission to manage players. Please contact a server admin.",
            ephemeral=True
        )
        return False
    # If the user has the role, allow access

    return True


# Convert the async function into an app_commands.check decorator
player_manager_role_check = app_commands.check(check_player_manager_role)


class RemoveClanView(discord.ui.View):
    try:
        def __init__(self, author: discord.User, clan: str):
            super().__init__(timeout=900)
            self.author = author
            self.clan = clan
            self.value = None

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            return interaction.user.id == self.author.id

        @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            await db.players.delete_many({"clan": self.clan, "guild_id": str(interaction.guild.id)})
            await interaction.response.send_message(
                content=f"⏪ all players from clan `{self.clan}` have been removed by {self.author.mention}",
                embed=None,
                ephemeral=False
            )
            self.value = True
            self.stop()

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(
                content="❌ operation cancelled",
                embed=None,
                ephemeral=True
            )
            self.value = False
            self.stop()
    except Exception as e:
        print(f"Error in RemoveClanView: {e}")
        raise e


class RemovePlayersDropdown(discord.ui.Select):
    def __init__(self, author: discord.User, players, parent_view, page=0, chunks=None, preselected=None):
        self.author = author
        self.players = players
        self.parent_view = parent_view
        self.page = page
        self.chunks = chunks or [players]
        # Always use the parent's selected_players set for defaults
        current_chunk = self.chunks[self.page]
        options = [
            discord.SelectOption(label=player, value=player, default=(player in self.parent_view.selected_players))
            for player in current_chunk
        ]
        super().__init__(
            placeholder=f"Select players to remove... (Page {self.page+1}/{len(self.chunks)})",
            min_values=1,
            max_values=min(len(current_chunk), 25),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ You're not allowed to use this.", ephemeral=True)
            return
        # Update the parent's selected_players with the current selection for this page
        current_chunk = self.chunks[self.page]
        self.parent_view.selected_players.difference_update(current_chunk)
        self.parent_view.selected_players.update(self.values)
        # Re-create the dropdown with the full current chunk, but mark selected as default
        self.parent_view.remove_item(self)
        preselected = [p for p in current_chunk if p in self.parent_view.selected_players]
        new_dropdown = RemovePlayersDropdown(
            self.author,
            self.players,
            self.parent_view,
            page=self.page,
            chunks=self.chunks,
            preselected=preselected
        )
        self.parent_view.dropdown = new_dropdown
        self.parent_view.add_item(new_dropdown)
        await interaction.response.edit_message(
            content=f"Selected players to remove: `{', '.join(self.parent_view.selected_players)}`\nPress **Confirm** to remove.",
            view=self.parent_view
        )


class RemovePlayersView(discord.ui.View):
    def __init__(self, author, players):
        super().__init__(timeout=300)
        self.author = author
        self.players = players
        self.selected_players = set()
        self.page = 0
        self.chunks = list(chunk_list(players, 25))
        self.confirm_button = discord.ui.Button(label="✅ Confirm", style=discord.ButtonStyle.danger)
        self.cancel_button = discord.ui.Button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary)
        self.prev_button = discord.ui.Button(label="Previous", style=discord.ButtonStyle.primary)
        self.confirm_button.callback = self.confirm
        self.cancel_button.callback = self.cancel
        self.next_button.callback = self.next_page
        self.prev_button.callback = self.prev_page
        self.update_dropdown()
        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.add_item(self.confirm_button)
        self.add_item(self.cancel_button)

    def update_dropdown(self):
        for item in list(self.children):
            if isinstance(item, RemovePlayersDropdown):
                self.remove_item(item)
        current_chunk = self.chunks[self.page] if self.chunks else []
        if current_chunk:
            preselected = [p for p in current_chunk if p in self.selected_players]
            self.dropdown = RemovePlayersDropdown(
                self.author,
                self.players,
                self,
                page=self.page,
                chunks=self.chunks,
                preselected=preselected
            )
            self.add_item(self.dropdown)
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.chunks) - 1

    async def next_page(self, interaction: discord.Interaction):
        if self.page < len(self.chunks) - 1:
            self.page += 1
            self.update_dropdown()
            await interaction.response.edit_message(view=self)

    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_dropdown()
            await interaction.response.edit_message(view=self)

    async def confirm(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        removed = []
        for username in self.selected_players:
            await db.players.delete_one({"username": username, "guild_id": guild_id})
            removed.append(username)
        await interaction.response.edit_message(
            content=f"🗑️ Removed players: `{', '.join(removed)}`",
            view=None
        )
        self.stop()

    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="❌ Player removal cancelled.",
            view=None
        )
        self.stop()


class PlayerListView(discord.ui.View):
    def __init__(self, players, per_page=15):  # Adjust per_page to fit character limits
        super().__init__(timeout=120)
        self.players = players
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(players) - 1) // per_page + 1

    def get_page_embed(self):
        header = f"{'Username':<22} {'Renown':<15} {' Clan':<24}\n"
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_players = self.players[start:end]
        rows = [f"{player[2]:<22} {player[3]:<15} {player[4] or '':<24}" for player in page_players]
        table = "```" + header + "\n".join(rows) + "```"
        
        embed = discord.Embed(
            title=f"Players List (Page {self.current_page + 1}/{self.total_pages})",
            description=table
        )
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_page_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_page_embed(), view=self)




class PlayersCommands(app_commands.Group):
    # SET PLAYER MANAGER ROLE COMMAND
    @app_commands.command(name="management_role", description="set the role that can manage players.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(role="pick a role that can manage players!")
    async def access_role(self, interaction: discord.Interaction, role: discord.Role):
        await db.server_config.update_one(
            {"guild_id": str(interaction.guild.id), "name": "player_management_role_id"},
            {"$set": {"value": str(role.id)}},
            upsert=True
        )
        await interaction.response.send_message(f"✅ Player management role set to {role.mention}.")
    
    # ADD PLAYER COMMAND
    @app_commands.command(name="addplayer", description="add a player to the database.")
    @player_manager_role_check
    @app_commands.describe(
        username="type the roblox username",
        renown="pick the player's renown (positive, negative, or neutral)",
        clan="Can be a clan name and/or the players rank on the leaderboard",
    )
    @app_commands.choices(
        renown=renown_choices
    )
    @app_commands.autocomplete(clan=clan_autocomplete)
    async def addplayer(
        self,
        interaction: discord.Interaction,
        username: str,
        renown: str,
        clan: str = None
    ):
        playerToAdd = await db.players.find_one({"username": username, "guild_id": str(interaction.guild.id)})
        if playerToAdd is None:
            await db.players.insert_one({
                "guild_id": str(interaction.guild.id),
                "username": username,
                "renown": renown,
                "clan": clan,
                "last_status": "Unknown",
                "logging": 0
            })
            await interaction.response.send_message(
                f"✅ added player `{username}` with renown type `{renown}` from clan `{clan}`."
            )
        else:
            await interaction.response.send_message(
                f"❌ player `{username}` is already in the database."
            )

    # LIST PLAYERS COMMAND

    
    @app_commands.command(name="listplayers", description="see all players in the database. you can filter by clan or renown.")
    @app_commands.describe(
        clan="filter by clan (optional)",
        renown="filter by renown (optional)"
    )
    @app_commands.choices(
        renown=renown_choices
    )
    @app_commands.autocomplete(clan=clan_autocomplete)
    async def list_players(
        self,
        interaction: discord.Interaction,
        clan: str = None,
        renown: str = None
    ):
        guild_id = str(interaction.guild.id)
        query = {"guild_id": guild_id}
        if clan:
            query["clan"] = clan
        if renown:
            query["renown"] = renown
        players_cursor = db.players.find(query)
        players = [player async for player in players_cursor]

        if not players:
            await interaction.response.send_message("No players found.", ephemeral=True)
            return

        # Convert MongoDB docs to tuple format expected by PlayerListView
        player_tuples = [(None, None, p["username"], p.get("renown"), p.get("clan")) for p in players]
        view = PlayerListView(player_tuples)
        await interaction.response.send_message(embed=view.get_page_embed(), view=view, ephemeral=True)

    # REMOVE PLAYERS COMMAND

    @app_commands.command(name="removeplayers", description="remove players from the database using a dropdown selector.")
    @player_manager_role_check
    async def removeplayers(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        players_cursor = db.players.find({"guild_id": guild_id})
        players = [p["username"] async for p in players_cursor]
        if not players:
            await interaction.response.send_message("No players to remove.", ephemeral=True)
            return
        view = RemovePlayersView(interaction.user, players)
        await interaction.response.send_message(
            content="Select players to remove:",
            view=view,
            ephemeral=True
        )
    
    @app_commands.command(name="export", description="download all players as a csv file.")
    async def export_players(self, interaction: discord.Interaction):
        players_cursor = db.players.find({"guild_id": str(interaction.guild.id)})
        players = [
            (p["username"], p.get("renown"), p.get("clan"))
            async for p in players_cursor
        ]

        if not players:
            await interaction.response.send_message("No players to export.", ephemeral=True)
            return

        # Create CSV in memory
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["username", "renown", "clan"])
        for row in players:
            writer.writerow(row)

        buffer.seek(0)
        file = discord.File(fp=io.BytesIO(buffer.read().encode()), filename="players_export.csv")
        await interaction.response.send_message("📤 Here is your exported player list:", file=file, ephemeral=True)


    @app_commands.command(name="import", description="import players from a csv file.")
    @player_manager_role_check
    @app_commands.describe(file="upload a csv with username, renown, clan columns.")
    async def import_players(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.filename.endswith(".csv"):
            await interaction.response.send_message("❌ Please upload a `.csv` file.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        content = await file.read()
        decoded = content.decode("utf-8")
        reader = csv.reader(io.StringIO(decoded))

        header = next(reader, None)
        if header is None or [h.lower().strip() for h in header] != ["username", "renown", "clan"]:
            await interaction.followup.send("❌ Invalid CSV header. Must be: `username, renown, clan`", ephemeral=True)
            return

        added = []
        skipped = []

        for i, row in enumerate(reader, start=2):  # start=2 accounts for header
            if len(row) < 2:
                skipped.append(f"Row {i}: Incomplete row")
                continue

            username = row[0].strip()
            renown = row[1].strip().upper()
            clan = row[2].strip() if len(row) > 2 and row[2].strip() else None

            if renown not in [choice.value for choice in renown_choices]:
                skipped.append(f"Row {i}: Invalid renown `{renown}`")
                continue

            # Check for existing
            existing = await db.players.find_one({"username": username, "guild_id": str(interaction.guild.id)})
            if existing:
                skipped.append(f"Row {i}: `{username}` already exists")
                continue

            await db.players.insert_one({
                "guild_id": str(interaction.guild.id),
                "username": username,
                "renown": renown,
                "clan": clan,
                "last_status": "Unknown",
                "logging": 0
            })
            added.append(username)

        summary = []
        if added:
            summary.append(f"✅ Imported: {', '.join(added)}")
        if skipped:
            summary.append("⚠️ Skipped:\n" + "\n".join(skipped))

        await interaction.followup.send("\n".join(summary) or "❌ No valid players imported.", ephemeral=True)

    # REMOVE PLAYER CLAN COMMAND
    # clan removal confirmation buttons
    

    @app_commands.command(name="removeplayerclan", description="remove every player from a specific clan.")
    @player_manager_role_check
    @app_commands.describe(clan="type the clan name to remove all its players")
    @app_commands.autocomplete(clan=clan_autocomplete)
    async def removeplayerclan(self, interaction: discord.Interaction, clan: str):
        confirmationEmbed = discord.Embed(
            title="confirm deletion",
            description=f"are you sure you want to remove **all** players from clan `{clan}`?",
            color=discord.Color.red()
        )
        confirmationView = RemoveClanView(interaction.user, clan)
        await interaction.response.send_message(embed=confirmationEmbed, view=confirmationView, ephemeral=True)

    # EDIT PLAYER COMMAND
    @app_commands.command(name="editplayer", description="edit a player's details.")
    @player_manager_role_check
    @app_commands.describe(
        username="the roblox username you want to edit",
        new_username="new username (optional)",
        new_renown="new renown (optional)",
        new_clan="new clan (optional)"
    )
    @app_commands.autocomplete(
        username=username_autocomplete,
        new_clan=clan_autocomplete
    )
    @app_commands.choices(
        new_renown=renown_choices
    )
    async def editplayer(
        self,
        interaction: discord.Interaction,
        username: str,
        new_username: str = None,
        new_renown: str = None,
        new_clan: str = None
    ):
        # Check if the player exists
        playerToEdit = await db.players.find_one({"username": username, "guild_id": str(interaction.guild.id)})
        if not playerToEdit:
            await interaction.response.send_message(f"❌ player `{username}` not found.", ephemeral=True)
            # add did you mean (name) functionality
            suggestions = await get_similar_usernames(username)
            if suggestions:
                await interaction.followup.send(f"Did you mean: {suggestions}?", ephemeral=True)
            return

        # Update the fields that are provided
        update_fields = {}
        if new_username:
            update_fields["username"] = new_username
        if new_renown:
            update_fields["renown"] = new_renown
        if new_clan:
            update_fields["clan"] = new_clan
        if update_fields:
            await db.players.update_one(
                {"username": username, "guild_id": str(interaction.guild.id)},
                {"$set": update_fields}
            )
        if playerToEdit:
            await interaction.response.send_message(f"✅ player `{username}` updated successfully.")

    

# LOG CHANNEL COMMANDS




# the user can configure a channel to log player online/offline status

class LogSettingsView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.message = None

    async def update_embed(self):
        guild_id = str(self.interaction.guild.id)
        
        # Fetch settings
        config = await db.server_config.find_one({"guild_id": guild_id, "name": "logging_enabled"})
        logging_enabled = config and config["value"] == "true"

        channel = await get_log_channel(guild_id)

        included_cursor = db.players.find({"guild_id": guild_id, "logging": 1})
        included = [row["username"] async for row in included_cursor]
        included_players = ", ".join(included) if included else "None"

        # Build improved help embed
        embed = discord.Embed(
            title="🛠️ Logging Settings",
            description=(
                "Here you can manage all logging options for your server! Need help? Try /help or ask <@968622168302833735> \n\n"
                "**Tips:**\n"
                "- Only players marked as 'included' will have their status tracked.\n"
                "- Make sure the bot has permission to send messages in the log channel!\n"
            ),
            color=discord.Color.green() if logging_enabled else discord.Color.red()
        )
        embed.add_field(
            name="Logging Status",
            value=("✅ Enabled" if logging_enabled else "❌ Disabled"),
            inline=False
        )
        embed.add_field(
            name="Log Channel",
            value=(channel.mention if channel else "Not set! Use the button below."),
            inline=False
        )
        embed.add_field(
            name="Included Players",
            value=(included_players if included_players else "None yet! Use 'Include Players' to add."),
            inline=False
        )

        # Edit the original message with new embed
        if self.message:
            await self.message.edit(embed=embed, view=self, content=None)

    @discord.ui.button(label="enable logging", style=discord.ButtonStyle.success, row=0)
    async def enable_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await enablelogging(interaction)
        await interaction.response.defer()
        await self.update_embed()
    @discord.ui.button(label="disable logging", style=discord.ButtonStyle.danger, row=0)
    async def disable_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await disablelogging(interaction)
        await interaction.response.defer()
        await self.update_embed()

    @discord.ui.button(label="set channel", style=discord.ButtonStyle.primary, row=1)
    async def set_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await setchannel(interaction, self)

    @discord.ui.button(label="include players", style=discord.ButtonStyle.secondary, row=1)
    async def include_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_logging_players_dropdown(interaction, self, mode="include")


    @discord.ui.button(label="exclude players", style=discord.ButtonStyle.secondary, row=1)
    async def exclude_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_logging_players_dropdown(interaction, self, mode="exclude")

    @discord.ui.button(label="done", style=discord.ButtonStyle.success, row=2)
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True

        try:
            await self.message.delete()
        except discord.NotFound:
            pass

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(
                content="⚠️ Settings timed out",
                embed=None,
                view=None  # Removes all buttons
            )

class LogsCommands(app_commands.Group):
    @app_commands.command(name="settings", description="manage all logging settings in one place.")
    @app_commands.checks.has_permissions(manage_channels=True)

    async def settings(self, interaction: discord.Interaction):
        view = LogSettingsView(interaction)
        await interaction.response.send_message(embed=discord.Embed(title="loading..."), view=view, ephemeral=True)
        sent = await interaction.original_response()
        view.message = sent
        await view.update_embed()

async def setchannel(interaction: discord.Interaction, parent_view: LogSettingsView = None):
    view = LoggingChannelView(interaction, parent_view)
    
    await interaction.response.edit_message(
        content="pick a channel for logging (i need send permissions!):",
        embed=None,
        view=view
    )


    

class LoggingChannelDropdown(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view

        # Build options list from available text channels
        options = [
            discord.SelectOption(label=channel.name, value=str(channel.id))
            for channel in parent_view.interaction.guild.text_channels
            if channel.permissions_for(parent_view.interaction.guild.me).view_channel
        ][:25]  # Discord limit

        super().__init__(
            placeholder="pick a log channel...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        selected_channel_id = int(self.values[0])
        selected_channel = interaction.guild.get_channel(selected_channel_id)

        # Permissions check
        perms = selected_channel.permissions_for(interaction.guild.me)
        if not perms.send_messages:
            await interaction.response.defer
            msg = await interaction.followup.send(f"❌ I can't send messages in {selected_channel.mention}.")
            await asyncio.sleep(5)
            await msg.delete()
            

        # Save to DB
        await db.server_config.update_one(
            {"guild_id": str(interaction.guild.id), "name": "log_channel"},
            {"$set": {"value": str(selected_channel.id)}},
            upsert=True
        )

        await interaction.response.defer()

        # Refresh original embed
        if self.parent_view and self.parent_view.parent_view:
            await self.parent_view.parent_view.update_embed()

        # Safely delete this dropdown message
        try:
            if self.parent_view.message:
                await self.parent_view.message.delete()
        except discord.NotFound:
            pass

class LoggingChannelView(discord.ui.View):
    def __init__(self, interaction, parent_view=None):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.parent_view = parent_view
        self.message = None
        self.add_item(LoggingChannelDropdown(self))


class LoggingPlayersDropdown(discord.ui.Select):
    def __init__(self, author: discord.User, players, parent_view, mode="include", preselected=None, page=0, chunks=None):
        self.author = author
        self.players = players
        self.parent_view = parent_view
        self.mode = mode
        self.page = page
        self.chunks = chunks or [players]
        preselected = preselected or []
        current_chunk = self.chunks[self.page]
        options = [
            discord.SelectOption(label=player, value=player, default=(player in preselected))
            for player in current_chunk
        ]
        super().__init__(
            placeholder=f"Select players... (Page {self.page+1}/{len(self.chunks)})",
            min_values=1,
            max_values=min(len(current_chunk), 25),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ You're not allowed to use this.", ephemeral=True)
            return
        # Update the parent's selected_players with the current selection for this page
        current_chunk = self.chunks[self.page] if hasattr(self.parent_view, 'chunks') and self.parent_view.chunks else []
        # Remove any players from this chunk from selected_players, then add the new selection
        self.parent_view.selected_players.difference_update(current_chunk)
        self.parent_view.selected_players.update(self.values)
        # Re-create the dropdown with the full current chunk, but mark selected as default
        self.parent_view.remove_item(self)
        preselected = [p for p in current_chunk if p in self.parent_view.selected_players]
        new_dropdown = LoggingPlayersDropdown(
            self.author,
            self.players,
            self.parent_view,
            self.mode,
            preselected=preselected,  # Only mark as selected, do not limit options
            page=self.page,
            chunks=self.chunks
        )
        self.parent_view.dropdown = new_dropdown
        self.parent_view.add_item(new_dropdown)
        action = "include" if self.mode == "include" else "exclude"
        embed = discord.Embed(
            title=f"Confirm Players to {action.capitalize()} in Logging",
            description=f"Selected players to **{action}**:\n`{', '.join(self.parent_view.selected_players)}`\n\nPress **Confirm** to save.",
            color=discord.Color.green() if self.mode == "include" else discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=self.parent_view)

class LoggingPlayersView(discord.ui.View):
    def __init__(self, author, players, mode="include", parent_view=None, preselected=None):
        super().__init__(timeout=300)
        self.author = author
        self.players = players
        self.mode = mode
        self.parent_view = parent_view
        # Persist selection across pages
        self.selected_players = set(preselected) if preselected else set()
        # Pagination setup
        self.page = 0
        self.chunks = list(chunk_list(players, 25))
        self.confirm_button = discord.ui.Button(label="✅ Confirm", style=discord.ButtonStyle.success)
        self.cancel_button = discord.ui.Button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary)
        self.prev_button = discord.ui.Button(label="Previous", style=discord.ButtonStyle.primary)
        self.confirm_button.callback = self.confirm
        self.cancel_button.callback = self.cancel
        self.next_button.callback = self.next_page
        self.prev_button.callback = self.prev_page
        self.update_dropdown()
        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.add_item(self.confirm_button)
        self.add_item(self.cancel_button)

    def update_dropdown(self):
        # Remove old dropdown if exists
        for item in list(self.children):
            if isinstance(item, LoggingPlayersDropdown):
                self.remove_item(item)
        current_chunk = self.chunks[self.page] if self.chunks else []
        if current_chunk:
            # Only mark as selected those in the current chunk and in selected_players
            preselected = [p for p in current_chunk if p in self.selected_players]
            self.dropdown = LoggingPlayersDropdown(
                self.author,
                self.players,
                self,
                self.mode,
                preselected=preselected,
                page=self.page,
                chunks=self.chunks
            )
            self.add_item(self.dropdown)
        # Update button states
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.chunks) - 1

    async def next_page(self, interaction: discord.Interaction):
        if self.page < len(self.chunks) - 1:
            self.page += 1
            self.update_dropdown()
            await interaction.response.edit_message(view=self)

    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_dropdown()
            await interaction.response.edit_message(view=self)

    async def confirm(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        for player in self.selected_players:
            if self.mode == "include":
                await db.players.update_one(
                    {"username": player, "guild_id": guild_id},
                    {"$set": {"logging": 1}}
                )
            elif self.mode == "exclude":
                await db.players.update_one(
                    {"username": player, "guild_id": guild_id},
                    {"$set": {"logging": 0}}
                )
        await interaction.response.edit_message(
            content=f"all done! 🍞 updated: {', '.join(self.selected_players) if self.selected_players else 'none'}",
            embed=None,
            view=None
        )
        self.stop()
        if self.parent_view:
            await self.parent_view.update_embed()

    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="cancelled! nothing changed. ❌",
            embed=None,
            view=None
        )
        self.stop()
        if self.parent_view:
            await self.parent_view.update_embed()

    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="❌ Logging update cancelled.",
            embed=None,
            view=None
        )
        self.stop()

        if self.parent_view:
            await self.parent_view.update_embed()


async def show_logging_players_dropdown(interaction: discord.Interaction, parent_view, mode="include"):
    guild_id = str(interaction.guild.id)
    if mode == "include":
        # Only show players not already included (robust to all possible values)
        players_cursor = db.players.find({"guild_id": guild_id, "$or": [{"logging": {"$exists": False}}, {"logging": 0}, {"logging": "0"}, {"logging": None}]})
        players = [row["username"] async for row in players_cursor]
        preselected = []
    else:
        # For exclude, only show currently included players (logging=1, robust to all possible values)
        players_cursor = db.players.find({"guild_id": guild_id, "logging": {"$in": [1, "1", True, "true"]}})
        players = [row["username"] async for row in players_cursor]
        preselected = []

    players = sorted(players, key=lambda x: x.lower())
    preselected = sorted(preselected, key=lambda x: x.lower())

    # Show current included/excluded players in the embed
    if mode == "include":
        included_cursor = db.players.find({"guild_id": guild_id, "logging": {"$in": [1, "1", True, "true"]}})
        included = [row["username"] async for row in included_cursor]
        summary = f"included: {', '.join(included) if included else 'none'}"
    else:
        excluded_cursor = db.players.find({"guild_id": guild_id, "$or": [{"logging": {"$exists": False}}, {"logging": 0}, {"logging": "0"}, {"logging": None}]})
        excluded = [row["username"] async for row in excluded_cursor]
        summary = f"excluded: {', '.join(excluded) if excluded else 'none'}"

    if not players:
        action_word = "include" if mode == "include" else "exclude"
        msg = await interaction.response.send_message(f"no players to {action_word}!", ephemeral=True)
        # Delete the notification after 5 seconds
        try:
            sent_msg = await interaction.original_response()
            await asyncio.sleep(5)
            await sent_msg.delete()
        except Exception:
            pass
        return

    view = LoggingPlayersView(interaction.user, players, mode, parent_view, preselected=preselected)
    await interaction.response.edit_message(
        content=f"Select players to {mode} logging:\n{summary}",
        embed=None,
        view=view
    )




async def enablelogging(interaction: discord.Interaction):
    await db.server_config.update_one(
        {"guild_id": str(interaction.guild.id), "name": "logging_enabled"},
        {"$set": {"value": "true"}},
        upsert=True
    )

async def disablelogging(interaction: discord.Interaction):
    await db.server_config.update_one(
        {"guild_id": str(interaction.guild.id), "name": "logging_enabled"},
        {"$set": {"value": "false"}},
        upsert=True
    )



class HelpView(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=300)
        self.pages = pages
        self.current_page = 0

        self.prev_button = discord.ui.Button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="Next ▶️", style=discord.ButtonStyle.secondary)

        self.prev_button.callback = self.go_previous
        self.next_button.callback = self.go_next

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

        self.update_button_states()

    def update_button_states(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.pages) - 1

    async def go_previous(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_button_states()
        await interaction.response.edit_message(content=self.pages[self.current_page], view=self)

    async def go_next(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_button_states()
        await interaction.response.edit_message(content=self.pages[self.current_page], view=self)

@bot.tree.command(name="help", description="help")
async def help_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    pages = []

    # Page 1: Logging & Channel Management
    page1 = (
        """
# Lumi Help (1/2): Logging & Channels

**/logs settings**
- Open the logging settings panel to enable/disable logging, set the log channel, and manage included/excluded players.

**Logging Features:**
- **Enable/Disable Logging:** Toggle player status tracking for your server.
- **Set Log Channel:** Choose which channel receives updates.
- **Include/Exclude Players:** Select which players are tracked.
- **Status Updates:** Get real-time online/offline/game status for included players.

_Use `/logs settings` to manage all logging options in one place!_

[Official Lumi Page](https://rentry.co/lumibot)
        """
    )

    # Page 2: Player Management
    page2 = (
        """
# Lumi Help (2/2): Player Management

**/players addplayer**
- Add a player to the database with renown and optional clan.

**/players listplayers**
- View all tracked players, filterable by clan or renown.

**/players removeplayers**
- Remove one or more players by username.

**/players editplayer**
- Edit a player's username, renown, or clan.

**/players removeplayerclan**
- Remove all players from a specific clan.

**/players export**
- Export all players as a CSV file.

**/players importplayers**
- Import players from a CSV file.

**/players management_role**
- Set which role can manage players.

_Pro tip: Use tab-complete or `/players` for all player commands!_

[Official Lumi Page](https://rentry.co/lumibot)
        """
    )

    pages.extend([page1, page2])
    view = HelpView(pages)
    await interaction.followup.send(content=pages[0], view=view, ephemeral=True)




# REGISTER PLAYERSCOMMANDS AND LOGSCOMMANDS
bot.tree.add_command(LogsCommands(name="logs", description="log channel management"))
bot.tree.add_command(PlayersCommands(name="players", description="player management"))





# PLAYER STATUS LOGGING






import aiohttp
users_url = "https://users.roblox.com/v1/usernames/users"
presence_url = "https://presence.roblox.com/v1/presence/users"
# Store message IDs for each guild
# Format: { guild_id: { "changes": message_id or None, "status_pages": [message_id, ...] } }
previous_log_messages = {}

import time
import json

# Global event for rate limiting
rate_limit_event = asyncio.Event()
rate_limit_event.set()

import bson

async def get_log_messages(guild_id):
    doc = await db.log_message_ids.find_one({"guild_id": str(guild_id)})
    if doc:
        changes_id = doc.get("changes_message_id")
        status_ids = doc.get("status_message_ids", [])
        return {"changes": changes_id, "status_pages": status_ids}
    else:
        return {"changes": None, "status_pages": []}

async def save_log_messages(guild_id, changes_id, status_ids):
    await db.log_message_ids.update_one(
        {"guild_id": str(guild_id)},
        {"$set": {"changes_message_id": changes_id, "status_message_ids": status_ids}},
        upsert=True
    )

async def send_or_edit_paginated(channel, player_list: list[dict], guild_id: str):
    log_messages = await get_log_messages(guild_id)
    old_message_ids = log_messages["status_pages"]

    MAX_FIELDS_PER_EMBED = 25
    MAX_FIELD_VALUE_LENGTH = 1024
    timestamp = int(time.time())
    timestamp_line = f"Updated: <t:{timestamp}:R>"

    # Paginate player_list into chunks of MAX_FIELDS_PER_EMBED
    embeds = []
    for i in range(0, len(player_list), MAX_FIELDS_PER_EMBED):
        chunk = player_list[i:i+MAX_FIELDS_PER_EMBED]
        embed = discord.Embed(title="📊 Player Status", color=discord.Color.blurple())
        for player in chunk:
            value = f"Renown: **{player['renown']}**\nStatus: {player['status']}"
            if len(value) > MAX_FIELD_VALUE_LENGTH:
                value = value[:MAX_FIELD_VALUE_LENGTH-3] + '...'
            embed.add_field(
                name=f"{player['username']} ({player['clan'] or 'No clan'})",
                value=value,
                inline=True
            )
        embeds.append(embed)

    new_message_ids = []
    for i, embed in enumerate(embeds):
        content = timestamp_line
        if i < len(old_message_ids):
            print(f"[DEBUG] Attempting to fetch and edit message ID: {old_message_ids[i]}")
            try:
                msg = await channel.fetch_message(old_message_ids[i])
                print(f"[DEBUG] Editing message ID: {msg.id}")
                await msg.edit(content=content, embed=embed)
                new_message_ids.append(msg.id)
            except (discord.NotFound, discord.Forbidden) as e:
                print(f"[DEBUG] Could not fetch/edit message ID {old_message_ids[i]}: {e}. Sending new message.")
                msg = await channel.send(content=content, embed=embed)
                new_message_ids.append(msg.id)
        else:
            print(f"[DEBUG] Sending new message for embed page {i}")
            msg = await channel.send(content=content, embed=embed)
            new_message_ids.append(msg.id)

    # Delete extra messages
    for msg_id in old_message_ids[len(embeds):]:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    await save_log_messages(guild_id, log_messages["changes"], new_message_ids)



# get logging enabled status


async def log_player_status():
    print("start logging")
    await bot.wait_until_ready()

    while True:
        for guild in bot.guilds:
            try:
                guild_id = str(guild.id)
                config = await db.server_config.find_one({"guild_id": guild_id, "name": "logging_enabled"})
                loggingEnabled = config and config["value"].lower() == "true"
                if not loggingEnabled:
                    continue

                channel = await get_log_channel(guild_id)
                if not channel:
                    print(f"[{guild.name}] No valid log channel set.")
                    continue

                usernames_cursor = db.players.find({"guild_id": guild_id, "logging": {"$in": [1, "1", True, "true"]}})
                usernames = [row["username"] async for row in usernames_cursor]
                print(usernames)
                if not usernames:
                    log_messages = await get_log_messages(guild_id)
                    content = "⚠ No players found in the database."
                    if log_messages["status_pages"]:
                        try:
                            msg = await channel.fetch_message(log_messages["status_pages"][0])
                            await msg.edit(content=content)
                        except (discord.NotFound, discord.Forbidden):
                            msg = await channel.send(content)
                            log_messages["status_pages"] = [msg.id]
                    else:
                        msg = await channel.send(content)
                        log_messages["status_pages"] = [msg.id]

                    await save_log_messages(guild_id, log_messages["changes"], log_messages["status_pages"])
                    continue
                payload1 = {
                    "usernames": usernames,
                    "excludeBannedUsers": False
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(users_url, json=payload1) as response:
                        if response.status != 200:
                            print("❌ Failed to fetch user info.")
                            continue
                        data = await response.json()

                user_ids = [user["id"] for user in data.get("data", [])]
                id_to_username = {user["id"]: user["name"] for user in data.get("data", [])}

                payload2 = {"userIds": user_ids}

                async with aiohttp.ClientSession() as session:
                    async with session.post(presence_url, json=payload2) as response:
                        if response.status != 200:
                            print("❌ Failed to fetch presence data.")
                            continue
                        presence_data = await response.json()

                player_statuses = []
                user_status_changes = []

                for presence in presence_data.get("userPresences", []):
                    user_id = presence["userId"]
                    username = id_to_username.get(user_id, "Unknown")
                    status_code = presence.get("userPresenceType", 0)

                    status_map = {
                        0: "Offline", 1: "Website",
                        2: "In a game", 3: "In Studio"
                    }
                    status = status_map.get(status_code, "Unknown")

                    player_doc = await db.players.find_one({"username": username, "guild_id": guild_id})
                    renown = player_doc["renown"] if player_doc and "renown" in player_doc else "Unknown"
                    clan = player_doc["clan"] if player_doc and "clan" in player_doc and player_doc["clan"] else ""
                    last_status = player_doc["last_status"] if player_doc and "last_status" in player_doc else "Unknown"

                    if status == "In a game" and last_status != "In a game":
                        user_status_changes.append(f"🟩 ***{username}*** is now in a game! Renown: `{renown}`, Clan: `{clan}`")
                    elif status != "In a game" and last_status == "In a game":
                        user_status_changes.append(f"🔴 ***{username}*** just went offline")

                    player_statuses.append({
                        'username': username,
                        'status': status,
                        'renown': renown,
                        'clan': clan
                    })

                    await db.players.update_one(
                        {"username": username, "guild_id": guild_id},
                        {"$set": {"last_status": status}}
                    )

                player_statuses.sort(key=lambda x: x['username'].lower())

                log_messages = await get_log_messages(guild_id)

                if user_status_changes:
                    embed = discord.Embed(title="Player Status Changes", description="\n".join(user_status_changes), color=discord.Color.blue())
                    if log_messages["changes"]:
                        try:
                            msg = await channel.fetch_message(log_messages["changes"])
                            await msg.edit(embed=embed)
                        except (discord.NotFound, discord.Forbidden):
                            msg = await channel.send(embed=embed)
                            log_messages["changes"] = msg.id
                    else:
                        msg = await channel.send(embed=embed)
                        log_messages["changes"] = msg.id
                else:
                    if log_messages["changes"]:
                        try:
                            msg = await channel.fetch_message(log_messages["changes"])
                            await msg.delete()
                        except (discord.NotFound, discord.Forbidden):
                            pass
                        log_messages["changes"] = None

                await save_log_messages(guild_id, log_messages["changes"], log_messages["status_pages"])

                print(f"Total players for guild {guild_id}: {len(player_statuses)}")
                await send_or_edit_paginated(channel, player_statuses, guild_id)

            except Exception as e:
                print(f"❌ Error in guild {guild.name} ({guild.id}): {e}")

        await asyncio.sleep(60)

bot.run(token) #
