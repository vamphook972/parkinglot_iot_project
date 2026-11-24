import json
import time
import paho.mqtt.client as mqtt

BROKER = "broker.emqx.io"
NODE_ID = "PARKING-101"  # ID propio para simulados, distinto de los físicos
STATUS_TOPIC = f"parqueadero/{NODE_ID}/status"

client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"parking-iot-{NODE_ID}",  # único en el broker público
)

# Last Will: el broker lo publica si este cliente se cae sin avisar
client.will_set(STATUS_TOPIC, payload="offline", qos=1, retain=True)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        # anuncio con las bahías (ajusta al JSON que definas)
        announce = {"node_id": NODE_ID, "bays": ["B-001", "B-002", "B-003"]}
        client.publish(f"parqueadero/{NODE_ID}/anuncio", json.dumps(announce), qos=1)
        print("Conectado y anunciado")
    else:
        print("Fallo al conectar:", reason_code)

client.on_connect = on_connect

client.connect(BROKER, 1883, keepalive=20)
client.loop_start()

try:
    while True:
        time.sleep(1)  # aquí iría la simulación de sensores
except KeyboardInterrupt:
    # salida limpia: con disconnect() normal el broker NO envía el will,
    # así que publicamos "offline" a mano antes de salir
    client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish()
    client.disconnect()
    client.loop_stop()
