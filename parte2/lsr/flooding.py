# flooding_node.py
from __future__ import annotations
import argparse
import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, Any, Tuple, Optional, Set

BUFFER_SIZE = 65535


@dataclass
class Graph:
    adj: Dict[str, Dict[str, float]] = field(default_factory=dict)
    directed: bool = False

    def add_edge(self, u: str, v: str, w: float = 1.0) -> None:
        self.adj.setdefault(u, {})
        self.adj.setdefault(v, {})
        self.adj[u][v] = float(w)
        if not self.directed:
            self.adj[v][u] = float(w)

    @classmethod
    def from_topology(cls, topo: Dict[str, Any], directed: bool = False) -> "Graph":
        if topo.get("type") != "topo" or "config" not in topo:
            raise ValueError('Topología inválida: se esperaba {"type":"topo","config":{...}}')
        g = cls(directed=directed)
        cfg = topo["config"]
        for u, neigh in cfg.items():
            if isinstance(neigh, list):
                for v in neigh:
                    g.add_edge(str(u), str(v), 1.0)
            elif isinstance(neigh, dict):
                for v, w in neigh.items():
                    g.add_edge(str(u), str(v), float(w))
            else:
                raise ValueError(f"Vecinos inválidos para {u}")
        return g

    def nodes(self) -> Iterable[str]:
        return self.adj.keys()

    def neighbors(self, u: str) -> Iterable[str]:
        return self.adj.get(u, {}).keys()



def envelope_message(
    proto: str,
    typ: str,
    src: str,
    dst: str,
    ttl: int,
    payload: Any,
    headers: Optional[list] = None,
    mid: Optional[str] = None,
) -> Dict[str, Any]:

    return {
        "id": mid or str(uuid.uuid4()),
        "proto": proto,           
        "type": typ,              
        "from": src,
        "to": dst,                
        "ttl": int(ttl),
        "headers": headers or [], 
        "payload": payload,
    }



def load_endpoints(path: str) -> Dict[str, Tuple[str, int]]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    eps: Dict[str, Tuple[str, int]] = {}
    for k, v in raw.items():
        if isinstance(v, list) and len(v) == 2:
            eps[str(k)] = (str(v[0]), int(v[1]))
        elif isinstance(v, dict) and "host" in v and "port" in v:
            eps[str(k)] = (str(v["host"]), int(v["port"]))
        else:
            raise ValueError("endpoint inválido (usa ['host',port] o {'host':...,'port':...})")
    return eps



class FloodingNode:
    def __init__(self, node_id: str, graph: Graph, endpoints: Dict[str, Tuple[str, int]], listen: bool = True):
        self.node_id = node_id
        self.graph = graph
        self.endpoints = endpoints        
        self.seen: Set[Tuple[str, str]] = set()  
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.listen = listen
        if self.listen:
            host, port = self.endpoints[self.node_id]
            self.sock.bind((host, port))

    def start(self) -> None:
        if not self.listen:
            return
        t = threading.Thread(target=self._serve, daemon=True)
        t.start()

    def _serve(self) -> None:
        while True:
            data, _ = self.sock.recvfrom(BUFFER_SIZE)
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            self._handle(msg)

    @staticmethod
    def _get_header(headers: list, key: str, default=None):
        if not isinstance(headers, list):
            return default
        for h in headers:
            if isinstance(h, dict) and key in h:
                return h[key]
        return default

    def _handle(self, msg: Dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            return
        proto = msg.get("proto")
        mtype = msg.get("type")
        origin = str(msg.get("from", ""))
        mid = str(msg.get("id", ""))
        dst = str(msg.get("to", ""))

        if proto != "flooding":
            return

        # De-dup por (origin, id)
        key = (origin, mid)
        if key in self.seen:
            return
        self.seen.add(key)

        # Entrega local 
        if dst == self.node_id or dst == "*" or mtype == "hello":
            print(json.dumps({"node": self.node_id, "event": "recv", "msg": msg}, ensure_ascii=False))

        # TTL y forwarding
        ttl = int(msg.get("ttl", 0)) - 1
        if ttl <= 0:
            return

        last_hop = self._get_header(msg.get("headers", []), "via", default=None)

        # Prepara copia con TTL decrementado y via = yo
        fwd = dict(msg)
        fwd["ttl"] = ttl
        headers = list(msg.get("headers", []))
        headers.append({"via": self.node_id})
        fwd["headers"] = headers

        # Flood a todos mis vecinos (excepto last_hop)
        self._flood(fwd, exclude=last_hop)

    def _flood(self, msg: Dict[str, Any], exclude: Optional[str] = None) -> None:
        for neigh in self.graph.neighbors(self.node_id):
            if neigh == exclude:
                continue
            ep = self.endpoints.get(neigh)
            if not ep:
                continue
            host, port = ep
            try:
                self.sock.sendto(json.dumps(msg).encode("utf-8"), (host, port))
            except Exception:
                # ignora fallos puntuales de envío
                pass

    def send(self, to: str, payload: Any, ttl: int = 8) -> None:
  
        ttl = max(1, int(ttl))
        msg = envelope_message("flooding", "message", self.node_id, str(to), ttl, payload)
        msg["headers"].append({"via": self.node_id})
        self._flood(msg, exclude=None)

    def hello(self, ttl: int = 4) -> None:
 
        ttl = max(1, int(ttl))
        msg = envelope_message("flooding", "hello", self.node_id, "*", ttl, {"ts": time.time()})
        msg["headers"].append({"via": self.node_id})
        self._flood(msg, exclude=None)

DEBUG_FLOOD = True  

# class FloodingCache:
#     def __init__(self, max_items: int = 10000, entry_ttl: float = 60.0):
#         self._seen: Dict[Tuple[str, str], float] = {}
#         self._max = max_items
#         self._ttl = entry_ttl

#     def _evict(self):
#         now = time.time()
#         expired = [k for k, exp in self._seen.items() if exp < now]
#         for k in expired:
#             self._seen.pop(k, None)
#         if len(self._seen) > self._max:
#             items = sorted(self._seen.items(), key=lambda kv: kv[1])
#             to_drop = len(self._seen) - self._max
#             for k, _ in items[:to_drop]:
#                 self._seen.pop(k, None)

#     def should_forward(self, origin: str, mid: str) -> bool:
#         if not origin or not mid:
#             if DEBUG_FLOOD:
#                 print(f"[FLOOD/DEDUP] mensaje sin origin/id: origin={origin} id={mid} -> DROP")
#             return False
#         self._evict()
#         key = (origin, mid)
#         if key in self._seen:
#             if DEBUG_FLOOD:
#                 print(f"[FLOOD/DEDUP] DUP origin={origin} id={mid} -> DROP")
#             return False
#         self._seen[key] = time.time() + self._ttl
#         if DEBUG_FLOOD:
#             print(f"[FLOOD/DEDUP] NEW origin={origin} id={mid} -> FORWARD")
#         return True

class FloodingCache:
    def __init__(self, max_items: int = 10000, entry_ttl: float = 60.0):
        self._seen: Dict[Tuple[str, str], float] = {}
        self._max = max_items
        self._ttl = entry_ttl

    def _evict(self):
        now = time.time()
        for k, exp in list(self._seen.items()):
            if exp < now:
                self._seen.pop(k, None)
        if len(self._seen) > self._max:
            items = sorted(self._seen.items(), key=lambda kv: kv[1])
            for k, _ in items[: len(self._seen) - self._max]:
                self._seen.pop(k, None)

    def should_forward(self, origin: str, mid: str) -> bool:
        if not origin or not mid:
            return False
        self._evict()
        key = (origin, mid)
        if key in self._seen:
            return False
        self._seen[key] = time.time() + self._ttl
        return True




def main() -> None:
    ap = argparse.ArgumentParser(description="Flooding - reenvío por inundación con TTL y de-dup por (origin,id).")
    ap.add_argument("--topo", required=True, help="Archivo JSON de topología {type:'topo', config:{...}}")
    ap.add_argument("--node", required=True, help="ID del nodo local")
    ap.add_argument("--endpoints", required=True, help="JSON endpoints { 'A':['127.0.0.1',5000], ... }")
    ap.add_argument("--directed", action="store_true", help="Usar grafo dirigido (por defecto no)")
    # acciones
    ap.add_argument("--send", action="store_true", help="Enviar un mensaje de prueba")
    ap.add_argument("--to", help="Destino del mensaje (ID de nodo)")
    ap.add_argument("--msg", help="Payload del mensaje")
    ap.add_argument("--ttl", type=int, default=8, help="TTL inicial")
    ap.add_argument("--hello", action="store_true", help="Enviar paquetes hello por flooding")
    args = ap.parse_args()

    with open(args.topo, "r", encoding="utf-8") as f:
        topo = json.load(f)
    g = Graph.from_topology(topo, directed=args.directed)

    eps = load_endpoints(args.endpoints)
    if args.node not in eps:
        raise SystemExit("Nodo local sin endpoint en --endpoints")

    listen = not (args.send or args.hello)
    node = FloodingNode(args.node, g, eps, listen=listen)

    if listen:
        node.start()

    time.sleep(0.2)

    if args.hello:
        node.hello(ttl=max(1, args.ttl))

    if args.send:
        if not args.to or args.msg is None:
            raise SystemExit("--send requiere --to y --msg")
        node.send(args.to, args.msg, ttl=max(1, args.ttl))

    while listen:
        time.sleep(1.0)


if __name__ == "__main__":
    main()
