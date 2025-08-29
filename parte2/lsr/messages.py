from __future__ import annotations
import json, uuid
from typing import Any, Dict, Optional
from .constants import MAX_TTL


# Formato JSON del lab
# {
# "proto": "dijkstra|flooding|lsr|...",
# "type": "message|echo|info|hello|...",
# "from": "nodeA",
# "to": "nodeB|*",
# "ttl": 5,
# "headers": [{...}],
# "payload": "..."
# }


def base(proto: str, mtype: str, src: str, dst: str, payload: Any, ttl: int = MAX_TTL, headers: Optional[list] = None) -> Dict[str, Any]:
    return {
    "id": str(uuid.uuid4()),
    "proto": proto,
    "type": mtype,
    "from": src,
    "to": dst,
    "ttl": ttl,
    "headers": headers or [],
    "payload": payload,
    }


# HELLO: medición de RTT
# payload = { "t0": epoch_float }


def hello(proto: str, src: str, dst: str, t0: float) -> Dict[str, Any]:
    return base(proto, "hello", src, dst, {"t0": t0})


# LSP (Link State Packet)
# payload = {
# "origin": node_id,
# "seq": int,
# "age": seconds_left,
# "links": { neighbor: cost, ... }
# }


def lsp(proto: str, src: str, dst: str, origin: str, seq: int, age: float, links: Dict[str, float]) -> Dict[str, Any]:
    return base(proto, "info", src, dst, {
    "origin": origin,
    "seq": seq,
    "age": age,
    "links": links
    })


# DATA
# payload = { "dst": node_id, "msg": str }


def data(proto: str, src: str, dst_node: str, msg: str) -> Dict[str, Any]:
    return base(proto, "message", src, dst_node, {"dst": dst_node, "msg": msg})




def encode(msg: Dict[str, Any]) -> bytes:
    return (json.dumps(msg) + "\n").encode("utf-8")


def decode(line: bytes) -> Dict[str, Any]:
    return json.loads(line.decode("utf-8").strip())