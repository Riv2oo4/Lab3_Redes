from __future__ import annotations
import argparse
import json
import math
import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Iterable, Any


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
            raise ValueError("Topología inválida: se esperaba {\"type\":\"topo\",\"config\":{...}}")

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
                raise ValueError(f"Entrada de vecinos inválida para nodo {u}: {type(neigh)}")
        return g

    def nodes(self) -> Iterable[str]:
        return self.adj.keys()

    def neighbors(self, u: str) -> Dict[str, float]:
        return self.adj.get(u, {})


@dataclass
class DijkstraResult:
    dist: Dict[str, float]
    prev: Dict[str, Optional[str]]

    def next_hop(self, src: str, dst: str) -> Optional[str]:
        if dst not in self.dist or math.isinf(self.dist[dst]):
            return None
        if src == dst:
            return src
        curr = dst
        parent = self.prev.get(curr)
        if parent is None:
            return None
        while parent is not None and parent != src:
            curr = parent
            parent = self.prev.get(curr)
        return curr if parent == src else None


class DijkstraRouter:

    def __init__(self, graph: Graph):
        self.g = graph

    def run(self, source: str) -> DijkstraResult:
        if source not in self.g.adj:
            raise ValueError(f"Nodo origen '{source}' no existe en la topología")

        dist = {u: math.inf for u in self.g.nodes()}
        prev = {u: None for u in self.g.nodes()}
        dist[source] = 0.0

        pq: List[Tuple[float, str]] = [(0.0, source)]  
        visited = set()

        while pq:
            d_u, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)

            if d_u > dist[u]:
                continue

            for v, w in self.g.neighbors(u).items():
                if w < 0:
                    raise ValueError("Dijkstra requiere pesos no negativos")
                alt = dist[u] + w
                if alt < dist[v]:
                    dist[v] = alt
                    prev[v] = u
                    heapq.heappush(pq, (alt, v))

        return DijkstraResult(dist=dist, prev=prev)

    @staticmethod
    def build_forwarding_table(result: DijkstraResult, source: str) -> List[Dict[str, Any]]:
        table = []
        for dst, cost in sorted(result.dist.items(), key=lambda kv: (math.isinf(kv[1]), kv[0])):
            if dst == source:
                nh = source
            else:
                nh = result.next_hop(source, dst)
            entry = {
                "dest": dst,
                "next_hop": nh,
                "cost": cost if not math.isinf(cost) else float("inf")
            }
            table.append(entry)
        return table


def envelope_info(source: str, table: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "proto": "dijkstra",
        "type": "info",
        "from": source,
        "ttl": 5,
        "headers": [],
        "payload": {"routing_table": table},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Dijkstra - Tabla de ruteo (next-hop) desde un origen.")
    ap.add_argument("--topo", required=True, help="Ruta al archivo de topología (JSON).")
    ap.add_argument("--source", required=True, help="Nodo origen.")
    ap.add_argument("--json", action="store_true", help="Imprimir salida en JSON (envelope 'info').")
    ap.add_argument("--directed", action="store_true", help="Tratar la topología como grafo dirigido.")
    args = ap.parse_args()

    with open(args.topo, "r", encoding="utf-8") as f:
        topo = json.load(f)

    g = Graph.from_topology(topo, directed=args.directed)
    router = DijkstraRouter(g)
    res = router.run(args.source)
    table = router.build_forwarding_table(res, args.source)

    if args.json:
        print(json.dumps(envelope_info(args.source, table), indent=2, ensure_ascii=False))
    else:
        # Tabla legible
        rows = [("Destino", "NextHop", "Costo")]
        for e in table:
            cost = e["cost"]
            if cost == float("inf") or (isinstance(cost, float) and math.isinf(cost)):
                cost_str = "Infinity"
            else:
                cost_str = str(int(cost)) if float(cost).is_integer() else f"{cost:.3f}"
            rows.append((e["dest"], str(e["next_hop"]) if e["next_hop"] is not None else "null", cost_str))
        w0 = max(len(r[0]) for r in rows)
        w1 = max(len(r[1]) for r in rows)
        w2 = max(len(r[2]) for r in rows)
        print(f"{rows[0][0]:<{w0}}  {rows[0][1]:<{w1}}  {rows[0][2]:>{w2}}")
        for r in rows[1:]:
            print(f"{r[0]:<{w0}}  {r[1]:<{w1}}  {r[2]:>{w2}}")


if __name__ == "__main__":
    main()
