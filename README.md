# Agente inteligente para Diamond Rush

Agente que juega solo a [Diamond Rush en minijuegos.com](https://www.minijuegos.com/juego/diamond-rush).
Mira la pantalla, reconoce el tablero, planifica la ruta y mueve al personaje simulando el teclado.
No lee la página web ni modifica el juego.


---

## 1. Requisitos

- **Python 3.11 o superior.** Se descarga en <https://www.python.org/downloads/>.
  En Windows, al instalarlo, **marca la casilla "Add Python to PATH"**.
- **Google Chrome** (u otro navegador) con el juego abierto.
- Windows 10/11. También funciona en macOS y Linux, con las diferencias que se indican más abajo.

## 2. Descargar el proyecto

Clonarlo o decargarlo en .zip

## 3. Instalar las dependencias (solo la primera vez)

```
pip install -r requirements.txt
```

Si `pip` no se reconoce, prueba con `python -m pip install -r requirements.txt`. En macOS o Linux usa `pip3` y `python3`.

## 4. Jugar un nivel

1. Abre el juego en el navegador y entra en el nivel.
2. Comprueba que **el tablero se ve entero** en el **monitor principal**, incluida la fila de abajo.
   Si hay un banner o un anuncio que tapa el juego, ciérralo o haz scroll.
3. En la terminal, dentro de la carpeta del proyecto, ejecuta:

   ```
   python agente.py --reconocer
   ```

4. Cambia al navegador, **haz clic sobre el juego** y pulsa **F8**. En un portátil puede que tengas que pulsar **Fn + F8**.
5. El agente detecta el tablero, reconoce las casillas, planifica y juega. En la terminal va mostrando lo que hace.

**No hay que calibrar nada.** El tablero se detecta solo, sea cual sea la resolución, el zoom o la posición de la ventana.

### Ver el plan sin mover al personaje

```
python agente.py --reconocer --solo-planificar
```

Espera a que pulses F8, reconoce el tablero y muestra el plan, pero no pulsa ninguna tecla.

### Comprobar solo la detección del tablero

```
python autocalibrar.py --mostrar
```

Tienes 3 segundos para cambiar al juego. Luego se abre una ventana con la cuadrícula dibujada sobre el tablero.

### Botón de pánico

Lleva el ratón **a una esquina de la pantalla** y el agente se detiene (es el *failsafe* de pyautogui).
También puedes pulsar **Ctrl+C** en la terminal.

## 5. Opciones útiles

| Opción | Para qué sirve |
|---|---|
| `--tecla F9` | Usa F9 (o F2) en vez de F8 para empezar. |
| `--sin-tecla` | Empieza a los 2 segundos sin esperar ninguna tecla. |
| `--diamantes-salida N` | Indica que la salida se abre con N diamantes. Por defecto recoge todos. |
| `--max-nodos N` | Límite de nodos de la búsqueda (por defecto 3.000.000). |

Para ver todas: `python agente.py --help`

## 6. Problemas frecuentes

| Problema | Solución |
|---|---|
| "No encuentro los botones del juego" | El juego no se veía entero en el monitor principal cuando pulsaste F8. Muévelo al monitor principal, cierra lo que lo tape y vuelve a intentarlo. |
| "Se esperaba exactamente un jugador y hay 0" | Algo tapaba el tablero (por ejemplo la terminal). Deja el juego visible y vuelve a pulsar F8. |
| Las teclas no llegan al juego | Haz clic sobre el juego antes de pulsar F8 para que tenga el foco. |
| F8 no hace nada | En un portátil prueba con Fn + F8, o usa `--tecla F9`. |
| El personaje se queda quieto o se pierde a mitad del nivel | Reinicia el nivel en el juego y vuelve a lanzar el agente. Si se repite en un nivel con pulsadores, borra `conexiones_aprendidas.json`. |
| `pip` o `python` no se reconocen | Reinstala Python marcando "Add Python to PATH", o usa `py` en vez de `python`. |

**macOS y Linux:** el agente no puede detectar F8 desde otra ventana. Te pedirá que pulses **Enter** en la terminal y te dará 3 segundos para pasar al navegador.
En macOS, además, la terminal necesita permisos de **Grabación de pantalla** y **Accesibilidad**, en Ajustes del Sistema → Privacidad y seguridad.

## 7. Cómo funciona

El agente repite un ciclo: **percibir → actualizar el modelo → planificar → actuar**.

1. **Detección del tablero** (`autocalibrar.py`). Busca en la captura los dos botones redondos del juego, el engranaje y el de reinicio, con *template matching* multiescala. La distancia entre ambos da el tamaño de casilla y su posición da la esquina del tablero. Así funciona con cualquier resolución, zoom o posición de la ventana, sin coordenadas fijas.
2. **Reconocimiento de casillas** (`vision.py`). Divide el tablero en una cuadrícula de 10 × 15 y compara cada casilla con las imágenes de ejemplo de la carpeta `ejemplos/`. Clasifica cada una como muro, suelo, diamante, piedra, llave, puerta, pulsador, reja, pinchos, hueco, lava, salida o jugador.
3. **Modelo del mundo** (`modelo.py`, `reglas.py`). Representa el estado: posición, piedras, diamantes, llaves, puertas abiertas, huecos rellenados y pinchos ya pisados. Simula cada movimiento con las reglas del juego.
4. **Planificación** (`planificador.py`). Usa una **búsqueda A\*** sobre estados de evento: solo cuenta como paso de la búsqueda empujar una piedra, recoger algo, abrir una puerta o pisar un pincho o un pulsador; los tramos en los que solo camina se calculan con un BFS. La **heurística** es el peso del árbol de expansión mínima que une al jugador, los diamantes que faltan y la salida, medido con distancias reales a través del mapa. Es **admisible**, porque cualquier recorrido válido tiene que pasar por todos esos puntos. Si la ruta óptima tarda demasiado, recurre a **A\* ponderado**, que encuentra una ruta válida mucho antes aunque no sea la más corta.
5. **Pulsadores y rejas** (`conexiones.py`, `aprendizaje.py`). No se sabe de antemano qué reja abre cada pulsador. Si hace falta, el agente pisa un pulsador, vuelve a capturar la pantalla, mira qué reja cambió, guarda la conexión en `conexiones_aprendidas.json` y vuelve a planificar. Cuando solo queda un pulsador y una reja sin relacionar, deduce la conexión sin observarla.
6. **Acción** (`control.py`, `ejecutor.py`). Envía las flechas con pyautogui.

**Tipo de agente (Russell y Norvig):** agente basado en objetivos con modelo interno (con estado).
El entorno es parcialmente observable (conexiones pulsador → reja desconocidas y pinchos escondidos), determinista, secuencial, estático, discreto y de un solo agente.
El agente replanifica cuando obtiene información nueva.

### Reglas que se suponen

Algunas mecánicas no se pueden ver en la pantalla, así que se dedujeron jugando niveles reales. El planificador empieza siempre por las más prudentes y solo relaja las dudosas si con ellas no encuentra ruta:

- Las piedras se pueden empujar sobre diamantes, pero no sobre llaves.
- Un pincho escondido se puede cruzar una vez; después queda activado y funciona como un muro.
- Bajo una piedra inicial puede haber un pincho escondido, así que volver a pisar esa casilla se penaliza.
- Primero se supone que una reja solo está abierta mientras su pulsador está pisado. Si así no hay ruta, se prueba con que la reja quede abierta.
- Si no hay otra ruta, se permite empujar piedras sobre pinchos escondidos que aún no se han activado.

## 8. Estructura del proyecto

```
agente.py            Programa principal (ciclo del agente y opciones)
tecla_inicio.py      Espera la tecla F8 para empezar
autocalibrar.py      Detección automática del tablero
vision.py            Captura de pantalla y reconocimiento de casillas
ejemplos/            Imágenes de ejemplo de cada tipo de casilla
modelo.py            Estado del juego y reglas configurables
reglas.py            Simulación de movimientos
planificador.py      Búsqueda A* y exploración de pulsadores
conexiones.py        Conexiones pulsador → reja aprendidas
aprendizaje.py       Observación de rejas tras pisar un pulsador
control.py           Envío de teclas (pyautogui)
ejecutor.py          Ejecución de las acciones del plan
test_agente.py       Pruebas automáticas (python -m unittest test_agente)
```
