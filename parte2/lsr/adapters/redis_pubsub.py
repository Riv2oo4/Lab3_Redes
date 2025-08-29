# lsr/adapters/redis_pubsub.py
from __future__ import annotations
import asyncio, json, threading
from typing import Callable, Dict, Optional

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

class RedisPubSubAdapter:
    """
    Adaptador de transporte vía Redis Pub/Sub.
    Interfaz:
      - send(peer_id, msg_dict)
      - stop()
    Llama a on_message(peer_id, msg_dict) cuando llega JSON por tu canal.
    """
    def __init__(
        self,
        node_id: str,
        channel_prefix: str,
        redis_host: str,
        redis_port: int,
        redis_pass: Optional[str],
        on_message: Callable[[str, Dict], None],
    ):
        if redis is None:
            raise RuntimeError("Falta dependencia: pip install redis>=5")
        self.node_id = node_id
        self.prefix = channel_prefix.rstrip(".")
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_pass = redis_pass
        self.on_message = on_message

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._stop_evt = threading.Event()

        self._r: Optional[redis.Redis] = None
        self._pubsub = None
        self._my_channel = f"{self.prefix}.{self.node_id}"


        # arranca el loop
        self._thread.start()
        # crea conexión y suscripción en el loop
        fut = asyncio.run_coroutine_threadsafe(self._async_init(), self._loop)
        fut.result()  # propaga errores si los hay

    # ---------- API pública ----------
    def send(self, peer_id: str, msg: Dict):
        """
        Publica el mensaje JSON en el canal del destino: <prefix>.<peer_id>
        """
        channel = f"{self.prefix}.{peer_id}"
        # Asegura que es JSON-serializable (línea por compatibilidad con otros grupos)
        payload = json.dumps(msg, ensure_ascii=False)
        fut = asyncio.run_coroutine_threadsafe(
            self._r.publish(channel, payload),
            self._loop,
        )
        # opcional: fut.result() para bloquear hasta publicar

    def stop(self):
        self._stop_evt.set()
        fut = asyncio.run_coroutine_threadsafe(self._async_close(), self._loop)
        try:
            fut.result(timeout=2)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)

    # ---------- Internos ----------
    def _run_loop(self):
        # En Windows, asegura política de loop compatible
        try:
            import platform, asyncio
            if platform.system() == "Windows":
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
        except Exception:
            pass
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _async_init(self):
        self._r = redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_pass,
            decode_responses=True,
        )
        await self._r.ping()
        self._pubsub = self._r.pubsub()
        await self._pubsub.subscribe(self._my_channel)

        # ✅ aquí sí existe self
        print(f"[REDIS] {self.node_id} suscrito a canal: {self._my_channel}")

        asyncio.create_task(self._reader())


    async def _async_close(self):
        try:
            if self._pubsub is not None:
                await self._pubsub.unsubscribe(self._my_channel)
                await self._pubsub.close()
        except Exception:
            pass
        try:
            if self._r is not None:
                await self._r.close()
        except Exception:
            pass

    async def _reader(self):
        # lee mensajes de nuestro canal y despacha a on_message
        while not self._stop_evt.is_set():
            try:
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if not msg:
                    await asyncio.sleep(0.05)
                    continue
                data = msg.get("data")
                if not data:
                    continue
                # data es un string JSON publicado por otros nodos
                try:
                    obj = json.loads(data)
                except Exception:
                    continue  # ignora basura o formatos distintos

                # Determina el "peer_id" para on_message; en nuestro protocolo,
                # el emisor viene en obj["from"] (que debe ser el ID del nodo).
                peer_id = obj.get("from", "?")
                # Llama al manejador superior (forwarding.on_message)
                self.on_message(peer_id, obj)

            except Exception:
                await asyncio.sleep(0.1)
