from __future__ import annotations
from typing import Dict, Callable
import time
from .constants import *
from .messages import hello, lsp, data
from .flooding import FloodingCache

class Forwarding:
    def __init__(self, node_id: str, send_func: Callable[[str, Dict], None], routing):
        self.node_id = node_id
        self.send = send_func            # send(peer_id, msg_dict)
        self.routing = routing
        self.cache = FloodingCache()
        self.lsp_seq = 0
        self.last_hello_sent: dict[str,float] = {}

    # --- SALIENTES ---
    def send_hello_all(self, neighbors: list[str]):
        t0 = time.time()
        for n in neighbors:
            self.last_hello_sent[n] = t0
            self.send(n, hello(self.routing.mode, self.node_id, n, t0))

    def send_lsp_all(self, neighbors: list[str]):
        self.lsp_seq += 1
        payload_links = {n: self.routing.costs_to_neighbors.get(n, 1.0) for n in neighbors}
        for n in neighbors:
            self.send(n, lsp(PROTO_LSR, self.node_id, n, self.node_id, self.lsp_seq, LSP_AGE_SEC, payload_links))

    def send_data(self, dst: str, msg: str):
        # decidir next-hop (LSR/Dijkstra) o flooding
        nh = self.routing.next_hop(dst)
        if nh:
            self.send(nh, data(self.routing.mode, self.node_id, dst, msg))
        else:
            # flooding controlado
            for n in list(self.routing.costs_to_neighbors.keys()):
                self.send(n, data(PROTO_FLOODING, self.node_id, dst, msg))

    # --- ENTRANTES ---
    def on_message(self, peer: str, msg: Dict):
        # decrementar TTL
        ttl = msg.get("ttl", MAX_TTL)
        ttl -= 1
        if ttl <= 0:
            return
        msg["ttl"] = ttl

        mtype = msg.get("type")
        proto = msg.get("proto")

        if mtype == TYPE_HELLO:
            # responder/medir RTT: si trae t0, calculamos costo
            t0 = msg.get("payload", {}).get("t0")
            if isinstance(t0, (int,float)) and peer in self.routing.costs_to_neighbors:
                rtt = max(0.1, time.time() - t0)
                changed = self.routing.update_neighbor_cost(peer, rtt)
                if changed:
                    self.routing.schedule_spf()

        elif mtype == TYPE_INFO and proto == PROTO_LSR:
            pl = msg.get("payload", {})
            origin = pl.get("origin")
            seq = int(pl.get("seq", 0))
            age = float(pl.get("age", LSP_AGE_SEC))
            links = pl.get("links", {})
            if self.routing.lsdb.apply_lsp(origin, seq, age, links):
                # re-flood a todos excepto quien lo envió
                for n in self.routing.costs_to_neighbors.keys():
                    if n != peer:
                        self.send(n, msg)
                self.routing.schedule_spf()

        elif mtype == TYPE_DATA:
            dst = msg.get("payload", {}).get("dst")
            if dst == self.node_id:
                print(f"[DATA] {msg['from']} -> {self.node_id}: {msg['payload'].get('msg')}")
                return
            # reenviar
            nh = self.routing.next_hop(dst)
            if nh:
                self.send(nh, msg)
            else:
                # flooding con de-dup por (origin,id)
                origin = msg.get("from", "?")
                mid = msg.get("id", "?")
                if self.cache.should_forward(origin, mid):
                    for n in self.routing.costs_to_neighbors.keys():
                        if n != peer:
                            self.send(n, msg)