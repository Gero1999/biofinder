"""Bounded, in-memory exact caches. No cached authorization grants or answers."""

from collections import OrderedDict
from dataclasses import dataclass
import time
from typing import Callable


@dataclass
class Entry:
    value: object
    expires: float


class ExactCache:
    def __init__(
        self, max_entries: int = 128, clock: Callable[[], float] = time.monotonic
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries, self.clock = max_entries, clock
        self.entries: OrderedDict[tuple, Entry] = OrderedDict()
        self.hits = self.misses = 0

    def get(self, key: tuple):
        entry = self.entries.get(key)
        if entry is None or entry.expires <= self.clock():
            self.entries.pop(key, None)
            self.misses += 1
            return None
        self.entries.move_to_end(key)
        self.hits += 1
        return entry.value

    def put(self, key: tuple, value: object, ttl: float) -> None:
        if ttl <= 0:
            return
        self.entries[key] = Entry(value, self.clock() + ttl)
        self.entries.move_to_end(key)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)

    def invalidate(self, predicate=lambda key: True) -> None:
        for key in list(self.entries):
            if predicate(key):
                del self.entries[key]
