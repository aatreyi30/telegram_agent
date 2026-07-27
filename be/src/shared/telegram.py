"""Single guarded entry point for every Telethon client in the process.

Telethon keeps its session in a SQLite file, which cannot be opened by two
clients at once ("database is locked"). Every TelegramClient in this codebase
uses the SAME session name, and several scheduler jobs (owned sync, competitor
sync, publish, jit_fill) run concurrently — so without serialization they
collide on the session file. This context manager (a) holds a process-wide lock
so only one client touches the session at a time, and (b) ALWAYS disconnects,
even when ``connect()`` itself raises — otherwise the raw sqlite3 connection
leaks (the "unclosed database" ResourceWarning).

ponytail: a process-wide blocking lock serializes ALL Telegram access — fine at
this throughput; switch to one long-lived shared client if concurrency ever
matters. The lock is in-process only, so a CLI run alongside the server can
still collide — run one at a time.
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager

# Non-reentrant on purpose: no code path opens a second client while holding one.
SESSION_LOCK = threading.Lock()


@asynccontextmanager
async def telegram_session(settings):
    """Yield a connected TelegramClient, serialized process-wide and always closed."""
    from telethon import TelegramClient

    SESSION_LOCK.acquire()
    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    try:
        await client.connect()
        yield client
    finally:
        try:
            dc = client.disconnect()
            if dc is not None:          # disconnect() returns None if never connected
                await dc
        finally:
            SESSION_LOCK.release()


def _demo() -> None:
    """Self-check: the lock serializes and is released even when connect fails."""
    import asyncio

    class _Boom:
        telegram_session_name = "x"
        telegram_api_id = 1
        telegram_api_hash = "y"

    async def run():
        # Monkeypatch a fake telethon so the demo needs no network/creds.
        import sys, types
        fake = types.ModuleType("telethon")

        class FakeClient:
            def __init__(self, *a): pass
            async def connect(self): raise RuntimeError("database is locked")
            def disconnect(self): return None

        fake.TelegramClient = FakeClient
        sys.modules["telethon"] = fake
        try:
            async with telegram_session(_Boom()):
                pass
        except RuntimeError:
            pass
        finally:
            del sys.modules["telethon"]
        # The lock must be free again despite connect() blowing up.
        assert SESSION_LOCK.acquire(blocking=False), "lock leaked after connect failure"
        SESSION_LOCK.release()

    asyncio.run(run())
    print("shared/telegram.py self-check OK")


if __name__ == "__main__":
    _demo()