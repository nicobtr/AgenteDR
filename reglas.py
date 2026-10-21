"""
reglas.py - Reglas del juego, simulacion de movimientos y ModeloJuego.

Funciones puras (usadas por el planificador):
    simular(tablero, estado, direccion, conexiones) -> Estado | None
    acciones_legales(tablero, estado, conexiones)   -> [(accion, nuevo_estado, coste)]

ModeloJuego agrupa tablero + estado actual + conexiones y se actualiza tras cada movimiento
sin necesidad de volver a capturar la pantalla.
"""

from dataclasses import dataclass
from typing import Optional

from conexiones import Conexiones
from modelo import (Estado, Tablero, parsear_matriz, MURO, SUELO, HUECO, LAVA, PINCHOS,
                    PUERTA, REJA, PULSADOR, SALIDA)

DIRECCIONES = {
    "arriba": (-1, 0),
    "abajo": (1, 0),
    "izquierda": (0, -1),
    "derecha": (0, 1),
}


class MovimientoIlegal(Exception):
    pass


# ----------------------------------------------------------------------------------------
# Consultas derivadas (pulsadores, rejas, salida)
# ----------------------------------------------------------------------------------------
def pulsadores_activos(tablero, estado):
    """Un pulsador esta activo mientras el jugador o una piedra lo oprime."""
    ocupadas = set(estado.piedras)
    ocupadas.add(estado.jugador)
    return frozenset(p for p in tablero.pulsadores if p in ocupadas)


def rejas_abiertas(tablero, estado, conexiones):
    """Rejas abiertas segun el conocimiento actual (las de conexion desconocida no se abren)."""
    if not tablero.rejas:
        return frozenset()
    abiertas = set(tablero.rejas_base_abiertas)
    activos = pulsadores_activos(tablero, estado)
    if tablero.reglas.rejas_permanentes:
        activos = activos | estado.pulsadores_pisados
    for p in activos:
        abiertas.update(conexiones.rejas_de(p))
    return frozenset(abiertas)


def salida_abierta(tablero, estado):
    n = tablero.reglas.diamantes_para_salida
    if n is None:
        return len(estado.diamantes) == 0
    return estado.diamantes_recogidos >= n


def meta_alcanzada(tablero, estado):
    return tablero.salida is not None and estado.jugador == tablero.salida


# ----------------------------------------------------------------------------------------
# Simulacion de un movimiento
# ----------------------------------------------------------------------------------------
def simular(tablero, estado, direccion, conexiones):
    """Devuelve el nuevo Estado o None si el movimiento es ilegal. No modifica nada."""
    df, dc = DIRECCIONES[direccion]
    f, c = estado.jugador
    destino = (f + df, c + dc)
    if not tablero.dentro(destino):
        return None

    terreno = tablero.terreno
    reglas = tablero.reglas
    piedras = estado.piedras
    diamantes = estado.diamantes
    llaves_t = estado.llaves_tablero
    llaves_m = estado.llaves_en_mano
    puertas = estado.puertas_abiertas
    huecos = estado.huecos_llenos
    recogidos = estado.diamantes_recogidos
    usados = estado.pinchos_usados
    if reglas.pinchos_se_cierran and terreno[f][c] == PINCHOS:
        usados = usados | {estado.jugador}   # al salir de un pincho escondido, queda activado

    if destino in piedras:
        # --- empuje de piedra ---
        mas_alla = (destino[0] + df, destino[1] + dc)
        if not tablero.dentro(mas_alla) or mas_alla in piedras:
            return None  # fuera del tablero o dos piedras seguidas
        if mas_alla in diamantes and not reglas.piedra_sobre_objetos:
            return None
        if mas_alla in llaves_t and not reglas.piedra_sobre_llaves:
            return None
        t = terreno[mas_alla[0]][mas_alla[1]]
        if t == HUECO and mas_alla not in huecos:
            piedras = piedras - {destino}
            huecos = huecos | {mas_alla}          # el hueco pasa a ser suelo
        elif t == LAVA:
            piedras = piedras - {destino}          # la piedra se pierde para siempre
        elif (t in (SUELO, PULSADOR) or t == HUECO
              or (t == PUERTA and mas_alla in puertas)):
            piedras = (piedras - {destino}) | {mas_alla}
        elif t == PINCHOS and mas_alla in getattr(tablero, "pinchos_bajo_piedra", ()) \
                and mas_alla not in usados:
            piedras = (piedras - {destino}) | {mas_alla}   # vuelve a una casilla inicial de piedra
        elif t == PINCHOS and reglas.piedra_sobre_pinchos and mas_alla not in usados:
            piedras = (piedras - {destino}) | {mas_alla}   # pincho escondido aun no activado
        else:
            return None                            # muro, reja, pinchos, salida, puerta...
    else:
        t = terreno[destino[0]][destino[1]]
        if t == MURO or t == LAVA:
            return None
        if t == HUECO and destino not in huecos:
            return None
        if t == PINCHOS and (not reglas.pinchos_transitables or destino in usados):
            # la casilla inicial de una piedra solo es un pincho "posible": se permite volver
            # a pisarla (con penalizacion en el coste, ver coste_movimiento)
            if not (destino in getattr(tablero, "pinchos_bajo_piedra", ())
                    and reglas.penalizacion_bajo_piedra is not None):
                return None
        if t == PUERTA and destino not in puertas:
            if llaves_m <= 0:
                return None
            llaves_m -= 1
            puertas = puertas | {destino}
            if reglas.puerta_abre_sin_avanzar:
                return Estado(estado.jugador, piedras, diamantes, llaves_t, llaves_m,
                              puertas, huecos, recogidos, estado.pinchos_usados,
                              estado.pulsadores_pisados)
        if t == SALIDA and not salida_abierta(tablero, estado):
            return None

    if destino in diamantes:
        diamantes = diamantes - {destino}
        recogidos += 1
    if destino in llaves_t:
        if llaves_m >= reglas.max_llaves:
            if reglas.llave_extra_bloquea:
                return None  # ya lleva el maximo de llaves: no se puede pisar otra
            # (si no bloquea, se pasa por encima y la llave se queda en el tablero)
        else:
            llaves_t = llaves_t - {destino}
            llaves_m += 1

    pisados = estado.pulsadores_pisados
    if reglas.rejas_permanentes and tablero.pulsadores:
        oprimidos = (piedras | {destino}) & tablero.pulsadores_set
        if not oprimidos <= pisados:
            pisados = pisados | oprimidos
    nuevo = Estado(destino, piedras, diamantes, llaves_t, llaves_m, puertas, huecos, recogidos,
                   usados, pisados)

    # Una reja que se cierra bajo los pies del jugador es un movimiento ilegal.
    if terreno[destino[0]][destino[1]] == REJA \
            and destino not in rejas_abiertas(tablero, nuevo, conexiones):
        return None
    return nuevo


def coste_movimiento(tablero, estado, nuevo):
    """Coste de un paso: 1, mas extras por pisar pinchos o volver a la casilla inicial de una
    piedra (pincho posible ya pisado)."""
    coste = 1
    destino = nuevo.jugador
    if tablero.terreno[destino[0]][destino[1]] == PINCHOS:
        coste += tablero.reglas.coste_extra_pinchos
        if destino in estado.pinchos_usados:   # solo posible en casillas iniciales de piedra
            coste += tablero.reglas.penalizacion_bajo_piedra or 0
    return coste


def acciones_legales(tablero, estado, conexiones):
    """[(accion, nuevo_estado, coste)]. Desde la salida no hay mas acciones."""
    resultado = []
    if meta_alcanzada(tablero, estado):
        return resultado
    for direccion in DIRECCIONES:
        nuevo = simular(tablero, estado, direccion, conexiones)
        if nuevo is None:
            continue
        coste = coste_movimiento(tablero, estado, nuevo)
        if nuevo.piedras != estado.piedras:   # empuja una piedra (a suelo, pulsador, hueco o lava)
            coste += tablero.reglas.coste_extra_empuje
        resultado.append((direccion, nuevo, coste))
    return resultado


# ----------------------------------------------------------------------------------------
# ModeloJuego
# ----------------------------------------------------------------------------------------
@dataclass
class InfoPaso:
    accion: str
    antes: Estado
    despues: Estado
    rejas_antes: frozenset
    rejas_despues: frozenset
    pulsadores_activados: frozenset
    pulsadores_liberados: frozenset
    piedra_empujada: bool = False
    destino_piedra: Optional[str] = None   # "suelo" | "pulsador" | "hueco" | "lava"
    recogio_diamante: bool = False
    recogio_llave: bool = False
    abrio_puerta: bool = False


class ModeloJuego:
    def __init__(self, tablero, estado, conexiones=None):
        self.tablero = tablero
        self.estado = estado
        self.conexiones = conexiones if conexiones is not None else Conexiones()
        self.desconocidas = []

    @classmethod
    def desde_matriz(cls, matriz, reglas=None, conexiones=None, previo=None,
                     diamantes_recogidos=0, llaves_en_mano=0, pinchos_usados=frozenset()):
        conexiones = conexiones if conexiones is not None else Conexiones()
        tablero, estado, desconocidas = parsear_matriz(
            matriz, reglas=reglas, conexiones=conexiones, previo=previo,
            diamantes_recogidos=diamantes_recogidos, llaves_en_mano=llaves_en_mano,
            pinchos_usados=pinchos_usados)
        modelo = cls(tablero, estado, conexiones)
        modelo.desconocidas = desconocidas
        return modelo

    # ---- consultas ----
    def pulsadores_activos(self):
        return pulsadores_activos(self.tablero, self.estado)

    def rejas_abiertas(self):
        return rejas_abiertas(self.tablero, self.estado, self.conexiones)

    def salida_abierta(self):
        return salida_abierta(self.tablero, self.estado)

    def meta_alcanzada(self):
        return meta_alcanzada(self.tablero, self.estado)

    def acciones_legales(self):
        return [a for a, _, _ in acciones_legales(self.tablero, self.estado, self.conexiones)]

    def es_legal(self, direccion):
        return (direccion in DIRECCIONES
                and simular(self.tablero, self.estado, direccion, self.conexiones) is not None)

    # ---- deduccion por eliminacion ----
    def rejas_sin_relacionar(self):
        """Rejas que no estan abiertas de base ni son controladas por un pulsador conocido."""
        t, c = self.tablero, self.conexiones
        controladas = c.rejas_controladas()
        return [r for r in t.rejas if r not in t.rejas_base_abiertas and r not in controladas]

    def inferir_conexiones(self):
        """
        Si queda exactamente UN pulsador sin conexion conocida y exactamente UNA reja sin
        relacionar, se enlazan sin necesidad de observarlos. Devuelve [(pulsador, reja)].
        Supuesto: cada reja con conexion depende de algun pulsador, y las rejas que se ven abiertas
        al iniciar se consideran abiertas de forma fija (regla 5 de modelo.py).
        """
        t, c = self.tablero, self.conexiones
        desconocidos = [p for p in t.pulsadores if not c.conoce(p)]
        libres = self.rejas_sin_relacionar()
        if len(desconocidos) == 1 and len(libres) == 1:
            c.registrar(desconocidos[0], {libres[0]})
            return [(desconocidos[0], libres[0])]
        return []

    # ---- actualizacion ----
    def aplicar(self, direccion):
        """Aplica el movimiento al modelo interno (sin capturar pantalla)."""
        if direccion not in DIRECCIONES:
            raise MovimientoIlegal("Direccion desconocida: {}".format(direccion))
        antes = self.estado
        nuevo = simular(self.tablero, antes, direccion, self.conexiones)
        if nuevo is None:
            raise MovimientoIlegal("Movimiento ilegal '{}' desde {}".format(direccion, antes.jugador))

        rejas_antes = rejas_abiertas(self.tablero, antes, self.conexiones)
        rejas_despues = rejas_abiertas(self.tablero, nuevo, self.conexiones)
        act_antes = pulsadores_activos(self.tablero, antes)
        act_despues = pulsadores_activos(self.tablero, nuevo)

        info = InfoPaso(
            accion=direccion, antes=antes, despues=nuevo,
            rejas_antes=rejas_antes, rejas_despues=rejas_despues,
            pulsadores_activados=act_despues - act_antes,
            pulsadores_liberados=act_antes - act_despues,
        )
        info.piedra_empujada = nuevo.jugador in antes.piedras
        if info.piedra_empujada:
            if len(nuevo.piedras) < len(antes.piedras):
                info.destino_piedra = ("hueco" if len(nuevo.huecos_llenos) > len(antes.huecos_llenos)
                                       else "lava")
            else:
                movida = next(iter(nuevo.piedras - antes.piedras))
                info.destino_piedra = "pulsador" if movida in self.tablero.pulsadores_set else "suelo"
        info.recogio_diamante = len(nuevo.diamantes) < len(antes.diamantes)
        info.recogio_llave = nuevo.llaves_en_mano > antes.llaves_en_mano
        info.abrio_puerta = len(nuevo.puertas_abiertas) > len(antes.puertas_abiertas)

        self.estado = nuevo
        return info

    # ---- depuracion ----
    def dibujar(self):
        t, e = self.tablero, self.estado
        abiertas = self.rejas_abiertas()
        activos = self.pulsadores_activos()
        sal = self.salida_abierta()
        fijos = {MURO: "#", SUELO: ".", LAVA: "L", PINCHOS: "^"}
        lineas = []
        for f in range(t.filas):
            fila = []
            for c in range(t.columnas):
                p = (f, c)
                tp = t.terreno[f][c]
                if p == e.jugador:
                    ch = "@"
                elif p in e.piedras:
                    ch = "O"
                elif p in e.diamantes:
                    ch = "D"
                elif p in e.llaves_tablero:
                    ch = "K"
                elif tp == PINCHOS and p in e.pinchos_usados:
                    ch = "#"
                elif tp == HUECO:
                    ch = "." if p in e.huecos_llenos else "H"
                elif tp == PUERTA:
                    ch = "." if p in e.puertas_abiertas else "U"
                elif tp == REJA:
                    ch = "r" if p in abiertas else "R"
                elif tp == PULSADOR:
                    ch = "*" if p in activos else "B"
                elif tp == SALIDA:
                    ch = "s" if sal else "S"
                else:
                    ch = fijos.get(tp, "?")
                fila.append(ch)
            lineas.append("".join(fila))
        return "\n".join(lineas)