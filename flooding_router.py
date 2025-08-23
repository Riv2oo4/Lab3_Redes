from __future__ import annotations
import argparse
import json
import socket
import threading
import time
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
            raise ValueError('Topología inválida')
        g = cls(directed=directed)
        cfg = topo["config"]
        for u, neigh in cfg.items():
            if isinstance(neigh, list):
                for v in neigh:
                    g.add_edge(u, str(v), 1.0)
            elif isinstance(neigh, dict):
                for v, w in neigh.items():
                    g.add_edge(u, str(v), float(w))
            else:
                raise ValueError(f"Vecinos inválidos para {u}")
        return g

    def nodes(self) -> Iterable[str]:
        return self.adj.keys()

    def neighbors(self, u: str) -> Iterable[str]:
        return self.adj.get(u, {}).keys()

def envelope_message(proto: str, typ: str, src: str, dst: str, ttl: int, payload: Any, headers: Optional[list] = None) -> Dict[str, Any]:
    return {
        "proto": proto,
        "type": typ,
        "from": src,
        "to": dst,
        "ttl": int(ttl),
        "headers": headers or [],
        "payload": payload,
    }

class FloodingNode:
    def __init__(self, node_id: str, graph: Graph, endpoints: Dict[str, Tuple[str, int]]):
        self.node_id = node_id
        self.graph = graph
        self.endpoints = endpoints
        self.seen: Set[str] = set()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        host, port = self.endpoints[self.node_id]
        self.sock.bind((host, port))

    def start(self) -> None:
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

    def _msg_key(self, msg: Dict[str, Any]) -> str:
        return json.dumps({"from": msg.get("from"), "to": msg.get("to"), "payload": msg.get("payload")}, sort_keys=True, ensure_ascii=False)

    def _handle(self, msg: Dict[str, Any]) -> None:
        key = self._msg_key(msg)
        if key in self.seen:
            return
        self.seen.add(key)
        if msg.get("to") == self.node_id or msg.get("type") == "echo":
            print(json.dumps({"node": self.node_id, "event": "recv", "msg": msg}, ensure_ascii=False))
            if msg.get("type") == "echo":
                return
        ttl = int(msg.get("ttl", 0)) - 1
        if ttl <= 0:
            return
        fwd = dict(msg)
        fwd["ttl"] = ttl
        self._flood(fwd, came_from=msg.get("from"))

    def _flood(self, msg: Dict[str, Any], came_from: Optional[str] = None) -> None:
        for neigh in self.graph.neighbors(self.node_id):
            if neigh == came_from:
                continue
            if neigh not in self.endpoints:
                continue
            host, port = self.endpoints[neigh]
            try:
                self.sock.sendto(json.dumps(msg).encode("utf-8"), (host, port))
            except Exception:
                pass

    def send(self, to: str, payload: Any, ttl: int = 8) -> None:
        msg = envelope_message("flooding", "message", self.node_id, to, ttl, payload)
        self._flood(msg, came_from=None)

    def ping(self, ttl: int = 4) -> None:
        for neigh in self.graph.neighbors(self.node_id):
            msg = envelope_message("flooding", "echo", self.node_id, neigh, ttl, {"ts": time.time(), "via": self.node_id})
            host, port = self.endpoints.get(neigh, ("127.0.0.1", 0))
            try:
                self.sock.sendto(json.dumps(msg).encode("utf-8"), (host, port))
            except Exception:
                pass

def load_endpoints(path: str) -> Dict[str, Tuple[str, int]]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    eps: Dict[str, Tuple[str, int]] = {}
    for k, v in raw.items():
        if isinstance(v, list) and len(v) == 2:
            eps[k] = (str(v[0]), int(v[1]))
        elif isinstance(v, dict) and "host" in v and "port" in v:
            eps[k] = (str(v["host"]), int(v["port"]))
        else:
            raise ValueError("endpoint inválido")
    return eps

def main() -> None:
    ap = argparse.ArgumentParser(description="Flooding - reenvío por inundación con TTL.")
    ap.add_argument("--topo", required=True, help="Archivo JSON de topología {type:'topo', config:{...}}")
    ap.add_argument("--node", required=True, help="ID del nodo local")
    ap.add_argument("--endpoints", required=True, help="JSON con endpoints { 'A':['127.0.0.1',5000], ... }")
    ap.add_argument("--send", action="store_true", help="Enviar un mensaje")
    ap.add_argument("--to", help="Destino del mensaje")
    ap.add_argument("--msg", help="Payload del mensaje")
    ap.add_argument("--ttl", type=int, default=8, help="TTL inicial")
    ap.add_argument("--ping", action="store_true", help="Enviar echos a vecinos")
    args = ap.parse_args()

    with open(args.topo, "r", encoding="utf-8") as f:
        topo = json.load(f)
    g = Graph.from_topology(topo)
    eps = load_endpoints(args.endpoints)

    if args.node not in eps:
        raise SystemExit("Nodo local sin endpoint")

    node = FloodingNode(args.node, g, eps)
    node.start()

    time.sleep(0.2)

    if args.ping:
        node.ping(ttl=max(1, args.ttl))

    if args.send:
        if not args.to or args.msg is None:
            raise SystemExit("--send requiere --to y --msg")
        node.send(args.to, args.msg, ttl=max(1, args.ttl))

    while True:
        time.sleep(1.0)

if __name__ == "__main__":
    main()
