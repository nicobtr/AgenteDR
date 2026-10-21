"""
autocalibrar.py - Detecta el tablero AUTOMATICAMENTE y escribe config_tablero.json.

Reemplaza a seleccionar_casilla.py / percepcion.py (seleccion manual con el raton).
No hay que senalar nada: busca en la pantalla los dos botones redondos del juego
(engranaje arriba a la izquierda y reinicio arriba a la derecha) con template matching
multiescala. La distancia entre ambos da el tamano de casilla (sirve para cualquier
resolucion o zoom del navegador) y su posicion da la esquina del tablero.

Uso:
    python autocalibrar.py                  # captura la pantalla, guarda config_tablero.json
    python autocalibrar.py --mostrar        # ademas dibuja la cuadricula para comprobarla
    python autocalibrar.py --imagen cap.png # prueba sobre una captura guardada

vision.py lo llama solo al arrancar, asi que normalmente no hace falta ejecutarlo a mano.
"""

import argparse
import json
import os

import cv2
import numpy as np

CARPETA = os.path.dirname(os.path.abspath(__file__))
RUTA_PLANTILLAS = os.path.join(CARPETA, "plantillas_calibracion")
RUTA_CONFIG = os.path.join(CARPETA, "config_tablero.json")

FILAS = 15
COLUMNAS = 10

# Geometria medida en una captura real, en unidades de casilla:
DIST_BOTONES = 7.447       # distancia horizontal engranaje -> reinicio
ENGRANAJE_DX = 1.171       # centro del engranaje respecto al borde izquierdo del tablero
ENGRANAJE_DY = 1.405       # centro del engranaje respecto al borde superior del tablero
CASILLA_PLANTILLA = 42.7   # tamano de casilla en la captura de la que salen las plantillas
UMBRAL = 0.6

# Plantillas incrustadas (no dependen de archivos externos).
PLANTILLAS_B64 = {
    "engranaje.png": "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",
    "reinicio.png": "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",
}


def capturar_pantalla():
    import mss
    crear = getattr(mss, "MSS", None) or mss.mss
    with crear() as captura:
        pantalla = np.array(captura.grab(captura.monitors[1]))
    return cv2.cvtColor(pantalla, cv2.COLOR_BGRA2BGR)


def _cargar(nombre):
    import base64
    datos = np.frombuffer(base64.b64decode(PLANTILLAS_B64[nombre]), np.uint8)
    img = cv2.imdecode(datos, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError("Falta la plantilla " + nombre)
    return img


def _buscar(gris, plantilla, escalas):
    """Devuelve (puntuacion, escala, centro_x, centro_y) del mejor encaje."""
    mejor = (-1.0, None, 0, 0)
    for s in escalas:
        t = cv2.resize(plantilla, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if t.shape[0] < 10 or t.shape[0] >= gris.shape[0] or t.shape[1] >= gris.shape[1]:
            continue
        r = cv2.matchTemplate(gris, t, cv2.TM_CCOEFF_NORMED)
        _, v, _, p = cv2.minMaxLoc(r)
        if v > mejor[0]:
            mejor = (v, s, p[0] + t.shape[1] / 2, p[1] + t.shape[0] / 2)
    return mejor


def detectar_tablero(pantalla):
    """Recibe una captura BGR y devuelve {"x","y","ancho","alto"} o lanza ValueError."""
    gris = cv2.cvtColor(pantalla, cv2.COLOR_BGR2GRAY)
    engranaje, reinicio = _cargar("engranaje.png"), _cargar("reinicio.png")

    # 1) Busqueda gruesa a media resolucion (rapida), escalas 0.35x - 3x.
    f = 0.5
    peq = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    gruesas = np.geomspace(0.35, 3.0, 45) * f
    v, s, _, _ = _buscar(peq, engranaje, gruesas)
    if s is None:
        raise ValueError("No se encontro el juego en la pantalla.")
    s /= f

    # 2) Refinado a resolucion completa alrededor de la mejor escala.
    finas = np.linspace(s * 0.93, s * 1.07, 15)
    v1, s1, gx, gy = _buscar(gris, engranaje, finas)
    v2, s2, rx, ry = _buscar(gris, reinicio, finas)

    if v1 < UMBRAL or v2 < UMBRAL:
        raise ValueError(
            "No encuentro los botones del juego (engranaje {:.2f}, reinicio {:.2f}). "
            "Comprueba que el nivel esta visible en el monitor principal.".format(v1, v2))
    if abs(gy - ry) > 0.25 * CASILLA_PLANTILLA * s1 or rx <= gx:
        raise ValueError("Los botones encontrados no estan alineados; captura dudosa.")

    casilla = (rx - gx) / DIST_BOTONES
    x = gx - ENGRANAJE_DX * casilla
    y = (gy + ry) / 2 - ENGRANAJE_DY * casilla
    config = {
        "x": int(round(x)),
        "y": int(round(y)),
        "ancho": int(round(COLUMNAS * casilla)),
        "alto": int(round(FILAS * casilla)),
    }
    alto_pantalla = pantalla.shape[0]
    if config["y"] + config["alto"] > alto_pantalla + 2:
        print("AVISO: el tablero se sale por abajo de la pantalla; "
              "haz scroll o reduce el zoom del navegador.")
    return config


def dibujar(pantalla, config):
    x, y, w, h = config["x"], config["y"], config["ancho"], config["alto"]
    vista = pantalla[max(y, 0):y + h, max(x, 0):x + w].copy()
    for c in range(COLUMNAS + 1):
        px = round(c * w / COLUMNAS)
        cv2.line(vista, (px, 0), (px, h), (0, 255, 0), 1)
    for fi in range(FILAS + 1):
        py = round(fi * h / FILAS)
        cv2.line(vista, (0, py), (w, py), (0, 255, 0), 1)
    return vista


def calibrar(pantalla=None, guardar=True):
    if pantalla is None:
        pantalla = capturar_pantalla()
    config = detectar_tablero(pantalla)
    if guardar:
        with open(RUTA_CONFIG, "w") as archivo:
            json.dump(config, archivo, indent=4)
    return config


def principal():
    ap = argparse.ArgumentParser(description="Detecta el tablero de Diamond Rush")
    ap.add_argument("--imagen", help="usar una captura guardada en vez de la pantalla")
    ap.add_argument("--mostrar", action="store_true", help="mostrar la cuadricula detectada")
    ap.add_argument("--guardar-vista", help="guardar la cuadricula dibujada en este PNG")
    args = ap.parse_args()

    if args.imagen:
        pantalla = cv2.imread(args.imagen)
        if pantalla is None:
            raise SystemExit("No se pudo leer " + args.imagen)
    else:
        print("Capturando en 3 segundos: deja visible el juego...")
        import time
        time.sleep(3)
        pantalla = capturar_pantalla()

    config = calibrar(pantalla)
    print("Tablero detectado:", config, "-> guardado en config_tablero.json")

    if args.guardar_vista or args.mostrar:
        vista = dibujar(pantalla, config)
        if args.guardar_vista:
            cv2.imwrite(args.guardar_vista, vista)
        if args.mostrar:
            cv2.imshow("Tablero detectado (cualquier tecla para cerrar)", vista)
            cv2.waitKey(0)
            cv2.destroyAllWindows()


if __name__ == "__main__":
    principal()