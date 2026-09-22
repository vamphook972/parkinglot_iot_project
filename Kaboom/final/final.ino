#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "time.h"
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Keypad.h>
#include "config.h"

// Configuración Wi-Fi y Servidor Node.js
const char* ssid             = WIFI_SSID;
const char* password         = WIFI_PASSWORD;
const char* serverStatusUrl  = SERVER_STATUS_URL;
const char* serverEventUrl   = SERVER_EVENT_URL;

// Servidor NTP (para sincronización de fecha y hora).
const char* ntpServer        = NTP_SERVER;
const long gmtOffset_sec     = GMT_OFFSET_SEC;
const int daylightOffset_sec  = DAYLIGHT_OFFSET;

// --------------------------------------------
//            Asignación de Pines.
// --------------------------------------------

// Control de Acceso:

// Sensores Infrarrojos.
const int SENSOR_ENTRADA_PIN = 18;
const int SENSOR_SALIDA_PIN  = 19;

// Configuración LCD e I2C.
LiquidCrystal_I2C lcd(0x27, 16, 2);

// --- Configuración Teclado Matricial.
const byte ROWS = 4;
const byte COLS = 4;

char keys[ROWS][COLS] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};

byte rowPins[ROWS] = {13, 12, 14, 27};
byte colPins[COLS] = {26, 25, 33, 32}; 

Keypad keypad = Keypad(makeKeymap(keys), rowPins, colPins, ROWS, COLS);

const char* keyMap[10] = {
  "0", "1ABC", "2DEF", "3GHI", "4JKL", 
  "5MNO", "6PQR", "7STU", "8VWX", "9YZ"
};

// Bahía:

// Botón y LEDs (El Botón simula el VL53L0X)
const int pinBoton           = 4;   
const int pinLedVerde        = 5;
const int pinLedAmarillo     = 17;
const int pinLedRojo         = 16;

// --------------------------------------------
//           Variables Globales.
// --------------------------------------------

// Estados del Control de Acceso.
enum EstadoSistema { 
  INICIO, 
  MODO_PLACA, 
  MODO_RESERVA, 
  ESPERANDO_PASO_ENTRADA, 
  ESPERANDO_PASO_SALIDA,
  MOSTRANDO_MENSAJE 
};
EstadoSistema estadoAccesoActual = INICIO;

// Estados de la Bahía.
enum EstadoBahia { DISPONIBLE, RESERVADA, OCUPADA };
EstadoBahia estadoBahiaActual = DISPONIBLE;

// Variables de Control de Acceso.
String inputBuffer = "";
char lastKeyPressed = '\0';
int multiPressIndex = 0;

bool esReservaValidada = false;
String idReservaValidada = "";
String placaValidada = "";
String ultimaPlacaRegistrada = ""; // Guarda la placa actual en el parqueadero. 
                                   /*(Dado que no hay base de datos, se asume que la última
                                     placa registrada es la que está actualmente en el parqueadero)*/
bool sensor1Prev = HIGH;
bool sensor2Prev = HIGH;

// Variables de la Bahía.
String idReservaBahia = "";
String placaBahia = "";

// Variables de Debounce y Confirmación de Ocupación.
int ultimoEstadoLectura = HIGH;
int estadoBotonEstable = HIGH;

// Temporizadores de Debounce y Confirmación.
unsigned long ultimoTiempoDebounce = 0;
const unsigned long debounceDelay = 50;

unsigned long tiempoInicioConfirmacion = 0;
// Se establecio un tiempo de 5 segundos para confirmar la ocupación de la bahía.
const unsigned long tiempoConfirmacion = 5000; // Para pruebas, se puede reducir a 5 segundos.
bool esperandoConfirmacion = false;

// Variables de Consulta Periódica al Servidor.
unsigned long ultimoTiempoConsulta = 0;
const unsigned long intervaloConsulta = 5000;

// Temporizadores Control Acceso.
unsigned long lastKeyTime = 0;
const unsigned long MULTI_PRESS_TIMEOUT = 800; // Tiempo máximo entre presiones de la misma tecla para multi-press.
unsigned long mensajeTimer = 0; // Temporizador para mostrar mensajes temporales en la pantalla.
const unsigned long MENSAJE_TIMEOUT = 3000; // Tiempo que se muestra un mensaje temporal en la pantalla.
unsigned long esperaPasoTimer = 0; // Temporizador para esperar que el vehículo pase por el sensor después de validar la reserva o placa.
const unsigned long ESPERA_PASO_TIMEOUT = 15000; // Tiempo para que el vehículo pase por el sensor después de validar 
                                                 // la reserva o placa.

// --------------------------------------------
//           Funciones Auxiliares.
// --------------------------------------------

// Obtener fecha y hora en formato ISO 8601.
String obtenerFechaISO() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    return "2026-09-07T03:00:00.000000-05:00";
  }
  char buffer[40];
  strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S.000000-05:00", &timeinfo);
  return String(buffer);
}

// Actualizar el estado de los LEDs según el estado de la bahía.
void actualizarLeds(EstadoBahia estado) {
  digitalWrite(pinLedVerde, estado == DISPONIBLE ? HIGH : LOW);
  digitalWrite(pinLedAmarillo, estado == RESERVADA ? HIGH : LOW);
  digitalWrite(pinLedRojo, estado == OCUPADA ? HIGH : LOW);
}

// Enviar evento de la bahía al servidor en formato JSON.
void enviarEventoBahiaJSON(const char* status, const char* plate, const char* reservationId) {
  StaticJsonDocument<256> doc;
  doc["event"] = "parking_space_status";
  doc["node_id"] = "PARKING-001";
  doc["space_id"] = "B-001";
  doc["status"] = status;
  doc["plate"] = plate ? plate : nullptr;
  doc["reservation_id"] = reservationId ? reservationId : nullptr;
  doc["date"] = obtenerFechaISO();

  String jsonString;
  serializeJson(doc, jsonString);

  Serial.println("\n--- EVENTO BAHÍA ---");
  serializeJsonPretty(doc, Serial);
  Serial.println("\n---------------------\n");

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverEventUrl);
    http.addHeader("Content-Type", "application/json");
    http.POST(jsonString);
    http.end();
  }
}

// Consultar el estado de la reserva en el servidor y actualizar el estado de la bahía.
void consultarReservaServidor() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(serverStatusUrl);
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    String payload = http.getString();
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, payload);

    if (!error) {
      bool activa = doc["active"] | false;
      const char* resId = doc["reservation_id"];
      const char* plate = doc["plate"];

      // Consulta exclusiva para reservas externas previas al estacionamiento
      if (activa && estadoBahiaActual == DISPONIBLE) {
        estadoBahiaActual = RESERVADA;
        idReservaBahia = resId ? String(resId) : "";
        placaBahia = plate ? String(plate) : "";
        actualizarLeds(estadoBahiaActual);
        enviarEventoBahiaJSON("reserved", nullptr, idReservaBahia.c_str());
      }
      else if (!activa && estadoBahiaActual == RESERVADA) {
        estadoBahiaActual = DISPONIBLE;
        idReservaBahia = "";
        placaBahia = "";
        actualizarLeds(estadoBahiaActual);
        enviarEventoBahiaJSON("available", nullptr, nullptr);
      }
    }
  }
  http.end();
}

// Actualizar la pantalla LCD con dos líneas de texto.
void actualizarPantalla(String L1, String L2 = "") {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(L1);
  lcd.setCursor(0, 1);
  lcd.print(L2);
}

// Mostrar la pantalla de inicio del sistema de control de acceso.
void mostrarInicio() {
  estadoAccesoActual = INICIO;
  inputBuffer = "";
  lastKeyPressed = '\0';
  actualizarPantalla("A:Placa  B:Reser", "Presione A o B..");
}

// Mostrar un mensaje temporal en la pantalla LCD.
void mostrarMensajeTemporal(String linea1, String linea2) {
  actualizarPantalla(linea1, linea2);
  estadoAccesoActual = MOSTRANDO_MENSAJE;
  mensajeTimer = millis();
}

// Renderizar el buffer de entrada, mostrando el carácter actual.
void renderizarBuffer() {
  lcd.setCursor(0, 1);
  String disp = inputBuffer;

  if (lastKeyPressed != '\0') {
    int keyDigit = lastKeyPressed - '0';
    disp += keyMap[keyDigit][multiPressIndex];
  }

  while (disp.length() < 16) {
    disp += " ";
  }
  lcd.print(disp);
}

// Fijar el carácter actual en el buffer de entrada.
void fijarCaracter() {
  if (lastKeyPressed != '\0') {
    int keyDigit = lastKeyPressed - '0';
    char charToCommit = keyMap[keyDigit][multiPressIndex];
    
    if (inputBuffer.length() < 6) {
      inputBuffer += charToCommit;
    }
    
    lastKeyPressed = '\0';
    multiPressIndex = 0;
    renderizarBuffer();
  }
}

// Generar e imprimir un evento de acceso (entrada/salida) en formato JSON.
void generarEImprimirJSONAcceso(String type, bool isReservation, String resId, String plateVal) {
  StaticJsonDocument<300> eventDoc;
  
  eventDoc["event"] = "vehicle_access";
  eventDoc["node_id"] = "PARKING-001";
  eventDoc["access_type"] = type; 
  eventDoc["reservation"] = isReservation;

  if (isReservation && resId.length() > 0) {
    eventDoc["reservation_id"] = resId;
  } else {
    eventDoc["reservation_id"] = nullptr;
  }

  if (plateVal.length() > 0) {
    eventDoc["plate"] = plateVal;
  } else {
    eventDoc["plate"] = nullptr;
  }

  eventDoc["date"] = obtenerFechaISO();

  Serial.println("\n--- EVENTO ACCESO ---");
  serializeJsonPretty(eventDoc, Serial);
  Serial.println("\n---------------------\n");
}

// Validar código de reserva.
void procesarValidacionReserva(String codigoIngresado) {
  actualizarPantalla("Validando...", "Consultando server");

  // Verificar si hay conexión Wi-Fi
  if (WiFi.status() != WL_CONNECTED) {
    mostrarMensajeTemporal("Error Red", "Sin WiFi");
    return;
  }

  // Realizar la consulta httpal servidor para validar la reserva
  HTTPClient http;
  http.begin(serverStatusUrl);
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    String payload = http.getString();
    http.end();

    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, payload);

    if (!error) {
      bool active = doc["active"] | false;
      const char* resIdServer = doc["reservation_id"] | "";
      const char* plateServer = doc["plate"] | "";

      if (active && String(resIdServer) == codigoIngresado) {
        esReservaValidada = true;
        idReservaValidada = String(resIdServer);
        placaValidada = String(plateServer);

        estadoAccesoActual = ESPERANDO_PASO_ENTRADA;
        esperaPasoTimer = millis();
        actualizarPantalla("Reserva OK", "Pase por Sensor1");
        return;
      }
    }
  } else {
    http.end();
  }

  mostrarMensajeTemporal("Error Reserva", "Invalida/Inactiva");
}

// Validar placa de vehículo.
void procesarValidacionPlaca(String placa) {
  esReservaValidada = false;
  idReservaValidada = "";
  placaValidada = placa;

  if (placa == ultimaPlacaRegistrada && ultimaPlacaRegistrada.length() > 0) {
    // Es una SALIDA: siempre se permite, sin importar el estado de la bahía.
    estadoAccesoActual = ESPERANDO_PASO_SALIDA;
    esperaPasoTimer = millis();
    actualizarPantalla("Salida Aceptada", "Pase por Sensor2");
  } else {
    // Es una ENTRADA sin reserva: solo se permite si hay espacio disponible.
    if (estadoBahiaActual != DISPONIBLE) {
      mostrarMensajeTemporal("Sin Espacio", "Parqueadero Lleno");
      return;
    }

    estadoAccesoActual = ESPERANDO_PASO_ENTRADA;
    esperaPasoTimer = millis();
    actualizarPantalla("Placa Aceptada", "Pase por Sensor1");
  }
}
// --------------------------------------------
//                  SETUP
// --------------------------------------------
void setup() {
  // Inicialización de Serial, Pines, LCD y Wi-Fi.
  
  // velocidad de 115200 baudios para depuración.
  Serial.begin(115200);
  
  // Configuración de pines para sensores, LEDs y botón.
  pinMode(SENSOR_ENTRADA_PIN, INPUT_PULLUP); // Se configura como INPUT_PULLUP para que el sensor esté en HIGH 
                                             // cuando no hay objeto y LOW cuando detecta un objeto.
  pinMode(SENSOR_SALIDA_PIN, INPUT_PULLUP);
  pinMode(pinLedVerde, OUTPUT);
  pinMode(pinLedAmarillo, OUTPUT);
  pinMode(pinLedRojo, OUTPUT);
  pinMode(pinBoton, INPUT_PULLUP);

  // Inicialización de los leds en estado DISPONIBLE.
  actualizarLeds(DISPONIBLE);

  // Inicialización de la pantalla LCD y comunicación I2C.
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  
  // Conexión a la red Wi-Fi.
  WiFi.begin(ssid, password);
  actualizarPantalla("Conectando WiFi", "Esperando...");
  Serial.print("Conectando a Wi-Fi");
  
  // Intentar conectarse a Wi-Fi durante 8 segundos.
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 8000) {
    delay(100);
  }

  // Configuración de la hora mediante NTP si hay conexión Wi-Fi.
  if (WiFi.status() == WL_CONNECTED) {
    configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
    Serial.println("\nWi-Fi Conectado. NTP Sincronizado.");
    mostrarMensajeTemporal("WiFi Conectado", "NTP Sincronizado");
  } else {
    mostrarMensajeTemporal("WiFi Error", "Modo Offline");
    Serial.println("\nWi-Fi Desconectado (Modo local).");
  }

  // Consulta inicial al servidor para obtener el estado de la reserva y actualizar la bahía.
  consultarReservaServidor();
  if (estadoBahiaActual == DISPONIBLE) {
    enviarEventoBahiaJSON("available", nullptr, nullptr);
  }
}

// --------------------------------------------
//              LOOP PRINCIPAL
// --------------------------------------------
void loop() {
  // Obtener el tiempo actual en milisegundos.
  unsigned long tiempoActual = millis();

  // ------------------------------------------
  //        LÓGICA DE CONTROL DE ACCESO
  // ------------------------------------------
  
  // Estado actual de los sensores de entrada y salida.
  bool sensor1Curr = digitalRead(SENSOR_ENTRADA_PIN);
  bool sensor2Curr = digitalRead(SENSOR_SALIDA_PIN);

  // Logica de entrada y salida de vehiculos.
  if (estadoAccesoActual == MOSTRANDO_MENSAJE) {
    if (tiempoActual - mensajeTimer >= MENSAJE_TIMEOUT) {
      mostrarInicio();
    }
  }
  else if (estadoAccesoActual == ESPERANDO_PASO_ENTRADA) {
    // Verificar si el vehículo pasó por el sensor de entrada (Sensor1).
    if (sensor1Curr == LOW && sensor1Prev == HIGH) {
      // Vehículo ingresó correctamente al parqueadero.
      ultimaPlacaRegistrada = placaValidada;
      generarEImprimirJSONAcceso("entry", esReservaValidada, idReservaValidada, placaValidada);
      mostrarMensajeTemporal("Acceso Exitoso", "Pase Adelante");
    } else if (tiempoActual - esperaPasoTimer >= ESPERA_PASO_TIMEOUT) {
      mostrarMensajeTemporal("Tiempo Agotado", "Acceso Cancelado");
    }
  } 
  else if (estadoAccesoActual == ESPERANDO_PASO_SALIDA) {
    // Verificar si el vehículo pasó por el sensor de salida (Sensor2).
    if (sensor2Curr == LOW && sensor2Prev == HIGH) {
      // Vehículo salió completamente del parqueadero.
      generarEImprimirJSONAcceso("exit", false, "", ultimaPlacaRegistrada);
      
      // Limpieza de datos de presencia del vehículo
      ultimaPlacaRegistrada = "";
      placaValidada = "";
      esReservaValidada = false;
      idReservaValidada = "";

      mostrarMensajeTemporal("Vehiculo Saliendo", "Buen Viaje!");
    } else if (tiempoActual - esperaPasoTimer >= ESPERA_PASO_TIMEOUT) {
      mostrarMensajeTemporal("Tiempo Agotado", "Salida Cancelada");
    }
  }

  // Actualización de los estados previos de los sensores.
  sensor1Prev = sensor1Curr;
  sensor2Prev = sensor2Curr;

  // Lógica Teclado
  if (lastKeyPressed != '\0' && (tiempoActual - lastKeyTime > MULTI_PRESS_TIMEOUT)) {
    fijarCaracter();
  }

  // Lectura del teclado y procesamiento de la entrada.
  char key = keypad.getKey();
  if (key) {
    // Si el estado actual es INICIO, se espera que el usuario presione A o B para seleccionar el modo de ingreso.
    if (estadoAccesoActual == INICIO) {
      if (key == 'A') {
        estadoAccesoActual = MODO_PLACA;
        inputBuffer = "";
        actualizarPantalla("Ingresar Placa:");
      } else if (key == 'B') {
        estadoAccesoActual = MODO_RESERVA;
        inputBuffer = "";
        actualizarPantalla("Cod. Reserva:");
      }
    } else if (estadoAccesoActual == MODO_PLACA || estadoAccesoActual == MODO_RESERVA) {
      if (key == 'A') { // Modo placa.
        fijarCaracter();
        estadoAccesoActual = MODO_PLACA;
        inputBuffer = "";
        actualizarPantalla("Ingresar Placa:");
      } else if (key == 'B') { // Modo reserva.
        fijarCaracter();
        estadoAccesoActual = MODO_RESERVA;
        inputBuffer = "";
        actualizarPantalla("Cod. Reserva:");
      } else if (key == '*') {  // Borrar último carácter.
        fijarCaracter();
        if (inputBuffer.length() > 0) {
          inputBuffer.remove(inputBuffer.length() - 1);
          renderizarBuffer();
        }
      } else if (key == '#') {  // Confirmar entrada.
        fijarCaracter();
        if (inputBuffer.length() > 0) {
          if (estadoAccesoActual == MODO_RESERVA) {
            procesarValidacionReserva(inputBuffer);
          } else if (estadoAccesoActual == MODO_PLACA) {
            procesarValidacionPlaca(inputBuffer);
          }
        }
      } else if (key >= '0' && key <= '9') {
        if (key == lastKeyPressed) {
          int keyDigit = key - '0';
          int numLetters = strlen(keyMap[keyDigit]);
          multiPressIndex = (multiPressIndex + 1) % numLetters;
        } else {
          fijarCaracter();
          if (inputBuffer.length() < 6) {
            lastKeyPressed = key;
            multiPressIndex = 0;
          }
        }
        lastKeyTime = tiempoActual;
        renderizarBuffer();
      }
    }
  }

  // ------------------------------------------
  // 2. LÓGICA DE LA BAHÍA
  // ------------------------------------------

  // Consulta periódica al servidor para verificar si hay una reserva activa para la bahía.
  if (estadoBahiaActual != OCUPADA && (tiempoActual - ultimoTiempoConsulta >= intervaloConsulta)) {
    ultimoTiempoConsulta = tiempoActual;
    consultarReservaServidor();
  }

  // Detectar cambios en el estado del botón.
  int lecturaActual = digitalRead(pinBoton);
  if (lecturaActual != ultimoEstadoLectura) {
    ultimoTiempoDebounce = tiempoActual;
    ultimoEstadoLectura = lecturaActual;
  }
  // Filtrado antirrebote
  if ((tiempoActual - ultimoTiempoDebounce) >= debounceDelay) {
    if (lecturaActual != estadoBotonEstable) {
      estadoBotonEstable = lecturaActual;

      if ((estadoBotonEstable == LOW && estadoBahiaActual != OCUPADA) || 
          (estadoBotonEstable == HIGH && estadoBahiaActual == OCUPADA)) {
        tiempoInicioConfirmacion = tiempoActual;
        esperandoConfirmacion = true;
      }
    }
  }

  // Verificación por tiempo de confirmación del sensor de la bahía.
  if (esperandoConfirmacion) {
    if ((estadoBahiaActual != OCUPADA && estadoBotonEstable == HIGH) ||
        (estadoBahiaActual == OCUPADA && estadoBotonEstable == LOW)) {
      esperandoConfirmacion = false; // Cancela si fue una detección/pulsación errónea.
    }
    else if ((tiempoActual - tiempoInicioConfirmacion) >= tiempoConfirmacion) {
      esperandoConfirmacion = false;

      // Bahía pasa a estar OCUPADA.
      if (estadoBotonEstable == LOW && estadoBahiaActual != OCUPADA) {
        estadoBahiaActual = OCUPADA;
        actualizarLeds(estadoBahiaActual);
        
        // Asigna la placa que ingresó previamente por el acceso.
        String placaAAsignar = (ultimaPlacaRegistrada.length() > 0) ? ultimaPlacaRegistrada : "S/N";
        enviarEventoBahiaJSON("occupied", placaAAsignar.c_str(), idReservaBahia.length() > 0 ? idReservaBahia.c_str() : nullptr);
      } 
      // Bahía pasa a estar DISPONIBLE.
      else if (estadoBotonEstable == HIGH && estadoBahiaActual == OCUPADA) {
        estadoBahiaActual = DISPONIBLE;
        // Consulta al servidor para verificar si hay una reserva activa para evitar cambios no deseados.
        consultarReservaServidor();
        if (estadoBahiaActual == DISPONIBLE) {
          idReservaBahia = "";
          placaBahia = "";
          actualizarLeds(DISPONIBLE);
          enviarEventoBahiaJSON("available", nullptr, nullptr);
        }
      }
    }
  }
}