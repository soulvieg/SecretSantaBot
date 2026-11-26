import logging
from logging.handlers import RotatingFileHandler
from bot import BotClient

import config
import crypto


def set_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level = level.upper(),
        format = "%(asctime)s:%(levelname)s:%(name)s: %(message)s",
        handlers = [
            logging.StreamHandler(),
            RotatingFileHandler("bot.log", maxBytes=5_000_000, backupCount=2, encoding="utf-8"),
        ],
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def main() -> None:
    settings = config.get_settings()
    #Setup the logger for debugging
    set_logging(settings.log_lvl)
    crypto.validate_key()
    logger = logging.getLogger(__name__)
#   logger.info("event %s created by %s", event.id, user.id)

    bot = BotClient(settings)
    bot.run(settings.discord_token)


if __name__ == "__main__":
    print("Hello, may your secret santa treats you well!")
    main()
