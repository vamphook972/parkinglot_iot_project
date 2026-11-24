// ==========================================================================
// Parking IoT · app de monitoreo (Taller 9)
// Consume la API REST de Node-RED y dibuja las gráficas con Chart.js.
// ==========================================================================

const NODE_RED = 'http://localhost:1880';        // dónde corre Node-RED
const TODOS = 'TODOS';

let nodoActual = TODOS;
let nodos = [];                  // filas de /api/nodos (comparación)
let horasTodos = [];             // perfil horario del conjunto: línea de referencia
const graficas = {};             // instancias de Chart.js, para destruirlas al redibujar

// ---------- Utilidades ----------
const $ = sel => document.querySelector(sel);
const css = nombre => getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
const num = (v, dec = 0) => v === null || v === undefined ? '–'
    : Number(v).toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec });
const hora = h => h === null || h === undefined ? '–' : String(h).padStart(2, '0') + ':00';
const nombre = id => id === TODOS ? 'Todos' : id;

function duracion(min) {
    if (min === null || min === undefined) return '–';
    const m = Math.round(min);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`;
}
function fechaCorta(iso) {                        // '2026-11-03' -> 'mar 3'
    const d = new Date(iso + 'T12:00:00');
    return d.toLocaleDateString('es-CO', { weekday: 'short' }).replace('.', '') + ' ' + d.getDate();
}
function fechaLarga(iso) {
    return new Date(iso + 'T12:00:00').toLocaleDateString('es-CO', { day: 'numeric', month: 'long' });
}

// Llama un recurso de la API y devuelve el JSON
async function api(ruta) {
    const respuesta = await fetch(`${NODE_RED}/api/${ruta}`);
    if (!respuesta.ok) throw new Error('La API respondió ' + respuesta.status);
    return respuesta.json();
}

function aviso(texto) {
    $('#aviso').textContent = texto || '';
    $('#aviso').hidden = !texto;
}

// ---------- Selector de parqueadero ----------
function pintarSelector() {
    const cont = $('#nodos');
    cont.innerHTML = '';
    for (const id of [TODOS, ...nodos.map(n => n.node_id)]) {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = nombre(id);
        b.className = id === nodoActual ? 'activa' : '';
        b.setAttribute('aria-pressed', id === nodoActual);
        b.onclick = () => elegir(id);
        cont.appendChild(b);
    }
}

// ---------- Indicadores ----------
function pintarIndicadores(r) {
    const filas = [
        ['Ocupación promedio', `${num(r.occupancy_pct, 1)} %`, `de ${r.bays} bahías`],
        ['Entradas por día', num(r.entries_per_day, 1), `${num(r.entries)} en el periodo`],
        ['Estadía media', duracion(r.avg_duration_min), `mediana ${duracion(r.median_duration_min)}`],
        ['Hora de mayor ocupación', hora(r.peak_hour), ''],
        ['Veces que se llenó', num(r.times_full), r.times_full > 0 ? `${duracion(r.minutes_full)} en total` : ''],
        ['Reservas sin llegada', r.no_show_pct === null ? '–' : `${num(r.no_show_pct, 1)} %`, `de ${num(r.reservations)} reservas`]
    ];
    $('#indicadores').innerHTML = filas
        .map(([dt, dd, extra]) => `<div><dt>${dt}</dt><dd>${dd}<small>${extra}</small></dd></div>`)
        .join('');
    $('#periodo').textContent = `Del ${fechaLarga(r.period_from)} al ${fechaLarga(r.period_to)}`;
}

// ---------- Gráficas ----------
function base() {                                  // opciones comunes a las tres gráficas
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 13;
    Chart.defaults.color = css('--texto-2');
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { position: 'top', align: 'end', labels: { boxWidth: 14, boxHeight: 3, color: css('--texto') } },
            tooltip: { backgroundColor: css('--texto'), titleColor: css('--panel'), bodyColor: css('--panel'), padding: 10 }
        }
    };
}
const ejeX = () => ({ grid: { display: false }, border: { color: css('--borde') }, ticks: { maxRotation: 0 } });
const ejeY = extra => ({ beginAtZero: true, grid: { color: css('--rejilla') }, border: { display: false }, ...extra });

function dibujar(id, config) {
    if (graficas[id]) graficas[id].destroy();
    graficas[id] = new Chart(document.getElementById(id), config);
}

// 1. Ocupación por hora. Con un nodo elegido se agrega el conjunto como referencia.
function graficaHoras(horas) {
    const rango = h => h.hour >= 5 && h.hour <= 22;
    const series = [{
        label: nombre(nodoActual) === 'Todos' ? 'Todos los parqueaderos' : nodoActual,
        data: horas.filter(rango).map(h => h.occupancy_pct),
        borderColor: css('--serie-1'), backgroundColor: css('--serie-1'),
        borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.3
    }];
    if (nodoActual !== TODOS) {
        series.push({
            label: 'Todos los parqueaderos',
            data: horasTodos.filter(rango).map(h => h.occupancy_pct),
            borderColor: css('--referencia'), backgroundColor: css('--referencia'),
            borderWidth: 2, borderDash: [6, 4], pointRadius: 0, pointHoverRadius: 5, tension: 0.3
        });
    }
    const opciones = base();
    opciones.plugins.legend.display = series.length > 1;
    opciones.plugins.tooltip.callbacks = { label: c => ` ${c.dataset.label}: ${num(c.parsed.y, 1)} %` };
    opciones.scales = { x: ejeX(), y: ejeY({ max: 100, ticks: { stepSize: 25, callback: v => v + ' %' } }) };
    dibujar('g-horas', { type: 'line', data: { labels: horas.filter(rango).map(h => hora(h.hour)), datasets: series }, options: opciones });
}

// 2. Entradas por día, apiladas por modo de acceso
function graficaDias(dias) {
    const serie = (label, campo, color, arriba) => ({
        label, data: dias.map(d => d[campo]), backgroundColor: css(color),
        borderColor: css('--panel'), borderWidth: { top: arriba ? 0 : 2 },      // separación de 2 px entre segmentos
        borderRadius: arriba ? { topLeft: 4, topRight: 4 } : 0, maxBarThickness: 44
    });
    const opciones = base();
    opciones.scales = { x: { ...ejeX(), stacked: true }, y: ejeY({ stacked: true, ticks: { precision: 0 } }) };
    dibujar('g-dias', {
        type: 'bar',
        data: {
            labels: dias.map(d => fechaCorta(d.day)),
            datasets: [serie('Por placa', 'entries_plate', '--serie-1', false), serie('Con QR', 'entries_qr', '--serie-2', true)]
        },
        options: opciones
    });
}

// 3. Estado final de las reservas
function graficaReservas(categorias) {
    const NOMBRES = { completed: 'Completadas', expired: 'Sin llegada', cancelled: 'Canceladas',
                      entered: 'Carro adentro', active: 'Vigentes', reserved: 'Por empezar' };
    const filas = categorias.filter(c => c.category === 'estado_reserva');
    const total = filas.reduce((s, c) => s + c.n, 0);
    $('#nota-reservas').textContent = total ? `${total} reservas en el periodo` : 'No hubo reservas en el periodo';
    const opciones = base();
    opciones.indexAxis = 'y';
    opciones.plugins.legend.display = false;
    opciones.plugins.tooltip.callbacks = { label: c => ` ${c.parsed.x} reservas` };
    opciones.scales = {
        x: ejeY({ ticks: { precision: 0 } }),
        y: { grid: { display: false }, border: { color: css('--borde') }, ticks: { color: css('--texto') } }
    };
    dibujar('g-reservas', {
        type: 'bar',
        data: {
            labels: filas.map(c => `${NOMBRES[c.label] || c.label} · ${num(c.pct)} %`),
            datasets: [{ label: 'Reservas', data: filas.map(c => c.n), backgroundColor: css('--serie-1'),
                         borderRadius: { topRight: 4, bottomRight: 4 }, maxBarThickness: 30 }]
        },
        options: opciones
    });
}

// ---------- Tabla de comparación ----------
function pintarTabla() {
    const cuerpo = $('#tabla tbody');
    cuerpo.innerHTML = '';
    for (const n of nodos) {
        const tr = document.createElement('tr');
        tr.tabIndex = 0;
        tr.className = n.node_id === nodoActual ? 'activa' : '';
        tr.innerHTML = `
            <td>${n.node_id}</td>
            <td class="num">${n.bays}</td>
            <td><div class="barra-celda">
                <span class="pista"><span class="relleno" style="width:${Math.min(100, n.occupancy_pct)}%"></span></span>
                <span class="valor">${num(n.occupancy_pct, 1)} %</span>
            </div></td>
            <td class="num">${num(n.entries_per_day, 1)}</td>
            <td class="num">${num(n.entries_per_bay_day, 1)}</td>
            <td class="num">${duracion(n.avg_duration_min)}</td>
            <td class="num">${hora(n.peak_hour)}</td>
            <td class="num">${num(n.times_full)}</td>`;
        tr.onclick = () => elegir(n.node_id);
        tr.onkeydown = e => { if (e.key === 'Enter') elegir(n.node_id); };
        cuerpo.appendChild(tr);
    }
}

// ---------- Carga ----------
async function elegir(id) {
    nodoActual = id;
    pintarSelector();
    pintarTabla();
    try {
        const [resumen, horas, dias, categorias] = await Promise.all([
            api(`resumen/${id}`), api(`horas/${id}`), api(`dias/${id}`), api(`categorias/${id}`)
        ]);
        if (resumen.length === 0) {
            aviso('Todavía no hay análisis guardado. Corre en Node-RED la limpieza y luego el análisis.');
            return;
        }
        aviso('');
        if (id === TODOS) horasTodos = horas;
        pintarIndicadores(resumen[0]);
        graficaHoras(horas);
        graficaDias(dias);
        graficaReservas(categorias);
    } catch (error) {
        aviso(`No se pudo leer la API en ${NODE_RED}. Revisa que Node-RED esté corriendo y que la pestaña de la API esté desplegada.`);
        console.error(error);
    }
}

async function iniciar() {
    try {
        nodos = await api('nodos');
        horasTodos = await api(`horas/${TODOS}`);
    } catch (error) {
        aviso(`No se pudo leer la API en ${NODE_RED}. Revisa que Node-RED esté corriendo y que la pestaña de la API esté desplegada.`);
        console.error(error);
        return;
    }
    elegir(TODOS);
}

// ---------- Cambio de vista: histórico / en vivo ----------
document.querySelectorAll('.vistas button').forEach(boton => {
    boton.onclick = () => {
        const vivo = boton.dataset.vista === 'vivo';
        document.querySelectorAll('.vistas button').forEach(b => b.classList.toggle('activa', b === boton));
        $('#vista-historico').hidden = vivo;
        $('#vista-vivo').hidden = !vivo;
        // el dashboard de Node-RED se carga solo cuando se abre la vista
        const marco = $('#dashboardFrame');
        if (vivo && !marco.src) marco.src = `${NODE_RED}/dashboard/page1`;
    };
});

// si el sistema cambia entre tema claro y oscuro, se redibuja con los colores nuevos
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => elegir(nodoActual));

iniciar()
