#!/usr/bin/env python3
"""
Genera un historial LIMPIO de prueba para un parqueadero, en el rango de fechas que se pida,
para probar la limpieza, el análisis y el filtro por fechas. SON DATOS DE PRUEBA.

A diferencia de generar_historial.py, aquí no se inyectan defectos: los datos siguen las mismas
reglas que aplica el flujo de Node-RED, así que la limpieza debería encontrar muy poco.

Reglas que respeta:
  * una placa no puede estar adentro dos veces al mismo tiempo (ACTIVE_SESSION)
  * un carro sin reserva no entra a una bahía apartada; si no hay bahía, no entra (NO_BAYS)
  * reserva: nace 'reserved', pasa a 'active' 10 min antes (revisión de cada minuto),
    el carro entra con QR entre -10 y +10 min del inicio ('entered'),
    'completed' cuando sale o cuando termina la franja (lo que pase primero);
    si nadie llega en 10 min -> 'expired'; algunas se cancelan antes de empezar
  * el sensor de la bahía se enciende 40-180 s después de la barrera y se apaga
    30-150 s antes de la salida
  * reservation_events lleva la hora real de cada cambio de estado

Uso:   python3 generar_datos.py --nodo PARKING-003 --bahias 4 --desde 2026-10-05 --semilla 3
       docker exec -i my-mariadb sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" parking_db' < historial_parking003.sql

Con --meses se cambia la demanda por mes: --meses 9:0.6,10:1.0,11:1.2
NO borra nada de otros nodos. Sí reemplaza el historial del nodo indicado.
"""

import argparse
import random
from datetime import date, datetime, timedelta, timezone

ap = argparse.ArgumentParser()
ap.add_argument("--nodo", required=True)
ap.add_argument("--bahias", type=int, required=True)
ap.add_argument("--desde", type=date.fromisoformat, required=True)
ap.add_argument("--semilla", type=int, default=1)
ap.add_argument("--demanda", type=float, default=1.0, help="1.0 llena el parqueadero en hora pico")
ap.add_argument("--reservas", type=float, default=5, help="reservas en un día normal")
ap.add_argument("--meses", default="", help="factor de demanda por mes, ej. 9:0.6,11:1.2")
args = ap.parse_args()

SEED = args.semilla
random.seed(SEED)

NODO = args.nodo
BAHIAS = [f"B-{i:03d}" for i in range(1, args.bahias + 1)]
ARCHIVO = f"historial_{NODO.lower().replace('-', '')}.sql"
DEMANDA = args.demanda
MESES = {int(k): float(v) for k, v in (x.split(":") for x in args.meses.split(",") if x)}

# Llegadas por hora (mismo perfil de campus que generar_historial.py)
PERFIL_HORA = [
    0.00, 0.00, 0.00, 0.00, 0.00, 0.03,   # 0-5
    0.25, 0.85, 1.00, 0.75, 0.55, 0.45,   # 6-11
    0.40, 0.50, 0.45, 0.35, 0.25, 0.18,   # 12-17
    0.12, 0.08, 0.04, 0.02, 0.00, 0.00,   # 18-23
]
FACTOR_DIA = [1.00, 1.05, 1.00, 1.00, 0.90, 0.45, 0.25]   # lunes..domingo

RESERVAS_DIA = args.reservas   # se escala con FACTOR_DIA y con el mes
PCT_NO_SHOW = 0.13
PCT_CANCELADA = 0.09

LETRAS = "ABCDEFGHJKLMNPRSTUVWXYZ"
COL = timezone(timedelta(hours=-5))
AHORA = datetime.now(COL).replace(tzinfo=None, microsecond=0)
HOY = AHORA.date()
INICIO = datetime.combine(args.desde, datetime.min.time())
DIAS = (HOY - args.desde).days


# ------------------------------------------------------------------ placas
def placa():
    return "".join(random.choice(LETRAS) for _ in range(3)) + f"{random.randint(0, 999):03d}"


FRECUENTES = [placa() for _ in range(22)]          # gente que viene casi a diario
OCASIONALES = [placa() for _ in range(160)]


def elegir_placa():
    return random.choice(FRECUENTES) if random.random() < 0.5 else random.choice(OCASIONALES)


def duracion_min(hora):
    r = random.random()
    if hora <= 9 and r < 0.35:
        return random.randint(420, 560)            # jornada completa
    if r < 0.45:
        return random.randint(25, 90)              # visita corta
    if r < 0.85:
        return random.randint(90, 240)             # media
    return random.randint(240, 420)                # larga


def cruza(intervalos, a, b):
    return any(a < y and x < b for x, y in intervalos)


# ------------------------------------------------------------------ estado
ocupada = {b: [] for b in BAHIAS}          # (entrada, salida) de carros en la bahía
apartada = {b: [] for b in BAHIAS}         # lo que bloquea a carros SIN reserva (una sin llegada se libera a los 10 min)
franjas = {b: [] for b in BAHIAS}          # lo que bloquea a OTRAS RESERVAS: la franja completa de toda reserva no cancelada
placa_adentro = {}                         # placa -> [(entrada, salida)]
sesiones, reservas, ev_reserva, ev_bahia = [], [], [], []
_rid = 0


def nuevo_rid():
    global _rid
    _rid += 1
    return f"RSV-{NODO[-3:]}-{_rid:05d}"


def placa_libre(p, a, b):
    return not cruza(placa_adentro.get(p, []), a, b)


def registrar_sesion(bahia, p, entrada, salida, rid=None):
    """Sesión + eventos del sensor. salida=None -> el carro sigue adentro."""
    fin_ocup = salida or AHORA + timedelta(days=1)
    ocupada[bahia].append((entrada, fin_ocup))
    placa_adentro.setdefault(p, []).append((entrada, fin_ocup))
    sesiones.append((rid, p, entrada, salida))
    on = entrada + timedelta(seconds=random.randint(40, 180))
    if on <= AHORA:
        ev_bahia.append((bahia, 1, on))
    if salida:
        off = salida - timedelta(seconds=random.randint(30, 150))
        ev_bahia.append((bahia, 0, max(off, on + timedelta(minutes=1))))


def lag():
    """La revisión corre cada minuto: el cambio llega 0-59 s tarde."""
    return timedelta(seconds=random.randint(0, 59))


# ------------------------------------------------------------------ 1. reservas
for d in range(DIAS + 2):                         # +2: incluye mañana y pasado (programadas)
    dia = INICIO.date() + timedelta(days=d)
    factor = FACTOR_DIA[dia.weekday()] * MESES.get(dia.month, 1.0)
    for _ in range(max(0, round(random.gauss(RESERVAS_DIA * factor, 1)))):
        hora = random.choices(range(24), weights=PERFIL_HORA)[0]
        if hora < 6:
            continue
        ini = datetime.combine(dia, datetime.min.time()) + timedelta(hours=hora, minutes=random.choice([0, 15, 30, 45]))
        fin = ini + timedelta(minutes=random.choice([60, 90, 120, 120, 180, 240]))
        ventana = (ini - timedelta(minutes=10), fin)
        # no generar reservas que estén "en el aire" justo ahora (las maneja el flujo en vivo)
        if ini - timedelta(minutes=10) <= AHORA < fin + timedelta(minutes=10):
            continue
        libres = [b for b in BAHIAS if not cruza(franjas[b], *ventana) and not cruza(ocupada[b], *ventana)]
        if not libres:
            continue
        bahia = random.choice(libres)
        p = elegir_placa()
        if not placa_libre(p, *ventana):
            continue
        creada = ini - timedelta(hours=random.uniform(0.5, 36))
        creada = max(creada, INICIO + timedelta(minutes=random.randint(1, 60)))
        creada = min(creada, AHORA - timedelta(minutes=random.randint(5, 90)))    # nadie reserva desde el futuro
        creada = creada.replace(microsecond=0)
        rid = nuevo_rid()
        nace = "active" if creada >= ini - timedelta(minutes=10) else "reserved"
        ev = [(rid, None, nace, creada)]

        if ini > AHORA:                                         # futura: sigue programada
            estado = "reserved" if nace == "reserved" else "active"
            if estado == "active":
                continue
            apartada[bahia].append(ventana)
            franjas[bahia].append(ventana)
        else:
            activa = creada
            if nace == "reserved":
                activa = ini - timedelta(minutes=10) + lag()
                ev.append((rid, "reserved", "active", activa))
            r = random.random()
            if r < PCT_CANCELADA:
                # se cancela antes de empezar; si ya estaba vigente, también vale
                cancel = creada + (ini - creada) * random.uniform(0.2, 0.9)
                ev = [ev[0]] if cancel < ini - timedelta(minutes=10) else ev
                ev.append((rid, ev[-1][2], "cancelled", cancel.replace(microsecond=0)))
                estado = "cancelled"
            elif r < PCT_CANCELADA + PCT_NO_SHOW:
                ev.append((rid, "active", "expired", ini + timedelta(minutes=10) + lag()))
                estado = "expired"
                apartada[bahia].append((ventana[0], ini + timedelta(minutes=10)))
                franjas[bahia].append(ventana)
            else:
                entrada = ini + timedelta(minutes=random.randint(-10, 8), seconds=random.randint(0, 59))
                entrada = max(entrada, activa + timedelta(seconds=random.randint(20, 90)))   # el QR solo vale ya 'active'
                salida = fin + timedelta(minutes=random.randint(-40, 10), seconds=random.randint(0, 59))
                salida = max(salida, entrada + timedelta(minutes=25))
                if salida > AHORA:
                    continue
                apartada[bahia].append(ventana)
                franjas[bahia].append(ventana)
                registrar_sesion(bahia, p, entrada, salida, rid)
                ev.append((rid, "active", "entered", entrada))
                ev.append((rid, "entered", "completed", min(salida, fin + lag())))
                estado = "completed"
        reservas.append((rid, bahia, p, ini, fin, estado, creada))
        ev_reserva.extend(ev)

# ------------------------------------------------------------------ 2. llegadas sin reserva
for d in range(DIAS + 1):
    dia = INICIO.date() + timedelta(days=d)
    factor = FACTOR_DIA[dia.weekday()] * MESES.get(dia.month, 1.0)
    for hora in range(24):
        lam = len(BAHIAS) * DEMANDA * PERFIL_HORA[hora] * factor
        # Poisson sencillo
        n, l, k = 0, pow(2.718281828, -lam), 1.0
        while True:
            k *= random.random()
            if k <= l:
                break
            n += 1
        for _ in range(n):
            entrada = datetime.combine(dia, datetime.min.time()) + timedelta(hours=hora, seconds=random.randint(0, 3599))
            if entrada >= AHORA:
                continue
            salida = entrada + timedelta(minutes=duracion_min(hora), seconds=random.randint(0, 59))
            abierta = salida > AHORA
            fin_chk = salida if not abierta else AHORA + timedelta(hours=12)
            libres = [b for b in BAHIAS if not cruza(ocupada[b], entrada, fin_chk) and not cruza(apartada[b], entrada, fin_chk)]
            if not libres:
                continue                                    # NO_BAYS: se devuelve en la barrera
            p = elegir_placa()
            for _ in range(5):
                if placa_libre(p, entrada, fin_chk):
                    break
                p = elegir_placa()
            else:
                continue
            registrar_sesion(random.choice(libres), p, entrada, None if abierta else salida)

# ------------------------------------------------------------------ 3. SQL
def f(dt):
    return "NULL" if dt is None else f"'{dt:%Y-%m-%d %H:%M:%S}'"


def s(v):
    return "NULL" if v is None else f"'{v}'"


def bay(code):
    return f"(SELECT bay_id FROM bays WHERE node_id = '{NODO}' AND space_code = '{code}')"


sesiones.sort(key=lambda x: x[2])
ev_bahia.sort(key=lambda x: x[2])
ev_reserva.sort(key=lambda x: (x[3], x[0]))
reservas.sort(key=lambda x: x[3])
adentro = sorted({b for b in BAHIAS for a, z in ocupada[b] if a <= AHORA < z})

L = []
L.append(f"-- Historial limpio de {NODO}: {INICIO:%Y-%m-%d} a {AHORA:%Y-%m-%d %H:%M} (semilla {SEED})")
L.append(f"-- {len(sesiones)} sesiones, {len(reservas)} reservas, {len(ev_bahia)} eventos de sensor")
L.append("USE parking_db;")
L.append("SET time_zone = '-05:00';")
L.append("START TRANSACTION;")
L.append(f"UPDATE nodes SET created_at = {f(INICIO)}, last_connection = NOW() WHERE node_id = '{NODO}';")
# borrar historial anterior del nodo
L.append(f"DELETE re FROM reservation_events re JOIN reservations r USING (reservation_id) JOIN bays b USING (bay_id) WHERE b.node_id = '{NODO}';")
L.append(f"DELETE FROM sessions WHERE node_id = '{NODO}';")
L.append(f"DELETE r FROM reservations r JOIN bays b USING (bay_id) WHERE b.node_id = '{NODO}';")
# estado final del sensor: el UPDATE dispara el trigger, por eso se hace ANTES de cargar bay_events
L.append(f"UPDATE bays SET sensor_status = 0 WHERE node_id = '{NODO}';")
for b in adentro:
    L.append(f"UPDATE bays SET sensor_status = 1 WHERE node_id = '{NODO}' AND space_code = '{b}';")
L.append(f"DELETE e FROM bay_events e JOIN bays b USING (bay_id) WHERE b.node_id = '{NODO}';")

if reservas:
    L.append("INSERT INTO reservations (reservation_id, bay_id, plate, starts_at, ends_at, status, created_at) VALUES")
    L.append(",\n".join(f"({s(r[0])}, {bay(r[1])}, {s(r[2])}, {f(r[3])}, {f(r[4])}, {s(r[5])}, {f(r[6])})" for r in reservas) + ";")
    # el trigger de INSERT anotó un evento con la hora de carga: se reemplaza por el historial real
    L.append(f"DELETE re FROM reservation_events re JOIN reservations r USING (reservation_id) JOIN bays b USING (bay_id) WHERE b.node_id = '{NODO}';")
    L.append("INSERT INTO reservation_events (reservation_id, old_status, new_status, created_at) VALUES")
    L.append(",\n".join(f"({s(e[0])}, {s(e[1])}, {s(e[2])}, {f(e[3])})" for e in ev_reserva) + ";")

L.append("INSERT INTO sessions (node_id, reservation_id, plate, entry_at, exit_at) VALUES")
L.append(",\n".join(f"('{NODO}', {s(x[0])}, {s(x[1])}, {f(x[2])}, {f(x[3])})" for x in sesiones) + ";")
L.append("INSERT INTO bay_events (bay_id, sensor_status, created_at) VALUES")
L.append(",\n".join(f"({bay(e[0])}, {e[1]}, {f(e[2])})" for e in ev_bahia) + ";")
L.append("COMMIT;")

with open(ARCHIVO, "w") as fh:
    fh.write("\n".join(L) + "\n")

est = {}
for r in reservas:
    est[r[5]] = est.get(r[5], 0) + 1
print(f"{ARCHIVO}: {len(sesiones)} sesiones ({sum(1 for x in sesiones if x[0])} con QR, "
      f"{sum(1 for x in sesiones if x[3] is None)} adentro ahora), {len(reservas)} reservas {est}, "
      f"{len(ev_bahia)} eventos de sensor, {len(ev_reserva)} eventos de reserva")
