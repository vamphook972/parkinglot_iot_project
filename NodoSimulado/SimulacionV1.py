import os
import sys
import json
import time
import random
import string
import argparse
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
# --------------------------------------------------------------------
# Configuración general
# --------------------------------------------------------------------
load_dotenv()
NODE_ID = "PARKING-002"

# --------------------------------------------------------------------
# Configuración MQTT
# --------------------------------------------------------------------
MQTT_BROKER = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_CLIENT_ID = os.getenv("MQTT_SIMULATOR_CLIENT_ID")
MQTT_TOPIC_BAHIA = os.getenv("MQTT_TOPIC_BAHIA")
MQTT_TOPIC_ACCESO = os.getenv("MQTT_TOPIC_ACCESO")
MQTT_TOPIC_RESERVA = os.getenv("MQTT_TOPIC_RESERVA")

# --------------------------------------------------------------------
# Habilitar colores ANSI en Windows
# --------------------------------------------------------------------
if os.name == "nt":
    os.system("")

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    GRAY = "\033[90m"
    BLUE = "\033[94m"

print_lock = threading.Lock()

def log(msg: str) -> None:
    with print_lock:
        print(msg)


# --------------------------------------------------------------------
# Fecha y hora
# --------------------------------------------------------------------
def now_iso() -> str:
    """
    Fecha/hora local en formato ISO8601 con microsegundos.
    """
    return datetime.now().astimezone().isoformat(
        timespec="microseconds"
    )

# --------------------------------------------------------------------
# Mostrar JSON
# --------------------------------------------------------------------
def print_json_event(
    titulo: str,
    data: dict,
    color: str
) -> None:

    with print_lock:
        print(
            f"\n{color}{Color.BOLD}"
            f"--- {titulo} ---"
            f"{Color.RESET}"
        )

        print(
            json.dumps(
                data,
                indent=4,
                ensure_ascii=False
            )
        )

        print(
            f"{color}"
            f"{'-' * 40}"
            f"{Color.RESET}"
        )


# --------------------------------------------------------------------
# Generación de placas
# --------------------------------------------------------------------
def generar_placa() -> str:

    letras = "".join(
        random.choices(
            string.ascii_uppercase,
            k=3
        )
    )

    numeros = "".join(
        random.choices(
            string.digits,
            k=3
        )
    )

    return f"{letras}{numeros}"


# --------------------------------------------------------------------
# Modelo de datos
# --------------------------------------------------------------------
@dataclass
class Vehiculo:
    placa: str
    reservation_id: Optional[str] = None
@dataclass
class Bahia:
    id: str
    estado: str = "DISPONIBLE"
    # DISPONIBLE | RESERVADA | OCUPADA

    placa: Optional[str] = None

    reservation_id: Optional[str] = None

# --------------------------------------------------------------------
# MQTT
# --------------------------------------------------------------------
mqtt_client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id=MQTT_CLIENT_ID
)
def mqtt_on_connect(
    client,
    userdata,
    flags,
    reason_code,
    properties
):
    if reason_code == 0:
        log(
            f"{Color.GREEN}"
            f"[MQTT] Nodo simulado conectado al broker"
            f"{Color.RESET}"
        )
        log(
            f"{Color.GRAY}"
            f"[MQTT] Broker: "
            f"{MQTT_BROKER}:{MQTT_PORT}"
            f"{Color.RESET}"
        )
        client.subscribe(
            MQTT_TOPIC_RESERVA
        )
        log(
            f"{Color.CYAN}"
            f"[MQTT] Suscrito a: "
            f"{MQTT_TOPIC_RESERVA}"
            f"{Color.RESET}"
        )
    else:
        log(
            f"{Color.RED}"
            f"[MQTT] Error de conexión. "
            f"Código: {reason_code}"
            f"{Color.RESET}"
        )
def mqtt_on_disconnect(
    client,
    userdata,
    flags,
    reason_code,
    properties
):
    log(
        f"{Color.YELLOW}"
        f"[MQTT] Nodo desconectado del broker. "
        f"Código: {reason_code}"
        f"{Color.RESET}"
    )
def mqtt_on_message(
    client,
    userdata,
    message
):
    try:
        payload = json.loads(
            message.payload.decode("utf-8")
        )
        log(
            f"{Color.YELLOW}"
            f"[MQTT IN] {message.topic}: "
            f"{payload}"
            f"{Color.RESET}"
        )
        if message.topic == MQTT_TOPIC_RESERVA:
            procesar_estado_reserva_mqtt(
                payload
            )
    except json.JSONDecodeError as error:
        log(
            f"{Color.RED}"
            f"[MQTT] JSON inválido recibido: "
            f"{error}"
            f"{Color.RESET}"
        )
    except Exception as error:
        log(
            f"{Color.RED}"
            f"[MQTT] Error procesando mensaje: "
            f"{error}"
            f"{Color.RESET}"
        )
def procesar_estado_reserva_mqtt(
    payload: dict
):
    reservation_id = payload.get(
        "reservation_id"
    )
    active = payload.get(
        "active",
        False
    )
    plate = payload.get(
        "plate"
    )
    if active:
        log(
            f"{Color.YELLOW}"
            f"[RESERVA MQTT] "
            f"Reserva recibida: "
            f"{reservation_id} | "
            f"Placa: {plate}"
            f"{Color.RESET}"
        )
    else:
        log(
            f"{Color.GRAY}"
            f"[RESERVA MQTT] "
            f"Reserva desactivada"
            f"{Color.RESET}"
        )
def publicar_mqtt(
    topic: str,
    data: dict
) -> None:
    try:
        payload = json.dumps(
            data,
            ensure_ascii=False
        )
        if not mqtt_client.is_connected():
            log(
                f"{Color.RED}"
                f"[MQTT] No conectado. "
                f"No se pudo publicar en {topic}"
                f"{Color.RESET}"
            )
            return
        resultado = mqtt_client.publish(
            topic,
            payload
        )
        if resultado.rc == mqtt.MQTT_ERR_SUCCESS:
            log(
                f"{Color.GREEN}"
                f"[MQTT OUT] Publicado en "
                f"{topic}"
                f"{Color.RESET}"
            )
        else:
            log(
                f"{Color.RED}"
                f"[MQTT] Error publicando en "
                f"{topic}. "
                f"Código: {resultado.rc}"
                f"{Color.RESET}"
            )
    except Exception as error:
        log(
            f"{Color.RED}"
            f"[MQTT] Error publicando: "
            f"{error}"
            f"{Color.RESET}"
        )
# Configurar callbacks MQTT
mqtt_client.on_connect = mqtt_on_connect
mqtt_client.on_disconnect = mqtt_on_disconnect
mqtt_client.on_message = mqtt_on_message
# --------------------------------------------------------------------
# "Servidor" interno de simulación
# Mantiene la lógica local de reservas del simulador.
# La comunicación de eventos hacia el servidor real se realiza
# mediante MQTT.
# --------------------------------------------------------------------
class Servidor:
    def __init__(self):
        self._reservas = {}
        self._lock = threading.Lock()
        self.stats = {
            "reservas_creadas": 0,
            "eventos_recibidos": 0
        }
    def crear_reserva(
        self,
        placa: str
    ) -> str:
        rid = (
            f"RES-"
            f"{random.randint(100000, 999999)}"
        )
        with self._lock:
            self._reservas[rid] = {
                "plate": placa,
                "active": True
            }
            self.stats[
                "reservas_creadas"
            ] += 1
        return rid
    def consultar_reserva(
        self,
        reservation_id: str
    ) -> Optional[dict]:
        with self._lock:
            reserva = self._reservas.get(
                reservation_id
            )
            if reserva is None:
                return None
            return reserva.copy()
    def desactivar_reserva(
        self,
        reservation_id: str
    ) -> None:
        with self._lock:
            if reservation_id in self._reservas:
                self._reservas[
                    reservation_id
                ]["active"] = False

# --------------------------------------------------------------------
# Parqueadero
# --------------------------------------------------------------------
class Parqueadero:
    def __init__(self, n: int):
        self.bahias = [
            Bahia(
                id=f"B-{i + 1:03d}"
            )
            for i in range(n)
        ]
        self._lock = threading.Lock()
    def reservar_bahia_libre(
        self,
        reservation_id: str
    ) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if b.estado == "DISPONIBLE":
                    b.estado = "RESERVADA"
                    b.reservation_id = (
                        reservation_id
                    )
                    return b
        return None
    def ocupar_bahia_reservada(
        self,
        reservation_id: str,
        placa: str
    ) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if (
                    b.estado == "RESERVADA"
                    and
                    b.reservation_id ==
                    reservation_id
                ):
                    b.estado = "OCUPADA"
                    b.placa = placa
                    return b
        return None
    def ocupar_bahia_libre(
        self,
        placa: str
    ) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if b.estado == "DISPONIBLE":
                    b.estado = "OCUPADA"
                    b.placa = placa
                    return b
        return None
    def buscar_por_placa_ocupada(
        self,
        placa: str
    ) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if (
                    b.estado == "OCUPADA"
                    and
                    b.placa == placa
                ):
                    return b
        return None
    def hay_bahia_disponible(self) -> bool:
        with self._lock:
            return any(
                b.estado == "DISPONIBLE"
                for b in self.bahias
            )
    def liberar_bahia(
        self,
        bahia: Bahia
    ) -> None:
        with self._lock:
            bahia.estado = "DISPONIBLE"
            bahia.placa = None
            bahia.reservation_id = None
    def snapshot(self):
        with self._lock:
            return [
                (b.id, b.estado)
                for b in self.bahias
            ]
# --------------------------------------------------------------------
# Terminal de acceso
# --------------------------------------------------------------------
class TerminalAcceso:
    def __init__(
        self,
        parqueadero: Parqueadero,
        servidor: Servidor,
        velocidad: float,
        stats: dict,
        stats_lock: threading.Lock
    ):
        self._lock = threading.Lock()
        self.parqueadero = parqueadero
        self.servidor = servidor
        self.velocidad = velocidad
        self.stats = stats
        self.stats_lock = stats_lock
    def _espera(
        self,
        minimo,
        maximo
    ):
        time.sleep(
            random.uniform(
                minimo,
                maximo
            ) * self.velocidad
        )
    def procesar_vehiculo(
        self,
        vehiculo: Vehiculo
    ) -> Optional[Bahia]:
        # Único gate/keypad físico:
        # procesa un vehículo a la vez.
        with self._lock:
            log(
                f"{Color.CYAN}"
                f"[GATE] {vehiculo.placa} "
                f"llega a la terminal..."
                f"{Color.RESET}"
            )
            self._espera(
                0.2,
                0.5
            )
            if vehiculo.reservation_id:
                return self._procesar_reserva(
                    vehiculo
                )
            bahia_actual = (
                self.parqueadero
                .buscar_por_placa_ocupada(
                    vehiculo.placa
                )
            )
            if bahia_actual:
                return self._procesar_salida(
                    vehiculo,
                    bahia_actual
                )
            return self._procesar_placa_entrada(
                vehiculo
            )

    # ----------------------------------------------------------------
    # Modo reserva
    # ----------------------------------------------------------------
    def _procesar_reserva(
        self,
        vehiculo: Vehiculo
    ) -> Optional[Bahia]:
        log(
            f"{Color.GRAY}"
            f"[GATE] Consultando reserva "
            f"{vehiculo.reservation_id} "
            f"en el servidor..."
            f"{Color.RESET}"
        )
        self._espera(
            0.15,
            0.3
        )
        reserva = (
            self.servidor
            .consultar_reserva(
                vehiculo.reservation_id
            )
        )
        if reserva and reserva["active"]:
            log(
                f"{Color.GREEN}"
                f"[GATE] Reserva OK. "
                f"Pase por Sensor1 (entrada)"
                f"{Color.RESET}"
            )
            return self._entrada(
                vehiculo,
                es_reserva=True
            )
        log(
            f"{Color.RED}"
            f"[GATE] Error Reserva: "
            f"inválida/inactiva. "
            f"Vuelve a inicio."
            f"{Color.RESET}"
        )
        return None

    # ----------------------------------------------------------------
    # Modo placa - entrada
    # ----------------------------------------------------------------
    def _procesar_placa_entrada(
        self,
        vehiculo: Vehiculo
    ) -> Optional[Bahia]:
        if not self.parqueadero.hay_bahia_disponible():
            log(
                f"{Color.RED}"
                f"[GATE] Sin Espacio. "
                f"Parqueadero Lleno. "
                f"Acceso denegado a "
                f"{vehiculo.placa}."
                f"{Color.RESET}"
            )
            self._contar(
                "rechazados_sin_espacio"
            )
            return None
        log(
            f"{Color.GREEN}"
            f"[GATE] Placa aceptada. "
            f"Pase por Sensor1 (entrada)"
            f"{Color.RESET}"
        )
        return self._entrada(
            vehiculo,
            es_reserva=False
        )

    # ----------------------------------------------------------------
    # Entrada física
    # ----------------------------------------------------------------
    def _entrada(self,vehiculo: Vehiculo,es_reserva: bool) -> Optional[Bahia]:
        # Simulación del paso por Sensor1.
        self._espera(0.3,0.8)
        # Muy rara vez falla el paso.
        paso_sensor = (random.random() > 0.03)
        if not paso_sensor:
            log(
                f"{Color.RED}"
                f"[GATE] Tiempo agotado. "
                f"Acceso cancelado para "
                f"{vehiculo.placa}."
                f"{Color.RESET}"
            )
            return None

        # ------------------------------------------------------------
        # Evento de acceso
        # ------------------------------------------------------------
        evento = {
            "event": "vehicle_access",
            "node_id": NODE_ID,
            "access_type": "entry",
            "reservation": es_reserva,
            "reservation_id": (
                vehiculo.reservation_id
                if es_reserva
                else None
            ),
            "plate": vehiculo.placa,
            "date": now_iso(),
        }
        print_json_event(
            "EVENTO ACCESO (ENTRADA)",
            evento,
            Color.CYAN
        )
        publicar_mqtt(
            MQTT_TOPIC_ACCESO,
            evento
        )
        self._contar(
            "entradas"
        )

        # ------------------------------------------------------------
        # Ocupar bahía
        # ------------------------------------------------------------
        bahia = None
        if es_reserva:
            bahia = (
                self.parqueadero
                .ocupar_bahia_reservada(
                    vehiculo.reservation_id,
                    vehiculo.placa
                )
            )
        if not bahia:
            bahia = (
                self.parqueadero
                .ocupar_bahia_libre(
                    vehiculo.placa
                )
            )
        if not bahia:
            log(
                f"{Color.RED}"
                f"[PARQUEADERO] Sin bahías "
                f"disponibles para "
                f"{vehiculo.placa}. "
                f"El vehículo se retira "
                f"sin parquear."
                f"{Color.RESET}"
            )
            return None

        # ------------------------------------------------------------
        # Confirmación de ocupación
        # ------------------------------------------------------------
        self._espera(
            0.3,
            0.6
        )
        evento_bahia = {
            "event": "parking_space_status",
            "node_id": NODE_ID,
            "space_id": bahia.id,
            "status": "occupied",
            "plate": vehiculo.placa,
            "reservation_id": (
                vehiculo.reservation_id
                if es_reserva
                else None
            ),
            "date": now_iso(),
        }
        print_json_event(
            f"EVENTO BAHÍA "
            f"{bahia.id} -> OCUPADA",
            evento_bahia,
            Color.RED
        )
        publicar_mqtt(
            MQTT_TOPIC_BAHIA,
            evento_bahia
        )
        if es_reserva:
            self.servidor.desactivar_reserva(
                vehiculo.reservation_id
            )
        log(
            f"{Color.GREEN}"
            f"[GATE] Acceso Exitoso. "
            f"{vehiculo.placa} -> "
            f"{bahia.id}"
            f"{Color.RESET}"
        )
        return bahia
    # ----------------------------------------------------------------
    # Modo placa - salida
    # ----------------------------------------------------------------
    def _procesar_salida(
        self,
        vehiculo: Vehiculo,
        bahia: Bahia
    ) -> Optional[Bahia]:
        log(
            f"{Color.MAGENTA}"
            f"[GATE] Placa reconocida como "
            f"vehículo dentro. "
            f"Pase por Sensor2 (salida)"
            f"{Color.RESET}"
        )
        self._espera(
            0.3,
            0.8
        )

        # ------------------------------------------------------------
        # Evento de salida
        # ------------------------------------------------------------
        evento = {
            "event": "vehicle_access",
            "node_id": NODE_ID,
            "access_type": "exit",
            "reservation": False,
            "reservation_id": None,
            "plate": vehiculo.placa,
            "date": now_iso(),
        }
        print_json_event(
            "EVENTO ACCESO (SALIDA)",
            evento,
            Color.MAGENTA
        )
        publicar_mqtt(
            MQTT_TOPIC_ACCESO,
            evento
        )
        self._contar(
            "salidas"
        )

        # ------------------------------------------------------------
        # Liberar bahía
        # ------------------------------------------------------------
        self.parqueadero.liberar_bahia(
            bahia
        )
        # Simulación de confirmación del sensor
        self._espera(
            0.3,
            0.6
        )
        evento_bahia = {
            "event": "parking_space_status",
            "node_id": NODE_ID,
            "space_id": bahia.id,
            "status": "available",
            "plate": None,
            "reservation_id": None,
            "date": now_iso(),
        }
        print_json_event(
            f"EVENTO BAHÍA "
            f"{bahia.id} -> DISPONIBLE",
            evento_bahia,
            Color.GREEN
        )
        publicar_mqtt(
            MQTT_TOPIC_BAHIA,
            evento_bahia
        )
        log(
            f"{Color.MAGENTA}"
            f"[GATE] {vehiculo.placa} salió. "
            f"¡Buen viaje!"
            f"{Color.RESET}"
        )
        return bahia
    # ----------------------------------------------------------------
    # Estadísticas
    # ----------------------------------------------------------------
    def _contar(
        self,
        clave
    ):
        with self.stats_lock:
            self.stats[clave] = (
                self.stats.get(clave, 0) + 1
            )

# --------------------------------------------------------------------
# Hilo de cada vehículo
# --------------------------------------------------------------------
def hilo_vehiculo(
    terminal: TerminalAcceso,
    servidor: Servidor,
    parqueadero: Parqueadero,
    velocidad: float,
    prob_reserva: float
):
    placa = generar_placa()
    usa_reserva = (
        random.random() < prob_reserva
    )
    reservation_id = None

    # ----------------------------------------------------------------
    # Crear reserva
    # ----------------------------------------------------------------
    if usa_reserva:
        reservation_id = (
            servidor.crear_reserva(
                placa
            )
        )
        bahia_reservada = (
            parqueadero.reservar_bahia_libre(
                reservation_id
            )
        )
        log(
            f"{Color.YELLOW}"
            f"[APP] {placa} generó código "
            f"de reserva {reservation_id}"
            f"{Color.RESET}"
        )
        if bahia_reservada:
            evento_bahia = {
                "event":
                    "parking_space_status",
                "node_id":
                    NODE_ID,
                "space_id":
                    bahia_reservada.id,
                "status":
                    "reserved",
                "plate":
                    None,
                "reservation_id":
                    reservation_id,
                "date":
                    now_iso(),
            }
            print_json_event(
                f"EVENTO BAHÍA "
                f"{bahia_reservada.id} -> RESERVADA",
                evento_bahia,
                Color.YELLOW
            )
            publicar_mqtt(
                MQTT_TOPIC_BAHIA,
                evento_bahia
            )
        # Tiempo entre reservar y llegar.
        time.sleep(
            random.uniform(
                0.5,
                1.5
            ) * velocidad
        )

    # ----------------------------------------------------------------
    # Llegada del vehículo
    # ----------------------------------------------------------------
    vehiculo = Vehiculo(
        placa=placa,
        reservation_id=reservation_id
    )
    bahia = terminal.procesar_vehiculo(
        vehiculo
    )

    # ----------------------------------------------------------------
    # Permanencia y salida
    # ----------------------------------------------------------------
    if bahia:
        tiempo_estadia = (
            random.uniform(
                1.5,
                4.0
            ) * velocidad
        )
        time.sleep(
            tiempo_estadia
        )
        vehiculo_salida = Vehiculo(
            placa=placa,
            reservation_id=None
        )
        terminal.procesar_vehiculo(
            vehiculo_salida
        )

# --------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------
def dashboard(
    parqueadero: Parqueadero,
    stop_event: threading.Event,
    servidor: Servidor,
    stats: dict,
    stats_lock: threading.Lock,
    intervalo: float,
    columnas: int = 6
):
    simbolo = {
        "DISPONIBLE": "🟩",
        "RESERVADA": "🟨",
        "OCUPADA": "🟥"
    }
    color = {
        "DISPONIBLE":
            Color.GREEN,
        "RESERVADA":
            Color.YELLOW,
        "OCUPADA":
            Color.RED
    }
    while not stop_event.wait(
        intervalo
    ):
        estado = (
            parqueadero.snapshot()
        )
        with print_lock:
            print(
                f"\n{Color.BOLD}"
                f"{'=' * 60}"
                f"{Color.RESET}"
            )
            print(
                "             "
                "ESTADO ACTUAL DEL PARQUEADERO"
            )
            print(
                f"{Color.BOLD}"
                f"{'=' * 60}"
                f"{Color.RESET}"
            )
            for i, (
                bid,
                est
            ) in enumerate(
                estado,
                start=1
            ):
                print(
                    f"{color[est]}"
                    f"{bid}:"
                    f"{simbolo[est]}"
                    f"{Color.RESET}",
                    end="   "
                )
                if i % columnas == 0:
                    print()
            if len(estado) % columnas != 0:
                print()
            disponibles = sum(
                1
                for _, e in estado
                if e == "DISPONIBLE"
            )
            reservadas = sum(
                1
                for _, e in estado
                if e == "RESERVADA"
            )
            ocupadas = sum(
                1
                for _, e in estado
                if e == "OCUPADA"
            )
            with stats_lock:
                entradas = stats.get(
                    "entradas",
                    0
                )
                salidas = stats.get(
                    "salidas",
                    0
                )
                rechazados = stats.get(
                    "rechazados_sin_espacio",
                    0
                )
            print(
                f"\n{Color.GREEN}"
                f"Disponibles: {disponibles}"
                f"{Color.RESET}  "
                f"{Color.YELLOW}"
                f"Reservadas: {reservadas}"
                f"{Color.RESET}  "
                f"{Color.RED}"
                f"Ocupadas: {ocupadas}"
                f"{Color.RESET}   "
                f"{Color.GRAY}"
                f"(Entradas: {entradas} | "
                f"Salidas: {salidas} | "
                f"Rechazados sin espacio: "
                f"{rechazados})"
                f"{Color.RESET}"
            )
            print(
                f"{Color.BOLD}"
                f"{'=' * 60}"
                f"{Color.RESET}\n"
            )

# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description=
        "Simulación de parqueadero inteligente "
        "(ESP32 -> N bahías)"
    )
    parser.add_argument(
        "--bahias",
        type=int,
        default=30,
        help=
        "Número de bahías "
        "(default: 30)"
    )
    parser.add_argument(
        "--vehiculos",
        type=int,
        default=40,
        help=
        "Número de vehículos a simular "
        "(default: 40)"
    )
    parser.add_argument(
        "--velocidad",
        type=float,
        default=1.0,
        help=
        "Multiplicador de tiempos: "
        ">1 más lento, <1 más rápido "
        "(default: 1.0)"
    )
    parser.add_argument(
        "--reserva-prob",
        type=float,
        default=0.4,
        help=
        "Probabilidad (0-1) de que un "
        "vehículo llegue con reserva "
        "(default: 0.4)"
    )
    parser.add_argument(
        "--dashboard-cada",
        type=float,
        default=3.0,
        help=
        "Segundos entre refrescos "
        "del tablero "
        "(default: 3.0)"
    )
    parser.add_argument(
        "--semilla",
        type=int,
        default=None,
        help=
        "Semilla aleatoria para "
        "reproducibilidad"
    )
    args = parser.parse_args()

    # ----------------------------------------------------------------
    # Validaciones
    # ----------------------------------------------------------------
    if args.bahias <= 0:
        parser.error(
            "--bahias debe ser mayor que 0"
        )
    if args.vehiculos < 0:
        parser.error(
            "--vehiculos no puede ser negativo"
        )
    if args.velocidad <= 0:
        parser.error(
            "--velocidad debe ser mayor que 0"
        )
    if not 0 <= args.reserva_prob <= 1:
        parser.error(
            "--reserva-prob debe estar "
            "entre 0 y 1"
        )
    if args.dashboard_cada <= 0:
        parser.error(
            "--dashboard-cada debe ser "
            "mayor que 0"
        )
    if args.semilla is not None:
        random.seed(
            args.semilla
        )

    # ----------------------------------------------------------------
    # Crear componentes
    # ----------------------------------------------------------------
    parqueadero = Parqueadero(
        args.bahias
    )
    servidor = Servidor()
    stats = {
        "entradas": 0,
        "salidas": 0,
        "rechazados_sin_espacio": 0
    }
    stats_lock = threading.Lock()
    terminal = TerminalAcceso(
        parqueadero,
        servidor,
        args.velocidad,
        stats,
        stats_lock
    )
    stop_event = threading.Event()

    # ----------------------------------------------------------------
    # Conectar al broker MQTT
    # ----------------------------------------------------------------
    log(
        f"{Color.CYAN}"
        f"[MQTT] Conectando a "
        f"{MQTT_BROKER}:{MQTT_PORT}..."
        f"{Color.RESET}"
    )
    try:
        mqtt_client.connect(
            MQTT_BROKER,
            MQTT_PORT,
            keepalive=60
        )
        mqtt_client.loop_start()
    except Exception as error:
        log(
            f"{Color.RED}"
            f"[MQTT] No se pudo conectar "
            f"al broker: {error}"
            f"{Color.RESET}"
        )
        return

    # ----------------------------------------------------------------
    # Dashboard
    # ----------------------------------------------------------------
    dash_thread = threading.Thread(
        target=dashboard,
        args=(
            parqueadero,
            stop_event,
            servidor,
            stats,
            stats_lock,
            args.dashboard_cada
        ),
        daemon=True
    )
    dash_thread.start()
    # ----------------------------------------------------------------
    # Inicio
    # ----------------------------------------------------------------
    log(
        f"{Color.BOLD}"
        f"=== Simulación de parqueadero: "
        f"{args.bahias} bahías, "
        f"{args.vehiculos} vehículos ==="
        f"{Color.RESET}\n"
    )
    hilos = []
    try:
        # ------------------------------------------------------------
        # Crear vehículos escalonadamente
        # ------------------------------------------------------------
        for _ in range(
            args.vehiculos
        ):
            t = threading.Thread(
                target=hilo_vehiculo,
                args=(
                    terminal,
                    servidor,
                    parqueadero,
                    args.velocidad,
                    args.reserva_prob
                )
            )
            hilos.append(t)
            t.start()
            # Llegada escalonada
            time.sleep(
                random.uniform(
                    0.2,
                    0.6
                ) * args.velocidad
            )
        # ------------------------------------------------------------
        # Esperar a todos los vehículos
        # ------------------------------------------------------------
        for t in hilos:
            t.join()

    except KeyboardInterrupt:
        log(
            f"\n{Color.RED}"
            f"Simulación interrumpida "
            f"por el usuario."
            f"{Color.RESET}"
        )
    finally:
        # ------------------------------------------------------------
        # Detener dashboard
        # ------------------------------------------------------------
        stop_event.set()
        # ------------------------------------------------------------
        # Detener MQTT
        # ------------------------------------------------------------
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        except Exception:
            pass
        time.sleep(0.2)
    # ----------------------------------------------------------------
    # Resultados
    # ----------------------------------------------------------------
    log(
        f"\n{Color.BOLD}"
        f"=== Simulación finalizada ==="
        f"{Color.RESET}"
    )
    log(
        f"Entradas registradas: "
        f"{stats.get('entradas', 0)}"
    )
    log(
        f"Salidas registradas:  "
        f"{stats.get('salidas', 0)}"
    )
    log(
        f"Rechazados "
        f"(sin reserva, parqueadero lleno): "
        f"{stats.get('rechazados_sin_espacio', 0)}"
    )
    log(
        f"Reservas creadas:     "
        f"{servidor.stats['reservas_creadas']}"
    )
    log(
        f"Eventos enviados por MQTT: "
        f"{servidor.stats['eventos_recibidos']}"
    )

# --------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------
if __name__ == "__main__":
    main()