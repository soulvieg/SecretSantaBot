import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass(frozen=True)
class Settings:
    discord_token: str
    db_url: str
    encryption_key: str
    dev: int | None
    log_lvl: str


def get_settings() -> Settings:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Discord token is missing in .env")
    return Settings(
        discord_token = token,
        db_url = os.getenv("DATABASE_URL","sqlite:///secretsanta.db"),
        encryption_key = os.getenv("ENCRYPTION_KEY", ""),
        dev = int(os.environ["DEV_ID"]) if os.getenv("DEV_ID") else None,
        log_lvl = os.getenv("LOG_LEVEL", "INFO"),
    )
