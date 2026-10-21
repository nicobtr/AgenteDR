"""
tecla_inicio.py - Espera a que el operador pulse la tecla de inicio (F8 por defecto).

Por que F8: ni Diamond Rush ni Chrome la usan (F5 recarga, F6 va a la barra de
direcciones, F7 activa la navegacion con cursor, F10 abre el menu, F11 pantalla
completa, F12 herramientas de desarrollo). Windows tampoco le da ninguna funcion.
En portatiles puede hacer falta pulsar Fn + F8.

En Windows la tecla se detecta aunque la ventana activa sea Chrome (no la terminal),
usando GetAsyncKeyState de user32 mediante ctypes: no hace falta ninguna libreria extra.
En macOS / Linux no hay equivalente sin librerias adicionales, asi que se pide Enter
en la terminal y se dan unos segundos para pasar al navegador.
"""

import sys
import time

TECLAS = {"F8": 0x77, "F9": 0x78, "F2": 0x71}   # codigos virtuales de Windows


def esperar_tecla(nombre="F8", segundos_fallback=3.0):
    if sys.platform.startswith("win"):
        import ctypes
        leer = ctypes.windll.user32.GetAsyncKeyState
        codigo = TECLAS[nombre]
        print(">>> Pasa al juego, haz clic en el y pulsa {} para empezar. "
              "(Ctrl+C en esta terminal para salir)".format(nombre))
        leer(codigo)                         # descarta pulsaciones anteriores
        while not (leer(codigo) & 0x8000):   # esperar a que se pulse
            time.sleep(0.02)
        while leer(codigo) & 0x8000:         # y a que se suelte
            time.sleep(0.02)
        print(">>> {} detectada, empiezo.".format(nombre))
    else:
        input(">>> Pulsa Enter y pasa al juego en {:.0f} s...".format(segundos_fallback))
        time.sleep(segundos_fallback)
