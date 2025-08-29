PROTO_DIJKSTRA = "dijkstra"
PROTO_FLOODING = "flooding"
PROTO_LSR = "lsr"


TYPE_HELLO = "hello"
TYPE_INFO = "info" # aquí viajan LSPs
TYPE_DATA = "message"


HELLO_PERIOD_SEC = 2.0
HELLO_TIMEOUT_SEC = 6.0
LSP_AGE_SEC = 30.0 # caducidad de entradas LSDB
SPF_DEBOUNCE_SEC = 1.0 # esperar antes de correr Dijkstra tras cambios
MAX_TTL = 16