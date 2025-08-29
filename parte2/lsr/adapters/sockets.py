from __future__ import annotations
import socket, selectors, threading
from typing import Dict, Callable
from ..messages import encode, decode

class SocketAdapter:
    def __init__(self, node_id: str, listen_host: str, listen_port: int, peer_endpoints: dict[str, tuple[str,int]], on_message: Callable[[str, dict], None]):
        self.node_id = node_id
        self.selector = selectors.DefaultSelector()
        self.on_message = on_message
        self.peers = peer_endpoints  # peer_id -> (host,port)
        self.out_socks: dict[str, socket.socket] = {}

        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.bind((listen_host, listen_port))
        self.lsock.listen()
        self.lsock.setblocking(False)
        self.selector.register(self.lsock, selectors.EVENT_READ, data=None)

        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _connect_peer(self, peer_id: str):
        if peer_id in self.out_socks:
            return
        host,port = self.peers[peer_id]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect((host,port))
            s.setblocking(False)
            self.selector.register(s, selectors.EVENT_READ, data=peer_id)
            self.out_socks[peer_id] = s
        except Exception:
            s.close()

    def send(self, peer_id: str, msg: dict):
        if peer_id not in self.out_socks and peer_id in self.peers:
            self._connect_peer(peer_id)
        s = self.out_socks.get(peer_id)
        if s:
            try:
                s.sendall(encode(msg))
            except Exception:
                try:
                    self.selector.unregister(s)
                except Exception:
                    pass
                self.out_socks.pop(peer_id, None)
                s.close()

    def _loop(self):
        while not self._stop.is_set():
            events = self.selector.select(timeout=0.2)
            for key, mask in events:
                if key.data is None:
                    # aceptar conexiones entrantes
                    conn, addr = self.lsock.accept()
                    conn.setblocking(False)
                    self.selector.register(conn, selectors.EVENT_READ, data="INCOMING")
                else:
                    peer_tag = key.data
                    sock = key.fileobj
                    try:
                        buf = sock.recv(65536)
                        if not buf:
                            self.selector.unregister(sock)
                            sock.close()
                            continue
                        # dividir por líneas (mensajes terminan en \n)
                        for line in buf.split(b"\n"):
                            if not line.strip():
                                continue
                            msg = decode(line + b"\n")
                            # Para sockets entrantes, no conocemos el peer_id real, se asume en campo 'from'
                            peer_id = msg.get("from", "?")
                            self.on_message(peer_id, msg)
                    except Exception:
                        try:
                            self.selector.unregister(sock)
                        except Exception:
                            pass
                        sock.close()

    def stop(self):
        self._stop.set()
        try:
            self.selector.unregister(self.lsock)
        except Exception:
            pass
        self.lsock.close()
        for s in list(self.out_socks.values()):
            try:
                self.selector.unregister(s)
            except Exception:
                pass
            s.close()