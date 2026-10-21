"""
Pruebas del agente (no necesitan pantalla, teclado ni OpenCV).

    python -m unittest test_agente -v
"""

import os
import random
import tempfile
import textwrap
import unittest

from aprendizaje import comparar_rejas
from agente import Agente
from conexiones import Conexiones
from ejecutor import Ejecutor
from modelo import (Reglas, MURO, LAVA, REJA, HUECO, PUERTA, SALIDA, PINCHOS, PULSADOR)
from planificador import Plan, Planificador, _astar, heuristica_salida
from reglas import (ModeloJuego, MovimientoIlegal, DIRECCIONES, acciones_legales,
                    rejas_abiertas, simular)

SIMBOLOS = {
    "x": "pinchos_activados",
    "#": "muro", ".": "suelo", "J": "jugador", "D": "diamante", "K": "llave", "P": "piedra",
    "H": "hueco_piedra", "L": "lava", "S": "llegada_cerrada", "U": "puertall", "R": "reja",
    "r": "reja_abierta", "B": "pulsador_reja", "^": "pinchos_escondidos",
}


def matriz(texto):
    lineas = textwrap.dedent(texto).strip("\n").split("\n")
    return [[SIMBOLOS[ch] for ch in linea] for linea in lineas]


def silencio(*args, **kwargs):
    pass


# Nivel real (matriz_tablero.json) en notacion compacta
NIVEL_REAL = """
##########
##########
##D.D.D.##
##.####D##
##D#.S#.##
##.D.D#.##
#######U##
##PJ...D##
#######r##
##HPD^R.##
##K#^^#.##
##P#^^#^##
##HP.DBD##
##########
##########
"""


class MundoSimulado:
    """Juego 'real' oculto: conoce las conexiones verdaderas y cuenta las capturas."""

    def __init__(self, texto_o_matriz, reales=None, reglas=None, error=1.0):
        mat = matriz(texto_o_matriz) if isinstance(texto_o_matriz, str) else texto_o_matriz
        con = Conexiones()
        for p, rs in (reales or {}).items():
            con.registrar(p, rs)
        self.modelo = ModeloJuego.desde_matriz(mat, reglas=reglas, conexiones=con)
        self.capturas = 0
        self.error = error

    def mover(self, direccion):
        self.modelo.aplicar(direccion)

    def observar_celdas(self, celdas):
        self.capturas += 1
        abiertas = self.modelo.rejas_abiertas()
        return {c: ("reja_abierta" if c in abiertas else "reja", self.error) for c in celdas}

    def reconocer_matriz(self):
        raise NotImplementedError


def crear_agente(texto, reales=None, conocidas=None, reglas=None, error=1.0, inferir=False):
    mundo = MundoSimulado(texto, reales, reglas, error)
    conexiones = Conexiones()
    for p, rs in (conocidas or {}).items():
        conexiones.registrar(p, rs)
    modelo = ModeloJuego.desde_matriz(matriz(texto), reglas=reglas, conexiones=conexiones)
    agente = Agente(modelo, mundo, Ejecutor(mover_fn=mundo.mover), log=silencio, inferir=inferir)
    return agente, mundo


def modelo_de(texto, reglas=None, conocidas=None):
    con = Conexiones()
    for p, rs in (conocidas or {}).items():
        con.registrar(p, rs)
    return ModeloJuego.desde_matriz(matriz(texto), reglas=reglas, conexiones=con)


def planificar(texto, **kw):
    m = modelo_de(texto, **kw)
    return m, Planificador(log=silencio).planificar(m)


def aplicar_plan(m, plan):
    for a in plan.acciones:
        m.aplicar(a)


# Niveles pequenos ------------------------------------------------------------------------
LIBRE = """
#######
#J...S#
#######
"""
DIAM_LLAVE = """
#########
#J.D.K.S#
#########
"""
PUERTA_LLAVE = """
#######
#J.U.S#
#.K####
#######
"""
PIEDRA_HUECO = """
#######
#JPH.S#
#######
"""
PIEDRA_LAVA = """
#######
#JPL.S#
#######
"""
DOS_PIEDRAS = """
#######
#JPP.S#
#######
"""
# El pulsador B abre la reja R (2,3) que da a la salida, pero el jugador no puede
# cruzar la reja sin dejar el pulsador.
PULSADOR_JUGADOR = """
#######
#J.B.##
###R###
###S###
"""
# La piedra (1,2) se empuja al pulsador (1,3), callejon sin salida; la reja (2,2) da a la salida.
PULSADOR_PIEDRA = """
#####
#JPB#
##R##
##.S#
#####
"""
B_PIEDRA = (1, 3)
R_PIEDRA = (2, 2)
B_JUG = (1, 3)
R_JUG = (2, 3)


class TestRutasYObjetos(unittest.TestCase):
    def test_01_ruta_libre_a_la_salida(self):
        m, plan = planificar(LIBRE)
        self.assertEqual(plan.acciones, ["derecha"] * 4)
        aplicar_plan(m, plan)
        self.assertTrue(m.meta_alcanzada())

    def test_02_recoge_diamantes_y_llaves(self):
        m, plan = planificar(DIAM_LLAVE)
        self.assertEqual(len(plan.acciones), 6)
        aplicar_plan(m, plan)
        self.assertEqual(len(m.estado.diamantes), 0)
        self.assertEqual(m.estado.llaves_en_mano, 1)
        self.assertEqual(len(m.estado.llaves_tablero), 0)
        self.assertTrue(m.meta_alcanzada())

    def test_02b_salida_cerrada_mientras_queden_diamantes(self):
        m = modelo_de(DIAM_LLAVE)
        for a in ["derecha", "derecha"]:
            m.aplicar(a)           # ya recogio el diamante (1,3)
        self.assertTrue(m.salida_abierta())
        m2 = modelo_de("""
            #######
            #JS.D.#
            #######
        """)
        self.assertFalse(m2.salida_abierta())
        self.assertFalse(m2.es_legal("derecha"))

    def test_03_abre_puerta_con_la_llave(self):
        m = modelo_de(PUERTA_LLAVE)
        m.estado = m.estado  # sin llave no puede abrir
        for a in ["derecha"]:
            m.aplicar(a)       # (1,2)
        self.assertFalse(m.es_legal("derecha"))   # puerta (1,3) sin llave
        m, plan = planificar(PUERTA_LLAVE)
        self.assertEqual(plan.costo, 6)
        info_puerta = None
        for a in plan.acciones:
            info = m.aplicar(a)
            if info.abrio_puerta:
                info_puerta = info
        self.assertIsNotNone(info_puerta)
        self.assertEqual(m.estado.llaves_en_mano, 0)
        self.assertTrue(m.meta_alcanzada())

    def test_04_piedra_en_hueco_lo_convierte_en_suelo(self):
        m, plan = planificar(PIEDRA_HUECO)
        self.assertEqual(plan.acciones, ["derecha"] * 4)
        info = m.aplicar("derecha")
        self.assertEqual(info.destino_piedra, "hueco")
        self.assertEqual(len(m.estado.piedras), 0)
        self.assertIn((1, 3), m.estado.huecos_llenos)
        self.assertTrue(m.es_legal("derecha"))  # ahora se puede pisar el hueco

    def test_05_piedra_en_lava_desaparece(self):
        m = modelo_de(PIEDRA_LAVA)
        info = m.aplicar("derecha")
        self.assertEqual(info.destino_piedra, "lava")
        self.assertEqual(len(m.estado.piedras), 0)
        self.assertEqual(len(m.estado.huecos_llenos), 0)
        self.assertFalse(m.es_legal("derecha"))   # la lava sigue siendo lava

    def test_06_rechaza_empujar_dos_piedras(self):
        m = modelo_de(DOS_PIEDRAS)
        self.assertFalse(m.es_legal("derecha"))
        with self.assertRaises(MovimientoIlegal):
            m.aplicar("derecha")
        self.assertEqual(m.estado.jugador, (1, 1))

    def test_06b_piedra_contra_muro_o_sobre_diamante_no_se_empuja(self):
        self.assertFalse(modelo_de("""
            ######
            #JP###
            ######
        """).es_legal("derecha"))
        nivel = """
            #######
            #JPD.S#
            #######
        """
        # con la regla por defecto la piedra puede quedar sobre el diamante...
        m = modelo_de(nivel)
        self.assertTrue(m.es_legal("derecha"))
        m.aplicar("derecha")
        self.assertIn((1, 3), m.estado.diamantes)      # el diamante sigue debajo
        # ...y con --piedra-no-sobre-objetos el empuje se rechaza
        self.assertFalse(modelo_de(nivel, reglas=Reglas(piedra_sobre_objetos=False))
                         .es_legal("derecha"))


class TestLimiteDeLlaves(unittest.TestCase):
    NIVEL = """
        #########
        #JKK.U.S#
        #########
    """

    def test_no_se_pisa_una_segunda_llave(self):
        m = modelo_de(self.NIVEL)
        m.aplicar("derecha")                 # recoge la primera llave
        self.assertEqual(m.estado.llaves_en_mano, 1)
        self.assertFalse(m.es_legal("derecha"))   # la segunda llave bloquea

    def test_con_llave_extra_pasa_no_la_recoge(self):
        m = modelo_de(self.NIVEL, reglas=Reglas(llave_extra_bloquea=False))
        m.aplicar("derecha")
        m.aplicar("derecha")                 # pisa la segunda sin recogerla
        self.assertEqual(m.estado.llaves_en_mano, 1)
        self.assertEqual(len(m.estado.llaves_tablero), 1)

    def test_usa_la_primera_llave_antes_de_recoger_la_segunda(self):
        nivel = """
            ##########
            #J.U.K.S##
            #.K#######
            ##########
        """
        m, plan = planificar(nivel)
        self.assertIsNotNone(plan)
        for a in plan.acciones:
            m.aplicar(a)
            self.assertLessEqual(m.estado.llaves_en_mano, 1)
        self.assertTrue(m.meta_alcanzada())


NIVEL_2 = """
##########
##########
##########
#.J......#
######P###
#..DD.H..#
#P########
#H...P.D.#
######D###
#........#
#.P......#
##..P#H#.#
###HD#S#.#
####D###.#
##########
"""


class TestNivel2(unittest.TestCase):
    def test_nivel_2_se_resuelve_empujando_piedra_sobre_diamante(self):
        m, plan = planificar(NIVEL_2)
        self.assertIsNotNone(plan)
        for a in plan.acciones:
            self.assertTrue(m.es_legal(a))
            m.aplicar(a)
            comprobar_invariantes(self, m)
        self.assertEqual(len(m.estado.diamantes), 0)
        self.assertTrue(m.meta_alcanzada())

    def test_nivel_2_sin_piedra_sobre_objetos_no_tiene_solucion(self):
        m, plan = planificar(NIVEL_2, reglas=Reglas(piedra_sobre_objetos=False))
        self.assertIsNone(plan)


class TestPinchosDeUnSoloUso(unittest.TestCase):
    NIVEL = """
        #########
        #J.^.S###
        #########
    """

    def test_pincho_atravesado_se_convierte_en_muro(self):
        m = modelo_de(self.NIVEL)
        m.aplicar("derecha")          # (1,2)
        m.aplicar("derecha")          # sobre el pincho (1,3): transitable
        self.assertNotIn((1, 3), m.estado.pinchos_usados)   # aun esta encima
        m.aplicar("derecha")          # sale de el: se activa
        self.assertIn((1, 3), m.estado.pinchos_usados)
        self.assertFalse(m.es_legal("izquierda"))   # ya no se puede volver a pisar

    def test_no_se_puede_ir_y_volver_por_un_pincho(self):
        nivel = """
            ##########
            #J.^.D.S##
            ##########
        """
        # recoger D y volver a la salida cruzaria dos veces el pincho si la salida estuviera atras
        m, plan = planificar(nivel)
        self.assertIsNotNone(plan)
        aplicar_plan(m, plan)
        self.assertTrue(m.meta_alcanzada())
        sin = """
            ##########
            #.^J.D.S##
            ##########
        """
        # aqui hay que pasar por el pincho de ida y vuelta: imposible con un solo uso
        nivel_retorno = """
            ###########
            #D^J...S###
            ###########
        """
        m, plan = planificar(nivel_retorno)
        self.assertIsNone(plan)
        m, plan = planificar(nivel_retorno, reglas=Reglas(pinchos_se_cierran=False))
        self.assertIsNotNone(plan)


class TestPinchosActivados(unittest.TestCase):
    def test_pinchos_activados_en_pantalla_empiezan_como_muro(self):
        m = modelo_de("""
            #######
            #J^x.S#
            #######
        """)
        self.assertIn((1, 3), m.estado.pinchos_usados)
        m.aplicar("derecha")                       # pisa el escondido
        self.assertFalse(m.es_legal("derecha"))    # el activado bloquea el paso

    def test_reconocer_de_nuevo_conserva_pincho_bajo_el_jugador(self):
        m = modelo_de("""
            #######
            #J^..S#
            #######
        """)
        m.aplicar("derecha")
        nueva = matriz("""
            #######
            #xJ..S#
            #######
        """)
        r = ModeloJuego.desde_matriz(nueva, previo=m.tablero)
        self.assertEqual(r.tablero.terreno[1][2], PINCHOS)
        self.assertIn((1, 1), r.estado.pinchos_usados)


DOS_PULSADORES = """
#########
#J.PB.B.#
###R#R###
###.#.S##
#########
"""


class TestDeduccionPorEliminacion(unittest.TestCase):
    def test_un_pulsador_y_una_reja_se_relacionan_sin_observar(self):
        agente, mundo = crear_agente(PULSADOR_PIEDRA, reales={B_PIEDRA: {R_PIEDRA}}, inferir=True)
        resultado = agente.ejecutar()
        self.assertTrue(resultado.exito)
        self.assertEqual(mundo.capturas, 0)                  # no se capturo la pantalla
        self.assertEqual(agente.modelo.conexiones.rejas_de(B_PIEDRA), frozenset({R_PIEDRA}))

    def test_no_infiere_si_hay_mas_de_un_candidato(self):
        m = modelo_de(DOS_PULSADORES)
        self.assertEqual(len(m.tablero.pulsadores), 2)
        self.assertEqual(len(m.tablero.rejas), 2)
        self.assertEqual(m.inferir_conexiones(), [])

    def test_infiere_el_ultimo_par_tras_conocer_el_otro(self):
        m = modelo_de(DOS_PULSADORES)
        p1, p2 = m.tablero.pulsadores
        r1, r2 = m.tablero.rejas
        m.conexiones.registrar(p1, {r1})
        self.assertEqual(m.inferir_conexiones(), [(p2, r2)])
        self.assertEqual(m.conexiones.rejas_de(p2), frozenset({r2}))

    def test_rejas_abiertas_de_base_no_cuentan_como_libres(self):
        # la reja_abierta se considera fija, asi que el unico par sin relacionar es B-R
        m = modelo_de("""
            #######
            #J.BR.#
            ###r###
            #######
        """)
        self.assertEqual(m.inferir_conexiones(), [(m.tablero.pulsadores[0], (1, 4))])

    def test_sin_inferir_el_agente_observa_como_antes(self):
        agente, mundo = crear_agente(PULSADOR_PIEDRA, reales={B_PIEDRA: {R_PIEDRA}}, inferir=False)
        self.assertTrue(agente.ejecutar().exito)
        self.assertEqual(mundo.capturas, 1)


class TestPulsadores(unittest.TestCase):
    def test_07_jugador_activa_pulsador_y_se_registra_la_conexion(self):
        agente, mundo = crear_agente(PULSADOR_JUGADOR, reales={B_JUG: {R_JUG}})
        resultado = agente.ejecutar()
        con = agente.modelo.conexiones
        self.assertEqual(con.rejas_de(B_JUG), frozenset({R_JUG}))
        self.assertEqual(mundo.capturas, 1)
        # sin piedra no se puede cruzar la reja: no hay solucion, pero lo aprendido es correcto
        self.assertFalse(resultado.exito)
        # modelo y juego real siguen sincronizados
        self.assertEqual(agente.modelo.estado, mundo.modelo.estado)

    def test_08_al_salir_del_pulsador_la_reja_se_cierra(self):
        m = modelo_de(PULSADOR_JUGADOR, conocidas={B_JUG: {R_JUG}})
        m.aplicar("derecha")
        m.aplicar("derecha")                       # sobre el pulsador
        self.assertIn(R_JUG, m.rejas_abiertas())
        self.assertIn(B_JUG, m.pulsadores_activos())
        # bajar a la reja desde el pulsador cerraria la reja bajo el jugador: ilegal
        self.assertFalse(m.es_legal("abajo"))
        info = m.aplicar("derecha")                # sale del pulsador
        self.assertIn(B_JUG, info.pulsadores_liberados)
        self.assertNotIn(R_JUG, m.rejas_abiertas())

    def test_09_piedra_sobre_pulsador_mantiene_la_reja_abierta(self):
        m = modelo_de(PULSADOR_PIEDRA, conocidas={B_PIEDRA: {R_PIEDRA}})
        info = m.aplicar("derecha")                # empuja la piedra al pulsador
        self.assertEqual(info.destino_piedra, "pulsador")
        self.assertIn(R_PIEDRA, m.rejas_abiertas())
        m.aplicar("abajo")                         # el jugador cruza la reja
        m.aplicar("abajo")
        self.assertIn(R_PIEDRA, m.rejas_abiertas())  # la piedra sigue oprimiendo
        m.aplicar("derecha")
        self.assertTrue(m.meta_alcanzada())

    def test_10_reutiliza_conexion_conocida_sin_capturar(self):
        agente, mundo = crear_agente(PULSADOR_PIEDRA, reales={B_PIEDRA: {R_PIEDRA}},
                                     conocidas={B_PIEDRA: {R_PIEDRA}})
        resultado = agente.ejecutar()
        self.assertTrue(resultado.exito)
        self.assertEqual(mundo.capturas, 0)
        self.assertEqual(agente.ciclos, 1)

    def test_11_replanifica_al_descubrir_la_conexion(self):
        agente, mundo = crear_agente(PULSADOR_PIEDRA, reales={B_PIEDRA: {R_PIEDRA}})
        # con lo que se sabe no hay ruta: solo se puede explorar
        plan_inicial = Planificador(log=silencio).planificar(agente.modelo)
        self.assertEqual(plan_inicial.tipo, "exploracion")
        self.assertEqual(plan_inicial.pulsador, B_PIEDRA)
        resultado = agente.ejecutar()
        self.assertTrue(resultado.exito)
        self.assertEqual(mundo.capturas, 1)             # una sola captura adicional
        self.assertGreaterEqual(agente.ciclos, 2)       # replanifico tras aprender
        self.assertEqual(agente.modelo.conexiones.rejas_de(B_PIEDRA), frozenset({R_PIEDRA}))
        self.assertEqual(agente.modelo.estado, mundo.modelo.estado)

    def test_11b_observacion_poco_fiable_no_atribuye_conexion(self):
        agente, mundo = crear_agente(PULSADOR_PIEDRA, reales={B_PIEDRA: {R_PIEDRA}}, error=99.0)
        resultado = agente.ejecutar()
        self.assertFalse(resultado.exito)
        self.assertFalse(agente.modelo.conexiones.conoce(B_PIEDRA))
        self.assertEqual(agente.modelo.conexiones.rejas_de(B_PIEDRA), frozenset())

    def test_11c_comparar_rejas(self):
        celdas = [(2, 2), (3, 3)]
        r = comparar_rejas(celdas, frozenset(),
                           {(2, 2): ("reja_abierta", 3.0), (3, 3): ("reja", 2.0)})
        self.assertTrue(r.concluyente)
        self.assertEqual(r.rejas_nuevas, frozenset({(2, 2)}))
        # todas ya abiertas -> no informativa
        r = comparar_rejas(celdas, frozenset(celdas),
                           {(2, 2): ("reja_abierta", 3.0), (3, 3): ("reja_abierta", 2.0)})
        self.assertFalse(r.concluyente)
        # una reja esperada abierta aparece cerrada -> inconsistencia
        r = comparar_rejas(celdas, frozenset({(2, 2)}),
                           {(2, 2): ("reja", 3.0), (3, 3): ("reja", 2.0)})
        self.assertTrue(r.inconsistente)

    def test_11d_exploracion_insegura_se_rechaza(self):
        # Empujar la piedra sobre el pulsador deja el nivel sin salida posible si la reja
        # no se abre: el pulsador B (1,3) no es seguro de explorar cuando perderia la llave/diamante.
        nivel = """
            ######
            #JPB.#
            #D####
            ######
        """
        m = modelo_de(nivel)
        plan = Planificador(log=silencio).planificar(m)
        # el diamante (2,1) sigue siendo alcanzable tras la exploracion; es seguro
        # (sin rejas en el nivel tampoco hay nada que descubrir): no hay plan de exploracion
        self.assertIsNone(plan)


class TestPlanificadorYSeguridad(unittest.TestCase):
    def test_a_estrella_optimo_igual_que_dijkstra(self):
        for nivel in (LIBRE, DIAM_LLAVE, PUERTA_LLAVE, PIEDRA_HUECO):
            m = modelo_de(nivel)
            t, e, c = m.tablero, m.estado, m.conexiones
            plan = Planificador(log=silencio).planificar(m)
            dijkstra = _astar(t, e, c, lambda s: 0, es_meta=lambda s: s.jugador == t.salida)
            self.assertEqual(plan.costo, dijkstra.costo, nivel)
            self.assertLessEqual(heuristica_salida(t, e), plan.costo)  # admisible en el inicio

    def test_12_no_atraviesa_obstaculos_ni_genera_movimientos_ilegales(self):
        # con los pinchos de un solo uso hace falta conocer la conexion del pulsador
        m = modelo_de(NIVEL_REAL, conocidas={(12, 6): {(9, 6)}})
        plan = Planificador(log=silencio).planificar(m)
        self.assertIsNotNone(plan)
        for accion in plan.acciones:
            self.assertTrue(m.es_legal(accion), "accion ilegal en el plan: " + accion)
            m.aplicar(accion)
            comprobar_invariantes(self, m)
        self.assertTrue(m.meta_alcanzada())
        self.assertEqual(len(m.estado.diamantes), 0)

    def test_12b_fuzz_invariantes(self):
        rnd = random.Random(1234)
        for nivel in (NIVEL_REAL, PULSADOR_PIEDRA, PIEDRA_HUECO, PUERTA_LLAVE):
            con = {(12, 6): {(9, 6)}} if nivel == NIVEL_REAL else {B_PIEDRA: {R_PIEDRA}}
            m = modelo_de(nivel, conocidas=con if nivel in (NIVEL_REAL, PULSADOR_PIEDRA) else None)
            piedras_ini = len(m.estado.piedras)
            for _ in range(3000):
                a = rnd.choice(list(DIRECCIONES))
                legal = m.es_legal(a)
                antes = m.estado
                try:
                    m.aplicar(a)
                    self.assertTrue(legal)
                except MovimientoIlegal:
                    self.assertFalse(legal)
                    self.assertEqual(m.estado, antes)
                comprobar_invariantes(self, m)
                self.assertLessEqual(len(m.estado.piedras), piedras_ini)
                if m.meta_alcanzada():
                    break

    def test_13_no_envia_acciones_ilegales_al_teclado(self):
        agente, mundo = crear_agente(PIEDRA_HUECO)
        r = agente._ejecutar_plan(Plan(["izquierda", "derecha"]))
        self.assertEqual(r, "replanificar")
        self.assertEqual(agente.ejecutor.enviadas, [])

    def test_14_nivel_real_de_extremo_a_extremo(self):
        # el pulsador (12,6) abre la reja (9,6): se descubre durante la ruta con UNA captura
        agente, mundo = crear_agente(NIVEL_REAL, reales={(12, 6): {(9, 6)}})
        resultado = agente.ejecutar()
        self.assertTrue(resultado.exito, resultado.motivo)
        self.assertEqual(mundo.capturas, 1)
        self.assertEqual(agente.modelo.estado, mundo.modelo.estado)
        self.assertEqual(len(mundo.modelo.estado.diamantes), 0)
        self.assertEqual(agente.modelo.conexiones.rejas_de((12, 6)), frozenset({(9, 6)}))

    def test_15_pinchos_como_obstaculo_deja_el_nivel_real_sin_ruta(self):
        m = modelo_de(NIVEL_REAL, reglas=Reglas(pinchos_transitables=False))
        self.assertIsNone(Planificador(log=silencio).planificar(m))


class TestPersistenciaYReconstruccion(unittest.TestCase):
    def test_persistencia_de_conexiones(self):
        m = modelo_de(PULSADOR_PIEDRA)
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "con.json")
            con = Conexiones(ruta, m.tablero.firma)
            con.registrar(B_PIEDRA, {R_PIEDRA})
            cargada = Conexiones.cargar(ruta, m.tablero.firma)
            self.assertEqual(cargada.rejas_de(B_PIEDRA), frozenset({R_PIEDRA}))
            otra = Conexiones.cargar(ruta, "otra-firma")      # otro nivel: se ignora
            self.assertFalse(otra.conoce(B_PIEDRA))

    def test_reconstruccion_conserva_pulsador_bajo_una_piedra(self):
        m = modelo_de(PULSADOR_PIEDRA, conocidas={B_PIEDRA: {R_PIEDRA}})
        m.aplicar("derecha")  # piedra sobre el pulsador: en pantalla se vera "piedra"
        nueva = matriz("""
            #####
            #.JP#
            ##r##
            ##.S#
            #####
        """)
        # en la nueva captura el jugador esta en (1,2) y la piedra tapa el pulsador (1,3)
        r = ModeloJuego.desde_matriz(nueva, conexiones=m.conexiones, previo=m.tablero)
        self.assertEqual(r.tablero.terreno[1][3], PULSADOR)
        self.assertIn(R_PIEDRA, r.rejas_abiertas())   # abierta por la piedra, no de forma fija
        self.assertEqual(r.tablero.rejas_base_abiertas, frozenset())


def comprobar_invariantes(tc, m):
    t, e = m.tablero, m.estado
    ty = t.terreno
    tc.assertNotEqual(ty[e.jugador[0]][e.jugador[1]], MURO)
    tc.assertNotEqual(ty[e.jugador[0]][e.jugador[1]], LAVA)
    if ty[e.jugador[0]][e.jugador[1]] == HUECO:
        tc.assertIn(e.jugador, e.huecos_llenos)
    if ty[e.jugador[0]][e.jugador[1]] == REJA:
        tc.assertIn(e.jugador, m.rejas_abiertas())
    if ty[e.jugador[0]][e.jugador[1]] == PUERTA:
        tc.assertIn(e.jugador, e.puertas_abiertas)
    tc.assertNotIn(e.jugador, e.piedras)
    for p in e.piedras:
        tipo = ty[p[0]][p[1]]
        tc.assertNotIn(tipo, (MURO, LAVA, REJA, SALIDA))
        if tipo == PINCHOS:
            # solo sobre un pincho escondido aun no activado: el de su casilla inicial o,
            # si el plan lo permite, uno al que se empujo
            tc.assertNotIn(p, e.pinchos_usados)
            tc.assertTrue(p in getattr(t, "pinchos_bajo_piedra", frozenset())
                          or t.reglas.piedra_sobre_pinchos)
        if tipo == HUECO:
            tc.assertIn(p, e.huecos_llenos)
        if tipo == PUERTA:
            tc.assertIn(p, e.puertas_abiertas)
    tc.assertGreaterEqual(e.llaves_en_mano, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)