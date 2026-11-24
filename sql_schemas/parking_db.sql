-- =========================================
-- DATABASE
-- =========================================
-- Requiere MySQL 8.0.16+ (CHECK constraints)

CREATE DATABASE IF NOT EXISTS parking_db;
USE parking_db;

-- =========================================
-- 1. NODES
-- =========================================
-- node_id es el mismo código que envía el ESP32 (ej. 'PARKING-002')

CREATE TABLE nodes (
    node_id VARCHAR(30) PRIMARY KEY,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_connection DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =========================================
-- 2. BAYS
-- =========================================
-- Solo estado físico. Nada de reservas aquí.

CREATE TABLE bays (
    bay_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    node_id VARCHAR(30) NOT NULL,
    space_code VARCHAR(20) NOT NULL,
    sensor_status BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE = detecta vehículo
    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_bays_nodes
        FOREIGN KEY (node_id)
        REFERENCES nodes(node_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    CONSTRAINT uq_bay_space
        UNIQUE (node_id, space_code)
);

-- =========================================
-- 3. RESERVATIONS
-- =========================================
-- reservation_id lo genera la app (es el contenido del QR).
-- Al ser PRIMARY KEY ya es único: un duplicado falla el INSERT (DUPLICATE_ID).
--
-- Ciclo de estados:
--   reserved  -> creada, fuera de la ventana de 10 min (amarillo apagado)
--   active    -> dentro de la ventana, ya se notificó al nodo (amarillo encendido)
--   entered   -> el carro entró con el QR (amarillo encendido)
--   completed -> el carro salió, o se acabó el tiempo estando adentro
--   expired   -> se acabó el tiempo y el carro nunca entró
--   cancelled -> cancelada desde la app

CREATE TABLE reservations (
    reservation_id VARCHAR(20) PRIMARY KEY,
    bay_id BIGINT UNSIGNED NOT NULL,
    plate VARCHAR(15) NOT NULL,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NOT NULL,

    status ENUM(
        'reserved',
        'active',
        'entered',
        'completed',
        'expired',
        'cancelled'
    ) NOT NULL DEFAULT 'reserved',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL
        DEFAULT NULL
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_reservations_bays
        FOREIGN KEY (bay_id)
        REFERENCES bays(bay_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,

    CONSTRAINT chk_reservation_dates
        CHECK (ends_at > starts_at)
);

-- =========================================
-- 4. SESSIONS
-- =========================================
-- Sesión activa = exit_at IS NULL

CREATE TABLE sessions (
    session_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    node_id VARCHAR(30) NULL,
    reservation_id VARCHAR(20) NULL,
    plate VARCHAR(15) NOT NULL,
    entry_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    exit_at DATETIME NULL,

    CONSTRAINT fk_sessions_nodes
        FOREIGN KEY (node_id)
        REFERENCES nodes(node_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,

    CONSTRAINT fk_sessions_reservations
        FOREIGN KEY (reservation_id)
        REFERENCES reservations(reservation_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,

    CONSTRAINT chk_session_dates
        CHECK (exit_at IS NULL OR exit_at >= entry_at)
);

-- =========================================
-- 5. BAY_EVENTS
-- =========================================
-- Historial de cambios de ocupación. Lo llena el trigger de bays.

CREATE TABLE bay_events (
    event_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    bay_id BIGINT UNSIGNED NOT NULL,
    sensor_status BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_bay_events_bays
        FOREIGN KEY (bay_id)
        REFERENCES bays(bay_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

-- =========================================
-- 6. RESERVATION_EVENTS
-- =========================================
-- Historial de cambios de estado de cada reserva. Lo llenan los triggers de reservations.

CREATE TABLE reservation_events (
    event_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reservation_id VARCHAR(20) NOT NULL,
    old_status ENUM('reserved','active','entered','completed','expired','cancelled') NULL,
    new_status ENUM('reserved','active','entered','completed','expired','cancelled') NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_reservation_events_reservations
        FOREIGN KEY (reservation_id)
        REFERENCES reservations(reservation_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

-- =========================================
-- TRIGGERS
-- =========================================
-- Correr este script desde MySQL Workbench o la consola (usa DELIMITER).

DELIMITER $$

-- Registra un evento solo cuando la ocupación realmente cambia
CREATE TRIGGER trg_bays_sensor_change
AFTER UPDATE ON bays
FOR EACH ROW
BEGIN
    IF OLD.sensor_status <> NEW.sensor_status THEN
        INSERT INTO bay_events (bay_id, sensor_status)
        VALUES (NEW.bay_id, NEW.sensor_status);
    END IF;
END$$

-- Registra la creación de la reserva
CREATE TRIGGER trg_reservations_insert
AFTER INSERT ON reservations
FOR EACH ROW
BEGIN
    INSERT INTO reservation_events (reservation_id, old_status, new_status)
    VALUES (NEW.reservation_id, NULL, NEW.status);
END$$

-- Registra cada cambio de estado
CREATE TRIGGER trg_reservations_status_change
AFTER UPDATE ON reservations
FOR EACH ROW
BEGIN
    IF OLD.status <> NEW.status THEN
        INSERT INTO reservation_events (reservation_id, old_status, new_status)
        VALUES (NEW.reservation_id, OLD.status, NEW.status);
    END IF;
END$$

DELIMITER ;


-- =========================================================================
-- CONSULTAS DE REFERENCIA PARA NODE-RED
-- (los ? son parámetros que llena Node-RED)
-- =========================================================================

-- ---------- Inicio de sesión ----------

-- Registro del nodo (crea o actualiza last_connection)
-- INSERT INTO nodes (node_id) VALUES (?)
--     ON DUPLICATE KEY UPDATE last_connection = NOW();

-- Bahías: crea las nuevas, ignora las que ya existen
-- INSERT IGNORE INTO bays (node_id, space_code) VALUES (?, ?), (?, ?), ...;

-- Lectura del sensor (también en cada cambio de ocupación)
-- UPDATE bays SET sensor_status = ? WHERE node_id = ? AND space_code = ?;

-- Bahías con reserva vigente para reenviar reserved: true
-- SELECT b.space_code
-- FROM reservations r JOIN bays b ON b.bay_id = r.bay_id
-- WHERE b.node_id = ? AND r.status IN ('active', 'entered');

-- ---------- Crear reserva ----------

-- Solape (si COUNT > 0 -> OVERLAP)
-- SELECT COUNT(*) FROM reservations
-- WHERE bay_id = ?
--   AND status IN ('reserved', 'active', 'entered')
--   AND starts_at < ?      -- ends_at de la nueva
--   AND ends_at   > ?;     -- starts_at de la nueva

-- ---------- Revisión de cada minuto ----------

-- Activar: publicar reserved: true y luego pasar a 'active'
-- SELECT r.reservation_id, b.node_id, b.space_code
-- FROM reservations r JOIN bays b ON b.bay_id = r.bay_id
-- WHERE r.status = 'reserved'
--   AND r.starts_at <= NOW() + INTERVAL 10 MINUTE
--   AND r.ends_at > NOW();
-- UPDATE reservations SET status = 'active' WHERE reservation_id IN (...);

-- Vencer: publicar reserved: false (solo las que estaban 'active' o 'entered')
-- SELECT r.reservation_id, r.status, b.node_id, b.space_code
-- FROM reservations r JOIN bays b ON b.bay_id = r.bay_id
-- WHERE r.status IN ('reserved', 'active', 'entered')
--   AND r.ends_at <= NOW();
-- UPDATE reservations SET status = 'expired'
--   WHERE status IN ('reserved', 'active') AND ends_at <= NOW();
-- UPDATE reservations SET status = 'completed'
--   WHERE status = 'entered' AND ends_at <= NOW();

-- ---------- Entrada por placa ----------

-- NO_BAYS: bahías libres y sin reserva vigente (si 0 -> NO_BAYS)
-- SELECT COUNT(*) FROM bays b
-- WHERE b.node_id = ?
--   AND b.sensor_status = FALSE
--   AND NOT EXISTS (
--       SELECT 1 FROM reservations r
--       WHERE r.bay_id = b.bay_id AND r.status IN ('active', 'entered')
--   );

-- ACTIVE_SESSION (también para QR y, al revés, NO_SESSION en salida)
-- SELECT session_id, reservation_id FROM sessions
-- WHERE plate = ? AND exit_at IS NULL;

-- Crear sesión
-- INSERT INTO sessions (node_id, plate) VALUES (?, ?);

-- ---------- Entrada por QR ----------

-- INVALID_RESERVATION / OUT_OF_WINDOW
-- SELECT r.reservation_id, r.plate, r.status, r.starts_at, r.ends_at
-- FROM reservations r JOIN bays b ON b.bay_id = r.bay_id
-- WHERE r.reservation_id = ? AND b.node_id = ?;
--   sin filas -> INVALID_RESERVATION
--   status no está en ('reserved','active')
--   o NOW() fuera de [starts_at - 10 min, ends_at) -> OUT_OF_WINDOW

-- Crear sesión con la placa de la reserva y marcarla como ingresada
-- INSERT INTO sessions (node_id, reservation_id, plate) VALUES (?, ?, ?);
-- UPDATE reservations SET status = 'entered' WHERE reservation_id = ?;

-- ---------- Salida ----------

-- Cerrar sesión
-- UPDATE sessions SET exit_at = NOW() WHERE session_id = ?;

-- Si la sesión tenía reserva y seguía 'entered': terminarla y publicar reserved: false
-- UPDATE reservations SET status = 'completed'
-- WHERE reservation_id = ? AND status = 'entered';
--   (si affectedRows = 0, ya había vencido y no se publica nada)

-- ---------- Cancelar desde la app ----------

-- SELECT status FROM reservations WHERE reservation_id = ?;
-- UPDATE reservations SET status = 'cancelled'
-- WHERE reservation_id = ? AND status IN ('reserved', 'active');
--   publicar reserved: false solo si estaba 'active'
