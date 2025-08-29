from __future__ import annotations
from typing import Dict, Tuple
from .graph import Graph
from .constants import LSP_AGE_SEC
import time


class LSDB:
    def __init__(self):
        self.db: Dict[str, tuple[int, float, dict[str,float]]] = {}


    def apply_lsp(self, origin: str, seq: int, age: float, links: dict[str,float]) -> bool:
        now = time.time()
        expires = now + min(age, LSP_AGE_SEC)
        cur = self.db.get(origin)
        if cur is None or seq > cur[0]:
            self.db[origin] = (seq, expires, links)
            return True
        return False


    def sweep(self) -> bool:
        now = time.time()
        rm = [o for o,(seq,exp,_) in self.db.items() if exp < now]
        for o in rm:
            del self.db[o]
        return bool(rm)


    def to_graph(self) -> Graph:
        g = Graph()
        for origin, (_,_,links) in self.db.items():
            for n,c in links.items():
                g.add_link(origin, n, c)
        return g