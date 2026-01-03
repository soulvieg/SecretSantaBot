import os
import discord
import logging
from dotenv import load_dotenv
from bot import BotClient

print("Hello from secret-santa-bot!")


# Setup the logger for debugging
logger = logging.getLogger("discord")
logger.setLevel(logging.DEBUG)
hand = logging.FileHandler(filename="bot.log", encoding="utf-8", mode="w")
hand.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(hand)

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

if token is None:
    raise ValueError("ERROR: DISCORD_TOKEN not found in .env file!")

client = BotClient()
client.run(token)
