import { Aedes } from 'aedes';
import net from 'node:net';
import dotenv from 'dotenv';

dotenv.config();

// Configuración del puerto del broker MQTT.
const PORT = Number(process.env.MQTT_PORT);
const HOST = process.env.MQTT_BIND_HOST ;
// Creación del broker MQTT.
const aedes = await Aedes.createBroker();
const server = net.createServer(aedes.handle);

// --------------------------------------------
//           Eventos del broker MQTT
// --------------------------------------------

// Conexión de clientes al broker.
aedes.on('client', (client) => {
    console.log(`[AEDES] Cliente conectado: ${client.id}`);
});
// Cliente listo para publicar y suscribirse.
aedes.on('clientReady', (client) => {
    console.log(`[AEDES] Cliente listo: ${client.id}`);
});
// Cliente desconectado del broker.
aedes.on('clientDisconnect', (client) => {
    console.log(`[AEDES] Cliente desconectado: ${client.id}`);
});
// Error en la conexión del cliente.
aedes.on('clientError', (client, error) => {
    console.error(`[AEDES] Error del cliente ${client?.id}:`, error);
});
// Error en la conexión del broker.
aedes.on('connectionError', (client, error) => {
    console.error(`[AEDES] Error de conexión:`, error);
});
// Evento de envío de CONNACK (mensaje de reconocimiento de conexión (Connection Acknowledgment)).
aedes.on('connackSent', (packet, client) => {
    console.log(`[AEDES] CONNACK enviado a: ${client.id}`);
});
// Evento de publicación de mensajes.
aedes.on('publish', (packet, client) => {
    if (client) {
        console.log(
            `[AEDES] PUBLICACIÓN: ${packet.topic} | ${packet.payload.toString()}`
        );
    }
});
// Evento de subscripción de clientes a topics.
aedes.on('subscribe', (subscriptions, client) => {
  console.log(`[AEDES] Cliente ${client.id} suscrito a: ${subscriptions.map((s) => s.topic).join(', ')}`);
});
// Evento de error del servidor.
server.on('error', (error) => {
    console.error('[BROKER] Error del servidor:', error);
});

// Inicia el servidor del broker MQTT.
server.listen(PORT, HOST, () => {
    console.log(`[BROKER] MQTT escuchando en ${HOST}:${PORT}`);
});