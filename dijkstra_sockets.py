#!/usr/bin/env python3

import argparse
import json
import socket
import threading
import time
import sys
from typing import Dict, Any, Optional
from dijkstra import Graph, DijkstraRouter, envelope_info

class DijkstraNode:
    def __init__(self, node_id: str, port: int, topo_file: str, names_file: str = None):
        self.node_id = node_id
        self.port = port
        self.neighbors = {}  
        self.routing_table = []
        
        # Cargar topología
        with open(topo_file, 'r') as f:
            topo_data = json.load(f)
        
        self.graph = Graph.from_topology(topo_data)
        self.router = DijkstraRouter(self.graph)
        
        self.node_addresses = {}
        if names_file:
            with open(names_file, 'r') as f:
                names_data = json.load(f)
                if names_data.get("type") == "names":
                    self.node_addresses = names_data["config"]
        
        self.server_socket = None
        self.running = False
        
        self.server_thread = None
        
    def start(self):
        print(f"Iniciando nodo {self.node_id} en puerto {self.port}")
        
        # Calcular tabla de ruteo inicial
        self.calculate_routing_table()
        
        # Iniciar servidor
        self.start_server()
        
        # Descubrir vecinos 
        self.discover_neighbors()
        
        # Intercambiar información inicial
        self.exchange_routing_info()
        
        print(f"Nodo {self.node_id} iniciado correctamente")
        self.print_routing_table()
        
    def start_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('localhost', self.port))
            self.server_socket.listen(5)
            
            self.running = True
            self.server_thread = threading.Thread(target=self.server_loop, daemon=True)
            self.server_thread.start()
            
            print(f"Servidor iniciado en localhost:{self.port}")
            
        except Exception as e:
            print(f"Error iniciando servidor: {e}")
            sys.exit(1)
    
    def server_loop(self):
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                # Manejar cada conexión en un thread separado
                handler_thread = threading.Thread(
                    target=self.handle_client, 
                    args=(client_socket, addr), 
                    daemon=True
                )
                handler_thread.start()
                
            except Exception as e:
                if self.running:
                    print(f"Error en server loop: {e}")
    
    def handle_client(self, client_socket: socket.socket, addr):
        try:
            data = client_socket.recv(4096).decode('utf-8')
            if data:
                message = json.loads(data)
                self.process_message(message)
                
                # Enviar confirmación
                response = {"status": "received", "from": self.node_id}
                client_socket.send(json.dumps(response).encode('utf-8'))
                
        except Exception as e:
            print(f"Error manejando cliente {addr}: {e}")
        finally:
            client_socket.close()
    
    def process_message(self, message: Dict[str, Any]):
        msg_type = message.get("type")
        msg_from = message.get("from")
        
        print(f"Mensaje recibido de {msg_from}: {msg_type}")
        
        if msg_type == "hello":
            self.handle_hello_message(message)
        elif msg_type == "info":
            self.handle_info_message(message)
        elif msg_type == "message":
            self.handle_data_message(message)
        else:
            print(f"Tipo de mensaje desconocido: {msg_type}")
    
    def handle_hello_message(self, message: Dict[str, Any]):
        sender = message.get("from")
        sender_port = message.get("payload", {}).get("port")
        
        if sender and sender_port:
            self.neighbors[sender] = ('localhost', sender_port)
            print(f"Vecino descubierto: {sender} en puerto {sender_port}")
    
    def handle_info_message(self, message: Dict[str, Any]):
        sender = message.get("from")
        routing_table = message.get("payload", {}).get("routing_table", [])
        
        print(f"Tabla de ruteo recibida de {sender}: {len(routing_table)} entradas")
    
    def handle_data_message(self, message: Dict[str, Any]):
        dest = message.get("to")
        payload = message.get("payload")
        
        if dest == self.node_id:
            print(f"MENSAJE PARA MI: {payload}")
        else:
            # Forward el mensaje
            print(f"Forwarding mensaje para {dest}")
            self.forward_message(message)
    
    def discover_neighbors(self):
        # Simular descubrimiento enviando HELLO a puertos consecutivos
        base_port = 8000
        for i in range(5):  # Probar puertos 8000-8004
            target_port = base_port + i
            if target_port != self.port:  # No enviarse a sí mismo
                self.send_hello(target_port)
                time.sleep(0.1)  # Pequeña pausa entre intentos
    
    def send_hello(self, target_port: int):
        try:
            hello_message = {
                "proto": "dijkstra",
                "type": "hello",
                "from": self.node_id,
                "ttl": 1,
                "headers": [],
                "payload": {
                    "port": self.port,
                    "message": "Hello from " + self.node_id
                }
            }
            
            self.send_message_to_port('localhost', target_port, hello_message)
            
        except Exception as e:
            pass
    
    def exchange_routing_info(self):
        if not self.neighbors:
            return
            
        info_message = envelope_info(self.node_id, self.routing_table)
        
        for neighbor_id, (host, port) in self.neighbors.items():
            try:
                self.send_message_to_port(host, port, info_message)
                print(f"Tabla enviada a {neighbor_id}")
            except Exception as e:
                print(f"Error enviando a {neighbor_id}: {e}")
    
    def send_message_to_port(self, host: str, port: int, message: Dict[str, Any]):
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(2)  
            client_socket.connect((host, port))
            
            message_json = json.dumps(message)
            client_socket.send(message_json.encode('utf-8'))
            
            # Recibir confirmación
            response = client_socket.recv(1024).decode('utf-8')
            
            client_socket.close()
            
        except Exception as e:
            raise Exception(f"Error enviando mensaje a {host}:{port}: {e}")
    
    def forward_message(self, message: Dict[str, Any]):
        dest = message.get("to")
        
        # Buscar next hop en la tabla de ruteo
        next_hop = None
        for entry in self.routing_table:
            if entry["dest"] == dest:
                next_hop = entry["next_hop"]
                break
        
        if next_hop and next_hop in self.neighbors:
            host, port = self.neighbors[next_hop]
            try:
                self.send_message_to_port(host, port, message)
                print(f"Mensaje forwarded a {dest} via {next_hop}")
            except Exception as e:
                print(f"Error forwarding: {e}")
        else:
            print(f"No se encontró ruta para {dest}")
    
    def calculate_routing_table(self):
        try:
            result = self.router.run(self.node_id)
            self.routing_table = self.router.build_forwarding_table(result, self.node_id)
            print(f"Tabla de ruteo calculada: {len(self.routing_table)} entradas")
        except Exception as e:
            print(f"Error calculando tabla: {e}")
            self.routing_table = []
    
    def print_routing_table(self):
        print(f"\nTabla de ruteo para {self.node_id}:")
        print("-" * 40)
        print(f"{'Destino':<10} {'NextHop':<10} {'Costo':<10}")
        print("-" * 40)
        
        for entry in self.routing_table:
            dest = entry["dest"]
            next_hop = entry["next_hop"] if entry["next_hop"] else "null"
            cost = entry["cost"]
            
            if cost == float("inf"):
                cost_str = "Infinity"
            else:
                cost_str = str(int(cost)) if float(cost).is_integer() else f"{cost:.2f}"
            
            print(f"{dest:<10} {next_hop:<10} {cost_str:<10}")
        
        print("-" * 40)
    
    def send_user_message(self, dest: str, message: str):
        user_message = {
            "proto": "dijkstra",
            "type": "message",
            "from": self.node_id,
            "to": dest,
            "ttl": 5,
            "headers": [],
            "payload": message
        }
        
        self.forward_message(user_message)
    
    def stop(self):
        """Detiene el nodo"""
        print(f"Deteniendo nodo {self.node_id}")
        self.running = False
        
        if self.server_socket:
            self.server_socket.close()

def main():
    parser = argparse.ArgumentParser(description="Nodo Dijkstra con comunicación por Sockets")
    parser.add_argument("--node-id", required=True, help="ID del nodo")
    parser.add_argument("--port", type=int, required=True, help="Puerto para este nodo")
    parser.add_argument("--topo", required=True, help="Archivo de topología")
    parser.add_argument("--names", help="Archivo de nombres (opcional)")
    
    args = parser.parse_args()
    
    # Crear e iniciar nodo
    node = DijkstraNode(args.node_id, args.port, args.topo, args.names)
    
    try:
        node.start()
        
        # Loop interactivo para enviar mensajes
        print("\nComandos disponibles:")
        print("  send <destino> <mensaje>  - Enviar mensaje a otro nodo")
        print("  table                     - Mostrar tabla de ruteo")
        print("  quit                      - Salir")
        
        while True:
            try:
                command = input(f"\n[{args.node_id}]> ").strip().split()
                
                if not command:
                    continue
                elif command[0] == "quit":
                    break
                elif command[0] == "table":
                    node.print_routing_table()
                elif command[0] == "send" and len(command) >= 3:
                    dest = command[1]
                    message = " ".join(command[2:])
                    node.send_user_message(dest, message)
                else:
                    print("Comando inválido")
                    
            except KeyboardInterrupt:
                break
    
    finally:
        node.stop()

if __name__ == "__main__":
    main()