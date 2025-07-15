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
from discord import Client, SelectOption
from discord.app_commands import checks
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
url = "https://users.roblox.com/v1/usernames/users"


# Init
bot = commands.Bot(command_prefix='?', intents=intents)
import discord





@bot.event
async def on_ready():
    print(f'live on {bot.user.name} - {bot.user.id}')

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

async def text_channel_options(guild_id: str):
    guild = bot.get_guild(guild_id)
    text_channel_list = []
    for channel in guild.text_channels:
        text_channel_list.append(SelectOption(label=channel.name, value=str(channel.id)))
    return text_channel_list
async def get_global_channel(guild_id: str):
    config = await db.server_config.find_one({"guild_id": str(guild_id), "name": "global_channel"})
    if not config:
        print(f"No global channel set for guild {guild_id}")
        return None
    channel_id = int(config["value"])
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            channel = await bot.fetch_channel(channel_id)
        print(f"Global channel set to: {channel.name} ({channel.id})")
        return channel
    except Exception as e:
        print(f"Failed to get global channel for guild {guild_id}: {e}")
        return None

async def get_global_pvp_enabled(guild_id: str):
    config = await db.server_config.find_one({"guild_id": str(guild_id), "name": "global_pvp_enabled"})
    if not config or config["value"] is False:
        return False
    return True

class GlobalChannelSelect(Select):
    def __init__(self, channels: list[SelectOption]):
        super().__init__(placeholder="Select a global PvP channel...", options=channels, row=2)

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]  # This is the value the user selected
        await interaction.response.send_message(f"You selected: `{selected_value}`", ephemeral=True)
        await self.update_embed(await interaction.original_response())

class GlobalSettingsView(discord.ui.View):
    def __init__(self, channels: list[SelectOption], guild_id: str):
        super().__init__()
        self.regional_roles = "Not configured"  # default value
        self.add_item(GlobalChannelSelect(channels))
        self.guild_id = guild_id
        self.message = None  # Will be assigned after sending

    @discord.ui.button(label="Set Regional PVP Roles", style=discord.ButtonStyle.primary, row=0)
    async def set_regional_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass
    
    @discord.ui.button(label="Enable Global PVP", style=discord.ButtonStyle.green, row=1)
    async def enable_global_pvp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.server_config.update_one(
            {"guild_id": str(interaction.guild.id), "name": "global_pvp_enabled"},
            {"$set": {"value": True}},
            upsert=True
        )
        await interaction.response.defer(ephemeral=True)  # prevents double send
        await self.update_embed()

    @discord.ui.button(label="Disable Global PVP", style=discord.ButtonStyle.red, row=1)
    async def disable_global_pvp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.server_config.update_one(
            {"guild_id": str(interaction.guild.id), "name": "global_pvp_enabled"},
            {"$set": {"value": False}},
            upsert=True
        )
        await interaction.response.defer(ephemeral=True)  # prevents double send
        await self.update_embed()
        
    async def update_embed(self):
        global_channel = await get_global_channel(self.guild_id)
        pvp_enabled = await get_global_pvp_enabled(self.guild_id)

        print(f"Global channel: {global_channel}, PVP enabled: {pvp_enabled}")

        newembed = discord.Embed(
            title="⚙️ AO Challenger Settings",
            description="Use the buttons below to configure your preferences.",
            color=discord.Color.blue()
        )
        newembed.add_field(name="Global PVP Channel", value=global_channel.mention if global_channel else "None", inline=False)
        newembed.add_field(name="Regional PVP Roles", value=self.regional_roles, inline=False)
        newembed.add_field(name=f"Global PVP {'✅ Enabled' if pvp_enabled else '❌ Disabled'}", value="", inline=False)
        
        if self.message:
            await self.message.edit(embed=newembed, view=self)


class GlobalsCommands(app_commands.Group):
    # show global setttings command
    @app_commands.command(name="settings", description="show the current global settings.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def globals(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="loading...",
            description="Use the buttons below to configure your preferences.",
            color=discord.Color.blue()
        )
       
        channels = await text_channel_options(interaction.guild.id)

        view = GlobalSettingsView(channels, interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        sent = await interaction.original_response()
        view.message = sent
        await view.update_embed()

# register globals class
bot.tree.add_command(GlobalsCommands(name="globals", description="global/public pvp management"))

# Global Settings View - Manage all global settings in one place with simple buttons
## features:
## displays the current settings in an updating embed
## set the global pvp channel using a button and dropdown with pagination
## set the regional ping roles using the same dropdown structure
## disable/enable global pvp using a button
## choose who can ping globally for pvp (everyone by default)
# should be fully functional and senior developer tier quality
# ALL FUNCTIONS, VARIABLES, CLASSES ETC. THAT YOU USE MUST BE DEFINED FIRST
# VALIDATE YOUR CODE FOR BEST PRACTICES AND NO ERRORS BEFORE ADDING
# Includes live settings via mongodb that save to database


bot.run(token) #
