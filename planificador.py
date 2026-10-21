"""
planificador.py - Busqueda de rutas sobre el ESTADO COMPLETO del juego.

* Plan "objetivo": A* hasta la salida (abierta) usando solo conexiones conocidas.
  - Heuristica admisible: cada movimiento entra en una casilla; hay que entrar en una casilla
    distinta por cada diamante restante y en la salida (>= diamantes + 1), y ademas
    max_d [dist(jugador,d) + dist(d,salida)] (Manhattan). El coste de pinchos solo suma, por
    lo que la heuristica sigue siendo un limite inferior.
  - Si se supera el limite de nodos se reintenta con A* ponderado (rapido, no optimo).
* Plan "exploracion": si no hay ruta con lo que se sabe, busca la forma mas barata de activar un
  pulsador de conexion desconocida (con el jugador o con una piedra), comprobando que sea seguro.
  Empujar una piedra se penaliza (penalizacion_empuje): se prefiere un rodeo largo antes que
  desacomodar piedras. Entre varios pulsadores candidatos, el A* elige el de menor coste total,
  es decir, el que menos piedras mueve.
"""

import copy
import heapq
import itertools
from collections import deque
from dataclasses import dataclass, replace
from typing import List, Optional

from modelo import Estado, SUELO, HUECO, PUERTA, PINCHOS
from reglas import acciones_legales, pulsadores_activos, coste_movimiento


@dataclass
class Plan:
    acciones: List[str]
    tipo: str = "objetivo"            # "objetivo" | "exploracion"
    costo: int = 0
    nodos: int = 0
    optimo: bool = True
    pulsador: Optional[tuple] = None  # pulsador a descubrir (plan de exploracion)
    estado_final: Optional[Estado] = None


def distancia(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


INF = float("inf")


def _distancias(tablero):
    """
    Distancias reales (BFS) entre casillas sobre el terreno ESTATICO, tratando como
    transitable todo lo que no sea muro o lava (huecos, puertas, rejas, pinchos...).
    Es una cota inferior de la distancia real en cualquier estado -> heuristica admisible.
    Se calcula una vez por tablero y se guarda en el propio objeto.
    """
    cache = getattr(tablero, "_cache_dist", None)
    if cache is not None:
        return cache
    from modelo import MURO, LAVA
    celdas = [(f, c) for f in range(tablero.filas) for c in range(tablero.columnas)
              if tablero.terreno[f][c] not in (MURO, LAVA)]
    validas = set(celdas)
    tabla = {}
    for origen in celdas:
        d = {origen: 0}
        cola = deque([origen])
        while cola:
            p = cola.popleft()
            for _, (df, dc) in DELTAS:
                q = (p[0] + df, p[1] + dc)
                if q in validas and q not in d:
                    d[q] = d[p] + 1
                    cola.append(q)
        tabla[origen] = d
    tablero._cache_dist = tabla
    return tabla


def _arbol_minimo(puntos, dist):
    """Peso del arbol de expansion minima (Prim) entre `puntos` con distancias reales."""
    if len(puntos) <= 1:
        return 0
    restantes = list(puntos[1:])
    mejor = {p: dist(puntos[0], p) for p in restantes}
    total = 0
    while restantes:
        p = min(restantes, key=mejor.__getitem__)
        total += mejor[p]
        if total == INF:
            return INF
        restantes.remove(p)
        for q in restantes:
            d = dist(p, q)
            if d < mejor[q]:
                mejor[q] = d
    return total


def heuristica_salida(tablero, estado):
    """
    Heuristica admisible con distancias reales a traves del mapa (no Manhattan):
      * Si hay que recoger todos los diamantes: peso del arbol de expansion minima que une
        jugador, diamantes restantes y salida. Cualquier recorrido valido pasa por todos esos
        puntos, asi que mide al menos lo que el arbol minimo.
      * Si solo hacen falta N: min_d [dist(jugador,d) + dist(d,salida)] y nunca menos que el
        numero de diamantes que faltan + 1.
    Si algo es inalcanzable en el terreno estatico devuelve infinito (rama podada).
    """
    salida = tablero.salida
    if salida is None:
        return 0
    tabla = _distancias(tablero)

    def dist(a, b):
        return tabla.get(a, {}).get(b, INF)

    jugador = estado.jugador
    n = tablero.reglas.diamantes_para_salida
    if n is None:
        if not estado.diamantes:
            return dist(jugador, salida)
        return _arbol_minimo([jugador] + sorted(estado.diamantes) + [salida], dist)
    faltan = max(0, n - estado.diamantes_recogidos)
    if faltan == 0:
        return dist(jugador, salida)
    if len(estado.diamantes) < faltan:
        return INF
    via = min(dist(jugador, d) + dist(d, salida) for d in estado.diamantes)
    return max(via, faltan + 1)


def _camino(padre, clave):
    acciones = []
    while padre[clave] is not None:
        previo, accion = padre[clave]
        acciones.append(accion)
        clave = previo
    acciones.reverse()
    return acciones


@dataclass
class _Resultado:
    acciones: Optional[List[str]] = None
    costo: int = 0
    nodos: int = 0
    agotado: bool = False
    estado_final: Optional[Estado] = None


def _astar(tablero, inicio, conexiones, heuristica, es_meta=None, meta_trans=None,
           peso=1.0, max_nodos=300000):
    """
    A* generico. Meta por estado (es_meta) o por transicion (meta_trans(prev, nuevo)).
    Las metas por transicion se encolan como nodos (estado, "meta") con h = 0.
    """
    inf = float("inf")
    contador = itertools.count()
    g = {inicio: 0}
    padre = {inicio: None}
    cerrados = set()
    abiertos = [(peso * heuristica(inicio), next(contador), inicio)]
    nodos = 0

    while abiertos:
        _, _, clave = heapq.heappop(abiertos)

        if isinstance(clave, tuple):  # meta por transicion
            return _Resultado(_camino(padre, clave), g[clave], nodos, False, clave[0])

        estado = clave
        if estado in cerrados:
            continue
        if estado != inicio and es_meta is not None and es_meta(estado):
            return _Resultado(_camino(padre, estado), g[estado], nodos, False, estado)

        cerrados.add(estado)
        nodos += 1
        if nodos > max_nodos:
            return _Resultado(None, 0, nodos, True)

        gc = g[estado]
        for accion, nuevo, coste in acciones_legales(tablero, estado, conexiones):
            ng = gc + coste
            if meta_trans is not None and meta_trans(estado, nuevo):
                clave_meta = (nuevo, "meta")
                if ng < g.get(clave_meta, inf):
                    g[clave_meta] = ng
                    padre[clave_meta] = (estado, accion)
                    heapq.heappush(abiertos, (ng, next(contador), clave_meta))
                continue
            if ng < g.get(nuevo, inf):
                g[nuevo] = ng
                padre[nuevo] = (estado, accion)
                heapq.heappush(abiertos, (ng + peso * heuristica(nuevo), next(contador), nuevo))

    return _Resultado(None, 0, nodos, False)


DELTAS = (("arriba", (-1, 0)), ("abajo", (1, 0)), ("izquierda", (0, -1)), ("derecha", (0, 1)))


def _expandir_macro(tablero, estado, conexiones):
    """
    Sucesores "por eventos" de `estado`.
    Primero un BFS recorre las casillas a las que el jugador puede CAMINAR sin cambiar nada
    del estado (suelo libre, hueco rellenado, puerta ya abierta). Desde cada una se prueban
    los 4 movimientos con simular(): los que cambian algo (empujar piedra, recoger diamante o
    llave, pisar pincho, abrir puerta, pisar pulsador/reja, llegar a la salida) son los
    sucesores. Devuelve [(acciones, nuevo_estado, coste)].
    Mismas reglas que acciones_legales (usa simular), pero sin crear un nodo por cada paso.
    """
    from reglas import simular, meta_alcanzada
    if meta_alcanzada(tablero, estado):
        return []
    terreno = tablero.terreno
    reglas = tablero.reglas
    piedras, diamantes, llaves = estado.piedras, estado.diamantes, estado.llaves_tablero
    huecos, puertas = estado.huecos_llenos, estado.puertas_abiertas
    inicio = estado.jugador

    def libre(p):
        if not tablero.dentro(p) or p in piedras or p in diamantes or p in llaves:
            return False
        tp = terreno[p[0]][p[1]]
        return (tp == SUELO or (tp == HUECO and p in huecos)
                or (tp == PUERTA and p in puertas))

    usados_fuera = estado.pinchos_usados
    if reglas.pinchos_se_cierran and terreno[inicio[0]][inicio[1]] == PINCHOS:
        usados_fuera = usados_fuera | {inicio}

    padre = {inicio: None}
    orden = [inicio]
    cola = deque([inicio])
    while cola:
        p = cola.popleft()
        for accion, (df, dc) in DELTAS:
            q = (p[0] + df, p[1] + dc)
            if q not in padre and libre(q):
                padre[q] = (p, accion)
                orden.append(q)
                cola.append(q)

    def camino(p):
        acciones = []
        while padre[p] is not None:
            p, a = padre[p][0], padre[p][1]
            acciones.append(a)
        acciones.reverse()
        return acciones

    sucesores = []
    for p in orden:
        if p == inicio:
            base = estado
        else:
            base = Estado(p, piedras, diamantes, llaves, estado.llaves_en_mano, puertas,
                          huecos, estado.diamantes_recogidos, usados_fuera,
                          estado.pulsadores_pisados)
        ruta = None
        for accion, (df, dc) in DELTAS:
            q = (p[0] + df, p[1] + dc)
            if q in padre:
                continue          # es un paso de caminar: ya lo cubre el BFS
            nuevo = simular(tablero, base, accion, conexiones)
            if nuevo is None:
                continue
            if ruta is None:
                ruta = camino(p)
            coste = len(ruta) + coste_movimiento(tablero, base, nuevo)
            if nuevo.piedras != piedras:
                coste += reglas.coste_extra_empuje
            sucesores.append((ruta + [accion], nuevo, coste))
    return sucesores


def _astar_macro(tablero, inicio, conexiones, heuristica, es_meta, peso=1.0, max_nodos=300000,
                 max_segundos=None):
    """A* sobre estados de evento (ver _expandir_macro). Mismo contrato que _astar.
    Se corta (agotado=True) al superar max_nodos o max_segundos."""
    import time
    limite = None if max_segundos is None else time.time() + max_segundos
    inf = float("inf")
    contador = itertools.count()
    g = {inicio: 0}
    padre = {inicio: None}
    cerrados = set()
    abiertos = [(peso * heuristica(inicio), next(contador), inicio)]
    nodos = 0
    while abiertos:
        _, _, estado = heapq.heappop(abiertos)
        if estado in cerrados:
            continue
        if estado != inicio and es_meta(estado):
            acciones = []
            clave = estado
            while padre[clave] is not None:
                previo, tramo = padre[clave]
                acciones[:0] = tramo
                clave = previo
            return _Resultado(acciones, g[estado], nodos, False, estado)
        cerrados.add(estado)
        nodos += 1
        if nodos > max_nodos or (limite is not None and nodos % 128 == 0
                                 and time.time() > limite):
            return _Resultado(None, 0, nodos, True)
        gc = g[estado]
        for tramo, nuevo, coste in _expandir_macro(tablero, estado, conexiones):
            ng = gc + coste
            if ng < g.get(nuevo, inf):
                hn = heuristica(nuevo)
                if hn == inf:
                    continue      # objetivo inalcanzable desde aqui: se poda la rama
                g[nuevo] = ng
                padre[nuevo] = (estado, tramo)
                heapq.heappush(abiertos, (ng + peso * hn, next(contador), nuevo))
    return _Resultado(None, 0, nodos, False)


class Planificador:
    def __init__(self, max_nodos=3000000, peso_fallback=3.0, max_nodos_fallback=4000000,
                 pesos_escalera=(6.0, 12.0, 30.0),
                 nodos_seguridad=20000, penalizacion_empuje=40, log=print):
        self.penalizacion_empuje = penalizacion_empuje
        self.max_nodos = max_nodos
        self.peso_fallback = peso_fallback
        # Si el A* ponderado inicial no llega, se reintenta con pesos cada vez mas voraces.
        self.pesos_escalera = tuple(pesos_escalera)
        self.max_nodos_fallback = max_nodos_fallback
        self.nodos_seguridad = nodos_seguridad
        self.log = log
        self.ultimo_motivo = ""

    # ------------------------------------------------------------------
    def planificar(self, modelo):
        t, e, c = modelo.tablero, modelo.estado, modelo.conexiones
        self.ultimo_motivo = ""
        if t.salida is None:
            self.ultimo_motivo = "El tablero no tiene casilla de salida reconocida."
            return None

        hay_desconocidos = any(c.puede_explorar(p) for p in t.pulsadores) and bool(t.rejas)
        if hay_desconocidos:
            # Con pulsadores sin explorar, primero un intento rapido de ir a la salida; si no,
            # se explora (aprender una conexion suele desbloquear el nivel) antes de gastar
            # tiempo en las etapas largas.
            plan = self._plan_objetivo(t, e, c, rapido=True)
            if plan is None:
                plan = self._explorar(t, e, c)
            if plan is None:
                plan = self._plan_objetivo(t, e, c)
        else:
            plan = self._plan_objetivo(t, e, c)
            if plan is None:
                plan = self._explorar(t, e, c)
        if plan is None and not self.ultimo_motivo:
            self.ultimo_motivo = ("No existe ruta a la salida con la informacion actual y no hay "
                                  "ningun pulsador desconocido que se pueda explorar con seguridad.")
        return plan

    def _explorar(self, t, e, c):
        plan = self._plan_exploracion(t, e, c)
        if plan is not None:
            self.ultimo_motivo = ""
        return plan

    # Etapas de busqueda: (piedras sobre pinchos escondidos, rejas permanentes, peso, segundos).
    # Peso 1 = A* optimo; pesos mayores = A* ponderado, mucho mas rapido aunque quiza no optimo
    # (completar el nivel importa mas que la ruta mas corta). Se empieza por las reglas mas
    # prudentes y solo se relajan si no hay ruta:
    #   * "pp": empujar piedras sobre pinchos escondidos no activados (el nivel 10 lo necesita).
    #   * "perm": la reja queda abierta tras pisar su pulsador una vez (el nivel 17 lo necesita).
    ETAPAS = ((False, False, 1, 2), (False, False, 5, 3), (True, False, 3, 4),
              (False, True, 3, 4), (True, True, 3, 4),
              (True, False, 10, 6), (False, False, 10, 6), (False, True, 10, 6),
              (True, True, 10, 6),
              (False, False, 30, 10), (True, False, 30, 10), (False, True, 30, 10),
              (True, True, 30, 10),
              (False, False, 3, 40), (True, False, 3, 40), (False, True, 3, 40),
              (True, True, 3, 40))
    ETAPAS_RAPIDAS = 5          # cuantas etapas iniciales forman el "intento rapido"
    NODOS_POR_ETAPA = 400000    # tope de memoria por etapa (~1-2 GB en el peor caso)

    @staticmethod
    def _variantes(t):
        """Tableros con las reglas de cada etapa: {(pp, perm): tablero}."""
        from modelo import PINCHOS
        opciones_pp = [False]
        if any(PINCHOS in fila for fila in t.terreno) and not t.reglas.piedra_sobre_pinchos:
            opciones_pp.append(True)
        opciones_perm = [False]
        if t.pulsadores and t.rejas and not t.reglas.rejas_permanentes:
            opciones_perm.append(True)
        variantes = {}
        for pp in opciones_pp:
            for perm in opciones_perm:
                if not pp and not perm:
                    variantes[(pp, perm)] = t
                    continue
                tb = copy.copy(t)
                tb.reglas = replace(t.reglas,
                                    piedra_sobre_pinchos=t.reglas.piedra_sobre_pinchos or pp,
                                    rejas_permanentes=t.reglas.rejas_permanentes or perm)
                variantes[(pp, perm)] = tb
        return variantes

    def _plan_objetivo(self, t, e, c, rapido=False):
        variantes = self._variantes(t)
        etapas = self.ETAPAS[:self.ETAPAS_RAPIDAS] if rapido else self.ETAPAS
        total = 0
        for pp, perm, peso, segundos in etapas:
            clave = (pp, perm)
            tb = variantes.get(clave)
            if tb is None:
                continue
            res = _astar_macro(tb, e, c, lambda s, tb=tb: heuristica_salida(tb, s),
                               lambda s, tb=tb: s.jugador == tb.salida, peso=peso,
                               max_nodos=min(self.max_nodos, self.NODOS_POR_ETAPA),
                               max_segundos=segundos)
            total += res.nodos
            if res.acciones is not None:
                if tb is not t:
                    if tb.reglas.piedra_sobre_pinchos and not t.reglas.piedra_sobre_pinchos:
                        self.log("[planificador] ruta encontrada empujando piedras sobre "
                                 "pinchos escondidos no activados.")
                    if tb.reglas.rejas_permanentes and not t.reglas.rejas_permanentes:
                        self.log("[planificador] ruta encontrada suponiendo que las rejas "
                                 "quedan abiertas tras pisar su pulsador.")
                    t.reglas = tb.reglas   # el modelo debe simular con las mismas reglas
                return Plan(res.acciones, "objetivo", res.costo, total, peso == 1,
                            estado_final=res.estado_final)
            if not res.agotado:
                # se recorrio todo el espacio sin meta: con estas reglas no hay ruta
                del variantes[clave]
                if not variantes:
                    break
                continue
            self.log("[planificador] etapa (piedra sobre pinchos={}, rejas permanentes={}, "
                     "peso {}): sin ruta en {} s; sigo.".format(pp, perm, peso, segundos))
        if not rapido:
            self.ultimo_motivo = "No encontre ruta a la salida en el tiempo disponible."
        return None

    # ------------------------------------------------------------------
    def _capacidad(self, t, estado, c):
        """
        Exploracion acotada desde `estado`, avanzando por EVENTOS (_expandir_macro), lo que
        llega mucho mas lejos que paso a paso. Devuelve
        (minimo de diamantes+llaves que quedan en alguna rama, salida_alcanzable, completa).
        completa=False si se corto por el limite de nodos: entonces el resultado no es fiable.
        """
        minimo = len(estado.diamantes) + len(estado.llaves_tablero)
        meta = False
        vistos = {estado}
        cola = deque([estado])
        while cola:
            if len(vistos) >= self.nodos_seguridad:
                return minimo, meta, False
            actual = cola.popleft()
            minimo = min(minimo, len(actual.diamantes) + len(actual.llaves_tablero))
            if actual.jugador == t.salida:
                meta = True
                continue
            for _, nuevo, _ in _expandir_macro(t, actual, c):
                if nuevo not in vistos:
                    vistos.add(nuevo)
                    cola.append(nuevo)
        return minimo, meta, True

    @staticmethod
    def _contar_empujes(t, estado, c, acciones):
        """Acciones del plan que empujan una piedra (reproduce el plan sobre el tablero real)."""
        empujes = 0
        for accion in acciones:
            for a, nuevo, _ in acciones_legales(t, estado, c):
                if a == accion:
                    if nuevo.piedras != estado.piedras:
                        empujes += 1
                    estado = nuevo
                    break
        return empujes

    def _plan_exploracion(self, t, e, c):
        candidatos = frozenset(p for p in t.pulsadores if c.puede_explorar(p))
        if not candidatos or not t.rejas:
            return None

        # Tablero de exploracion: igual que el real pero penalizando empujar piedras
        # (copia superficial: el terreno es inmutable y no se toca).
        t_real = t
        t = copy.copy(t_real)
        t.reglas = replace(t_real.reglas, coste_extra_empuje=self.penalizacion_empuje)

        pre = {}
        cache = {}

        def seguro(estado):
            if estado in cache:
                return cache[estado]
            if "valor" not in pre:
                pre["valor"] = self._capacidad(t, e, c)
            post = self._capacidad(t, estado, c)
            minimo_pre, meta_pre, _ = pre["valor"]
            if not post[2]:
                ok = True   # busqueda cortada: no hay pruebas de que explorar sea danino
            else:
                ok = post[0] <= minimo_pre and (post[1] or not meta_pre)
            cache[estado] = ok
            return ok

        def meta_trans(previo, nuevo):
            antes = pulsadores_activos(t, previo)
            despues = pulsadores_activos(t, nuevo)
            if len((despues - antes) & candidatos) != 1:
                return False
            # solo un pulsador desconocido activo: si no, la observacion seria ambigua
            if sum(1 for p in despues if not c.conoce(p)) != 1:
                return False
            return seguro(nuevo)

        def h(estado):
            mejor = None
            for p in candidatos:
                d = distancia(estado.jugador, p)
                for s in estado.piedras:
                    d = min(d, distancia(s, p))
                mejor = d if mejor is None else min(mejor, d)
            return mejor or 0

        res = _astar(t, e, c, h, meta_trans=meta_trans, peso=1.0, max_nodos=self.max_nodos)
        if res.acciones is None:
            return None
        activados = pulsadores_activos(t, res.estado_final) & candidatos
        empujes = self._contar_empujes(t_real, e, c, res.acciones)
        costo_real = res.costo - self.penalizacion_empuje * empujes
        if empujes:
            self.log("[planificador] la exploracion requiere mover piedras ({} empujes); "
                     "no hay alternativa sin empujar.".format(empujes))
        return Plan(res.acciones, "exploracion", costo_real, res.nodos, True,
                    pulsador=next(iter(activados)) if activados else None,
                    estado_final=res.estado_final)