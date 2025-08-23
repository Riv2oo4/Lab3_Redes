from __future__ import annotations
import time, threading
from typing import Dict
from .constants import PROTO_DIJKSTRA, PROTO_FLOODING, PROTO_LSR, SPF_DEBOUNCE_SEC
from .dijkstra import shortest_paths
from .lsdb import LSDB


class Routing:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.mode = PROTO_LSR # o flooding / dijkstra
        self.table: Dict[str,str] = {} # destino -> next_hop
        self.costs_to_neighbors: Dict[str,float] = {} # medidos por HELLO
        self.lsdb = LSDB()
        self._spf_lock = threading.Lock()
        self._spf_deadline = 0.0


    def set_mode(self, mode: str):
        self.mode = mode


    def update_neighbor_cost(self, n: str, cost: float) -> bool:
        old = self.costs_to_neighbors.get(n)
        self.costs_to_neighbors[n] = cost
        return old != cost


    def schedule_spf(self):
        with self._spf_lock:
            self._spf_deadline = time.time() + SPF_DEBOUNCE_SEC


    def maybe_run_spf(self):
        with self._spf_lock:
            if self._spf_deadline and time.time() >= self._spf_deadline:
                self._spf_deadline = 0.0
            else:
                return
        # Ejecutar SPF
        g = self.lsdb.to_graph()
        # agregar enlaces locales del propio nodo (garantiza presencia)
        for n,c in self.costs_to_neighbors.items():
            g.add_link(self.node_id, n, c)
        dist, prev, nh = shortest_paths(g, self.node_id)
        # construir FIB/tabla
        new_table = {dst: hop for dst, hop in nh.items() if dst != self.node_id}
        self.table = new_table


    def next_hop(self, dst: str) -> str | None:
        if self.mode == PROTO_FLOODING:
            return None
        if self.mode == PROTO_DIJKSTRA and dst in self.table:
            return self.table[dst]
        if self.mode == PROTO_LSR and dst in self.table:
            return self.table[dst]
        return None