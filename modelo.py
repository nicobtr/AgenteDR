"""
modelo.py - Modelo interno de Diamond Rush.

Separa:
  * Tablero  -> parte ESTATICA (muros, lava, huecos, puertas, rejas, pulsadores, salida).
  * Estado   -> parte DINAMICA e inmutable/hashable (jugador, piedras, diamantes, llaves,
                puertas abiertas, huecos rellenados...). Sirve como nodo de la busqueda.

REGLAS QUE NO SE PUEDEN DEDUCIR DEL CODIGO NI DEL ENUNCIADO (estan en `Reglas`, cambialas
si el juego se comporta distinto):
  1. pinchos_transitables (True): en tu matriz, la zona inferior del nivel solo es alcanzable
     cruzando casillas "pinchos_escondidos"; por eso se asume que son transitables.
     coste_extra_pinchos=2 solo hace que el planificador prefiera rutas sin pinchos.
  2. diamantes_para_salida (None = todos): se asume que la salida se abre al recoger todos
     los diamantes. Pon un entero N si el juego exige solo N.
  3. puerta_abre_sin_avanzar (False): se asume que al caminar hacia una puerta con llave
     se abre Y el jugador avanza en el mismo paso. Si en el juego hacen falta dos pulsaciones,
     ponlo en True.
  4. Una piedra solo puede empujarse a: suelo, pulsador, hueco, lava o puerta ya abierta, y
     NUNCA sobre reja, salida, puerta cerrada ni llave (piedra_sobre_llaves=False; en el
     nivel 6 el juego no lo permite). Sobre un diamante SI (piedra_sobre_objetos=True; el
     nivel 4 solo se resuelve asi): el diamante sigue debajo. Sobre un pincho escondido aun no
     activado solo se permite si no hay otra ruta (planificador, regla piedra_sobre_pinchos).
  11. Bajo cada piedra inicial puede haber un pincho escondido invisible en la captura: esa
     casilla se trata como pincho escondido (piedra_inicial_sobre_pinchos=True), pero de forma
     SUAVE: volver a pisarla no esta prohibido, cuesta penalizacion_bajo_piedra (30) pasos
     extra. Asi el planificador la evita si hay alternativa (nivel 10) y la usa si no la hay
     (niveles 7, 14 y 17 obligan a cruzarla varias veces).
  5. Una reja vista "abierta" al iniciar (reja_abierta) se considera abierta de forma fija,
     salvo que se conozca un pulsador que la controle.
  6. Una piedra que cae en lava desaparece y la lava sigue siendo lava.
  7. Si el jugador abandona un pulsador y la reja que se cierra es la casilla a la que entra,
     el movimiento se considera ilegal (quedaria atrapado dentro de la reja).
  9. Solo se puede llevar UNA llave a la vez (max_llaves=1). Con una llave en la mano, la casilla
     de otra llave se trata como obstaculo (llave_extra_bloquea=True); si en el juego se puede
     pisar sin recogerla, usa --llave-extra-pasa.
  10. Un pincho escondido se puede cruzar UNA vez: al salir de su casilla queda activado y pasa a
     comportarse como un muro (pinchos_se_cierran=True; --pinchos-reutilizables lo desactiva).
  8. Un pulsador oculto bajo el jugador o una piedra en la captura inicial no es visible.
  12. Por defecto una reja solo esta abierta MIENTRAS su pulsador esta oprimido (jugador o
     piedra encima). Si asi no hay ruta, el planificador prueba rejas_permanentes=True (la reja
     queda abierta tras pisar el pulsador una vez): el nivel 17 solo se resuelve asi.
"""

from dataclasses import dataclass
import hashlib
from typing import FrozenSet, List, Optional, Tuple

Pos = Tuple[int, int]

# Tipos de terreno (parte estatica)
MURO = "muro"
SUELO = "suelo"
HUECO = "hueco"
LAVA = "lava"
PINCHOS = "pinchos"
PUERTA = "puerta"
REJA = "reja"
PULSADOR = "pulsador"
SALIDA = "salida"

# Categorias de reconocer_tablero.py -> (terreno, objeto dinamico)
CATEGORIAS = {
    "muro": (MURO, None),
    "suelo": (SUELO, None),
    "diamante": (SUELO, "diamante"),
    "llave": (SUELO, "llave"),
    "piedra": (SUELO, "piedra"),
    "jugador": (SUELO, "jugador"),
    "puertall": (PUERTA, None),
    "hueco_piedra": (HUECO, None),
    "lava": (LAVA, None),
    "pinchos_escondidos": (PINCHOS, None),
    "pinchos_activados": (PINCHOS, None),   # ya pisados: se comportan como muro
    "pulsador_reja": (PULSADOR, None),
    "reja": (REJA, None),
    "reja_abierta": (REJA, None),
    "llegada_cerrada": (SALIDA, None),
    "llegada_abierta": (SALIDA, None),
}

CATEGORIAS_REJA = ("reja", "reja_abierta")


@dataclass(frozen=True)
class Reglas:
    pinchos_transitables: bool = True
    coste_extra_pinchos: int = 2
    diamantes_para_salida: Optional[int] = None
    puerta_abre_sin_avanzar: bool = False
    max_llaves: int = 1                # llaves que se pueden llevar a la vez
    llave_extra_bloquea: bool = True   # con el maximo de llaves, no se pisa otra llave
    piedra_sobre_objetos: bool = True   # una piedra puede quedar encima de un DIAMANTE (nivel 4)
    piedra_sobre_llaves: bool = False   # pero NO encima de una llave (nivel 6)
    piedra_inicial_sobre_pinchos: bool = True  # bajo cada piedra inicial puede haber un pincho escondido
    penalizacion_bajo_piedra: int = 30  # coste extra por volver a pisar la casilla inicial de una piedra
    rejas_permanentes: bool = False    # True: una reja queda abierta tras pisar su pulsador una vez
    pinchos_se_cierran: bool = True    # un pincho escondido atravesado pasa a ser muro
    piedra_sobre_pinchos: bool = False  # una piedra puede pasar por un pincho escondido no activado
    coste_extra_empuje: int = 0        # penalizacion por empujar una piedra (se usa al explorar)


@dataclass(frozen=True)
class Estado:
    """Estado dinamico completo. Hashable: se usa para evitar estados duplicados."""
    jugador: Pos
    piedras: FrozenSet[Pos]
    diamantes: FrozenSet[Pos]
    llaves_tablero: FrozenSet[Pos]
    llaves_en_mano: int = 0
    puertas_abiertas: FrozenSet[Pos] = frozenset()
    huecos_llenos: FrozenSet[Pos] = frozenset()
    diamantes_recogidos: int = 0
    pinchos_usados: FrozenSet[Pos] = frozenset()  # pinchos ya atravesados (ahora son muro)
    pulsadores_pisados: FrozenSet[Pos] = frozenset()  # solo con rejas_permanentes


class Tablero:
    """Parte estatica del nivel."""

    def __init__(self, terreno, rejas_base_abiertas=(), reglas=None):
        self.terreno = tuple(tuple(fila) for fila in terreno)
        self.filas = len(self.terreno)
        self.columnas = len(self.terreno[0]) if self.filas else 0
        self.reglas = reglas or Reglas()
        self.rejas_base_abiertas = frozenset(rejas_base_abiertas)

        celdas = [
            ((f, c), self.terreno[f][c])
            for f in range(self.filas)
            for c in range(self.columnas)
        ]
        self.pulsadores = tuple(p for p, t in celdas if t == PULSADOR)
        self.pulsadores_set = frozenset(self.pulsadores)
        self.rejas = tuple(p for p, t in celdas if t == REJA)
        salidas = [p for p, t in celdas if t == SALIDA]
        self.salida = salidas[0] if salidas else None

        simbolos = {MURO: "#", REJA: "R", PULSADOR: "B"}
        texto = "|".join(
            "".join(simbolos.get(t, ".") for t in fila) for fila in self.terreno
        )
        self.firma = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12]

    def dentro(self, pos):
        return 0 <= pos[0] < self.filas and 0 <= pos[1] < self.columnas

    def tipo(self, pos):
        if not self.dentro(pos):
            return MURO
        return self.terreno[pos[0]][pos[1]]


def parsear_matriz(matriz, reglas=None, conexiones=None, previo=None,
                   diamantes_recogidos=0, llaves_en_mano=0, pinchos_usados=frozenset()):
    """
    Convierte la matriz de categorias (matriz_tablero.json) en (Tablero, Estado, desconocidas).

    previo: Tablero anterior; permite conservar pulsadores/rejas que quedaron ocultos bajo
            el jugador o una piedra al volver a reconocer el tablero.
    conexiones: si se conocen, las rejas controladas por pulsadores se consideran cerradas
            de base (su apertura visible se debe al pulsador, no es permanente).
    """
    reglas = reglas or Reglas()
    filas = len(matriz)
    columnas = len(matriz[0])
    if any(len(fila) != columnas for fila in matriz):
        raise ValueError("La matriz no es rectangular.")

    controladas = conexiones.rejas_controladas() if conexiones is not None else frozenset()
    usar_previo = (previo is not None and previo.filas == filas
                   and previo.columnas == columnas)

    terreno = []
    piedras, diamantes, llaves, rejas_abiertas = set(), set(), set(), set()
    jugadores = []
    desconocidas = []
    usados = set(pinchos_usados)
    pinchos_bajo_piedra = set()

    for f in range(filas):
        fila_terreno = []
        for c in range(columnas):
            pos = (f, c)
            cat = str(matriz[f][c]).strip().lower()
            if cat in CATEGORIAS:
                tipo, obj = CATEGORIAS[cat]
            else:
                desconocidas.append((pos, cat))
                tipo, obj = MURO, None  # lo desconocido se trata como obstaculo

            if usar_previo and obj in ("jugador", "piedra"):
                previo_tipo = previo.terreno[f][c]
                if previo_tipo in (PULSADOR, REJA, PINCHOS):
                    tipo = previo_tipo

            # Bajo una piedra puede esconderse un pincho que no se ve en la captura (nivel 10):
            # se asume que esa casilla solo se puede pisar una vez. Solo en el primer
            # reconocimiento; en los siguientes se conserva el terreno del tablero previo.
            if obj == "piedra" and not usar_previo and reglas.piedra_inicial_sobre_pinchos \
                    and tipo == SUELO:
                tipo = PINCHOS
                pinchos_bajo_piedra.add(pos)

            if cat == "pinchos_activados":
                usados.add(pos)   # ya pisado en pantalla: se comporta como muro
            if tipo == REJA and (cat == "reja_abierta" or obj == "jugador") \
                    and pos not in controladas:
                rejas_abiertas.add(pos)

            if obj == "jugador":
                jugadores.append(pos)
            elif obj == "piedra":
                piedras.add(pos)
            elif obj == "diamante":
                diamantes.add(pos)
            elif obj == "llave":
                llaves.add(pos)
            fila_terreno.append(tipo)
        terreno.append(fila_terreno)

    if len(jugadores) != 1:
        raise ValueError("Se esperaba exactamente un jugador y hay {}.".format(len(jugadores)))

    tablero = Tablero(terreno, rejas_abiertas, reglas)
    tablero.pinchos_bajo_piedra = frozenset(pinchos_bajo_piedra)
    estado = Estado(
        jugador=jugadores[0],
        piedras=frozenset(piedras),
        diamantes=frozenset(diamantes),
        llaves_tablero=frozenset(llaves),
        llaves_en_mano=llaves_en_mano,
        diamantes_recogidos=diamantes_recogidos,
        pinchos_usados=frozenset(usados),
    )
    return tablero, estado, desconocidas