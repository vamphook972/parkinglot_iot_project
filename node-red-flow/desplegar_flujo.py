"""Sube node-red-flow/flow.json al Node-RED que está corriendo, sin reiniciarlo.

Solo cambia los nodos de la pestaña "Parqueadero IoT". Las demás pestañas, los nodos de
configuración y las credenciales no se tocan. Antes guarda un respaldo de todos los flujos.

Uso (desde la raíz del repo):  python3 node-red-flow/desplegar_flujo.py
Si el editor tiene contraseña (adminAuth), la pide por consola y no la guarda.
"""
import getpass
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.getenv('NODE_RED', 'http://localhost:1880')
TAB = 'parqueadero_unico'
NUEVO = json.loads((pathlib.Path(__file__).parent / 'flow.json').read_text())


def pedir(metodo, ruta, cuerpo=None, token=None, **cab):
    h = {'Node-RED-API-Version': 'v2', **cab}
    datos = None
    if isinstance(cuerpo, dict):
        datos, h['Content-Type'] = json.dumps(cuerpo).encode(), 'application/json'
    elif cuerpo:
        datos, h['Content-Type'] = cuerpo.encode(), 'application/x-www-form-urlencoded'
    if token:
        h['Authorization'] = 'Bearer ' + token
    with urllib.request.urlopen(urllib.request.Request(BASE + ruta, datos, h, method=metodo), timeout=20) as r:
        t = r.read().decode()
        return json.loads(t) if t else None


def main():
    token = None
    if pedir('GET', '/auth/login'):
        user = input('Usuario del editor [admin]: ').strip() or 'admin'
        clave = getpass.getpass('Contraseña (no se ve al escribir): ')
        token = pedir('POST', '/auth/token', urllib.parse.urlencode({
            'client_id': 'node-red-admin', 'grant_type': 'password', 'scope': '*',
            'username': user, 'password': clave}))['access_token']

    actual = pedir('GET', '/flows', token=token)
    respaldo = pathlib.Path.home() / '.node-red' / f'flows_respaldo_{time.strftime("%Y%m%d_%H%M%S")}.json'
    respaldo.write_text(json.dumps(actual['flows'], ensure_ascii=False, indent=4))

    mios = {n['id']: n for n in NUEVO if n.get('z') == TAB}
    if not any(n['id'] == TAB for n in actual['flows']):
        sys.exit('No encontré la pestaña "Parqueadero IoT": importa flow.json desde el editor.')
    flujos = [mios.pop(n['id'], n) for n in actual['flows']]
    flujos += mios.values()                        # nodos nuevos
    sobran = [n['id'] for n in actual['flows'] if n.get('z') == TAB and n['id'] not in {x['id'] for x in NUEVO}]
    pedir('POST', '/flows', {'flows': flujos, 'rev': actual['rev']}, token=token,
          **{'Node-RED-Deployment-Type': 'nodes'})
    print(f'Listo: {len(mios)} nodos nuevos. Respaldo en {respaldo}')
    if sobran:
        print(f'En el editor hay {len(sobran)} nodos que no están en flow.json; no los borré: {sobran}')


try:
    main()
except urllib.error.HTTPError as e:
    sys.exit({401: 'Usuario o contraseña incorrectos.', 403: 'Usuario o contraseña incorrectos.',
              409: 'Los flujos cambiaron mientras se subían; vuelve a intentarlo.'}.get(e.code, f'Node-RED respondió {e.code}: {e.read().decode()[:300]}'))
except urllib.error.URLError as e:
    sys.exit(f'No hay conexión con Node-RED en {BASE}: {e.reason}')
