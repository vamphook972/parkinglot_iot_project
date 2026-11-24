#!/usr/bin/env python3
"""
Nodo simulado del Parking IoT.

Se comporta como el ESP32 (entrada + salida, un solo nodo lógico):
  - Se conecta al broker y se suscribe a acceso/cmd y bahia/reserva ANTES de publicar.
  - Publica registro y luego un bahia/sensor por cada bahía (re-sincronización).
  - Envía acceso/input (placa, QR o salida) y espera la respuesta en acceso/cmd.
  - Solo "abre el servo" si allowed es true.
  - Enciende/apaga el LED amarillo según bahia/reserva.
  - Publica bahia/sensor cada vez que cambia la ocupación de una bahía.

No agrega fechas: la hora la asigna Node-RED o la base de datos.

Requisitos:  pip install "paho-mqtt>=2.0"
Uso:         python nodo_simulado.py --node-id PARKING-002 --bays B-001,B-002,B-003
"""

import argparse
import json
import random
import string
import threading

import paho.mqtt.client as mqtt

QOS = 1

REASONS = {
    "OK": "Acceso aprobado",
    "NO_BAYS": "No hay bahías libres sin reserva",
    "ACTIVE_SESSION": "El vehículo ya tiene una sesión activa",
    "NO_SESSION": "La placa no tiene una sesión activa",
    "INVALID_RESERVATION": "La reserva no existe o es de otro nodo",
    "OUT_OF_WINDOW": "La reserva está fuera de su franja horaria",
    "BAD_REQUEST": "No se registro los datos correctamente",
}

TIPOS = {"entry": "ENTRADA", "exit": "SALIDA"}


def log(msg):
    print(f"\n{msg}", flush=True)


class NodoSimulado:
    def __init__(self, node_id, bays, ocupadas, broker, port, barrier_seconds, timeout):
        self.node_id = node_id
        self.base = f"parqueadero/{node_id}/"
        self.broker = broker
        self.port = port
        self.barrier_seconds = barrier_seconds
        self.timeout = timeout

        self.lock = threading.RLock()
        # Estado de cada bahía: lo que leen los sensores y lo que dice Node-RED.
        self.bays = {
            b: {"sensor_status": b in ocupadas, "reserved": False} for b in bays
        }
        # Una barrera por tipo de acceso (entrada y salida pueden operar a la vez).
        self.pending = {"entry": None, "exit": None}  # solicitud esperando respuesta
        self.barrier_open = {"entry": False, "exit": False}

        self.sub_mid = None
        self.synced = False

        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{node_id}-{suffix}"
        )
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    # ------------------------------------------------------------------ MQTT

    def topic(self, name):
        return self.base + name

    def publicar(self, name, payload):
        data = json.dumps(payload, ensure_ascii=False)
        self.client.publish(self.topic(name), data, qos=QOS)
        print(f"  → {name}: {data}", flush=True)

    def conectar(self):
        log(f"Conectando a {self.broker}:{self.port} como {self.node_id}...")
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_start()

    def desconectar(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log(f"[MQTT] Conexión rechazada: {reason_code}")
            return
        log("[MQTT] Conectado. Suscribiendo a acceso/cmd y bahia/reserva...")
        with self.lock:
            self.synced = False
            # Al (re)conectar el nodo arranca con todos los amarillos apagados;
            # Node-RED vuelve a enviar los reserved:true vigentes tras el registro.
            for estado in self.bays.values():
                estado["reserved"] = False
        _, self.sub_mid = client.subscribe(
            [(self.topic("acceso/cmd"), QOS), (self.topic("bahia/reserva"), QOS)]
        )

    def _on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        if mid != self.sub_mid:
            return
        fallas = [rc for rc in reason_code_list if rc.is_failure]
        if fallas:
            log(f"[MQTT] Falló la suscripción: {fallas}. No se publica el registro.")
            return
        log("[MQTT] Suscrito. Iniciando sesión del nodo:")
        self._sincronizar()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.synced = False
        log(f"[MQTT] Desconectado ({reason_code}). Reintentando...")

    def _sincronizar(self):
        """Pasos 2 y 4 del inicio de sesión: registro + lectura actual de cada bahía."""
        with self.lock:
            self.publicar(
                "registro", {"node_id": self.node_id, "bays": list(self.bays)}
            )
            for bay, estado in self.bays.items():
                self.publicar(
                    "bahia/sensor",
                    {
                        "node_id": self.node_id,
                        "space_id": bay,
                        "sensor_status": estado["sensor_status"],
                    },
                )
            self.synced = True
        log("Sincronizado. Esperando reservas vigentes de Node-RED.")
        self.mostrar_estado()

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log(f"[MQTT] Mensaje no válido en {msg.topic}: {msg.payload!r}")
            return
        if data.get("node_id") != self.node_id:
            log(
                f"[MQTT] Ignorado: node_id {data.get('node_id')!r} no es {self.node_id}"
            )
            return

        name = msg.topic[len(self.base) :]
        print(f"\n  ← {name}: {json.dumps(data, ensure_ascii=False)}", flush=True)
        if name == "acceso/cmd":
            self._on_cmd(data)
        elif name == "bahia/reserva":
            self._on_reserva(data)

    # -------------------------------------------------------------- Reservas

    def _on_reserva(self, data):
        bay = data.get("space_id")
        reserved = data.get("reserved")
        if not isinstance(reserved, bool):
            log("[RESERVA] Campo 'reserved' inválido, ignorado.")
            return
        with self.lock:
            if bay not in self.bays:
                log(f"[RESERVA] La bahía {bay} no existe en este nodo, ignorada.")
                return
            self.bays[bay]["reserved"] = reserved
        log(f"[LED] {bay}: amarillo {'ENCENDIDO' if reserved else 'APAGADO'}")
        self.mostrar_estado()

    # -------------------------------------------------------------- Accesos

    def solicitar_acceso(self, access_type, plate=None, reservation_id=None):
        tipo = TIPOS[access_type]
        with self.lock:
            if not self.synced:
                log("El nodo no está sincronizado con Node-RED todavía.")
                return
            if self.barrier_open[access_type]:
                log(f"La barrera de {tipo} sigue abierta, espera a que baje.")
                return
            if self.pending[access_type]:
                log(f"Ya hay una solicitud de {tipo} esperando respuesta.")
                return

            log(f"[INFRARROJO {tipo}] Vehículo detectado.")
            payload = {
                "node_id": self.node_id,
                "access_type": access_type,
                "reservation_id": reservation_id,
                "plate": plate,
            }
            timer = threading.Timer(self.timeout, self._timeout, args=(access_type,))
            timer.daemon = True
            self.pending[access_type] = {"payload": payload, "timer": timer}
            self.publicar("acceso/input", payload)
            timer.start()
        print(f"  Esperando respuesta de Node-RED para {tipo}...", flush=True)

    def _timeout(self, access_type):
        with self.lock:
            if self.pending[access_type] is None:
                return
            self.pending[access_type] = None
        log(
            f"[{TIPOS[access_type]}] Sin respuesta de Node-RED en {self.timeout}s. "
            "La barrera no se mueve."
        )

    def _on_cmd(self, data):
        access_type = data.get("access_type")
        if access_type not in TIPOS:
            log(f"[CMD] access_type inválido: {access_type!r}")
            return
        tipo = TIPOS[access_type]
        with self.lock:
            pend = self.pending[access_type]
            if pend is None:
                log(
                    f"[CMD] Respuesta de {tipo} sin solicitud pendiente (¿llegó tarde?). "
                    "Ignorada."
                )
                return
            pend["timer"].cancel()
            self.pending[access_type] = None

            reason = data.get("reason")
            descripcion = REASONS.get(reason, "reason desconocido")
            if data.get("allowed") is True:
                self.barrier_open[access_type] = True
                log(f"[SERVO {tipo}] Barrera ABIERTA ({reason}: {descripcion})")
                t = threading.Timer(
                    self.barrier_seconds, self._bajar_barrera, args=(access_type,)
                )
                t.daemon = True
                t.start()
            else:
                log(
                    f"[{tipo}] DENEGADO → {reason}: {descripcion}. La barrera no se mueve."
                )

    def _bajar_barrera(self, access_type):
        with self.lock:
            self.barrier_open[access_type] = False
        log(f"[SERVO {TIPOS[access_type]}] Barrera CERRADA")

    # -------------------------------------------------------------- Bahías

    def set_sensor(self, bay, value):
        with self.lock:
            if bay not in self.bays:
                log(f"La bahía {bay} no existe. Bahías: {', '.join(self.bays)}")
                return
            if self.bays[bay]["sensor_status"] == value:
                log(
                    f"{bay} ya está {'ocupada' if value else 'libre'}, no se publica nada."
                )
                return
            self.bays[bay]["sensor_status"] = value
            log(f"[SENSOR] {bay}: {'vehículo detectado' if value else 'sin vehículo'}")
            if self.synced:
                self.publicar(
                    "bahia/sensor",
                    {
                        "node_id": self.node_id,
                        "space_id": bay,
                        "sensor_status": value,
                    },
                )
            else:
                print("  (sin conexión: se enviará al re-sincronizar)", flush=True)
        self.mostrar_estado()

    def mostrar_estado(self):
        with self.lock:
            print("\n  Bahía    Ocupación    Reserva", flush=True)
            for bay, e in self.bays.items():
                ocup = "🔴 ocupada" if e["sensor_status"] else "🟢 libre  "
                res = "🟡 reservada" if e["reserved"] else "⚫ —"
                print(f"  {bay:<8} {ocup}   {res}", flush=True)
            for at, tipo in TIPOS.items():
                barrera = "abierta" if self.barrier_open[at] else "cerrada"
                espera = " (esperando respuesta)" if self.pending[at] else ""
                print(f"  Barrera {tipo.lower()}: {barrera}{espera}", flush=True)

    def reiniciar(self):
        """Simula un reinicio del ESP32: se desconecta y vuelve a hacer todo el inicio de sesión."""
        log("Reiniciando nodo...")
        self.client.disconnect()
        self.client.reconnect()


AYUDA = """
Comandos:
  e <PLACA>        Entrada por placa (teclado)         ej: e BTQ636
  q <RESERVA>      Entrada por QR (lector GM65)        ej: q RSV-8F3K2
  s <PLACA>        Salida por placa                    ej: s BTQ636
  o <BAHIA>        Sensor de bahía: llega un carro     ej: o B-001
  l <BAHIA>        Sensor de bahía: sale el carro      ej: l B-001
  estado           Ver LEDs y barreras
  reiniciar        Simular reinicio del nodo (re-sincroniza)
  ayuda            Mostrar esta ayuda
  salir            Terminar
"""


def limpiar_placa(texto):
    placa = texto.strip().upper().replace("-", "").replace(" ", "")
    if not placa.isalnum() or not 5 <= len(placa) <= 7:
        return None
    return placa


def main():
    parser = argparse.ArgumentParser(description="Nodo simulado del Parking IoT")
    parser.add_argument("--node-id", default="PARKING-003")
    parser.add_argument(
        "--bays", default="B-001,B-002,B-003,B-004", help="Bahías separadas por coma"
    )
    parser.add_argument(
        "--ocupadas",
        default="",
        help="Bahías que arrancan ocupadas, separadas por coma",
    )
    parser.add_argument("--broker", default="test.mosquitto.org")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument(
        "--barrera", type=float, default=5, help="Segundos que la barrera queda abierta"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10,
        help="Segundos máximos esperando respuesta de Node-RED",
    )
    args = parser.parse_args()

    bays = [b.strip() for b in args.bays.split(",") if b.strip()]
    ocupadas = {b.strip() for b in args.ocupadas.split(",") if b.strip()}

    nodo = NodoSimulado(
        args.node_id, bays, ocupadas, args.broker, args.port, args.barrera, args.timeout
    )
    nodo.conectar()
    print(AYUDA, flush=True)

    try:
        while True:
            linea = input("> ").strip()
            if not linea:
                continue
            cmd, _, arg = linea.partition(" ")
            cmd, arg = cmd.lower(), arg.strip()

            if cmd in ("e", "s"):
                placa = limpiar_placa(arg)
                if not placa:
                    print("Placa inválida (5 a 7 caracteres alfanuméricos).")
                    continue
                nodo.solicitar_acceso("entry" if cmd == "e" else "exit", plate=placa)
            elif cmd == "q":
                if not arg:
                    print("Falta el código de la reserva leído del QR.")
                    continue
                nodo.solicitar_acceso("entry", reservation_id=arg.upper())
            elif cmd in ("o", "l"):
                nodo.set_sensor(arg.upper(), cmd == "o")
            elif cmd == "estado":
                nodo.mostrar_estado()
            elif cmd == "reiniciar":
                nodo.reiniciar()
            elif cmd == "ayuda":
                print(AYUDA)
            elif cmd == "salir":
                break
            else:
                print("Comando no reconocido. Escribe 'ayuda'.")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        nodo.desconectar()
        print("\nNodo detenido.")


if __name__ == "__main__":
    main()
