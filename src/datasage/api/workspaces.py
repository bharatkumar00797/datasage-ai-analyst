"""Per-caller workspaces: each caller gets a private copy of the sample database plus their
own uploads, so one visitor's CSV is never visible to (or queryable by) another."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from datasage.analyst import Analyst
from datasage.dataset import build_sample_db
from datasage.providers import Provider


@dataclass
class Workspace:
    analyst: Analyst
    uploads: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class WorkspaceStore:
    """Bounded LRU of workspaces keyed by caller; the least recently used one is dropped."""

    def __init__(
        self, provider: Provider, max_rows: int, timeout_ms: int, max_workspaces: int = 200
    ) -> None:
        self.provider = provider
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms
        self.max_workspaces = max(1, max_workspaces)
        self._items: OrderedDict[str, Workspace] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, owner: str) -> Workspace:
        with self._lock:
            ws = self._items.get(owner)
            if ws is not None:
                self._items.move_to_end(owner)
                return ws
        # Build outside the store lock: generating the sample data takes a few milliseconds.
        fresh = Workspace(Analyst(build_sample_db(), self.provider, self.max_rows, self.timeout_ms))
        with self._lock:
            ws = self._items.setdefault(owner, fresh)
            self._items.move_to_end(owner)
            while len(self._items) > self.max_workspaces:
                _, old = self._items.popitem(last=False)
                old.analyst.conn.close()
            return ws

    def reset(self, owner: str) -> None:
        with self._lock:
            ws = self._items.pop(owner, None)
        if ws is not None:
            ws.analyst.conn.close()

    def __len__(self) -> int:
        return len(self._items)
