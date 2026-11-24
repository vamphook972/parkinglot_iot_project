# Parking IoT

Sistema de parqueaderos inteligentes. Cada parqueadero es un nodo IoT, sea un ESP32 o un simulador en Python, que reporta por MQTT la ocupación de sus bahías y controla la entrada con placa o QR. Node-RED recibe esos mensajes, los guarda en MariaDB, gestiona las reservas y sirve una API REST con dos páginas web:

- **Página del usuario:** muestra en vivo los parqueaderos y sus bahías y permite reservar. Tiene una línea de tiempo para reservar una bahía después de que termine la reserva que ya tiene, y entrega un QR para entrar.
- **Panel de administración:** muestra los datos en vivo y la lista de reservas, incluidas las canceladas. También trae el análisis de ocupación, horas pico, días, reservas, accesos y estadía.

Página publicada: https://vamphook972.github.io/parkinglot_iot_project/

## Arquitectura

```
ESP32 / nodo_simulado.py ──MQTT (test.mosquitto.org)──► Node-RED ◄──► MariaDB (parking_db)
                                                           │
                                     API REST + /app ──────┤
                                                           ▼
                        Túnel de Cloudflare ──► GitHub Pages (página del usuario)
```

Los tópicos MQTT siguen la forma `parqueadero/{node_id}/...`:

| Tópico | Contenido |
|---|---|
| `registro` | Anuncio del nodo y de sus bahías. |
| `bahia/sensor` | Cambio de ocupación de una bahía. |
| `acceso/input` → `acceso/cmd` | Solicitud de entrada o salida y la respuesta. |
| `bahia/reserva` | Enciende o apaga el LED de la bahía reservada. |

## Estructura

| Carpeta | Contenido |
|---|---|
| `node-red-flow/` | `flow.json` (flujo único de Node-RED) y `validar_flujo.py` (pruebas de punta a punta). |
| `parking-app/` | Las páginas web y `publicar_pages.sh`, que publica la página del usuario en GitHub Pages. |
| `simulation_node/` | `nodo_simulado.py` (simula un ESP32) y los generadores de historial con su SQL. |
| `sql_schemas/` | Esquema de la base: tablas crudas, capa limpia y tablas de análisis. |
| `REST_methods/` | Colección de Bruno: una petición por cada ruta de la API. |

## Puesta en marcha

### 1. Base de datos

1. Levanta MariaDB (o MySQL 8.0.16 o superior). Por ejemplo, con Docker en un contenedor `my-mariadb`.
2. Carga los esquemas en este orden: `sql_schemas/parking_db.sql`, `clean_data.sql` y `analytics_data.sql`.
3. Ajusta la zona horaria de Colombia:

   ```sql
   SET GLOBAL time_zone = '-05:00';
   ```

4. Si quieres datos de prueba, carga `simulation_node/historial_parking002.sql` (desde el 7 de septiembre) e `historial_parking003.sql` (desde el 5 de octubre). Los genera `generar_datos.py`, que acepta cualquier nodo y fecha de inicio. El nodo debe haberse registrado antes.

### 2. Node-RED

1. Importa `node-red-flow/flow.json`. Necesitas el paquete `node-red-node-mysql`.
2. Configura la conexión a `parking_db` en el nodo de MySQL.
3. En el nodo **web_ruta**, ajusta la ruta `CARPETA` a la carpeta `parking-app/` de tu equipo.

Con eso las páginas quedan en:

- **Usuario:** http://localhost:1880/app
- **Administración:** http://localhost:1880/app/admin.html

En `~/.node-red/settings.js` hay dos ajustes:

- **`adminAuth`:** protege el editor con usuario y contraseña. El hash se genera con `node-red admin hash-pw`.
- **`httpNodeCors`:** permite que la página de GitHub Pages llame a la API.

  ```js
  httpNodeCors: {
      origin: ['https://vamphook972.github.io', 'http://localhost:1880'],
      methods: 'GET,POST,DELETE'
  },
  ```

Para subir después los cambios de `flow.json` a un Node-RED que ya tiene la pestaña (pide la contraseña del editor y guarda un respaldo):

```bash
python3 node-red-flow/desplegar_flujo.py
```

### 3. Nodo simulado

```bash
cd simulation_node
python3 -m venv .venv && .venv/bin/pip install "paho-mqtt>=2.0"
.venv/bin/python nodo_simulado.py --node-id PARKING-002 --bays B-001,B-002,B-003
```

### 4. Publicar la página del usuario

1. Abre el túnel hacia Node-RED:

   ```bash
   cloudflared tunnel --url http://localhost:1880
   ```

2. Publica con la URL que te da el túnel:

   ```bash
   parking-app/publicar_pages.sh https://xxxx.trycloudflare.com
   ```

El script actualiza `config.js`, hace push a `main` y publica la rama `gh-pages`. El túnel rápido cambia de URL cada vez que se reinicia, así que hay que repetir este paso cada vez. Solo se publica la página del usuario: el panel de administración muestra placas y permite cancelar reservas, por eso se queda en local.

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/parqueaderos` | Parqueaderos con su resumen de bahías. |
| GET | `/parqueaderos/:node_id/bahias` | Bahías de un parqueadero. Acepta una franja para ver la disponibilidad. |
| GET | `/parqueaderos/:node_id/agenda?fecha=AAAA-MM-DD` | Reservas del día por bahía, sin placas. |
| POST | `/reservas` | Crea una reserva. |
| GET | `/reservas`, `/reservas/:id` | Consulta reservas, por estado o por placa. |
| DELETE | `/reservas/:id` | Cancela una reserva. |
| GET | `/api/nodos`, `/api/resumen/:nodo`, `/api/horas/:nodo`, `/api/dias/:nodo`, `/api/categorias/:nodo` | Análisis guardado (todo el historial hasta ayer). |
| GET | `/api/analisis?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Análisis de un periodo, calculado al momento. No guarda nada. |

### Limpieza y análisis

Corren cada noche a la 1:00 a. m.: primero la limpieza y, si termina bien, el análisis. Node-RED tiene que estar encendido a esa hora; si no, se corren con los botones *Correr limpieza* y *Correr análisis* del flujo. El panel de administración permite ver el análisis de todo el historial o de un rango de fechas.

### Estados de una reserva

| Estado | Cuándo |
|---|---|
| `reserved` | Programada. |
| `active` | Faltan 10 minutos o menos para que empiece. La bahía queda apartada y el LED se enciende. |
| `entered` | El carro entró con la placa o el QR. |
| `completed` | El carro salió. |
| `expired` | El carro no llegó en los 10 minutos de tolerancia, o la franja terminó. |
| `cancelled` | El usuario o el administrador la canceló. |

## Pruebas

```bash
NODE_RED_USER=admin NODE_RED_PASS='...' simulation_node/.venv/bin/python node-red-flow/validar_flujo.py
```

Recorre el flujo completo: MQTT, accesos, reservas y sus reglas, tolerancia de llegada, limpieza, análisis y las páginas web. Usa el parqueadero temporal PARKING-TEST; el docstring del script trae el SQL para borrarlo al terminar.
