from __future__ import annotations
import json, time, threading, queue, sys
from typing import Any, Dict


now = lambda: time.time()


class StoppableThread(threading.Thread):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._stop = threading.Event()
    def stop(self):
        self._stop.set()
    def stopped(self):
        return self._stop.is_set()


class SafeQueue(queue.Queue):
    def put_now(self, item):
        try:
            self.put_nowait(item)
        except queue.Full:
            pass


def pretty(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)