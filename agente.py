"""
agente.py - Coordinacion general: planifica, ejecuta, aprende y replanifica.

Uso (en la misma carpeta que control.py, config_tablero.json, matriz_tablero.json y ejemplos/):

    python agente.py --solo-planificar      # calcula y muestra el plan, sin tocar el teclado
    python agente.py                        # usa matriz_tablero.json y juega (5 s para enfocar)
    python agente.py --reconocer            # espera F8, captura la pantalla, actualiza el JSON y juega

Flujo:
  1. Planifica con el modelo interno (A*).
  2. Ejecuta cada accion: comprueba que es legal -> la envia al teclado -> actualiza el modelo.
     No hay capturas rutinarias.
  3. Solo si se activa un pulsador de conexion desconocida: captura las rejas, compara y
     registra la conexion. Si se aprende algo, replanifica.
  4. Si la observacion contradice al modelo: reconstruye el estado con un reconocimiento completo.
"""

import argparse
import json
import time
from dataclasses import dataclass

from aprendizaje import Aprendiz, UMBRAL_ERROR
from conexiones import Conexiones
from ejecutor import Ejecutor
from modelo import Reglas, parsear_matriz
from planificador import Planificador
from reglas import ModeloJuego, pulsadores_activos


@dataclass
class ResultadoEjecucion:
    exito: bool
    motivo: str
    pasos: int
    ciclos: int
    capturas: int


class Agente:
    MAX_RECONSTRUCCIONES = 3

    def __init__(self, modelo, observador, ejecutor=None, planificador=None, aprendiz=None,
                 log=print, max_ciclos=60, inferir=True):
        self.inferir = inferir
        self.modelo = modelo
        self.observador = observador
        self.ejecutor = ejecutor or Ejecutor()
        self.log = log
        self.planificador = planificador or Planificador(log=log)
        self.aprendiz = aprendiz or Aprendiz(modelo.conexiones, observador, log=log)
        self.max_ciclos = max_ciclos
        self.pasos = 0
        self.ciclos = 0
        self.reconstrucciones = 0

    # ------------------------------------------------------------------
    def ejecutar(self):
        while not self.modelo.meta_alcanzada():
            self.ciclos += 1
            if self.ciclos > self.max_ciclos:
                return self._fin(False, "Se supero el maximo de ciclos de planificacion.")

            self._inferir()
            plan = self.planificador.planificar(self.modelo)
            if plan is None:
                return self._fin(False, self.planificador.ultimo_motivo)

            etiqueta = "explorar pulsador {}".format(plan.pulsador) if plan.tipo == "exploracion" \
                else "ir a la salida"
            self.log("[agente] plan ({}): {} acciones, coste {}, {} nodos{}".format(
                etiqueta, len(plan.acciones), plan.costo, plan.nodos,
                "" if plan.optimo else " (no optimo)"))

            resultado = self._ejecutar_plan(plan)
            if resultado == "error":
                return self._fin(False, "Inconsistencia irrecuperable entre modelo y juego.")

        return self._verificar_meta()

    # ------------------------------------------------------------------
    def _inferir(self):
        if not self.inferir:
            return
        for pulsador, reja in self.modelo.inferir_conexiones():
            self.log("[agente] deduccion: el unico pulsador sin relacionar {} abre la unica "
                     "reja sin relacionar {} (sin observar).".format(pulsador, reja))

    # ------------------------------------------------------------------
    def _ejecutar_plan(self, plan):
        m = self.modelo
        for accion in plan.acciones:
            if not m.es_legal(accion):
                self.log("[agente] '{}' es ilegal segun el modelo; no se envia. "
                         "Replanifico.".format(accion))
                return "replanificar"

            self.ejecutor.enviar(accion)
            info = m.aplicar(accion)
            self.pasos += 1
            if m.meta_alcanzada():
                return "ok"

            candidatos = [p for p in info.pulsadores_activados if m.conexiones.puede_explorar(p)]
            if candidatos:
                resultado = self._aprender(candidatos, info)
                if resultado != "ok":
                    return resultado
        return "ok"

    def _aprender(self, candidatos, info):
        m = self.modelo
        activos_desconocidos = [p for p in pulsadores_activos(m.tablero, m.estado)
                                if not m.conexiones.conoce(p)]
        if len(candidatos) != 1 or len(activos_desconocidos) != 1:
            self.log("[agente] varios pulsadores desconocidos activos a la vez: observacion "
                     "ambigua, no se atribuye ninguna conexion.")
            for p in candidatos:
                m.conexiones.registrar_intento(p)
            return "ok"

        res = self.aprendiz.observar(m, candidatos[0], rejas_esperadas=info.rejas_despues)
        if res.inconsistente:
            return self._reconstruir()
        if res.concluyente and res.rejas_nuevas:
            self.log("[agente] informacion nueva: replanifico.")
            return "replanificar"
        return "ok"

    def _reconstruir(self):
        if self.reconstrucciones >= self.MAX_RECONSTRUCCIONES:
            return "error"
        self.reconstrucciones += 1
        self.log("[agente] reconstruyendo el estado con un reconocimiento completo...")
        matriz = self.observador.reconocer_matriz()
        anterior = self.modelo
        self.modelo = ModeloJuego.desde_matriz(
            matriz, reglas=anterior.tablero.reglas, conexiones=anterior.conexiones,
            previo=anterior.tablero,
            diamantes_recogidos=anterior.estado.diamantes_recogidos,
            llaves_en_mano=anterior.estado.llaves_en_mano,
            pinchos_usados=anterior.estado.pinchos_usados)
        return "reconstruido"

    def _verificar_meta(self):
        m = self.modelo
        if m.meta_alcanzada() and m.tablero.salida is not None:
            return self._fin(True, "Salida alcanzada ({} diamantes restantes).".format(
                len(m.estado.diamantes)))
        return self._fin(False, "El modelo no confirma que se haya alcanzado la salida.")

    def _fin(self, exito, motivo):
        self.log("[agente] {}: {}".format("EXITO" if exito else "FIN SIN EXITO", motivo))
        return ResultadoEjecucion(exito, motivo, self.pasos, self.ciclos, self.aprendiz.capturas)


# ----------------------------------------------------------------------------------------
def principal(argv=None):
    ap = argparse.ArgumentParser(description="Agente de Diamond Rush")
    ap.add_argument("--matriz", default="matriz_tablero.json")
    ap.add_argument("--reconocer", action="store_true",
                    help="captura la pantalla y actualiza la matriz antes de jugar")
    ap.add_argument("--solo-planificar", action="store_true")
    ap.add_argument("--espera", type=float, default=5.0, help="segundos para enfocar el juego")
    ap.add_argument("--espera-animacion", type=float, default=0.6)
    ap.add_argument("--conexiones", default="conexiones_aprendidas.json")
    ap.add_argument("--umbral-error", type=float, default=UMBRAL_ERROR)
    ap.add_argument("--pinchos-bloquean", action="store_true",
                    help="tratar pinchos_escondidos como obstaculo")
    ap.add_argument("--puerta-paso-extra", action="store_true")
    ap.add_argument("--diamantes-salida", type=int, default=None)
    ap.add_argument("--max-llaves", type=int, default=1,
                    help="llaves que se pueden llevar a la vez (por defecto 1)")
    ap.add_argument("--llave-extra-pasa", action="store_true",
                    help="con el maximo de llaves, se puede pisar otra llave sin recogerla")
    ap.add_argument("--piedra-no-sobre-objetos", action="store_true",
                    help="una piedra NO puede empujarse sobre un diamante")
    ap.add_argument("--pinchos-reutilizables", action="store_true",
                    help="los pinchos escondidos NO se convierten en muro tras cruzarlos")
    ap.add_argument("--max-nodos", type=int, default=3000000,
                    help="limite de nodos de A* (por defecto 3.000.000; cada millon usa ~1,2 GB de RAM)")
    ap.add_argument("--max-nodos-fallback", type=int, default=4000000,
                    help="limite del A* ponderado de respaldo (por defecto 4.000.000)")
    ap.add_argument("--penalizacion-empuje", type=int, default=40,
                    help="coste extra por empujar una piedra al EXPLORAR un pulsador (0 = sin penalizar)")
    ap.add_argument("--no-inferir", action="store_true",
                    help="no deducir conexiones por eliminacion (observar siempre)")
    ap.add_argument("--tecla", default="F8", choices=["F8", "F9", "F2"],
                    help="tecla que inicia el agente (por defecto F8)")
    ap.add_argument("--sin-tecla", action="store_true",
                    help="no esperar la tecla: empezar enseguida (comportamiento antiguo)")
    args = ap.parse_args(argv)

    reglas = Reglas(pinchos_transitables=not args.pinchos_bloquean,
                    puerta_abre_sin_avanzar=args.puerta_paso_extra,
                    diamantes_para_salida=args.diamantes_salida,
                    max_llaves=args.max_llaves,
                    llave_extra_bloquea=not args.llave_extra_pasa,
                    piedra_sobre_objetos=not args.piedra_no_sobre_objetos,
                    pinchos_se_cierran=not args.pinchos_reutilizables)

    observador = None
    if args.reconocer or not args.solo_planificar:
        if not args.sin_tecla:
            from tecla_inicio import esperar_tecla
            esperar_tecla(args.tecla)
        from vision import ObservadorPantalla
        observador = ObservadorPantalla(espera=args.espera_animacion)

    if args.reconocer:
        matriz = observador.reconocer_matriz()
        observador.guardar_matriz(matriz, args.matriz)
        print("Matriz reconocida y guardada en", args.matriz)
    else:
        with open(args.matriz, "r", encoding="utf-8") as archivo:
            matriz = json.load(archivo)

    tablero, _, _ = parsear_matriz(matriz, reglas)
    conexiones = Conexiones.cargar(args.conexiones, tablero.firma)
    modelo = ModeloJuego.desde_matriz(matriz, reglas=reglas, conexiones=conexiones)

    for pos, cat in modelo.desconocidas:
        print("AVISO: categoria desconocida '{}' en {}; se trata como muro.".format(cat, pos))
    if not args.no_inferir:
        for pulsador, reja in modelo.inferir_conexiones():
            print("Deduccion: el pulsador {} abre la reja {} (unicos sin relacionar).".format(
                pulsador, reja))
    print(modelo.dibujar())
    conocidas, desconocidas = conexiones.resumen(tablero.pulsadores)
    print("Conexiones conocidas:", conocidas, "| desconocidas:", desconocidas)

    planificador = Planificador(max_nodos=args.max_nodos,
                                max_nodos_fallback=args.max_nodos_fallback,
                                penalizacion_empuje=args.penalizacion_empuje)
    if args.solo_planificar:
        plan = planificador.planificar(modelo)
        if plan is None:
            print("Sin plan:", planificador.ultimo_motivo or "no hay ruta con la informacion actual")
        else:
            print("Plan ({}, coste {}):".format(plan.tipo, plan.costo))
            print(" ".join(plan.acciones))
        return

    if args.sin_tecla:
        print("Enfoca la ventana del juego. Empiezo en 2 segundos.")
        time.sleep(2)
    agente = Agente(modelo, observador, Ejecutor(), planificador=planificador,
                    aprendiz=Aprendiz(conexiones, observador, umbral_error=args.umbral_error),
                    inferir=not args.no_inferir)
    resultado = agente.ejecutar()
    print(resultado)


if __name__ == "__main__":
    principal()