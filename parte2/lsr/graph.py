from __future__ import annotations
from typing import Dict, Set


class Graph:
    def __init__(self):
        self.adj: Dict[str, Dict[str, float]] = {}


    def add_link(self, u: str, v: str, w: float):
        self.adj.setdefault(u, {})[v] = w
        self.adj.setdefault(v, {})[u] = w


    def neighbors(self, u: str) -> Dict[str, float]:
        return self.adj.get(u, {})


    def nodes(self) -> Set[str]:
        return set(self.adj.keys())