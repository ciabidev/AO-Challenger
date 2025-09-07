import { Client, GatewayIntentBits, REST } from 'discord.js';
import { config } from 'dotenv';
import { MongoClient } from 'mongodb';
import axios from 'axios';

config();

const token = process.env.DISCORD_TOKEN;
const mongoUri = process.env.MONGO_URI;

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});

const mongoClient = new MongoClient(mongoUri);
await mongoClient.connect();
const db = mongoClient.db('challenger');

const threadCache = new Map();

// Roblox API functions
async function robloxUserExists(username) {
  try {
    const response = await axios.post('https://users.roblox.com/v1/usernames/users', {
      usernames: [username],
      excludeBannedUsers: false,
    });
    return response.data.data[0].name;
  } catch (error) {
    console.error('Failed request:', error.response.status);
    return false;
  }
}

async function getRobloxUserId(username) {
  try {
    const response = await axios.post('https://users.roblox.com/v1/usernames/users', {
      usernames: [username],
      excludeBannedUsers: false,
    });
    return response.data.data[0].id;
  } catch (error) {
    console.error('Failed request:', error.response.status);
    return false;
  }
}

async function getRobloxHeadshot(userId) {
  try {
    const response = await axios.get('https://thumbnails.roblox.com/v1/users/avatar-headshot', {
      params: {
        userIds: userId,
        size: '150x150',
        format: 'Png',
        isCircular: false,
      },
    });
    return response.data.data[0].imageUrl;
  } catch (error) {
    return null;
  }
}

// Bot ready event
client.once('ready', async () => {
  console.log(`Logged in as ${client.user.tag}`);

  // Sync commands
  const rest = new REST({ version: '10' }).setToken(token);
  try {
    await rest.put(
      `/applications/${client.user.id}/commands`,
      { body: [] } // Add commands here
    );
    console.log('Synced commands');
  } catch (error) {
    console.error('Error syncing commands:', error);
  }

  // Cache threads
  for (const guild of client.guilds.cache.values()) {
    const threads = await guild.channels.fetchActiveThreads();
    for (const thread of threads) {
      threadCache.set(thread[1].id, thread[1]);
    }
  }
  console.log(`Cached ${threadCache.size} threads`);
});

// Discord interaction handler
async function handleInteraction(request, env) {
  const body = await request.text();
  const signature = request.headers.get('X-Signature-Ed25519');
  const timestamp = request.headers.get('X-Signature-Timestamp');

  // Verify signature (implement verification)
  // For now, assume valid

  const interaction = JSON.parse(body);

  if (interaction.type === 1) { // Ping
    return new Response(JSON.stringify({ type: 1 }), { status: 200 });
  }

  // Handle commands
  if (interaction.type === 2) { // Application command
    const command = interaction.data.name;
    // Handle commands here
    return new Response(JSON.stringify({
      type: 4,
      data: {
        content: `Command ${command} received`,
      },
    }), { status: 200 });
  }

  return new Response('Unknown interaction', { status: 400 });
}

// Export for Cloudflare Workers
export default {
  async fetch(request, env) {
    if (request.method === 'POST' && new URL(request.url).pathname === '/interactions') {
      return await handleInteraction(request, env);
    }
    return new Response('Bot is running', { status: 200 });
  },
};

// For local development
if (typeof process !== 'undefined') {
  client.login(token);
}