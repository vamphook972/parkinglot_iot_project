#!/usr/bin/env python3
"""
Generador de historial para el proyecto Parking IoT.

Produce un archivo historial.sql con 7 dias de datos para 4 nodos
(1 fisico + 3 simulados), con patrones realistas de ocupacion y una
cantidad controlada de defectos inyectados a proposito, para poder
demostrar la limpieza del Taller 8.

Uso:   python3 generar_historial.py
Salida: historial.sql  (se carga en MySQL Workbench sobre parking_db)

No se conecta a la base de datos: solo escribe SQL.
"""

import random
from datetime import date, datetime, timedelta

SEED = 20261110
random.seed(SEED)

# =========================================================================
# CONFIGURACION
# =========================================================================

DIAS = 7                    # dias de historial (terminan ayer)
ARCHIVO = "historial.sql"

# busy = factor de demanda. 1.0 llena el parqueadero en hora pico.
NODOS = [
    {"id": "PARKING-002", "bahias": 3, "busy": 1.20, "nota": "nodo fisico"},
    {"id": "PARKING-003", "bahias": 5, "busy": 0.85, "nota": "simulado"},
    {"id": "PARKING-004", "bahias": 8, "busy": 0.55, "nota": "simulado"},
    {"id": "PARKING-005", "bahias": 4, "busy": 1.00, "nota": "simulado"},
]

# Llegadas por hora (0-23), en proporcion.
# Perfil tipo campus: las LLEGADAS se concentran en la manana. El pico de la
# tarde es de salidas, y esas no se modelan aqui porque salen solas de la
# duracion de cada sesion. Si se pusiera un pico de llegadas a las 18:00, la
# ocupacion terminaria subiendo toda la tarde, que es justo lo contrario de
# lo que pasa en un parqueadero universitario.
PERFIL_HORA = [
    0.00, 0.00, 0.00, 0.00, 0.00, 0.03,   # 0-5
    0.25, 0.85, 1.00, 0.75, 0.55, 0.45,   # 6-11  pico de llegadas
    0.40, 0.50, 0.45, 0.35, 0.25, 0.18,   # 12-17
    0.12, 0.08, 0.04, 0.02, 0.00, 0.00,   # 18-23
]

# Factor por dia de la semana (lunes=0 ... domingo=6)
FACTOR_DIA = [1.00, 1.05, 1.00, 1.00, 0.90, 0.35, 0.20]

PCT_CON_RESERVA = 0.30      # cuantas llegadas vienen de una reserva
PCT_NO_SHOW = 0.15          # reservas que se vencen sin que llegue el carro
PCT_CANCELADA = 0.08        # reservas canceladas desde la app

LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# =========================================================================
# PLACAS
# =========================================================================

def placa_carro():
    return "".join(random.choice(LETRAS) for _ in range(3)) + \
           "".join(str(random.randint(0, 9)) for _ in range(3))

def placa_moto():
    return "".join(random.choice(LETRAS) for _ in range(3)) + \
           str(random.randint(0, 9)) + str(random.randint(0, 9)) + \
           random.choice(LETRAS)

# Pool con placas frecuentes (gente que viene a diario) y ocasionales.
PLACAS_FRECUENTES = [placa_carro() for _ in range(18)]
PLACAS_OCASIONALES = [placa_carro() for _ in range(90)] + \
                     [placa_moto() for _ in range(12)]

def elegir_placa():
    if random.random() < 0.45:
        return random.choice(PLACAS_FRECUENTES)
    return random.choice(PLACAS_OCASIONALES)

# =========================================================================
# DURACIONES
# =========================================================================

def duracion_minutos(hora_entrada):
    """Mezcla de visitas cortas, medias y de jornada completa."""
    r = random.random()
    if hora_entrada <= 9 and r < 0.35:
        return random.randint(420, 560)          # jornada completa
    if r < 0.45:
        return random.randint(25, 90)            # visita corta
    if r < 0.85:
        return random.randint(90, 240)           # media
    return random.randint(240, 420)              # larga

# =========================================================================
# ESTRUCTURAS
# =========================================================================

class Bahia:
    def __init__(self, bay_id, node_id, space_code):
        self.bay_id = bay_id
        self.node_id = node_id
        self.space_code = space_code
        self.ocupada = []     # intervalos (ini, fin) de sesiones
        self.reservada = []   # intervalos (ini, fin) de reservas vigentes

    def libre(self, ini, fin):
        for a, b in self.ocupada:
            if ini < b and a < fin:
                return False
        return True

    def sin_reserva(self, ini, fin):
        for a, b in self.reservada:
            if ini < b and a < fin:
                return False
        return True


HOY = date.today()
AHORA = datetime.now().replace(microsecond=0)
INICIO = HOY - timedelta(days=DIAS)        # primer dia con datos
FIN = HOY                                  # el ultimo dia llega hasta AHORA

# Los dias de generacion incluyen hoy, hasta la hora actual. Es necesario para
# el Taller 9: si el historial terminara ayer, no habria ningun carro adentro
# y el dashboard en tiempo real y la tabla de bahias se verian vacios.
DIAS_GEN = DIAS + 1

bahias = []
sesiones = []            # dicts
reservas = []            # dicts
eventos_reserva = []     # (reservation_id, old, new, ts)
defectos = []            # (tipo, descripcion)

_bay_id = 0
for n in NODOS:
    for i in range(1, n["bahias"] + 1):
        _bay_id += 1
        bahias.append(Bahia(_bay_id, n["id"], f"B-{i:03d}"))

bahias_por_nodo = {n["id"]: [b for b in bahias if b.node_id == n["id"]] for n in NODOS}

_rsv = 0
def nuevo_reservation_id():
    global _rsv
    _rsv += 1
    return f"RSV-{_rsv:05d}"

# Ventana de perdida de comunicacion que se va a simular (TIME_GAP).
NODO_CAIDO = "PARKING-004"
DIA_CAIDO = INICIO + timedelta(days=3)
CAIDA_INI = datetime.combine(DIA_CAIDO, datetime.min.time()) + timedelta(hours=9)
CAIDA_FIN = CAIDA_INI + timedelta(hours=5)

def en_caida(node_id, ini, fin):
    if node_id != NODO_CAIDO:
        return False
    return (CAIDA_INI <= ini <= CAIDA_FIN) or (CAIDA_INI <= fin <= CAIDA_FIN)

# =========================================================================
# 1. RESERVAS
# =========================================================================
# Se generan primero porque bloquean bahias y condicionan las llegadas.

for n in NODOS:
    for d in range(DIAS_GEN):
        dia = INICIO + timedelta(days=d)
        factor = FACTOR_DIA[dia.weekday()]
        # cuantas reservas ese dia en ese nodo
        cuantas = int(round(n["bahias"] * 1.2 * n["busy"] * factor * PCT_CON_RESERVA * 3))
        for _ in range(cuantas):
            hora = random.choices(range(24), weights=PERFIL_HORA)[0]
            if hora < 6:
                continue
            inicio = datetime.combine(dia, datetime.min.time()) + \
                     timedelta(hours=hora, minutes=random.choice([0, 15, 30, 45]))
            largo = random.choice([60, 90, 120, 120, 180, 240])
            fin = inicio + timedelta(minutes=largo)

            candidatas = [b for b in bahias_por_nodo[n["id"]]
                          if b.sin_reserva(inicio, fin)]
            if not candidatas:
                continue
            bahia = random.choice(candidatas)

            rid = nuevo_reservation_id()
            placa = elegir_placa()
            creada = inicio - timedelta(hours=random.randint(2, 40))
            if creada < datetime.combine(INICIO, datetime.min.time()):
                creada = datetime.combine(INICIO, datetime.min.time()) + timedelta(minutes=5)

            r = random.random()
            if r < PCT_CANCELADA:
                desenlace = "cancelled"
            elif r < PCT_CANCELADA + PCT_NO_SHOW:
                desenlace = "expired"
            else:
                desenlace = "usada"

            reservas.append({
                "id": rid, "bay": bahia, "placa": placa,
                "inicio": inicio, "fin": fin, "creada": creada,
                "desenlace": desenlace, "status": None,
            })
            # la reserva bloquea la bahia salvo que se cancele antes de empezar
            if desenlace != "cancelled":
                bahia.reservada.append((inicio, fin))

# =========================================================================
# 2. SESIONES QUE VIENEN DE UNA RESERVA
# =========================================================================

for r in reservas:
    activa_en = r["inicio"] - timedelta(minutes=10)

    # Reservas que todavia no empiezan: quedan en reserved o active, sin mas.
    if activa_en > AHORA:
        eventos_reserva.append((r["id"], None, "reserved", r["creada"]))
        r["status"] = "reserved"
        continue
    if r["inicio"] <= AHORA < r["fin"] and r["desenlace"] != "cancelled":
        # vigente ahora mismo
        eventos_reserva.append((r["id"], None, "reserved", r["creada"]))
        eventos_reserva.append((r["id"], "reserved", "active", activa_en))
        entrada = r["inicio"] + timedelta(minutes=random.randint(-10, 20))
        if entrada <= AHORA and r["bay"].libre(entrada, r["fin"]):
            r["bay"].ocupada.append((entrada, r["fin"]))
            eventos_reserva.append((r["id"], "active", "entered", entrada))
            r["status"] = "entered"
            sesiones.append({
                "node_id": r["bay"].node_id, "rid": r["id"], "placa": r["placa"],
                "entrada": entrada, "salida": None, "bay": r["bay"],
            })
        else:
            r["status"] = "active"
        continue

    if r["desenlace"] == "cancelled":
        # cancelada antes de entrar en vigencia
        cancel_ts = r["creada"] + timedelta(minutes=random.randint(30, 600))
        if cancel_ts >= activa_en:
            cancel_ts = activa_en - timedelta(minutes=5)
        eventos_reserva.append((r["id"], None, "reserved", r["creada"]))
        eventos_reserva.append((r["id"], "reserved", "cancelled", cancel_ts))
        r["status"] = "cancelled"
        continue

    eventos_reserva.append((r["id"], None, "reserved", r["creada"]))
    eventos_reserva.append((r["id"], "reserved", "active", activa_en))

    if r["desenlace"] == "expired":
        eventos_reserva.append((r["id"], "active", "expired", r["fin"]))
        r["status"] = "expired"
        continue

    # el carro llega: entre 10 min antes del inicio y la primera media hora
    entrada = r["inicio"] + timedelta(minutes=random.randint(-10, 30),
                                      seconds=random.randint(0, 59))
    salida = r["fin"] - timedelta(minutes=random.randint(0, 25),
                                  seconds=random.randint(0, 59))
    if salida <= entrada:
        salida = entrada + timedelta(minutes=20)

    if en_caida(r["bay"].node_id, entrada, salida):
        # el nodo estaba sin comunicacion: no se registra nada
        eventos_reserva.append((r["id"], "active", "expired", r["fin"]))
        r["status"] = "expired"
        continue

    if not r["bay"].libre(entrada, salida):
        eventos_reserva.append((r["id"], "active", "expired", r["fin"]))
        r["status"] = "expired"
        continue

    r["bay"].ocupada.append((entrada, salida))
    eventos_reserva.append((r["id"], "active", "entered", entrada))
    eventos_reserva.append((r["id"], "entered", "completed", salida))
    r["status"] = "completed"

    sesiones.append({
        "node_id": r["bay"].node_id, "rid": r["id"], "placa": r["placa"],
        "entrada": entrada, "salida": salida, "bay": r["bay"],
    })

# =========================================================================
# 3. SESIONES SIN RESERVA (entrada por placa)
# =========================================================================

for n in NODOS:
    for d in range(DIAS_GEN):
        dia = INICIO + timedelta(days=d)
        factor = FACTOR_DIA[dia.weekday()]
        for hora in range(24):
            tasa = PERFIL_HORA[hora] * factor * n["busy"] * n["bahias"] * 0.85
            llegadas = 0
            # aproximacion simple de Poisson
            for _ in range(int(tasa * 3) + 1):
                if random.random() < tasa / (int(tasa * 3) + 1):
                    llegadas += 1
            for _ in range(llegadas):
                # Los segundos se aleatorizan a proposito: si todas las
                # entradas y salidas cayeran en el segundo 00, la salida de un
                # carro y la entrada del siguiente en la misma bahia podrian
                # coincidir al segundo y la regla de rebote las leeria como un
                # rebote de sensor.
                entrada = datetime.combine(dia, datetime.min.time()) + \
                          timedelta(hours=hora, minutes=random.randint(0, 59),
                                    seconds=random.randint(0, 59))
                if entrada > AHORA:
                    continue       # todavia no ha pasado
                salida = entrada + timedelta(minutes=duracion_minutos(hora),
                                             seconds=random.randint(0, 59))

                if en_caida(n["id"], entrada, salida):
                    continue

                # El carro sigue adentro: la sesion queda abierta y la bahia
                # ocupada. Esto es lo que alimenta el dashboard en vivo.
                adentro = salida > AHORA

                candidatas = [b for b in bahias_por_nodo[n["id"]]
                              if b.libre(entrada, salida) and b.sin_reserva(entrada, salida)]
                if not candidatas:
                    continue    # NO_BAYS: el acceso se habria negado
                bahia = random.choice(candidatas)
                bahia.ocupada.append((entrada, salida))

                sesiones.append({
                    "node_id": n["id"], "rid": None, "placa": elegir_placa(),
                    "entrada": entrada,
                    "salida": None if adentro else salida,
                    "bay": bahia,
                })

# =========================================================================
# 4. DEFECTOS INYECTADOS
# =========================================================================
# Cada uno corresponde a una regla de limpieza de parking_analytics.

sesiones.sort(key=lambda s: s["entrada"])
limpias = [s for s in sesiones if s["salida"] is not None]

def marcar(tipo, desc):
    defectos.append((tipo, desc))

# 4.1 FORMAT: placas en minuscula
for s in random.sample(limpias, 6):
    s["placa"] = s["placa"].lower()
marcar("FORMAT / correct", "6 sesiones con la placa en minuscula")

# 4.2 OUT_OF_RANGE: placas que no cumplen el formato colombiano
malas = ["AB1234", "ABCD12", "12ABC3", "XY789"]
for s, mala in zip(random.sample(limpias, 4), malas):
    s["placa"] = mala
marcar("OUT_OF_RANGE / exclude", "4 sesiones con placa mal digitada en el teclado")

# 4.3 OUT_OF_RANGE: duracion imposible
for s in random.sample(limpias, 2):
    s["salida"] = s["entrada"] + timedelta(hours=random.randint(30, 50))
marcar("OUT_OF_RANGE / exclude", "2 sesiones de mas de 30 h")

# 4.4 ORPHAN_SESSION: sesiones que nunca registraron salida
for s in random.sample([x for x in limpias
                        if x["entrada"] < datetime.combine(HOY - timedelta(days=2),
                                                           datetime.min.time())], 3):
    s["salida"] = None
marcar("ORPHAN_SESSION / report", "3 sesiones abiertas hace mas de 24 h")

# 4.5 DUPLICATE: reentrega del broker con QoS 1
duplicados = []
for s in random.sample([x for x in sesiones if x["salida"]], 4):
    copia = dict(s)
    copia["entrada"] = s["entrada"] + timedelta(seconds=random.randint(2, 40))
    copia["bay"] = None          # el duplicado no genera eventos de bahia
    duplicados.append(copia)
sesiones.extend(duplicados)
marcar("DUPLICATE / exclude", "4 sesiones duplicadas a menos de 60 s")

# 4.6 INCOMPLETE: sesion sin nodo
huerfana = dict(random.choice([x for x in sesiones if x["salida"]]))
huerfana["node_id"] = None
huerfana["bay"] = None
sesiones.append(huerfana)
marcar("INCOMPLETE / exclude", "1 sesion sin node_id")

# 4.7 INCONSISTENT: reserva marcada entered sin sesion asociada
cand = [r for r in reservas if r["status"] == "expired"]
if cand:
    r = random.choice(cand)
    eventos_reserva[:] = [e for e in eventos_reserva
                          if not (e[0] == r["id"] and e[2] == "expired")]
    eventos_reserva.append((r["id"], "active", "entered", r["inicio"]))
    r["status"] = "entered"
    marcar("INCONSISTENT / report", "1 reserva en entered sin sesion asociada")

# 4.8 FORMAT en reservas
for r in random.sample(reservas, 3):
    r["placa"] = r["placa"].lower()
marcar("FORMAT / correct", "3 reservas con la placa en minuscula")

# 4.9 OUT_OF_RANGE: franja de reserva desproporcionada
r = random.choice(reservas)
r["fin"] = r["inicio"] + timedelta(hours=40)
marcar("OUT_OF_RANGE / report", "1 reserva con franja de 40 h")

marcar("TIME_GAP / report",
       f"{NODO_CAIDO} sin datos de 9:00 a 14:00 el {DIA_CAIDO}")

# 4.10 ANOMALIA: alguien sin reserva se parquea en una bahia reservada.
# No es un error de dato: es el caso rojo + amarillo que hoy resuelve una
# persona en el parqueadero, y es lo que alimenta la vista v_anomalies.
# Sin inyectarlo, esa vista sale vacia porque el generador respeta las
# reservas y nunca produciria la situacion por si solo.
invasiones = 0
for r in [x for x in reservas if x["status"] == "expired"]:
    if invasiones >= 3:
        break
    entrada = r["inicio"] + timedelta(minutes=random.randint(5, 25))
    salida = min(r["fin"] - timedelta(minutes=10), entrada + timedelta(minutes=70))
    if salida <= entrada or entrada > AHORA:
        continue
    if not r["bay"].libre(entrada, salida):
        continue
    r["bay"].ocupada.append((entrada, salida))
    sesiones.append({
        "node_id": r["bay"].node_id, "rid": None, "placa": elegir_placa(),
        "entrada": entrada, "salida": salida, "bay": r["bay"],
    })
    invasiones += 1
marcar("ANOMALIA (no es defecto de dato)",
       f"{invasiones} carros sin reserva parqueados en bahia reservada")

# =========================================================================
# 5. EVENTOS DE BAHIA
# =========================================================================
# Se derivan de las sesiones: TRUE al entrar, FALSE al salir.

eventos_bahia = {}     # bay_id -> lista de (ts, estado)
for b in bahias:
    eventos_bahia[b.bay_id] = []

for s in sesiones:
    b = s["bay"]
    if b is None:
        continue
    eventos_bahia[b.bay_id].append((s["entrada"], True))
    if s["salida"] is not None:
        eventos_bahia[b.bay_id].append((s["salida"], False))

# 5.1 SENSOR_BOUNCE: rebote del VL53L0X / HC-SR04
rebotes = 0
for b in random.sample(bahias, 6):
    lista = sorted(eventos_bahia[b.bay_id])
    if not lista:
        continue
    # El rebote se mete en una ventana en la que la bahia esta LIBRE, es decir
    # despues de un evento FALSE y con espacio antes del siguiente. Si se
    # metiera dentro de un periodo ocupado, la secuencia quedaria TRUE-TRUE y
    # el rebote tambien se contaria como estado repetido, inflando esa regla.
    huecos = []
    for i, (ts, estado) in enumerate(lista):
        if estado:
            continue
        siguiente = lista[i + 1][0] if i + 1 < len(lista) else ts + timedelta(hours=4)
        if (siguiente - ts) > timedelta(minutes=40):
            huecos.append((ts, siguiente))
    if not huecos:
        continue
    ini, _fin = random.choice(huecos)
    t = ini + timedelta(minutes=random.randint(5, 30))
    eventos_bahia[b.bay_id].append((t, True))
    eventos_bahia[b.bay_id].append((t + timedelta(seconds=1), False))
    rebotes += 1
marcar("SENSOR_BOUNCE / exclude", f"{rebotes} rebotes de sensor (pares a 1 s)")

# 5.2 DUPLICATE: estado repetido por reentrega del mensaje
repetidos = 0
for b in random.sample([x for x in bahias if eventos_bahia[x.bay_id]], 3):
    lista = eventos_bahia[b.bay_id]
    verdaderos = [(t, e) for t, e in lista if e]
    if not verdaderos:
        continue
    t, _ = random.choice(verdaderos)
    lista.append((t + timedelta(seconds=random.randint(3, 20)), True))
    repetidos += 1
marcar("DUPLICATE / exclude", f"{repetidos} eventos de bahia con estado repetido")

# =========================================================================
# 6. ESCRITURA DEL SQL
# =========================================================================

def sql_dt(dt):
    return "'" + dt.strftime("%Y-%m-%d %H:%M:%S") + "'"

def sql_str(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"

def bloques(filas, por_bloque=500):
    for i in range(0, len(filas), por_bloque):
        yield filas[i:i + por_bloque]

out = []
w = out.append

w("-- =====================================================================")
w(f"-- Historial generado el {datetime.now():%Y-%m-%d %H:%M} (semilla {SEED})")
w(f"-- Periodo: {INICIO} a {FIN - timedelta(days=1)}  ({DIAS} dias)")
w("--")
w("-- ATENCION: borra el contenido actual de parking_db. Es data semilla")
w("-- para los talleres 8 y 9. Si quieres conservar lo que tienes, saca la")
w("-- seccion de limpieza de abajo.")
w("-- =====================================================================")
w("")
w("USE parking_db;")
w("SET time_zone = '-05:00';")
w("")
w("-- ---------- limpieza ----------")
w("SET FOREIGN_KEY_CHECKS = 0;")
for t in ["reservation_events", "bay_events", "sessions", "reservations", "bays", "nodes"]:
    w(f"TRUNCATE TABLE {t};")
w("SET FOREIGN_KEY_CHECKS = 1;")
w("")

w("-- ---------- nodos ----------")
creado = datetime.combine(INICIO, datetime.min.time())
filas = [f"({sql_str(n['id'])}, {sql_dt(creado)}, {sql_dt(datetime.now())})" for n in NODOS]
w("INSERT INTO nodes (node_id, created_at, last_connection) VALUES")
w(",\n".join(filas) + ";")
w("")

w("-- ---------- bahias ----------")
w("-- El sensor_status final se calcula aqui y se inserta ya resuelto.")
w("-- No se puede dejar para un UPDATE al final del script: ese UPDATE")
w("-- dispararia trg_bays_sensor_change, y MySQL rechaza que un trigger")
w("-- escriba en bay_events si la misma sentencia esta leyendo esa tabla")
w("-- (error 1442). Ademas, el trigger insertaria un evento espurio con la")
w("-- hora de la carga, que la limpieza marcaria como estado repetido.")
estado_final = {}
for b in bahias:
    evs = sorted(eventos_bahia[b.bay_id])
    estado_final[b.bay_id] = evs[-1][1] if evs else False
filas = [f"({b.bay_id}, {sql_str(b.node_id)}, {sql_str(b.space_code)}, "
         f"{'TRUE' if estado_final[b.bay_id] else 'FALSE'})" for b in bahias]
w("INSERT INTO bays (bay_id, node_id, space_code, sensor_status) VALUES")
w(",\n".join(filas) + ";")
w("")

w("-- ---------- reservas ----------")
for grupo in bloques(reservas):
    filas = []
    for r in grupo:
        filas.append(
            f"({sql_str(r['id'])}, {r['bay'].bay_id}, {sql_str(r['placa'])}, "
            f"{sql_dt(r['inicio'])}, {sql_dt(r['fin'])}, {sql_str(r['status'])}, "
            f"{sql_dt(r['creada'])})"
        )
    w("INSERT INTO reservations (reservation_id, bay_id, plate, starts_at, ends_at, status, created_at) VALUES")
    w(",\n".join(filas) + ";")
w("")

w("-- ---------- sesiones ----------")
for grupo in bloques(sesiones):
    filas = []
    for s in grupo:
        salida = sql_dt(s["salida"]) if s["salida"] else "NULL"
        filas.append(
            f"({sql_str(s['node_id'])}, {sql_str(s['rid'])}, {sql_str(s['placa'])}, "
            f"{sql_dt(s['entrada'])}, {salida})"
        )
    w("INSERT INTO sessions (node_id, reservation_id, plate, entry_at, exit_at) VALUES")
    w(",\n".join(filas) + ";")
w("")

w("-- ---------- eventos de bahia ----------")
w("-- Los triggers no aplican aqui: es carga historica, se insertan directo")
w("-- con su created_at real.")
todos_eventos = []
for b in bahias:
    for ts, estado in sorted(eventos_bahia[b.bay_id]):
        todos_eventos.append((b.bay_id, estado, ts))
todos_eventos.sort(key=lambda x: (x[2], x[0]))
for grupo in bloques(todos_eventos):
    filas = [f"({bid}, {'TRUE' if est else 'FALSE'}, {sql_dt(ts)})"
             for bid, est, ts in grupo]
    w("INSERT INTO bay_events (bay_id, sensor_status, created_at) VALUES")
    w(",\n".join(filas) + ";")
w("")

w("-- ---------- historial de reservas ----------")
w("-- Se borra lo que generaron los triggers al insertar las reservas y se")
w("-- reemplaza por el historial con sus fechas reales.")
w("DELETE FROM reservation_events;")
eventos_reserva.sort(key=lambda e: e[3])
for grupo in bloques(eventos_reserva):
    filas = [f"({sql_str(rid)}, {sql_str(old)}, {sql_str(new)}, {sql_dt(ts)})"
             for rid, old, new, ts in grupo]
    w("INSERT INTO reservation_events (reservation_id, old_status, new_status, created_at) VALUES")
    w(",\n".join(filas) + ";")
w("")

w("-- ---------- recalcular la capa de analisis ----------")
w("CALL parking_analytics.sp_refresh_all();")

with open(ARCHIVO, "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")

# =========================================================================
# 7. VERIFICACION Y RESUMEN
# =========================================================================

problemas = []
for b in bahias:
    prev = None
    for ts, estado in sorted(eventos_bahia[b.bay_id]):
        if prev is not None and prev == estado:
            pass    # esperado solo en los duplicados inyectados
        prev = estado

con_reserva = sum(1 for s in sesiones if s["rid"])
abiertas = sum(1 for s in sesiones if s["salida"] is None)

print(f"Archivo: {ARCHIVO}")
print(f"Periodo: {INICIO} a {FIN - timedelta(days=1)} ({DIAS} dias)")
print()
print(f"  nodos .................. {len(NODOS)}")
print(f"  bahias ................. {len(bahias)}")
print(f"  sesiones ............... {len(sesiones)}  ({con_reserva} con reserva, {abiertas} abiertas)")
print(f"  reservas ............... {len(reservas)}")
print(f"  eventos de bahia ....... {len(todos_eventos)}")
print(f"  eventos de reserva ..... {len(eventos_reserva)}")
print()
print("Desenlace de las reservas:")
for st in ["completed", "entered", "expired", "cancelled"]:
    c = sum(1 for r in reservas if r["status"] == st)
    print(f"  {st:<12} {c}")
print()
print("Defectos inyectados (cada uno dispara una regla de limpieza):")
for tipo, desc in defectos:
    print(f"  [{tipo}] {desc}")
