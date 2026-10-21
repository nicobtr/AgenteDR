"""
vision.py - Reconocimiento visual BAJO DEMANDA.

Reutiliza exactamente la misma logica de reconocer_tablero.py (config_tablero.json, carpeta
ejemplos/, comparacion con desplazamiento de +-3 px, casillas fijas de muro), pero como clase
importable: reconocer_tablero.py ejecuta todo al importarse, por eso no se puede reutilizar
directamente y se deja SIN modificar.

    observar_celdas(celdas)  -> {(f, c): (categoria, error)}   (captura + clasifica solo esas)
    reconocer_matriz()       -> matriz completa de categorias   (para reconstruir el estado)
"""

import json
import os
import time

import cv2
import mss
import numpy as np

FILAS = 15
COLUMNAS = 10
CARPETA_EJEMPLOS = "ejemplos"
RADIO_DESPLAZAMIENTO = 3


class ObservadorPantalla:
    def __init__(self, ruta_config="config_tablero.json", carpeta_ejemplos=CARPETA_EJEMPLOS,
                 espera=0.6, autocalibrar=True):
        if autocalibrar:
            # Detecta el tablero en la pantalla actual (sin seleccion manual).
            from autocalibrar import calibrar
            try:
                self.config = calibrar()
                print("Tablero detectado automaticamente:", self.config)
            except Exception as error:
                print("AVISO: autocalibracion fallida ({}). Uso {}.".format(error, ruta_config))
                with open(ruta_config, "r") as archivo:
                    self.config = json.load(archivo)
        else:
            with open(ruta_config, "r") as archivo:
                self.config = json.load(archivo)
        self.ejemplos = self._cargar_ejemplos(carpeta_ejemplos)
        if not self.ejemplos:
            raise ValueError("No se encontraron imagenes dentro de {}/.".format(carpeta_ejemplos))
        self.espera = espera          # tiempo para que termine la animacion de la reja
        self.capturas = 0

    # ---------------- utilidades (misma logica que reconocer_tablero.py) ----------------
    @staticmethod
    def _cargar_ejemplos(carpeta):
        ejemplos = {}
        for categoria in os.listdir(carpeta):
            ruta_categoria = os.path.join(carpeta, categoria)
            if not os.path.isdir(ruta_categoria):
                continue
            imagenes = []
            for nombre in os.listdir(ruta_categoria):
                imagen = cv2.imread(os.path.join(ruta_categoria, nombre))
                if imagen is not None:
                    imagenes.append(cv2.resize(imagen, (64, 64)))
            if imagenes:
                ejemplos[categoria] = imagenes
        return ejemplos

    @staticmethod
    def _comparar(a, b):
        mejor = float("inf")
        r = RADIO_DESPLAZAMIENTO
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                desplazada = np.roll(b, (dy, dx), axis=(0, 1))
                error = np.mean(cv2.absdiff(a, desplazada))
                if error < mejor:
                    mejor = error
        return mejor

    def _clasificar(self, casilla):
        imagen = cv2.resize(casilla, (64, 64))
        mejor_categoria, menor_error = "desconocido", float("inf")
        for categoria, muestras in self.ejemplos.items():
            for muestra in muestras:
                error = self._comparar(imagen, muestra)
                if error < menor_error:
                    menor_error, mejor_categoria = error, categoria
        return mejor_categoria, menor_error

    def _capturar_tablero(self):
        with (getattr(mss, "MSS", None) or mss.mss)() as captura:
            pantalla = np.array(captura.grab(captura.monitors[1]))
        pantalla = cv2.cvtColor(pantalla, cv2.COLOR_BGRA2BGR)
        x, y = self.config["x"], self.config["y"]
        ancho, alto = self.config["ancho"], self.config["alto"]
        tablero = pantalla[y:y + alto, x:x + ancho]
        if tablero.size == 0:
            raise ValueError("La region del tablero esta vacia.")
        self.capturas += 1
        return tablero

    @staticmethod
    def _recorte(tablero, f, c):
        alto, ancho = tablero.shape[:2]
        x1 = round(c * ancho / COLUMNAS)
        x2 = round((c + 1) * ancho / COLUMNAS)
        y1 = round(f * alto / FILAS)
        y2 = round((f + 1) * alto / FILAS)
        return tablero[y1:y2, x1:x2]

    # ---------------- API ----------------
    def observar_celdas(self, celdas):
        time.sleep(self.espera)
        tablero = self._capturar_tablero()
        return {(f, c): self._clasificar(self._recorte(tablero, f, c)) for f, c in celdas}

    def reconocer_matriz(self):
        tablero = self._capturar_tablero()
        matriz = [["muro"] * COLUMNAS for _ in range(FILAS)]
        for f in range(FILAS):
            for c in range(COLUMNAS):
                if f in (0, 1, FILAS - 1) or c in (0, COLUMNAS - 1):
                    continue  # casillas que siempre son muro
                matriz[f][c] = self._clasificar(self._recorte(tablero, f, c))[0]
        return matriz

    def guardar_matriz(self, matriz, ruta="matriz_tablero.json"):
        with open(ruta, "w", encoding="utf-8") as archivo:
            json.dump(matriz, archivo, indent=2, ensure_ascii=False)