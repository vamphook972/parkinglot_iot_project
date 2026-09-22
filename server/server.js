import express from 'express';
import http from 'http';
import { Server } from 'socket.io';
import cors from 'cors';
import mqtt from 'mqtt';
import dotenv from 'dotenv';

dotenv.config();

// Configuración del servidor Express y Socket.IO
const app = express();
const server = http.createServer(app);
const io = new Server(server);
const PORT = Number(process.env.PORT);

// Configuración de la conexión al Broker MQTT independiente
const MQTT_HOST = process.env.MQTT_HOST;
const MQTT_PORT = Number(process.env.MQTT_PORT);
const MQTT_BROKER = `mqtt://${MQTT_HOST}:${MQTT_PORT}`;
const mqttClient = mqtt.connect(MQTT_BROKER, {
    clientId: process.env.MQTT_CLIENT_ID,
    reconnectPeriod:Number(process.env.MQTT_RECONNECT_PERIOD)
});

// Definición de los topics MQTT
const TOPIC_BAHIA = process.env.MQTT_TOPIC_BAHIA;
const TOPIC_ACCESO = process.env.MQTT_TOPIC_ACCESO;
const TOPIC_RESERVA = process.env.MQTT_TOPIC_RESERVA;

// Middleware
app.use(cors());
app.use(express.json());

// Estado global de la reserva
let reservaActual = {
  reservation_id: null,
  active: false,
  userName: null,
  plate: null
};

// Generador de código aleatorio
function generarCodigo(longitud = 6) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let res = '';
  for (let i = 0; i < longitud; i++) res += chars.charAt(Math.floor(Math.random() * chars.length));
  return res;
}

// --------------------------------------------
//             EVENTOS MQTT
// --------------------------------------------

mqttClient.on('connect', () => {
  console.log('[MQTT CLIENT] Servidor Web conectado exitosamente al Broker');
  // Suscripción a los eventos generados por el ESP32
  mqttClient.subscribe(TOPIC_BAHIA);
  mqttClient.subscribe(TOPIC_ACCESO);
});

mqttClient.on('message', (topic, message) => {
  try {
    const payload = JSON.parse(message.toString());
    console.log(`[MQTT IN] (${topic}):`, payload);

    if (topic === TOPIC_BAHIA) {
      if (payload.status === 'occupied') {
        io.emit('bahia_ocupada', { 
          teniaReserva: reservaActual.active, 
          reservation_id: reservaActual.reservation_id,
          userName: reservaActual.userName
        });
      } else if (payload.status === 'available' || payload.status === 'reserved') {
        io.emit('reserva_actualizada', reservaActual);
      }
    }
  } catch (err) {
    console.error('[MQTT Error] Mensaje recibido con formato inválido:', err.message);
  }
});

// Función para notificar cambios de reserva al ESP32 por MQTT
function publicarEstadoReserva() {
  const payload = JSON.stringify({
    reservation_id: reservaActual.reservation_id,
    active: reservaActual.active,
    plate: reservaActual.plate
  });

  // retain: true asegura que si el ESP32 se reinicia, reciba el último estado inmediatamente
  mqttClient.publish(TOPIC_RESERVA,payload,{ retain: true });
}

// --------------------------------------------
//             RUTAS HTTP Y SOCKET.IO
// --------------------------------------------

// Crear reserva
app.post('/api/reservar', (req, res) => {
  const { userName, plate } = req.body;

  if (!userName || !plate) {
    return res.status(400).json({ error: 'Debes ingresar tu nombre y la placa del vehículo.' });
  }

  const codigo = generarCodigo(6);
  reservaActual = {
    reservation_id: codigo,
    active: true,
    userName: userName.trim(),
    plate: plate.trim().toUpperCase()
  };

  console.log(`[SERVIDOR] Nueva reserva: ${reservaActual.userName} (${reservaActual.plate}) -> ${codigo}`);
  
  publicarEstadoReserva();
  io.emit('reserva_actualizada', reservaActual);
  res.json({ message: 'Reserva creada', codigo, plate: reservaActual.plate });
});

// Cancelar reserva
app.post('/api/cancelar', (req, res) => {
  console.log(`[SERVIDOR] Reserva cancelada: ${reservaActual.reservation_id}`);
  reservaActual = { reservation_id: null, active: false, userName: null, plate: null };
  
  publicarEstadoReserva();
  io.emit('reserva_actualizada', reservaActual);
  res.json({ message: 'Reserva cancelada' });
});

// Confirmar llegada del usuario
app.post('/api/confirmar-llegada', (req, res) => {
  console.log(`[SERVIDOR] Reserva ${reservaActual.reservation_id} confirmada por el usuario.`);
  reservaActual = { reservation_id: null, active: false, userName: null, plate: null };
  
  publicarEstadoReserva();
  io.emit('reserva_actualizada', reservaActual);
  res.json({ status: 'ok' });
});

// Reportar infracción
app.post('/api/reportar-infraccion', (req, res) => {
  console.log(`[SEGURIDAD] Alerta: Bahía ocupada sin autorización.`);
  res.json({ status: 'ok' });
});

// Interfaz Web HTML (Mantiene la misma interfaz)
app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <title>Gestión de Reservas - Bahía B-001</title>
      <script src="/socket.io/socket.io.js"></script>
      <style>
        body { font-family: sans-serif; text-align: center; margin-top: 30px; background: #f4f4f9; }
        .card { background: white; padding: 25px; display: inline-block; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); width: 360px; }
        .input-group { margin-bottom: 12px; text-align: left; }
        .input-group label { display: block; font-size: 13px; font-weight: bold; margin-bottom: 4px; color: #333; }
        .input-group input { width: 100%; padding: 8px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
        .btn { padding: 10px 18px; font-size: 15px; cursor: pointer; border: none; border-radius: 5px; margin: 5px 2px; }
        .btn-green { background: #28a745; color: white; }
        .btn-red { background: #dc3545; color: white; }
        .btn-blue { background: #007bff; color: white; }
        
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 1000; }
        .modal { background: white; width: 330px; padding: 25px; border-radius: 12px; margin: 12% auto; position: relative; box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
        .timer { font-size: 24px; font-weight: bold; color: #e74c3c; margin: 12px 0; }
        .alert-security { color: #721c24; background-color: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; border-radius: 5px; display: none; margin-top: 15px; }
      </style>
    </head>
    <body>

      <div class="card">
        <h1>Bahía B-001</h1>

        <div id="formReserva">
          <div class="input-group">
            <label for="userName">Nombre del Usuario:</label>
            <input type="text" id="userName" placeholder="Ej: Carlos Pérez">
          </div>
          <div class="input-group">
            <label for="plate">Placa del Vehículo:</label>
            <input type="text" id="plate" placeholder="Ej: ABC123" maxlength="6">
          </div>
          <button class="btn btn-green" onclick="crearReserva()">Generar Reserva</button>
        </div>

        <button class="btn btn-red" id="btnCancelar" style="display:none;" onclick="cancelarReserva()">Cancelar Reserva</button>
        <h2 id="codigo">Sin reserva activa</h2>
      </div>

      <div id="modalConfirmacion" class="modal-overlay">
        <div class="modal">
          <h3 id="modalTitulo">¿Ocupaste tu reserva?</h3>
          <p id="modalTexto">Detectamos que la bahía acaba de ser ocupada.</p>
          <div class="timer" id="timer">60s</div>
          <button class="btn btn-blue" onclick="confirmarLlegada(true)">Sí, ya llegué</button>
          <button class="btn btn-red" onclick="confirmarLlegada(false)">No fui yo</button>
          <div id="alertaSeguridad" class="alert-security">
            ⚠️ Informando del inconveniente a seguridad...
          </div>
        </div>
      </div>

      <script>
        const socket = io();
        let tiempoRestante = 60;
        let intervaloTimer = null;
        let reservaActivaMemoria = null;

        async function crearReserva() {
          const userName = document.getElementById('userName').value;
          const plate = document.getElementById('plate').value;

          if (!userName || !plate) {
            alert("Por favor completa tu nombre y la placa.");
            return;
          }

          const res = await fetch('/api/reservar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ userName, plate })
          });

          const data = await res.json();
          if (res.ok) {
            actualizarInterfazReserva(data.codigo, userName, data.plate);
          } else {
            alert(data.error);
          }
        }

        async function cancelarReserva() {
          await fetch('/api/cancelar', { method: 'POST' });
          reservaActivaMemoria = null;
          document.getElementById('formReserva').style.display = 'block';
          document.getElementById('btnCancelar').style.display = 'none';
          document.getElementById('codigo').innerText = 'Sin reserva activa';
        }

        socket.on('bahia_ocupada', (data) => {
          if (data.teniaReserva) {
            abrirModal(data.userName);
          } else {
            document.getElementById('codigo').innerText = 'Bahía Ocupada (Sin reserva)';
          }
        });

        socket.on('reserva_actualizada', (data) => {
          if (!data.active) {
            reservaActivaMemoria = null;
            document.getElementById('formReserva').style.display = 'block';
            document.getElementById('btnCancelar').style.display = 'none';
            document.getElementById('codigo').innerText = 'Sin reserva activa';
          } else {
            actualizarInterfazReserva(data.reservation_id, data.userName, data.plate);
          }
        });

        function actualizarInterfazReserva(codigo, usuario, placa) {
          reservaActivaMemoria = { codigo, usuario, placa };
          document.getElementById('formReserva').style.display = 'none';
          document.getElementById('btnCancelar').style.display = 'inline-block';
          document.getElementById('codigo').innerText = 'Código: ' + codigo + ' (' + placa + ')';
        }

        function abrirModal(nombreUsuario) {
          document.getElementById('modalConfirmacion').style.display = 'block';
          document.getElementById('alertaSeguridad').style.display = 'none';
          document.getElementById('modalTitulo').innerText = 'Hola ' + (nombreUsuario || '') + ', ¿ocupaste tu lugar?';
          
          tiempoRestante = 60;
          document.getElementById('timer').innerText = tiempoRestante + 's';

          clearInterval(intervaloTimer);
          intervaloTimer = setInterval(() => {
            tiempoRestante--;
            document.getElementById('timer').innerText = tiempoRestante + 's';
            if (tiempoRestante <= 0) {
              confirmarLlegada(true);
            }
          }, 1000);
        }

        async function confirmarLlegada(fueElUsuario) {
          clearInterval(intervaloTimer);
          
          if (fueElUsuario) {
            await fetch('/api/confirmar-llegada', { method: 'POST' });
            document.getElementById('modalConfirmacion').style.display = 'none';
            document.getElementById('codigo').innerText = 'Vehículo en Bahía';
          } else {
            await fetch('/api/reportar-infraccion', { method: 'POST' });
            document.getElementById('alertaSeguridad').style.display = 'block';
            setTimeout(() => {
              document.getElementById('modalConfirmacion').style.display = 'none';
              if (reservaActivaMemoria) {
                actualizarInterfazReserva(reservaActivaMemoria.codigo, reservaActivaMemoria.usuario, reservaActivaMemoria.placa);
              }
            }, 3000);
          }
        }
      </script>
    </body>
    </html>
  `);
});

server.listen(PORT, () => {
  console.log(`[SERVIDOR WEB] Ejecutándose en http://localhost:${PORT}`);
});