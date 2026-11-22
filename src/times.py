from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")

def parse_local(val: str) -> datetime:
    try:
        local = datetime.strptime(val.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("Use format YYYY-MM-DD, ex. 2026-12-12")
    return local.replace(tzinfo=ROME).astimezone(timezone.utc).replace(tzinfo=None)

def optional_parse(val: str) -> datetime | None:
    if not val.strip():
        return None
    return parse_local(val)


def discord_ts(val: datetime, style: str = "f"):
    return f"<t:{int(val.replace(tzinfo=timezone.utc).timestamp())}:{style}>"
