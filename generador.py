#!/usr/bin/env python3
import json
import os

# Crear directorio ejemplos
os.makedirs("ejemplos", exist_ok=True)

# Topología simple para prueba básica
topo_simple = {
    "type": "topo",
    "config": {
        "A": ["B", "C"],
        "B": ["A", "D"],
        "C": ["A", "D"],
        "D": ["B", "C"]
    }
}

with open("ejemplos/topo-simple.txt", "w") as f:
    json.dump(topo_simple, f, indent=2)

print("Archivo ejemplos/topo-simple.txt creado")