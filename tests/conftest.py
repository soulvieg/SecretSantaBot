import os

# db.engine builds its engine at import time, which calls get_settings().
# pytest must work without a real .env (and in CI), so provide a dummy token.
os.environ.setdefault("DISCORD_TOKEN", "test-token")
