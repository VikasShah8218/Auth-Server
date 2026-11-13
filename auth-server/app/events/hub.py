"""Wakes SSE streams when Postgres reports a new event.

Every replica holds one LISTEN connection, so a stream on any replica hears events committed by any other.
NOTIFY is only a wake-up: streams read the outbox themselves, and they poll as well, so a lost connection
delays delivery but can't lose an event.
"""

import asyncio
from collections import defaultdict

import asyncpg

from app.events.services import KEYS_CHANNEL, NOTIFY_CHANNEL
from app.keys.services import clear_key_cache
from settings.settings import settings
from utilities.common import logger

_RECONNECT_SECONDS = 2


class EventHub:
    def __init__(self) -> None:
        self._waiters: dict[int, set[asyncio.Event]] = defaultdict(set)
        self._task: asyncio.Task | None = None

    def _on_notify(self, _connection, _pid, _channel, payload: str) -> None:
        for waiter in self._waiters.get(int(payload), ()):
            waiter.set()

    def _on_keys_changed(self, _connection, _pid, _channel, _payload: str) -> None:
        clear_key_cache()

    async def _listen(self) -> None:
        while True:
            connection = None
            try:
                connection = await asyncpg.connect(settings.db_url)
                await connection.add_listener(NOTIFY_CHANNEL, self._on_notify)
                # A revoked key must stop working on every replica, not just this one.
                await connection.add_listener(KEYS_CHANNEL, self._on_keys_changed)
                while not connection.is_closed():
                    await asyncio.sleep(_RECONNECT_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Event listener lost: %s", type(exc).__name__)
            finally:
                if connection is not None and not connection.is_closed():
                    await connection.close()
            await asyncio.sleep(_RECONNECT_SECONDS)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def wait(self, app_id: int, timeout: float) -> None:
        """Return on the next event for this app, or when the timeout passes."""
        waiter = asyncio.Event()
        self._waiters[app_id].add(waiter)
        try:
            await asyncio.wait_for(waiter.wait(), timeout)
        except TimeoutError:
            pass
        finally:
            self._waiters[app_id].discard(waiter)


hub = EventHub()
