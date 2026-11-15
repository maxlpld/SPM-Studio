"""Bounded LRU for loaded scans and processed data."""
from collections import OrderedDict
import numpy as np

class ArrayCache:
    def __init__(self, limit_mb=384):
        self.limit_bytes = limit_mb * 1024 * 1024
        self._items = OrderedDict()
        self._bytes = 0

    def get(self, key):
        if key in self._items:
            value, size = self._items.pop(key)
            self._items[key] = (value, size)
            return value
        return None

    def put(self, key, value, size=None):
        if size is None:
            if isinstance(value, np.ndarray):
                size = value.nbytes
            elif hasattr(value, 'channels'):
                size = sum(a.nbytes for ch in value.channels.values() for a in ch.traces.values())
            else:
                size = 0
        if key in self._items:
            _, prior = self._items.pop(key)
            self._bytes -= prior
        if size > self.limit_bytes:
            return
        self._items[key] = (value, size)
        self._bytes += size
        while self._bytes > self.limit_bytes:
            _, (_, cost) = self._items.popitem(last=False)
            self._bytes -= cost

    def evict_scan(self,path):
        """Forget one scan's cached arrays without flushing other loaded scans."""
        target=str(path)
        for key in list(self._items):
            if (isinstance(key,tuple) and key and key[0]=='scan' and
                isinstance(key[1],tuple) and key[1] and str(key[1][0])==target):
                _, cost=self._items.pop(key)
                self._bytes-=cost

    def clear(self):
        self._items.clear()
        self._bytes = 0

    @property
    def memory_bytes(self):
        return self._bytes
