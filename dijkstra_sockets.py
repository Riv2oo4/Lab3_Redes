#!/usr/bin/env python3
"""
Dijkstra Router con comunicación por Sockets (Parte 1)
Cada nodo es un proceso independiente que se comunica via TCP sockets
"""

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
        self.neighbors = {}  # {neighbor_id: (host, port)}
        self.routing_table = []
        
        # Cargar topología
        with open(topo_file, 'r') as f:
            topo_data = json.load(f)
        
        self.graph = Graph.from_topology(topo_data)
        self.router = DijkstraRouter(self.graph)
        
        # Cargar nombres si se proporciona
        self.node_addresses = {}
        if names_file:
            with open(names_file, 'r') as f:
                names_data = json.load(f)
                if names_data.get("type") == "names":
                    self.node_addresses = names_data["config"]
        
        # Socket server
        self.server_socket = None
        self.running = False
        
        # Threads
        self.server_thread = None
        
    def start(self):
        """Inicia el nodo (servidor y descubrimiento de vecinos)"""
        print(f"Iniciando nodo {self.node_id} en puerto {self.port}")
        
        # Calcular tabla de ruteo inicial
        self.calculate_routing_table()
        
        # Iniciar servidor
        self.start_server()
        
        # Descubrir vecinos (simular con puertos consecutivos)
        self.discover_neighbors()
        
        # Intercambiar información inicial
        self.exchange_routing_info()
        
        print(f"Nodo {self.node_id} iniciado correctamente")
        self.print_routing_table()
        
    def start_server(self):
        """Inicia el servidor TCP para recibir mensajes"""
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
        """Loop principal del servidor"""
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
        """Maneja mensajes entrantes de un cliente"""
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
        """Procesa mensajes recibidos según el protocolo"""
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
        """Maneja mensajes HELLO para descubrimiento de vecinos"""
        sender = message.get("from")
        sender_port = message.get("payload", {}).get("port")
        
        if sender and sender_port:
            self.neighbors[sender] = ('localhost', sender_port)
            print(f"Vecino descubierto: {sender} en puerto {sender_port}")
    
    def handle_info_message(self, message: Dict[str, Any]):
        """Maneja mensajes INFO con tablas de ruteo"""
        sender = message.get("from")
        routing_table = message.get("payload", {}).get("routing_table", [])
        
        print(f"Tabla de ruteo recibida de {sender}: {len(routing_table)} entradas")
        # En una implementación completa, aquí actualizarías tu conocimiento de la red
    
    def handle_data_message(self, message: Dict[str, Any]):
        """Maneja mensajes de datos de usuario"""
        dest = message.get("to")
        payload = message.get("payload")
        
        if dest == self.node_id:
            print(f"MENSAJE PARA MI: {payload}")
        else:
            # Forward el mensaje
            print(f"Forwarding mensaje para {dest}")
            self.forward_message(message)
    
    def discover_neighbors(self):
        """Descubre vecinos enviando mensajes HELLO"""
        # Simular descubrimiento enviando HELLO a puertos consecutivos
        base_port = 8000
        for i in range(5):  # Probar puertos 8000-8004
            target_port = base_port + i
            if target_port != self.port:  # No enviarse a sí mismo
                self.send_hello(target_port)
                time.sleep(0.1)  # Pequeña pausa entre intentos
    
    def send_hello(self, target_port: int):
        """Envía mensaje HELLO a un puerto específico"""
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
            # Es normal que falle si no hay nodo en ese puerto
            pass
    
    def exchange_routing_info(self):
        """Intercambia información de ruteo con vecinos conocidos"""
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
        """Envía mensaje a un host:puerto específico"""
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(2)  # Timeout de 2 segundos
            client_socket.connect((host, port))
            
            message_json = json.dumps(message)
            client_socket.send(message_json.encode('utf-8'))
            
            # Recibir confirmación
            response = client_socket.recv(1024).decode('utf-8')
            
            client_socket.close()
            
        except Exception as e:
            raise Exception(f"Error enviando mensaje a {host}:{port}: {e}")
    
    def forward_message(self, message: Dict[str, Any]):
        """Forward un mensaje según la tabla de ruteo"""
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
        """Calcula la tabla de ruteo usando Dijkstra"""
        try:
            result = self.router.run(self.node_id)
            self.routing_table = self.router.build_forwarding_table(result, self.node_id)
            print(f"Tabla de ruteo calculada: {len(self.routing_table)} entradas")
        except Exception as e:
            print(f"Error calculando tabla: {e}")
            self.routing_table = []
    
    def print_routing_table(self):
        """Imprime la tabla de ruteo de forma legible"""
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
        """Envía un mensaje de usuario a otro nodo"""
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
    
    # Crear y iniciar nodo
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