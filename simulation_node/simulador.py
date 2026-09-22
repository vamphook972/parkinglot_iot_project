from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
import json
import random
import string
import time

import paho.mqtt.client as mqtt


# ============================================================
# ENUMS
# ============================================================


class ParkingSpaceStatus(Enum):
    FREE = "free"
    RESERVED = "reserved"
    OCCUPIED = "occupied"


class AccessType(Enum):
    ENTRY = "entry"
    EXIT = "exit"


# ============================================================
# PARKING SPACE
# ============================================================


@dataclass
class ParkingSpace:
    space_id: str
    status: ParkingSpaceStatus = ParkingSpaceStatus.FREE
    plate: str | None = None
    reservation_id: str | None = None

    def reserve(self, reservation_id: str):
        if self.status != ParkingSpaceStatus.FREE:
            return False

        self.status = ParkingSpaceStatus.RESERVED
        self.reservation_id = reservation_id

        return True

    def occupy(self, plate: str):
        if self.status not in [
            ParkingSpaceStatus.FREE,
            ParkingSpaceStatus.RESERVED
        ]:
            return False

        self.status = ParkingSpaceStatus.OCCUPIED
        self.plate = plate

        return True

    def free(self):
        self.status = ParkingSpaceStatus.FREE
        self.plate = None
        self.reservation_id = None


# ============================================================
# RESERVATION
# ============================================================


@dataclass
class Reservation:
    reservation_id: str
    plate: str
    space_id: str
    active: bool = True


# ============================================================
# PARKING LOT
# ============================================================


class ParkingLot:

    def __init__(self, number_of_spaces: int = 10):

        self.spaces = {
            f"B-{i:03d}": ParkingSpace(f"B-{i:03d}")
            for i in range(1, number_of_spaces + 1)
        }

        self.reservations = {}

        # historial de eventos generados durante la sesión
        self.event_log = []

    # --------------------------------------------------------
    # RESERVATION
    # --------------------------------------------------------

    def create_reservation(self, plate: str):

        available_spaces = [
            space
            for space in self.spaces.values()
            if space.status == ParkingSpaceStatus.FREE
        ]

        if not available_spaces:
            return None

        space = random.choice(available_spaces)

        reservation_id = self.generate_reservation_id()

        space.reserve(reservation_id)

        reservation = Reservation(
            reservation_id=reservation_id,
            plate=plate,
            space_id=space.space_id
        )

        self.reservations[reservation_id] = reservation

        return reservation

    # --------------------------------------------------------
    # RESERVATION EVENT
    # --------------------------------------------------------

    def create_reservation_event(self, reservation: Reservation):

        event = {
            "event": "parking_reservation",
            "node_id": "PARKING-005",
            "reservation_id": reservation.reservation_id,
            "plate": reservation.plate,
            "space_id": reservation.space_id,
            "active": reservation.active,
            "date": datetime.now().astimezone().isoformat(),
        }

        self.event_log.append(event)

        return event

    # --------------------------------------------------------
    # ENTRY
    # --------------------------------------------------------

    def vehicle_entry(
        self,
        plate: str,
        reservation_id: str | None = None
    ):

        reservation = None

        # -----------------------------------------------
        # Vehicle already inside?
        # -----------------------------------------------

        already_inside = any(
            space.status == ParkingSpaceStatus.OCCUPIED
            and space.plate == plate
            for space in self.spaces.values()
        )

        if already_inside:
            print("Ese vehículo ya se encuentra dentro del parqueadero!")
            return None

        # -----------------------------------------------
        # Vehicle WITH reservation
        # -----------------------------------------------

        if reservation_id:

            reservation = self.reservations.get(reservation_id)

            if reservation is None:
                print("Reservation not found!")
                return None

            if not reservation.active:
                print("Reservation is no longer active!")
                return None

            if reservation.plate != plate:
                print("Plate does not match reservation!")
                return None

            space = self.spaces[reservation.space_id]

        # -----------------------------------------------
        # Vehicle WITHOUT reservation
        # -----------------------------------------------

        else:

            available_spaces = [
                space
                for space in self.spaces.values()
                if space.status == ParkingSpaceStatus.FREE
            ]

            if not available_spaces:
                print("Parking lot is full!")
                return None

            space = random.choice(available_spaces)

        # -----------------------------------------------
        # Occupy space
        # -----------------------------------------------

        if not space.occupy(plate):
            print("Could not occupy parking space!")
            return None

        if reservation:
            reservation.active = False

        event = self.create_access_event(
            access_type=AccessType.ENTRY,
            plate=plate,
            reservation=reservation
        )

        self.event_log.append(event)

        return event

    # --------------------------------------------------------
    # EXIT
    # --------------------------------------------------------

    def vehicle_exit(self, plate: str):

        occupied_spaces = [
            space
            for space in self.spaces.values()
            if (
                space.status == ParkingSpaceStatus.OCCUPIED
                and space.plate == plate
            )
        ]

        if not occupied_spaces:
            print("Vehicle not found inside parking lot!")
            return None

        space = occupied_spaces[0]

        space.free()

        event = self.create_access_event(
            access_type=AccessType.EXIT,
            plate=plate,
            reservation=None
        )

        self.event_log.append(event)

        return event

    # --------------------------------------------------------
    # ACCESS EVENT
    # --------------------------------------------------------

    def create_access_event(
        self,
        access_type: AccessType,
        plate: str,
        reservation: Reservation | None
    ):

        event = {
            "event": "vehicle_access",
            "node_id": "PARKING-005",
            "access_type": access_type.value,
            "reservation": reservation is not None,
            "reservation_id": (
                reservation.reservation_id
                if reservation
                else None
            ),
            "plate": plate,
            "date": datetime.now().astimezone().isoformat(),
        }

        return event

    # --------------------------------------------------------
    # RESERVATION ID
    # --------------------------------------------------------

    @staticmethod
    def generate_reservation_id():

        random_number = "".join(
            random.choices(string.digits, k=6)
        )

        return f"{random_number}"

    # --------------------------------------------------------
    # RANDOM PLATE
    # --------------------------------------------------------

    @staticmethod
    def generate_random_plate():

        letters = "".join(
            random.choices(string.ascii_uppercase, k=3)
        )

        numbers = "".join(
            random.choices(string.digits, k=3)
        )

        return f"{letters}{numbers}"

    # --------------------------------------------------------
    # PARKING STATUS
    # --------------------------------------------------------

    def get_status_events(self):

        events = []

        for space in self.spaces.values():

            event = {
                "event": "parking_space_status",
                "node_id": f"SENSOR-{space.space_id}",
                "space_id": space.space_id,
                "status": space.status.value,
                "plate": space.plate,
                "reservation_id": space.reservation_id,
                "date": datetime.now().astimezone().isoformat(),
            }

            events.append(event)

        return events

    # --------------------------------------------------------
    # OCCUPIED PLATES
    # --------------------------------------------------------

    def get_occupied_plates(self):

        return [
            space.plate
            for space in self.spaces.values()
            if space.status == ParkingSpaceStatus.OCCUPIED
        ]

    # --------------------------------------------------------
    # ACTIVE RESERVATIONS
    # --------------------------------------------------------

    def get_active_reservations(self):

        return [
            r
            for r in self.reservations.values()
            if r.active
        ]

    # --------------------------------------------------------
    # DISPLAY
    # --------------------------------------------------------

    def display_status(self):

        print("\n" + "=" * 55)
        print("                 ESTADO DEL PARQUEADERO")
        print("=" * 55)

        free = reserved = occupied = 0

        for space in self.spaces.values():

            if space.status == ParkingSpaceStatus.FREE:
                free += 1

            elif space.status == ParkingSpaceStatus.RESERVED:
                reserved += 1

            else:
                occupied += 1

            extra = space.plate or space.reservation_id or "-"

            print(
                f"{space.space_id} → "
                f"{space.status.value.upper():<9} "
                f"{extra}"
            )

        print("-" * 55)

        print(
            f"Libres: {free}   "
            f"Reservados: {reserved}   "
            f"Ocupados: {occupied}"
        )

        print("=" * 55)


# ============================================================
# INTERFAZ DE TERMINAL
# ============================================================


class ParkingCLI:

    MQTT_HOST = "10.71.155.38"
    MQTT_PORT = 1883

    MQTT_CLIENT_ID = "Parking-005"

    # --------------------------------------------------------
    # MQTT TOPICS
    # --------------------------------------------------------

    MQTT_TOPIC_BAHIA = "parqueadero/PARKING-005/bahia"
    MQTT_TOPIC_ACCESO = "parqueadero/PARKING-005/acceso"
    MQTT_TOPIC_RESERVA = "parqueadero/PARKING-005/reserva"

    # --------------------------------------------------------

    def __init__(self, parking: ParkingLot):

        self.parking = parking

        self.mqtt_client = mqtt.Client(
            client_id=self.MQTT_CLIENT_ID
        )

        try:

            self.mqtt_client.connect(
                self.MQTT_HOST,
                self.MQTT_PORT,
                60
            )

            self.mqtt_client.loop_start()

            print(
                f"MQTT conectado a "
                f"{self.MQTT_HOST}:{self.MQTT_PORT}"
            )

            print(
                "Tópicos MQTT:"
            )

            print(
                f"  Bahía   → {self.MQTT_TOPIC_BAHIA}"
            )

            print(
                f"  Acceso  → {self.MQTT_TOPIC_ACCESO}"
            )

            print(
                f"  Reserva → {self.MQTT_TOPIC_RESERVA}"
            )

        except Exception as e:

            print(
                f"No se pudo conectar al broker MQTT: {e}"
            )

            self.mqtt_client = None

    # --------------------------------------------------------
    # PUBLISH JSON
    # --------------------------------------------------------

    def publish_json(self, event):

        """
        Publica un evento JSON en el tópico MQTT
        correspondiente según el tipo de evento.
        """

        if self.mqtt_client is None:
            return

        payload = json.dumps(
            event,
            ensure_ascii=False
        )

        event_type = event.get("event")

        # -----------------------------------------------
        # Seleccionar tópico
        # -----------------------------------------------

        if event_type == "parking_space_status":

            topic = self.MQTT_TOPIC_BAHIA

        elif event_type == "vehicle_access":

            topic = self.MQTT_TOPIC_ACCESO

        elif event_type == "parking_reservation":

            topic = self.MQTT_TOPIC_RESERVA

        else:

            print(
                f"Tipo de evento MQTT desconocido: "
                f"{event_type}"
            )

            return

        # -----------------------------------------------
        # Publicar
        # -----------------------------------------------

        result = self.mqtt_client.publish(
            topic,
            payload
        )

        if result.rc != mqtt.MQTT_ERR_SUCCESS:

            print(
                f"Error publicando MQTT en {topic}: "
                f"{mqtt.error_string(result.rc)}"
            )

        else:

            print(
                f"MQTT → {topic}"
            )

    # --------------------------------------------------------
    # CLOSE MQTT
    # --------------------------------------------------------

    def close_mqtt(self):

        if self.mqtt_client is not None:

            self.mqtt_client.loop_stop()

            self.mqtt_client.disconnect()

    # ========================================================
    # MENU PRINCIPAL
    # ========================================================

    def run(self):

        self.print_header()

        while True:

            self.print_menu()

            choice = input(
                "\n Elige una opción: "
            ).strip()

            # -------------------------------------------
            # VER ESTADO
            # -------------------------------------------

            if choice == "1":

                self.parking.display_status()

            # -------------------------------------------
            # CREAR RESERVA
            # -------------------------------------------

            elif choice == "2":

                self.action_create_reservation()

            # -------------------------------------------
            # ENTRADA
            # -------------------------------------------

            elif choice == "3":

                self.action_vehicle_entry()

            # -------------------------------------------
            # SALIDA
            # -------------------------------------------

            elif choice == "4":

                self.action_vehicle_exit()

            # -------------------------------------------
            # EVENTOS DE SENSORES
            # -------------------------------------------

            elif choice == "5":

                self.action_show_sensor_events()

            # -------------------------------------------
            # RESERVAS
            # -------------------------------------------

            elif choice == "6":

                self.action_show_reservations()

            # -------------------------------------------
            # SIMULACIÓN
            # -------------------------------------------

            elif choice == "7":

                self.action_auto_simulation()

            # -------------------------------------------
            # SALIR
            # -------------------------------------------

            elif choice == "0":

                self.close_mqtt()

                print(
                    "\nCerrando simulador. "
                    "¡Hasta luego!\n"
                )

                break

            else:

                print(
                    "Opción no válida, intenta de nuevo."
                )

            input(
                "\n(Enter para continuar...)"
            )

    # ========================================================
    # HEADER / MENU
    # ========================================================

    def print_header(self):

        print("=" * 55)

        print(
            "           SIMULADOR IoT DE PARQUEADERO"
        )

        print("=" * 55)

    def print_menu(self):

        print(
            "\n" + "-" * 55
        )

        print(
            "1. Ver estado del parqueadero"
        )

        print(
            "2. Crear reserva"
        )

        print(
            "3. Registrar entrada de vehículo"
        )

        print(
            "4. Registrar salida de vehículo"
        )

        print(
            "5. Ver eventos de sensores (JSON)"
        )

        print(
            "6. Ver reservas activas"
        )

        print(
            "7. Simulación automática"
        )

        print(
            "0. Salir"
        )

        print(
            "-" * 55
        )

    # ========================================================
    # ACCIONES
    # ========================================================

    def action_create_reservation(self):

        plate = input(
            "Placa del vehículo a reservar: "
        ).strip().upper()

        if not plate:

            print(
                "Debes ingresar una placa."
            )

            return

        reservation = self.parking.create_reservation(
            plate
        )

        if reservation is None:

            print(
                "No hay espacios disponibles para reservar."
            )

            return

        # -----------------------------------------------
        # Crear JSON de reserva
        # -----------------------------------------------

        event = self.parking.create_reservation_event(
            reservation
        )

        # -----------------------------------------------
        # Publicar en /reserva
        # -----------------------------------------------

        self.publish_json(event)

        # -----------------------------------------------
        # Mostrar
        # -----------------------------------------------

        print(
            f"Reserva creada: "
            f"{reservation.reservation_id} "
            f"→ {reservation.plate} "
            f"→ {reservation.space_id}"
        )

        print(
            json.dumps(
                event,
                indent=4,
                ensure_ascii=False
            )
        )

    # --------------------------------------------------------
    # VEHICLE ENTRY
    # --------------------------------------------------------

    def action_vehicle_entry(self):

        plate = input(
            "Placa del vehículo que ingresa: "
        ).strip().upper()

        if not plate:

            print(
                "Debes ingresar una placa."
            )

            return

        has_reservation = input(
            "¿Tiene reserva? (s/n): "
        ).strip().lower()

        reservation_id = None

        if has_reservation == "s":

            reservation_id = input(
                "ID de la reserva (RES-XXXXXX): "
            ).strip().upper()

        event = self.parking.vehicle_entry(
            plate=plate,
            reservation_id=reservation_id or None
        )

        if event:

            self.publish_json(event)

            print(
                "Entrada registrada:"
            )

            print(
                json.dumps(
                    event,
                    indent=4,
                    ensure_ascii=False
                )
            )

    # --------------------------------------------------------
    # VEHICLE EXIT
    # --------------------------------------------------------

    def action_vehicle_exit(self):

        occupied = self.parking.get_occupied_plates()

        if not occupied:

            print(
                "No hay vehículos dentro del parqueadero."
            )

            return

        print(
            f"Vehículos dentro: "
            f"{', '.join(occupied)}"
        )

        plate = input(
            "Placa del vehículo que sale: "
        ).strip().upper()

        event = self.parking.vehicle_exit(
            plate
        )

        if event:

            self.publish_json(event)

            print(
                "Salida registrada:"
            )

            print(
                json.dumps(
                    event,
                    indent=4,
                    ensure_ascii=False
                )
            )

    # --------------------------------------------------------
    # SENSOR EVENTS / BAHIAS
    # --------------------------------------------------------

    def action_show_sensor_events(self):

        events = self.parking.get_status_events()

        print(
            "\nEventos de sensores:"
        )

        for event in events:

            self.publish_json(event)

            print(
                json.dumps(
                    event,
                    indent=4,
                    ensure_ascii=False
                )
            )

    # --------------------------------------------------------
    # ACTIVE RESERVATIONS
    # --------------------------------------------------------

    def action_show_reservations(self):

        active = self.parking.get_active_reservations()

        if not active:

            print(
                "No hay reservas activas."
            )

            return

        print(
            "\n Reservas activas:"
        )

        for r in active:

            print(
                f"{r.reservation_id} "
                f"→ {r.plate} "
                f"→ {r.space_id}"
            )

    # --------------------------------------------------------
    # AUTOMATIC SIMULATION
    # --------------------------------------------------------

    def action_auto_simulation(self):

        try:

            n_events = int(
                input(
                    "¿Cuántos eventos aleatorios generar? "
                    "(ej: 10): "
                ).strip()
            )

        except ValueError:

            print(
                "Debes ingresar un número."
            )

            return

        try:

            delay = float(
                input(
                    "Segundos de espera entre eventos "
                    "(ej: 0.5, 0 = sin espera): "
                ).strip()
                or 0
            )

        except ValueError:

            delay = 0

        print(
            f"\n Simulando "
            f"{n_events} eventos aleatorios...\n"
        )

        for i in range(n_events):

            occupied = self.parking.get_occupied_plates()

            # -------------------------------------------
            # Decidir acción
            # -------------------------------------------

            action = random.choice(
                [
                    "entry",
                    "entry",
                    "exit",
                    "reservation"
                ]
            )

            # ===========================================
            # EXIT
            # ===========================================

            if action == "exit" and occupied:

                plate = random.choice(
                    occupied
                )

                event = self.parking.vehicle_exit(
                    plate
                )

                if event:

                    self.publish_json(event)

                    print(
                        f"[{i + 1}] "
                        f"Salida → {plate}"
                    )

            # ===========================================
            # RESERVATION
            # ===========================================

            elif action == "reservation":

                plate = self.parking.generate_random_plate()

                reservation = self.parking.create_reservation(
                    plate
                )

                if reservation:

                    # -----------------------------------
                    # Crear JSON
                    # -----------------------------------

                    event = (
                        self.parking
                        .create_reservation_event(
                            reservation
                        )
                    )

                    # -----------------------------------
                    # Publicar
                    # -----------------------------------

                    self.publish_json(event)

                    print(
                        f"[{i + 1}] "
                        f"Reserva → "
                        f"{reservation.plate} "
                        f"→ {reservation.space_id}"
                    )

                    print(
                        json.dumps(
                            event,
                            indent=4,
                            ensure_ascii=False
                        )
                    )

                else:

                    print(
                        f"[{i + 1}] "
                        f"No hay espacios para reservar"
                    )

            # ===========================================
            # ENTRY
            # ===========================================

            else:

                # ---------------------------------------
                # A veces utiliza una reserva activa
                # ---------------------------------------

                active_reservations = (
                    self.parking
                    .get_active_reservations()
                )

                if (
                    active_reservations
                    and random.random() < 0.5
                ):

                    reservation = random.choice(
                        active_reservations
                    )

                    event = self.parking.vehicle_entry(
                        plate=reservation.plate,
                        reservation_id=(
                            reservation.reservation_id
                        )
                    )

                else:

                    plate = (
                        self.parking
                        .generate_random_plate()
                    )

                    event = self.parking.vehicle_entry(
                        plate=plate
                    )

                if event:

                    self.publish_json(event)

                    print(
                        f"[{i + 1}] "
                        f"Entrada → "
                        f"{event['plate']}"
                    )

            # -------------------------------------------
            # DELAY
            # -------------------------------------------

            if delay > 0:

                time.sleep(delay)

        print(
            "\n Simulación automática finalizada."
        )

        self.parking.display_status()


# ============================================================
# MAIN
# ============================================================


def main():

    try:

        n_spaces = input(
            "Número de espacios del parqueadero "
            "(Enter = 10): "
        ).strip()

        n_spaces = (
            int(n_spaces)
            if n_spaces
            else 10
        )

    except ValueError:

        n_spaces = 10

    parking = ParkingLot(
        number_of_spaces=n_spaces
    )

    cli = ParkingCLI(
        parking
    )

    cli.run()


# ============================================================
# START
# ============================================================


if __name__ == "__main__":

    main()