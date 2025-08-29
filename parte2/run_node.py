from __future__ import annotations
import argparse, json, time, threading, sys
from lsr.constants import *
from lsr.routing import Routing
from lsr.forwarding import Forwarding
from lsr.adapters.sockets import SocketAdapter
from lsr.messages import data
from lsr.adapters.sockets import SocketAdapter
from lsr.adapters.redis_pubsub import RedisPubSubAdapter


# --- CLI ---
parser = argparse.ArgumentParser()
parser.add_argument("--node", required=True, help="ID del nodo, p.ej. A")
parser.add_argument("--mode", choices=[PROTO_FLOODING, PROTO_DIJKSTRA, PROTO_LSR], default=PROTO_LSR)
parser.add_argument("--config-topo", required=True)
parser.add_argument("--config-names", required=True)
parser.add_argument("--listen", required=True, help="host:port")
parser.add_argument("--peers", default="", help="lista host:port separados por coma EN ORDEN de los vecinos del archivo topo para este nodo")

parser.add_argument("--transport", choices=["sockets", "redis"], default="sockets")

# Redis settings (por defecto los que te compartieron)
parser.add_argument("--redis-host", default="lab3.redesuvg.cloud")
parser.add_argument("--redis-port", type=int, default=6379)
parser.add_argument("--redis-pass", default="UVGRedis2025")

# Prefijo de canal: sección/topología (acuerden esto con todos)
parser.add_argument("--channel-prefix", default="sec20.topologia1")

args = parser.parse_args()

node_id = args.node

# Cargar config
with open(args.config_topo, "r", encoding="utf-8") as f:
    topo = json.load(f)["config"]
with open(args.config_names, "r", encoding="utf-8") as f:
    names = json.load(f)["config"]

neighbors = topo.get(node_id, [])
peer_eps = {}
if args.peers:
    eps = args.peers.split(",")
    assert len(eps) == len(neighbors), "--peers debe tener misma cantidad que vecinos en topo"
    for n, ep in zip(neighbors, eps):
        host,port = ep.split(":")
        peer_eps[n] = (host, int(port))

listen_host, listen_port = args.listen.split(":")
listen_port = int(listen_port)

routing = Routing(node_id)
routing.set_mode(args.mode)

# Inicializar costos a vecinos con un valor base
for n in neighbors:
    routing.update_neighbor_cost(n, 1.0)

forwarding = None
# Función de envío (la rellenamos según el adaptador elegido)
adapter = None

def _send(peer_id, msg_dict):
    adapter.send(peer_id, msg_dict)

forwarding = Forwarding(node_id, _send, routing)

# --- Selección de transporte ---
if args.transport == "sockets":
    adapter = SocketAdapter(
        node_id=node_id,
        listen_host=listen_host,
        listen_port=listen_port,
        peer_endpoints=peer_eps,
        on_message=forwarding.on_message,
    )
elif args.transport == "redis":
    adapter = RedisPubSubAdapter(
        node_id=node_id,
        channel_prefix=args.channel_prefix,
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_pass=args.redis_pass,
        on_message=forwarding.on_message,
    )
else:
    raise SystemExit("Transporte no soportado")


print(f"Nodo {node_id} levantado en modo {args.mode}. Vecinos: {neighbors}")
print("Comandos: send <DEST> <TEXTO> | lsp | hello | table | quit")

# Hilo periódico
stop = threading.Event()

def periodic():
    t_hello = 0
    t_lsp = 0
    while not stop.is_set():
        now = time.time()
        if now - t_hello >= HELLO_PERIOD_SEC:
            forwarding.send_hello_all(neighbors)
            t_hello = now
        if args.mode == PROTO_LSR and now - t_lsp >= HELLO_PERIOD_SEC * 2:
            forwarding.send_lsp_all(neighbors)
            t_lsp = now
        # lsdb aging + SPF
        if routing.lsdb.sweep():
            routing.schedule_spf()
        routing.maybe_run_spf()
        time.sleep(0.1)

thr = threading.Thread(target=periodic, daemon=True)
thr.start()

# Prompt interactivo
try:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "quit":
            break
        if line.startswith("send "):
            _, dst, *msg = line.split(" ")
            forwarding.send_data(dst, " ".join(msg))
        elif line == "lsp":
            forwarding.send_lsp_all(neighbors)
        elif line == "hello":
            forwarding.send_hello_all(neighbors)
        elif line == "table":
            print("Tabla de ruteo:", routing.table)
        else:
            print("Comando desconocido")
finally:
    stop.set()
    thr.join(timeout=1)
    adapter.stop()