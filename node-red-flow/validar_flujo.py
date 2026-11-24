"""Validaciones end-to-end del flujo de Node-RED (HTTP + MQTT) con el nodo PARKING-TEST.

Replica las pruebas de Bruno (REST_methods/parking-iot-bruno) y agrega los casos
de acceso por MQTT de la nota de requerimientos.

Uso (desde la raíz del repo):
    simulation_node/.venv/bin/python node-red-flow/validar_flujo.py
Opcional: NODE_RED=http://localhost:1880  MQTT_HOST=test.mosquitto.org

Deja datos de prueba en la BD (reservas RSV-*, sesiones de placas V*) en PARKING-TEST,
igual que las pruebas de Bruno. El nodo PARKING-TEST se crea solo con el registro MQTT.
Para quitarlo después (las reservas no se borran en cascada con la bahía):

    DELETE re FROM reservation_events re JOIN reservations r USING (reservation_id)
      JOIN bays b USING (bay_id) WHERE b.node_id = 'PARKING-TEST';
    DELETE r FROM reservations r JOIN bays b USING (bay_id) WHERE b.node_id = 'PARKING-TEST';
    DELETE FROM sessions WHERE node_id = 'PARKING-TEST';
    DELETE FROM nodes WHERE node_id = 'PARKING-TEST';     -- bahías y bay_events en cascada
"""
import json
import os
import queue
import random
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

BASE = os.getenv('NODE_RED', 'http://localhost:1880')
BROKER = os.getenv('MQTT_HOST', 'test.mosquitto.org')
NODE = 'PARKING-TEST'
PREF = f'parqueadero/{NODE}'
COL = timezone(timedelta(hours=-5))
RUN = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

resultados = []


def check(nombre, ok, detalle=''):
    resultados.append((nombre, ok))
    print(('  OK   ' if ok else '  FALLA') + f'  {nombre}' + ('' if ok else f'  -> {detalle}'))


def fecha(min_desde_ahora):
    return (datetime.now(COL) + timedelta(minutes=min_desde_ahora)).strftime('%Y-%m-%dT%H:%M:%S-05:00')


def http(metodo, ruta, cuerpo=None, content_type='application/json'):
    data = None
    if cuerpo is not None:
        data = cuerpo.encode() if isinstance(cuerpo, str) else json.dumps(cuerpo).encode()
    req = urllib.request.Request(BASE + ruta, data=data, method=metodo)
    if data is not None:
        req.add_header('Content-Type', content_type)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw, code, headers = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        raw, code, headers = e.read(), e.code, e.headers
    try:
        body = json.loads(raw)
    except ValueError:
        body = raw.decode(errors='replace')
    return code, body, headers


def reserva(rid, bay, plate, ini, fin):
    return {'reservation_id': rid, 'node_id': NODE, 'space_id': bay, 'plate': plate,
            'starts_at': ini, 'ends_at': fin}


# ---------------------------------------------------------------- MQTT
mensajes = queue.Queue()
cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f'validar-{RUN}')
cli.on_message = lambda c, u, m: mensajes.put((m.topic[len(PREF) + 1:], json.loads(m.payload)))
cli.connect(BROKER, 1883, 30)
cli.subscribe(f'{PREF}/#', qos=1)
cli.loop_start()
time.sleep(2)


def vaciar():
    while not mensajes.empty():
        mensajes.get_nowait()


def publicar(sub, payload):
    cli.publish(f'{PREF}/{sub}', json.dumps(payload), qos=1)


def esperar(pred, seg=8):
    """Devuelve (mensajes vistos, primer mensaje que cumple pred)."""
    vistos, fin = [], time.time() + seg
    while time.time() < fin:
        try:
            t, p = mensajes.get(timeout=0.2)
        except queue.Empty:
            continue
        vistos.append((t, p))
        if pred(t, p):
            return vistos, (t, p)
    return vistos, None


def acceso(tipo, plate=None, rid=None, extra_seg=1.5):
    """Publica acceso/input y devuelve (cmd, otros mensajes recibidos)."""
    vaciar()
    publicar('acceso/input', {'node_id': NODE, 'access_type': tipo, 'reservation_id': rid, 'plate': plate})
    vistos, cmd = esperar(lambda t, p: t == 'acceso/cmd')
    vistos += esperar(lambda t, p: False, extra_seg)[0]      # recoge evento / bahia/reserva
    return (cmd[1] if cmd else None), vistos


def tiene(vistos, topic, **campos):
    return any(t == topic and all(p.get(k) == v for k, v in campos.items()) for t, p in vistos)


print(f'\n== MQTT ({BROKER}) · corrida {RUN}')

vaciar()
publicar('registro', {'node_id': NODE, 'bays': ['B-001', 'B-002', 'B-003']})
time.sleep(3)
code, bays, _ = http('GET', f'/parqueaderos/{NODE}/bahias')
check('registro crea el nodo y sus 3 bahías', code == 200 and len(bays) >= 3, (code, bays))

# Sensores
publicar('bahia/sensor', {'node_id': NODE, 'space_id': 'B-001', 'sensor_status': False})
time.sleep(2.5)
vaciar()
publicar('bahia/sensor', {'node_id': NODE, 'space_id': 'B-001', 'sensor_status': True})
_, ev = esperar(lambda t, p: t == 'bahia/evento')
check('sensor true -> bahia/evento con sensor_status true',
      ev is not None and ev[1]['sensor_status'] is True and ev[1]['space_id'] == 'B-001' and 'date' in ev[1], ev)
vaciar()
publicar('bahia/sensor', {'node_id': NODE, 'space_id': 'B-001', 'sensor_status': True})
_, ev = esperar(lambda t, p: t == 'bahia/evento', 4)
check('misma lectura repetida -> sin bahia/evento', ev is None, ev)
publicar('bahia/sensor', {'node_id': NODE, 'space_id': 'B-001', 'sensor_status': False})
_, ev = esperar(lambda t, p: t == 'bahia/evento')
check('sensor false -> bahia/evento con sensor_status false', ev is not None and ev[1]['sensor_status'] is False, ev)
vaciar()
publicar('bahia/sensor', {'node_id': NODE, 'space_id': 'B-999', 'sensor_status': True})
publicar('bahia/sensor', {'node_id': 'OTRO', 'space_id': 'B-001', 'sensor_status': True})
_, ev = esperar(lambda t, p: t == 'bahia/evento', 6)
check('bahía inexistente / node_id distinto -> se descartan', ev is None, ev)

# Accesos por placa
p1 = f'V{RUN}1'
cmd, v = acceso('entry', plate=p1)
check('entrada por placa -> OK', cmd and cmd['allowed'] is True and cmd['reason'] == 'OK', cmd)
check('entrada aprobada -> acceso/evento con fecha', tiene(v, 'acceso/evento', plate=p1, access_type='entry'), v)
cmd, _ = acceso('entry', plate=p1.lower()[:2] + '-' + p1.lower()[2:])
check('misma placa (minúsculas y guion) -> ACTIVE_SESSION', cmd and cmd['reason'] == 'ACTIVE_SESSION' and cmd['allowed'] is False, cmd)
cmd, v = acceso('exit', plate=p1)
check('salida con sesión -> OK', cmd and cmd['reason'] == 'OK' and cmd['access_type'] == 'exit', cmd)
check('salida aprobada -> acceso/evento', tiene(v, 'acceso/evento', plate=p1, access_type='exit'), v)
cmd, _ = acceso('exit', plate=p1)
check('salida sin sesión -> NO_SESSION', cmd and cmd['reason'] == 'NO_SESSION', cmd)
cmd, _ = acceso('entry', plate=p1, rid='RSV-X')
check('placa y QR a la vez -> BAD_REQUEST', cmd and cmd['reason'] == 'BAD_REQUEST', cmd)
cmd, _ = acceso('entry', rid='RSV-NOEXISTE')
check('QR inexistente -> INVALID_RESERVATION', cmd and cmd['reason'] == 'INVALID_RESERVATION', cmd)

# Accesos por QR
qa, qb, pq = f'RSV-VA{RUN}', f'RSV-VB{RUN}', f'V{RUN}Q'
vaciar()
code, body, _ = http('POST', '/reservas', reserva(qa, 'B-003', pq, fecha(5), fecha(65)))
check('reserva en 5 min -> 201 active', code == 201 and body.get('status') == 'active', (code, body))
_, br = esperar(lambda t, p: t == 'bahia/reserva' and p.get('space_id') == 'B-003')
check('reserva active -> bahia/reserva true (amarillo)', br is not None and br[1]['reserved'] is True, br)
cmd, v = acceso('entry', rid=qa)
check('entrada por QR -> OK', cmd and cmd['reason'] == 'OK', cmd)
check('entrada por QR -> acceso/evento con la placa de la reserva', tiene(v, 'acceso/evento', plate=pq, reservation_id=qa), v)
cmd, _ = acceso('entry', plate=pq)
check('placa de la reserva ya adentro -> ACTIVE_SESSION', cmd and cmd['reason'] == 'ACTIVE_SESSION', cmd)
cmd, v = acceso('exit', plate=pq)
check('salida con reserva -> OK', cmd and cmd['reason'] == 'OK', cmd)
check('salida con reserva -> bahia/reserva false', tiene(v, 'bahia/reserva', space_id='B-003', reserved=False), v)
cmd, _ = acceso('entry', rid=qa)
check('QR ya usado (completed) -> INVALID_RESERVATION', cmd and cmd['reason'] == 'INVALID_RESERVATION', cmd)
code, body, _ = http('POST', '/reservas', reserva(qb, 'B-002', f'V{RUN}R', fecha(120), fecha(180)))
check('reserva en 2 h -> 201 reserved', code == 201 and body.get('status') == 'reserved', (code, body))
cmd, _ = acceso('entry', rid=qb)
check('QR fuera de franja -> OUT_OF_WINDOW', cmd and cmd['reason'] == 'OUT_OF_WINDOW', cmd)
vaciar()
code, body, _ = http('DELETE', f'/reservas/{qb}')
check('cancelar reserva reserved -> 200 cancelled', code == 200 and body.get('status') == 'cancelled', (code, body))
_, br = esperar(lambda t, p: t == 'bahia/reserva', 4)
check('cancelar reserva que no estaba vigente -> no publica bahia/reserva', br is None, br)

# Sin bahías
adentro, razon = [], None
for i in range(6):
    p = f'V{RUN}F{i}'
    cmd, _ = acceso('entry', plate=p, extra_seg=0.3)
    if cmd and cmd['reason'] == 'OK':
        adentro.append(p)
    else:
        razon = cmd and cmd['reason']
        break
check(f'parqueadero lleno ({len(adentro)} entraron) -> NO_BAYS', razon == 'NO_BAYS', razon)
for p in adentro:
    acceso('exit', plate=p, extra_seg=0.3)

# ---------------------------------------------------------------- HTTP: reservas (Bruno 1 - Reservas)
print('\n== HTTP reservas (Bruno)')
rA, rB, rC = f'RSV-A{RUN}', f'RSV-B{RUN}', f'RSV-C{RUN}'
pA, pB, pC = f'PA{RUN}', f'PB{RUN}', f'PC{RUN}'
casos = [
    ('01 crear en 5 min -> active', reserva(rA, 'B-001', pA, fecha(5), fecha(65)), 201, {'reservation_id': rA, 'status': 'active'}),
    ('02 ID duplicado', reserva(rA, 'B-003', pC, fecha(30), fecha(90)), 409, {'error': 'DUPLICATE_ID'}),
    ('03 cruce en la bahía', reserva(rB, 'B-001', pB, fecha(30), fecha(90)), 409, {'error': 'OVERLAP'}),
    ('04 misma placa en otra bahía', reserva(rB, 'B-002', pA, fecha(30), fecha(90)), 409, {'error': 'PLATE_OVERLAP'}),
    ('05 crear en 2 h -> reserved', reserva(rC, 'B-003', pC, fecha(120), fecha(180)), 201, {'reservation_id': rC, 'status': 'reserved'}),
    ('06 bahía inexistente', reserva(rB, 'B-999', pB, fecha(30), fecha(90)), 404, {'error': 'INVALID_BAY'}),
    ('07 fechas al revés', reserva(rB, 'B-003', pB, fecha(90), fecha(30)), 400, {'error': 'BAD_REQUEST'}),
    ('08 franja ya terminada', reserva(rB, 'B-003', pB, fecha(-120), fecha(-60)), 400, {'error': 'BAD_REQUEST'}),
    ('10 fecha sin zona horaria', reserva(rB, 'B-003', pB, '2030-01-01T08:00:00', '2030-01-01T10:00:00'), 400, {'error': 'BAD_REQUEST'}),
    ('11 placa inválida', reserva(rB, 'B-003', 'A!B#1', fecha(30), fecha(90)), 400, {'error': 'BAD_REQUEST'}),
]
for nombre, cuerpo, esperado, campos in casos:
    code, body, _ = http('POST', '/reservas', cuerpo)
    ok = code == esperado and isinstance(body, dict) and all(body.get(k) == v for k, v in campos.items())
    check(nombre, ok, (code, body))

sin_placa = reserva(rB, 'B-003', pB, fecha(30), fecha(90))
del sin_placa['plate']
code, body, _ = http('POST', '/reservas', sin_placa)
check('09 faltan campos (detalle menciona plate)', code == 400 and body.get('error') == 'BAD_REQUEST' and 'plate' in body.get('detail', ''), (code, body))
code, body, _ = http('POST', '/reservas', 'esto no es json', 'text/plain')
check('12 cuerpo no JSON', code == 400 and isinstance(body, dict) and body.get('error') == 'BAD_REQUEST', (code, body))
for nombre, ruta, esperado, campos in [
    ('13 cancelar reserva active', f'/reservas/{rA}', 200, {'status': 'cancelled'}),
    ('14 cancelar reserva reserved', f'/reservas/{rC}', 200, {'status': 'cancelled'}),
    ('15 cancelar otra vez', f'/reservas/{rA}', 409, {'error': 'NOT_CANCELLABLE'}),
    ('16 cancelar inexistente', '/reservas/RSV-NOEXISTE', 404, {'error': 'NOT_FOUND'}),
]:
    code, body, _ = http('DELETE', ruta)
    check(nombre, code == esperado and all(body.get(k) == v for k, v in campos.items()), (code, body))

# ---------------------------------------------------------------- HTTP: consulta (app)
print('\n== HTTP consulta (app)')
code, body, h = http('GET', '/parqueaderos')
check('GET /parqueaderos -> lista con total_bays y free_now',
      code == 200 and any(f['node_id'] == NODE and 'free_now' in f for f in body), (code, body))
check('GET /parqueaderos trae CORS', h.get('Access-Control-Allow-Origin') == '*', dict(h))
code, body, _ = http('GET', f'/parqueaderos/{NODE}/bahias')
check('GET bahías -> booleanos sensor_status/reserved_now/available',
      code == 200 and all(isinstance(b[k], bool) for b in body for k in ('sensor_status', 'reserved_now', 'available')), (code, body))
q = urllib.parse.urlencode({'desde': fecha(60), 'hasta': fecha(120)})
code, body, _ = http('GET', f'/parqueaderos/{NODE}/bahias?{q}')
check('GET bahías con franja -> 200', code == 200 and len(body) >= 3, (code, body))
code, body, _ = http('GET', f'/parqueaderos/{NODE}/bahias?desde=' + urllib.parse.quote(fecha(60)))
check('GET bahías solo con desde -> 400', code == 400 and body.get('error') == 'BAD_REQUEST', (code, body))
code, body, _ = http('GET', '/parqueaderos/NOEXISTE/bahias')
check('GET bahías de nodo inexistente -> 404', code == 404 and body.get('error') == 'NOT_FOUND', (code, body))
code, body, _ = http('GET', f'/reservas/{rA}')
check('GET /reservas/:id -> detalle con fechas -05:00',
      code == 200 and body.get('reservation_id') == rA and body.get('starts_at', '').endswith('-05:00'), (code, body))
code, body, _ = http('GET', '/reservas/RSV-NOEXISTE')
check('GET /reservas/:id inexistente -> 404', code == 404, (code, body))
code, body, _ = http('GET', '/reservas')
check('GET /reservas sin filtros -> 400', code == 400 and body.get('error') == 'BAD_REQUEST', (code, body))
code, body, _ = http('GET', f'/reservas?placa={pA.lower()}')
check('GET /reservas?placa (normaliza) -> 200', code == 200 and any(r['reservation_id'] == rA for r in body), (code, body))
code, body, _ = http('GET', '/reservas?status=volando')
check('GET /reservas?status inválido -> 400', code == 400, (code, body))

# ---------------------------------------------------------------- App web, agenda, bahía libre ahora, tolerancia
print('\n== App web y reglas de reserva')
code, _, h = None, None, None
req = urllib.request.Request(BASE + '/app')
opener = urllib.request.build_opener(type('SinRedireccion', (urllib.request.HTTPRedirectHandler,),
                                          {'redirect_request': lambda *a, **k: None}))
try:
    opener.open(req, timeout=10)
except urllib.error.HTTPError as e:
    code, h = e.code, e.headers
check('GET /app -> 302 a /app/index.html', code == 302 and h.get('Location') == '/app/index.html', (code, h and h.get('Location')))
for archivo, tipo in [('index.html', 'text/html'), ('admin.html', 'text/html'), ('estilos.css', 'text/css'),
                      ('comun.js', 'text/javascript'), ('usuario.js', 'text/javascript'), ('admin.js', 'text/javascript')]:
    code, body, h = http('GET', f'/app/{archivo}')
    check(f'GET /app/{archivo} -> 200 {tipo}', code == 200 and h.get('Content-Type', '').startswith(tipo), (code, h.get('Content-Type')))
code, body, _ = http('GET', '/app/flow.json')
check('GET /app/<archivo fuera de la lista> -> 404', code == 404, code)
code, body, _ = http('GET', '/app/..%2F..%2Fnode-red-flow%2Fflow.json')
check('GET /app con ../ -> 404', code == 404, code)

# Agenda (línea de tiempo): sin placas, solo reservas vivas del día
rD, pD = f'RSV-D{RUN}', f'PD{RUN}'
ini_d, fin_d = fecha(120), fecha(180)
code, body, _ = http('POST', '/reservas', reserva(rD, 'B-002', pD, ini_d, fin_d))
check('reserva para la agenda (en 2 h) -> 201', code == 201, (code, body))
code, body, _ = http('GET', f'/parqueaderos/{NODE}/agenda?fecha={ini_d[:10]}')
mia = [r for r in body if r.get('starts_at') == ini_d and r.get('space_id') == 'B-002'] if code == 200 else []
check('GET agenda -> incluye la reserva del día', code == 200 and len(mia) == 1, (code, body))
check('GET agenda -> no expone placa ni código', code == 200 and all('plate' not in r and 'reservation_id' not in r for r in body), body)
code, body, _ = http('GET', f'/parqueaderos/{NODE}/agenda?fecha=2026-13-01')
check('GET agenda con fecha inválida -> 400', code == 400 and body.get('error') == 'BAD_REQUEST', (code, body))
http('DELETE', f'/reservas/{rD}')
code, body, _ = http('GET', f'/parqueaderos/{NODE}/agenda?fecha={ini_d[:10]}')
check('GET agenda -> la cancelada ya no aparece', code == 200 and not any(r.get('starts_at') == ini_d and r.get('space_id') == 'B-002' for r in body), body)

# Bahía con carro ahora: no se puede reservar para ya, sí para mañana
publicar('bahia/sensor', {'node_id': NODE, 'space_id': 'B-003', 'sensor_status': True})
time.sleep(2.5)
code, body, _ = http('POST', '/reservas', reserva(f'RSV-E{RUN}', 'B-003', f'PE{RUN}', fecha(2), fecha(62)))
check('reservar para ya una bahía con carro -> 409 OVERLAP', code == 409 and body.get('error') == 'OVERLAP', (code, body))
q = urllib.parse.urlencode({'desde': fecha(0), 'hasta': fecha(60)})
code, body, _ = http('GET', f'/parqueaderos/{NODE}/bahias?{q}')
b3 = next((b for b in body if b['space_id'] == 'B-003'), {}) if code == 200 else {}
check('franja que empieza ya -> bahía con carro no disponible', b3.get('available') is False, (code, body))
q = urllib.parse.urlencode({'desde': fecha(24 * 60), 'hasta': fecha(25 * 60)})
code, body, _ = http('GET', f'/parqueaderos/{NODE}/bahias?{q}')
b3 = next((b for b in body if b['space_id'] == 'B-003'), {}) if code == 200 else {}
check('franja de mañana -> la misma bahía sí disponible', b3.get('available') is True, (code, body))
publicar('bahia/sensor', {'node_id': NODE, 'space_id': 'B-003', 'sensor_status': False})
time.sleep(2.5)

# Tolerancia: sin llegada 15 min después del inicio -> expired y amarillo OFF
rT = f'RSV-T{RUN}'
code, body, _ = http('POST', '/reservas', reserva(rT, 'B-001', f'PT{RUN}', fecha(-20), fecha(40)))
check('reserva que empezó hace 20 min -> 201 active', code == 201 and body.get('status') == 'active', (code, body))
time.sleep(1.5)
vaciar()
http('POST', '/inject/v_tick')
_, br = esperar(lambda t, p: t == 'bahia/reserva' and p.get('space_id') == 'B-001' and p.get('reserved') is False, 8)
code, body, _ = http('GET', f'/reservas/{rT}')
check('revisión: sin llegada a los 15 min -> expired', code == 200 and body.get('status') == 'expired', (code, body))
check('revisión: sin llegada -> bahia/reserva false (amarillo OFF)', br is not None, br)

# ---------------------------------------------------------------- HTTP: análisis (Bruno 2 - Analisis)
print('\n== HTTP análisis (Bruno)')
code, body, h = http('GET', '/api/nodos')
check('01 /api/nodos -> lista', code == 200 and isinstance(body, list), (code, body))
check('01 /api/nodos trae CORS', h.get('Access-Control-Allow-Origin') == '*', dict(h))
code, body, _ = http('GET', '/api/resumen/TODOS')
check('02 /api/resumen/TODOS -> lista', code == 200 and isinstance(body, list), (code, body))
code, body, _ = http('GET', '/api/resumen/PARKING-002')
check('03 /api/resumen/PARKING-002 -> lista', code == 200 and isinstance(body, list), (code, body))
code, body, _ = http('GET', '/api/resumen/NO-EXISTE')
check('04 nodo inexistente -> []', code == 200 and body == [], (code, body))
code, body, _ = http('GET', '/api/resumen/%27%20OR%20%271%27%3D%271')
check('05 intento de SQL injection -> []', code == 200 and body == [], (code, body))
code, body, _ = http('GET', '/api/horas/TODOS')
check('06 /api/horas -> 24 horas ordenadas si hay datos',
      code == 200 and (not body or [f['hour'] for f in body] == list(range(24))), (code, str(body)[:200]))
code, body, _ = http('GET', '/api/dias/TODOS')
check('07 /api/dias -> day YYYY-MM-DD',
      code == 200 and all(len(f['day']) == 10 and f['day'][4] == '-' for f in body), (code, str(body)[:200]))
code, body, _ = http('GET', '/api/categorias/TODOS')
check('08 /api/categorias -> categorías válidas',
      code == 200 and all(f['category'] in ('estado_reserva', 'modo_acceso', 'tipo_estadia') for f in body), (code, str(body)[:200]))
code, body, _ = http('GET', '/api/no-existe')
check('09 ruta inexistente -> 404', code == 404, code)

cli.loop_stop()
fallas = [n for n, ok in resultados if not ok]
print(f'\n{len(resultados) - len(fallas)}/{len(resultados)} validaciones OK')
for n in fallas:
    print('  FALLA:', n)
sys.exit(1 if fallas else 0)
