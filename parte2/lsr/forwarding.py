from __future__ import annotations
from typing import Dict, Callable
import time
from .constants import *
from .messages import hello, lsp, data
from .flooding import FloodingCache

class Forwarding:
    def __init__(self, node_id: str, send_func: Callable[[str, Dict], None], routing):
        self.node_id = node_id
        self.send = send_func            
        self.routing = routing
        self.cache = FloodingCache()
        self.lsp_seq = 0
        self.last_hello_sent: dict[str,float] = {}

    # SALIENTES 
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
        nh = self.routing.next_hop(dst)
        if nh and self.routing.mode != PROTO_FLOODING:
            # En LSR/Dijkstra: proto del modo actual
            self.send(nh, data(self.routing.mode, self.node_id, dst, msg))
            return

        # Flooding (si estás en modo flooding o no hay ruta)
        for n in list(self.routing.costs_to_neighbors.keys()):
            # data(...) ya pone: to=dst y payload={"dst":dst,"msg":msg}
            self.send(n, data(PROTO_FLOODING, self.node_id, dst, msg))


    # ENTRANTES
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
            # --- DESTINO: preferir "to"; fallback a payload.dst
            dst_raw = msg.get("to")
            if not dst_raw:
                dst_raw = msg.get("payload", {}).get("dst")

            # Quitar prefijo tipo "sec20.topologia2." → quedarnos con el ID "nodo7"
            dst_bare = None
            if isinstance(dst_raw, str):
                dst_bare = dst_raw.split(".")[-1].strip()

            origin = msg.get("from", "?")
            mid = msg.get("id", "?")
            proto = msg.get("proto", "?")

            # DEBUG: usar repr para detectar espacios ocultos
            print(f"[RX/{proto.upper()}] node={repr(self.node_id)} from={origin} dst={repr(dst_raw)} bare={repr(dst_bare)} id={mid} ttl={msg.get('ttl')} via={peer}")

            # --- ENTREGA LOCAL: destino específico (bare) o broadcast "*"
            if dst_raw == "*" or (dst_bare and dst_bare == self.node_id.strip()):
                user_msg = msg.get("payload", {})
                if isinstance(user_msg, dict):
                    user_msg = user_msg.get("msg", user_msg)
                print(f"[DATA] {origin} -> {self.node_id}: {user_msg}")
                # si el destino es específico, detenemos aquí; si es "*", seguimos reenviando
                if dst_raw != "*":
                    return

            # --- NEXT-HOP por tabla (solo si no es broadcast)
            nh = None
            if dst_raw != "*" and dst_bare:
                nh = self.routing.next_hop(dst_bare)

            if nh:
                print(f"[FWD/NH/{self.routing.mode.upper()}] node={self.node_id} -> next-hop={nh} dst={dst_bare} id={mid}")
                self.send(nh, msg)
                return

            # --- FLOODING controlado (sin ruta): de-dup + no devolver al que lo envió
            origin = msg.get("from", "?")
            mid = msg.get("id", "?")
            if self.cache.should_forward(origin, mid):
                msg_copy = dict(msg)
                headers = list(msg_copy.get("headers", []))
                headers.append({"via": self.node_id})
                msg_copy["headers"] = headers

                vecinos = [n for n in self.routing.costs_to_neighbors.keys() if n != peer]
                print(f"[FWD/FLOOD] node={self.node_id} -> vecinos={vecinos} dst={dst_bare} id={mid}")
                for n in vecinos:
                    self.send(n, msg_copy)
            else:
                print(f"[FWD/FLOOD] node={self.node_id} DUP -> NO reenviar id={mid}")
