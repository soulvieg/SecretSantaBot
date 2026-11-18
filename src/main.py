import os
import discord
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from bot import BotClient


def set_logging(lvl: srt = "INFO") -> None:
    logging.basicConfig(
        lvl = lvl.upper(),
        format = "%(asctime)s:%(levelname)s:%(name)s: %(message)s",
        handlers = [
            logging.StreamHandler(),
            RotatingFileHandler("bot.log", maxBytes=5_000_000, backupCount=2, encoding="utf-8"),
        ],
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def main() -> None:
    #Setup the logger for debugging
    set_logging()
    logger = logging.getLogger(__name__)
    logger.info("event %s created by %s", event.id, user.id)

    bot = BotClient()
    bot.run()


if __name__ == "__main__":
    print("Hello from secret-santa-bot!")
    main()

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

if token is None:
    raise ValueError("ERROR: DISCORD_TOKEN not found in .env file!")

client = BotClient()
client.run(token)
