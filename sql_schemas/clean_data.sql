-- =========================================================================
-- Tablas de la capa limpia (Taller 8)
--
-- Las llena la pestaña "Limpieza" de Node-RED. Aquí NO hay lógica de
-- limpieza: ni triggers, ni procedimientos, ni vistas. La BD solo guarda
-- el resultado; todas las validaciones viven en los nodos function.
--
-- Las tablas crudas (sessions, bay_events, reservations, ...) no se tocan.
-- Cada corrida de la limpieza borra y vuelve a llenar las clean_* y
-- dq_issues, y agrega una fila en dq_runs.
--
-- Columna flags: códigos de las reglas que MARCARON el registro, separados
-- por coma (ej. 'A2,I2'). El registro se conserva y cada análisis decide
-- si lo excluye. Los registros DESCARTADOS no llegan a estas tablas.
-- =========================================================================

USE parking_db;

CREATE TABLE IF NOT EXISTS clean_sessions (
    session_id      BIGINT UNSIGNED PRIMARY KEY,
    node_id         VARCHAR(30)  NULL,
    reservation_id  VARCHAR(20)  NULL,
    plate           VARCHAR(15)  NOT NULL,
    access_mode     ENUM('qr','placa') NOT NULL,
    entry_at        DATETIME     NOT NULL,
    exit_at         DATETIME     NULL,
    duration_min    DECIMAL(8,1) NULL,          -- NULL si sigue abierta
    flags           VARCHAR(100) NOT NULL DEFAULT '',
    INDEX idx_cs_node_entry (node_id, entry_at)
);

CREATE TABLE IF NOT EXISTS clean_bay_events (
    event_id        BIGINT UNSIGNED PRIMARY KEY,
    bay_id          BIGINT UNSIGNED NOT NULL,
    node_id         VARCHAR(30)  NOT NULL,
    space_code      VARCHAR(20)  NOT NULL,
    sensor_status   BOOLEAN      NOT NULL,
    created_at      DATETIME     NOT NULL,
    flags           VARCHAR(100) NOT NULL DEFAULT '',
    INDEX idx_cbe_bay_time (bay_id, created_at),
    INDEX idx_cbe_node_time (node_id, created_at)
);

CREATE TABLE IF NOT EXISTS clean_reservations (
    reservation_id  VARCHAR(20)  PRIMARY KEY,
    bay_id          BIGINT UNSIGNED NOT NULL,
    node_id         VARCHAR(30)  NOT NULL,
    space_code      VARCHAR(20)  NOT NULL,
    plate           VARCHAR(15)  NOT NULL,
    starts_at       DATETIME     NOT NULL,
    ends_at         DATETIME     NOT NULL,
    status          VARCHAR(12)  NOT NULL,
    created_at      DATETIME     NOT NULL,
    duration_min    DECIMAL(8,1) NOT NULL,
    flags           VARCHAR(100) NOT NULL DEFAULT '',
    INDEX idx_cr_node_start (node_id, starts_at)
);

-- Un registro por cada hallazgo de la última corrida
CREATE TABLE IF NOT EXISTS dq_issues (
    issue_id        BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id          VARCHAR(30)  NOT NULL,
    rule_id         VARCHAR(4)   NOT NULL,      -- H1, D3, A5, T1, ...
    rule_group      ENUM('formato','duplicado','incompleto','atipico','temporal') NOT NULL,
    source_table    VARCHAR(30)  NOT NULL,
    record_id       VARCHAR(40)  NOT NULL,
    action          ENUM('corregido','descartado','marcado') NOT NULL,
    detail          VARCHAR(255) NOT NULL,
    INDEX idx_dq_rule (rule_id)
);

-- Historial de corridas (esta tabla no se borra)
CREATE TABLE IF NOT EXISTS dq_runs (
    run_id          VARCHAR(30)  PRIMARY KEY,
    started_at      DATETIME     NOT NULL,
    finished_at     DATETIME     NOT NULL,
    rows_in         INT UNSIGNED NOT NULL,
    rows_out        INT UNSIGNED NOT NULL,
    corrected       INT UNSIGNED NOT NULL,
    discarded       INT UNSIGNED NOT NULL,
    flagged         INT UNSIGNED NOT NULL,
    summary         VARCHAR(500) NOT NULL       -- conteo por regla, ej. "H1:6 D1:3 ..."
);
