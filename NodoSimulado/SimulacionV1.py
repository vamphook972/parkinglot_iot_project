import os
import sys
import json
import time
import random
import string
import argparse
import threading
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------
# Configuración general
# --------------------------------------------------------------------
NODE_ID = "PARKING-001"

# Habilitar colores ANSI en cmd.exe de Windows 10+
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


def now_iso() -> str:
    """Fecha/hora local en formato ISO8601 con microsegundos, igual que el ESP32."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def print_json_event(titulo: str, data: dict, color: str) -> None:
    with print_lock:
        print(f"\n{color}{Color.BOLD}--- {titulo} ---{Color.RESET}")
        print(json.dumps(data, indent=4, ensure_ascii=False))
        print(f"{color}{'-' * 40}{Color.RESET}")


def generar_placa() -> str:
    letras = "".join(random.choices(string.ascii_uppercase, k=3))
    numeros = "".join(random.choices(string.digits, k=3))
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
    estado: str = "DISPONIBLE"  # DISPONIBLE | RESERVADA | OCUPADA
    placa: Optional[str] = None
    reservation_id: Optional[str] = None


# --------------------------------------------------------------------
# "Servidor" (equivalente a /api/reserva/status y /api/evento)
# --------------------------------------------------------------------
class Servidor:
    def __init__(self):
        self._reservas = {}
        self._lock = threading.Lock()
        self.stats = {"reservas_creadas": 0, "eventos_recibidos": 0}

    def crear_reserva(self, placa: str) -> str:
        rid = f"RES-{random.randint(100000, 999999)}"
        with self._lock:
            self._reservas[rid] = {"plate": placa, "active": True}
            self.stats["reservas_creadas"] += 1
        return rid

    def consultar_reserva(self, reservation_id: str) -> Optional[dict]:
        # equivalente a GET /api/reserva/status
        with self._lock:
            return self._reservas.get(reservation_id)

    def desactivar_reserva(self, reservation_id: str) -> None:
        with self._lock:
            if reservation_id in self._reservas:
                self._reservas[reservation_id]["active"] = False

    def recibir_evento(self, evento: dict) -> None:
        # equivalente a POST /api/evento
        with self._lock:
            self.stats["eventos_recibidos"] += 1


# --------------------------------------------------------------------
# Parqueadero: conjunto de bahías con operaciones atómicas
# --------------------------------------------------------------------
class Parqueadero:
    def __init__(self, n: int):
        self.bahias = [Bahia(id=f"B-{i + 1:03d}") for i in range(n)]
        self._lock = threading.Lock()

    def reservar_bahia_libre(self, reservation_id: str) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if b.estado == "DISPONIBLE":
                    b.estado = "RESERVADA"
                    b.reservation_id = reservation_id
                    return b
        return None

    def ocupar_bahia_reservada(self, reservation_id: str, placa: str) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if b.estado == "RESERVADA" and b.reservation_id == reservation_id:
                    b.estado = "OCUPADA"
                    b.placa = placa
                    return b
        return None

    def ocupar_bahia_libre(self, placa: str) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if b.estado == "DISPONIBLE":
                    b.estado = "OCUPADA"
                    b.placa = placa
                    return b
        return None

    def buscar_por_placa_ocupada(self, placa: str) -> Optional[Bahia]:
        with self._lock:
            for b in self.bahias:
                if b.estado == "OCUPADA" and b.placa == placa:
                    return b
        return None

    def hay_bahia_disponible(self) -> bool:
        """True si existe al menos una bahía en estado DISPONIBLE.
        Las RESERVADA no cuentan como disponibles para un walk-in sin reserva."""
        with self._lock:
            return any(b.estado == "DISPONIBLE" for b in self.bahias)

    def liberar_bahia(self, bahia: Bahia) -> None:
        with self._lock:
            bahia.estado = "DISPONIBLE"
            bahia.placa = None
            bahia.reservation_id = None

    def snapshot(self):
        with self._lock:
            return [(b.id, b.estado) for b in self.bahias]


# --------------------------------------------------------------------
# Terminal de acceso (equivalente al ESP32: keypad + sensores + LCD)
# Solo un vehículo puede usarla a la vez -> igual que el hardware real.
# --------------------------------------------------------------------
class TerminalAcceso:
    def __init__(self, parqueadero: Parqueadero, servidor: Servidor, velocidad: float, stats: dict, stats_lock: threading.Lock):
        self._lock = threading.Lock()
        self.parqueadero = parqueadero
        self.servidor = servidor
        self.velocidad = velocidad  # 1.0 = normal, >1 = más lento, <1 = más rápido
        self.stats = stats
        self.stats_lock = stats_lock

    def _espera(self, minimo, maximo):
        time.sleep(random.uniform(minimo, maximo) * self.velocidad)

    def procesar_vehiculo(self, vehiculo: Vehiculo) -> Optional[Bahia]:
        with self._lock:  # <- único gate/keypad físico, procesa uno a la vez
            log(f"{Color.CYAN}[GATE] {vehiculo.placa} llega a la terminal...{Color.RESET}")
            self._espera(0.2, 0.5)  # tiempo tecleando en el keypad

            if vehiculo.reservation_id:
                bahia_actual = None  # con reserva siempre se trata como entrada
                return self._procesar_reserva(vehiculo)

            bahia_actual = self.parqueadero.buscar_por_placa_ocupada(vehiculo.placa)
            if bahia_actual:
                return self._procesar_salida(vehiculo, bahia_actual)
            return self._procesar_placa_entrada(vehiculo)

    # ---- MODO_RESERVA -------------------------------------------------
    def _procesar_reserva(self, vehiculo: Vehiculo) -> Optional[Bahia]:
        log(f"{Color.GRAY}[GATE] Consultando reserva {vehiculo.reservation_id} en el servidor...{Color.RESET}")
        self._espera(0.15, 0.3)
        reserva = self.servidor.consultar_reserva(vehiculo.reservation_id)

        if reserva and reserva["active"]:
            log(f"{Color.GREEN}[GATE] Reserva OK. Pase por Sensor1 (entrada){Color.RESET}")
            return self._entrada(vehiculo, es_reserva=True)

        log(f"{Color.RED}[GATE] Error Reserva: inválida/inactiva. Vuelve a inicio.{Color.RESET}")
        return None

    # ---- MODO_PLACA (entrada) ------------------------------------------
    def _procesar_placa_entrada(self, vehiculo: Vehiculo) -> Optional[Bahia]:
        # Sin reserva: solo se deja pasar si hay al menos una bahía DISPONIBLE.
        # (Con reserva NO se hace este chequeo: la bahía ya quedó apartada
        # para ese vehículo desde que generó el código de reserva.)
        if not self.parqueadero.hay_bahia_disponible():
            log(f"{Color.RED}[GATE] Sin Espacio. Parqueadero Lleno. "
                f"Acceso denegado a {vehiculo.placa}.{Color.RESET}")
            self._contar("rechazados_sin_espacio")
            return None

        log(f"{Color.GREEN}[GATE] Placa aceptada. Pase por Sensor1 (entrada){Color.RESET}")
        return self._entrada(vehiculo, es_reserva=False)

    # ---- Paso físico por el sensor de entrada + ocupar bahía -----------
    def _entrada(self, vehiculo: Vehiculo, es_reserva: bool) -> Optional[Bahia]:
        self._espera(0.3, 0.8)  # tiempo en pasar por el sensor (timeout real: 15s)
        paso_sensor = random.random() > 0.03  # muy rara vez no pasa (timeout)

        if not paso_sensor:
            log(f"{Color.RED}[GATE] Tiempo agotado. Acceso cancelado para {vehiculo.placa}.{Color.RESET}")
            return None

        evento = {
            "event": "vehicle_access",
            "node_id": NODE_ID,
            "access_type": "entry",
            "reservation": es_reserva,
            "reservation_id": vehiculo.reservation_id if es_reserva else None,
            "plate": vehiculo.placa,
            "date": now_iso(),
        }
        print_json_event("EVENTO ACCESO (ENTRADA)", evento, Color.CYAN)
        self.servidor.recibir_evento(evento)
        self._contar("entradas")

        bahia = None
        if es_reserva:
            bahia = self.parqueadero.ocupar_bahia_reservada(vehiculo.reservation_id, vehiculo.placa)
        if not bahia:
            bahia = self.parqueadero.ocupar_bahia_libre(vehiculo.placa)

        if not bahia:
            log(f"{Color.RED}[PARQUEADERO] Sin bahías disponibles para {vehiculo.placa}. "
                f"El vehículo se retira sin parquear.{Color.RESET}")
            return None

        # Simula el tiempo de confirmación del sensor de bahía (real: 5s)
        self._espera(0.3, 0.6)

        evento_bahia = {
            "event": "parking_space_status",
            "node_id": NODE_ID,
            "space_id": bahia.id,
            "status": "occupied",
            "plate": vehiculo.placa,
            "reservation_id": vehiculo.reservation_id if es_reserva else None,
            "date": now_iso(),
        }
        print_json_event(f"EVENTO BAHÍA {bahia.id} -> OCUPADA", evento_bahia, Color.RED)
        self.servidor.recibir_evento(evento_bahia)

        if es_reserva:
            self.servidor.desactivar_reserva(vehiculo.reservation_id)

        log(f"{Color.GREEN}[GATE] Acceso Exitoso. {vehiculo.placa} -> {bahia.id}{Color.RESET}")
        return bahia

    # ---- MODO_PLACA (salida) -------------------------------------------
    def _procesar_salida(self, vehiculo: Vehiculo, bahia: Bahia) -> Optional[Bahia]:
        log(f"{Color.MAGENTA}[GATE] Placa reconocida como vehículo dentro. "
            f"Pase por Sensor2 (salida){Color.RESET}")
        self._espera(0.3, 0.8)  # tiempo en pasar por el sensor (timeout real: 15s)

        evento = {
            "event": "vehicle_access",
            "node_id": NODE_ID,
            "access_type": "exit",
            "reservation": False,
            "reservation_id": None,
            "plate": vehiculo.placa,
            "date": now_iso(),
        }
        print_json_event("EVENTO ACCESO (SALIDA)", evento, Color.MAGENTA)
        self.servidor.recibir_evento(evento)
        self._contar("salidas")

        self.parqueadero.liberar_bahia(bahia)
        self._espera(0.3, 0.6)  # confirmación del sensor de bahía

        evento_bahia = {
            "event": "parking_space_status",
            "node_id": NODE_ID,
            "space_id": bahia.id,
            "status": "available",
            "plate": None,
            "reservation_id": None,
            "date": now_iso(),
        }
        print_json_event(f"EVENTO BAHÍA {bahia.id} -> DISPONIBLE", evento_bahia, Color.GREEN)
        self.servidor.recibir_evento(evento_bahia)

        log(f"{Color.MAGENTA}[GATE] {vehiculo.placa} salió. ¡Buen viaje!{Color.RESET}")
        return bahia

    def _contar(self, clave):
        with self.stats_lock:
            self.stats[clave] = self.stats.get(clave, 0) + 1


# --------------------------------------------------------------------
# Hilo de cada vehículo (llega, entra/reserva, permanece, sale)
# --------------------------------------------------------------------
def hilo_vehiculo(terminal: TerminalAcceso, servidor: Servidor, parqueadero: Parqueadero,
                   velocidad: float, prob_reserva: float):
    placa = generar_placa()
    usa_reserva = random.random() < prob_reserva
    reservation_id = None

    if usa_reserva:
        reservation_id = servidor.crear_reserva(placa)
        bahia_reservada = parqueadero.reservar_bahia_libre(reservation_id)
        log(f"{Color.YELLOW}[APP] {placa} generó código de reserva {reservation_id}{Color.RESET}")

        if bahia_reservada:
            evento_bahia = {
                "event": "parking_space_status",
                "node_id": NODE_ID,
                "space_id": bahia_reservada.id,
                "status": "reserved",
                "plate": None,
                "reservation_id": reservation_id,
                "date": now_iso(),
            }
            print_json_event(f"EVENTO BAHÍA {bahia_reservada.id} -> RESERVADA", evento_bahia, Color.YELLOW)
            servidor.recibir_evento(evento_bahia)

        time.sleep(random.uniform(0.5, 1.5) * velocidad)  # tiempo entre reservar y llegar

    vehiculo = Vehiculo(placa=placa, reservation_id=reservation_id)
    bahia = terminal.procesar_vehiculo(vehiculo)

    if bahia:
        tiempo_estadia = random.uniform(1.5, 4.0) * velocidad
        time.sleep(tiempo_estadia)

        vehiculo_salida = Vehiculo(placa=placa, reservation_id=None)
        terminal.procesar_vehiculo(vehiculo_salida)


# --------------------------------------------------------------------
# Tablero visual del estado de las bahías
# --------------------------------------------------------------------
def dashboard(parqueadero: Parqueadero, stop_event: threading.Event, servidor: Servidor,
              stats: dict, stats_lock: threading.Lock, intervalo: float, columnas: int = 6):
    simbolo = {"DISPONIBLE": "🟩", "RESERVADA": "🟨", "OCUPADA": "🟥"}
    color = {"DISPONIBLE": Color.GREEN, "RESERVADA": Color.YELLOW, "OCUPADA": Color.RED}

    while not stop_event.wait(intervalo):
        estado = parqueadero.snapshot()
        with print_lock:
            print(f"\n{Color.BOLD}{'=' * 60}")
            print("             ESTADO ACTUAL DEL PARQUEADERO")
            print(f"{'=' * 60}{Color.RESET}")
            for i, (bid, est) in enumerate(estado, start=1):
                print(f"{color[est]}{bid}:{simbolo[est]}{Color.RESET}", end="   ")
                if i % columnas == 0:
                    print()
            if len(estado) % columnas != 0:
                print()

            disponibles = sum(1 for _, e in estado if e == "DISPONIBLE")
            reservadas = sum(1 for _, e in estado if e == "RESERVADA")
            ocupadas = sum(1 for _, e in estado if e == "OCUPADA")
            with stats_lock:
                entradas = stats.get("entradas", 0)
                salidas = stats.get("salidas", 0)
                rechazados = stats.get("rechazados_sin_espacio", 0)

            print(f"\n{Color.GREEN}Disponibles: {disponibles}{Color.RESET}  "
                  f"{Color.YELLOW}Reservadas: {reservadas}{Color.RESET}  "
                  f"{Color.RED}Ocupadas: {ocupadas}{Color.RESET}   "
                  f"{Color.GRAY}(Entradas: {entradas} | Salidas: {salidas} | "
                  f"Rechazados sin espacio: {rechazados}){Color.RESET}")
            print(f"{Color.BOLD}{'=' * 60}{Color.RESET}\n")


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Simulación de parqueadero inteligente (ESP32 -> N bahías)")
    parser.add_argument("--bahias", type=int, default=30, help="Número de bahías (default: 30)")
    parser.add_argument("--vehiculos", type=int, default=40, help="Número de vehículos a simular (default: 40)")
    parser.add_argument("--velocidad", type=float, default=1.0,
                         help="Multiplicador de tiempos: >1 más lento, <1 más rápido (default: 1.0)")
    parser.add_argument("--reserva-prob", type=float, default=0.4,
                         help="Probabilidad (0-1) de que un vehículo llegue con reserva (default: 0.4)")
    parser.add_argument("--dashboard-cada", type=float, default=3.0,
                         help="Segundos entre refrescos del tablero (default: 3.0)")
    parser.add_argument("--semilla", type=int, default=None, help="Semilla aleatoria para reproducibilidad")
    args = parser.parse_args()

    if args.semilla is not None:
        random.seed(args.semilla)

    parqueadero = Parqueadero(args.bahias)
    servidor = Servidor()
    stats = {"entradas": 0, "salidas": 0, "rechazados_sin_espacio": 0}
    stats_lock = threading.Lock()
    terminal = TerminalAcceso(parqueadero, servidor, args.velocidad, stats, stats_lock)

    stop_event = threading.Event()
    dash_thread = threading.Thread(
        target=dashboard,
        args=(parqueadero, stop_event, servidor, stats, stats_lock, args.dashboard_cada),
        daemon=True,
    )
    dash_thread.start()

    log(f"{Color.BOLD}=== Simulación de parqueadero: {args.bahias} bahías, "
        f"{args.vehiculos} vehículos ==={Color.RESET}\n")

    hilos = []
    try:
        for _ in range(args.vehiculos):
            t = threading.Thread(
                target=hilo_vehiculo,
                args=(terminal, servidor, parqueadero, args.velocidad, args.reserva_prob),
            )
            hilos.append(t)
            t.start()
            time.sleep(random.uniform(0.2, 0.6) * args.velocidad)  # llegada escalonada

        for t in hilos:
            t.join()
    except KeyboardInterrupt:
        log(f"\n{Color.RED}Simulación interrumpida por el usuario.{Color.RESET}")

    stop_event.set()
    time.sleep(0.2)

    log(f"\n{Color.BOLD}=== Simulación finalizada ==={Color.RESET}")
    log(f"Entradas registradas: {stats.get('entradas', 0)}")
    log(f"Salidas registradas:  {stats.get('salidas', 0)}")
    log(f"Rechazados (sin reserva, parqueadero lleno): {stats.get('rechazados_sin_espacio', 0)}")
    log(f"Reservas creadas:     {servidor.stats['reservas_creadas']}")
    log(f"Eventos enviados al servidor: {servidor.stats['eventos_recibidos']}")


if __name__ == "__main__":
    main()