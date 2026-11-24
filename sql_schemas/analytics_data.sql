-- =========================================================================
-- Tablas de resultados del análisis descriptivo (Taller 8)
--
-- Las llena la pestaña "Análisis" de Node-RED a partir de las tablas clean_*
-- y de dq_issues. Aquí no hay lógica: todos los cálculos están en los nodos
-- function. Cada corrida vacía estas tablas y las vuelve a llenar.
-- En todas, node_id = 'TODOS' es el total de los nodos.
-- =========================================================================

USE parking_db;

-- Procesos 1 y 2: tendencia central y dispersión
CREATE TABLE IF NOT EXISTS an_stats (
    scope_type   ENUM('total','nodo','acceso') NOT NULL,
    scope        VARCHAR(30)  NOT NULL,      -- 'TODOS', un node_id, 'qr' o 'placa'
    variable     VARCHAR(30)  NOT NULL,      -- 'duracion_min' o 'hora_entrada'
    n            INT UNSIGNED NOT NULL,
    mean         DECIMAL(10,2) NOT NULL,
    median       DECIMAL(10,2) NOT NULL,
    mode         DECIMAL(10,2) NOT NULL,
    min          DECIMAL(10,2) NOT NULL,
    max          DECIMAL(10,2) NOT NULL,
    value_range  DECIMAL(10,2) NOT NULL,
    std_dev      DECIMAL(10,2) NOT NULL,
    variance     DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (scope_type, scope, variable)
);

-- Proceso 3: frecuencia de eventos por día (y serie diaria para el proceso 5)
CREATE TABLE IF NOT EXISTS an_daily (
    node_id          VARCHAR(30) NOT NULL,
    day              DATE        NOT NULL,
    entries          INT UNSIGNED NOT NULL,
    entries_qr       INT UNSIGNED NOT NULL,
    entries_plate    INT UNSIGNED NOT NULL,
    reservations     INT UNSIGNED NOT NULL,   -- reservas que empezaban ese día
    no_shows         INT UNSIGNED NOT NULL,   -- vencieron sin que el carro llegara
    cancelled        INT UNSIGNED NOT NULL,
    times_full       INT UNSIGNED NOT NULL,   -- veces que el nodo se llenó
    minutes_full     INT UNSIGNED NOT NULL,
    occupancy_pct    DECIMAL(5,1) NOT NULL,   -- en horario operativo
    avg_duration_min DECIMAL(8,1) NULL,
    PRIMARY KEY (node_id, day)
);

-- Proceso 4: distribución de categorías
CREATE TABLE IF NOT EXISTS an_categories (
    node_id      VARCHAR(30) NOT NULL,
    category     VARCHAR(20) NOT NULL,       -- 'estado_reserva', 'modo_acceso', 'tipo_estadia'
    label        VARCHAR(20) NOT NULL,
    n            INT UNSIGNED NOT NULL,
    pct          DECIMAL(5,1) NOT NULL,
    PRIMARY KEY (node_id, category, label)
);

-- Proceso 5: perfil por hora del día
CREATE TABLE IF NOT EXISTS an_hourly (
    node_id          VARCHAR(30) NOT NULL,
    hour             TINYINT UNSIGNED NOT NULL,   -- 0 a 23
    entries          INT UNSIGNED NOT NULL,       -- total del periodo
    entries_per_day  DECIMAL(6,2) NOT NULL,
    occupancy_pct    DECIMAL(5,1) NOT NULL,
    avg_duration_min DECIMAL(8,1) NULL,           -- de los carros que entraron a esa hora
    PRIMARY KEY (node_id, hour)
);

-- Proceso 6: relación entre variables (correlación de Pearson)
CREATE TABLE IF NOT EXISTS an_relations (
    pair         VARCHAR(40) NOT NULL,
    scope        VARCHAR(30) NOT NULL,
    n            INT UNSIGNED NOT NULL,
    r            DECIMAL(5,3) NULL,
    reading      VARCHAR(40) NOT NULL,
    PRIMARY KEY (pair, scope)
);

-- Proceso 7: anomalías (lo que marcó la limpieza), por nodo y regla
CREATE TABLE IF NOT EXISTS an_anomalies (
    node_id      VARCHAR(30) NOT NULL,       -- 'SIN NODO' si el registro no lo tiene
    rule_id      VARCHAR(4)  NOT NULL,
    rule_group   VARCHAR(12) NOT NULL,
    action       VARCHAR(12) NOT NULL,
    n            INT UNSIGNED NOT NULL,
    PRIMARY KEY (node_id, rule_id, action)
);

-- Proceso 8: comparación entre nodos
CREATE TABLE IF NOT EXISTS an_nodes (
    node_id             VARCHAR(30) PRIMARY KEY,
    bays                INT UNSIGNED NOT NULL,
    entries             INT UNSIGNED NOT NULL,
    entries_per_day     DECIMAL(6,1) NOT NULL,
    entries_per_bay_day DECIMAL(6,2) NOT NULL,   -- rotación: carros por bahía al día
    avg_duration_min    DECIMAL(8,1) NULL,
    median_duration_min DECIMAL(8,1) NULL,
    occupancy_pct       DECIMAL(5,1) NOT NULL,
    peak_hour           TINYINT UNSIGNED NULL,   -- hora con mayor ocupación
    pct_qr              DECIMAL(5,1) NOT NULL,
    reservations        INT UNSIGNED NOT NULL,
    no_show_pct         DECIMAL(5,1) NULL,
    times_full          INT UNSIGNED NOT NULL,
    minutes_full        INT UNSIGNED NOT NULL,
    entries_trend       DECIMAL(6,2) NULL,       -- pendiente: entradas de más (o de menos) por día
    issues              INT UNSIGNED NOT NULL,
    period_from         DATE NOT NULL,
    period_to           DATE NOT NULL
);
