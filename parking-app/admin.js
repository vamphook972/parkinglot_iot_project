// ==========================================================================
// Parking IoT · panel de administración
// En vivo:  GET /parqueaderos, /parqueaderos/:id/bahias, /reservas?status=…, DELETE /reservas/:id
// Análisis: GET /api/nodos, /api/resumen|horas|dias|categorias/:nodo  (tablas an_*)
// ==========================================================================

const TODOS = 'TODOS';
const graficas = {};
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ======================= PESTAÑAS =======================
function abrir(vista) {
    const analisis = vista === 'analisis';
    $('#tab-vivo').setAttribute('aria-selected', !analisis);
    $('#tab-analisis').setAttribute('aria-selected', analisis);
    $('#vista-vivo').hidden = analisis;
    $('#vista-analisis').hidden = !analisis;
    history.replaceState(null, '', analisis ? '#analisis' : '#vivo');
    if (analisis && !analisisIniciado) iniciarAnalisis();
}
$('#tab-vivo').onclick = () => abrir('vivo');
$('#tab-analisis').onclick = () => abrir('analisis');

// ======================= EN VIVO =======================
let reservasVivas = [];
let reservasCanceladas = [];     // historial: las más recientes primero
let filtroReservas = 'todas';

async function refrescarVivo() {
    const r = await api('/parqueaderos');
    if (!r.ok) {
        marcarVivo($('#vivo'), false, 'Sin conexión');
        $('#aviso-global').innerHTML = `${ICONOS.alerta}<span>No se pudo leer la API en ${esc(NODE_RED)}. Revisa que Node-RED esté corriendo.</span>`;
        $('#aviso-global').hidden = false;
        return;
    }
    marcarVivo($('#vivo'), true, 'En vivo');
    $('#aviso-global').hidden = true;
    const lotes = r.data || [];

    const [bahias, ...porEstado] = await Promise.all([
        Promise.all(lotes.map(l => api(`/parqueaderos/${encodeURIComponent(l.node_id)}/bahias`))),
        ...['active', 'entered', 'reserved', 'cancelled'].map(s => api(`/reservas?status=${s}&limit=200`))
    ]);
    const canceladas = porEstado.pop();
    reservasCanceladas = canceladas.ok ? canceladas.data : [];   // la API ya las trae de la más reciente a la más vieja
    lotes.forEach((l, i) => { l.bahias = bahias[i].ok ? bahias[i].data : []; });
    reservasVivas = porEstado.flatMap(x => (x.ok ? x.data : []))
        .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at));

    pintarKpisVivo(lotes);
    pintarLotesAdmin(lotes);
    pintarReservas();
}

function pintarKpisVivo(lotes) {
    const todas = lotes.flatMap(l => l.bahias);
    const cuenta = e => todas.filter(b => estadoBahia(b) === e).length;
    const total = todas.length;
    const ocupadas = cuenta('ocupada');
    const items = [
        ['Parqueaderos', lotes.length, `${lotes.filter(l => Date.now() - Date.parse(l.last_connection) < 3600e3).length} con señal en la última hora`, ''],
        ['Bahías', total, 'registradas por los nodos', ''],
        ['Libres', cuenta('libre'), total ? `${num(100 * cuenta('libre') / total)} % del total` : '', 'var(--libre)'],
        ['Ocupadas', ocupadas, total ? `${num(100 * ocupadas / total)} % de ocupación` : '', 'var(--ocupada)'],
        ['Reservadas ahora', cuenta('reservada'), `${reservasVivas.filter(r => r.status === 'reserved').length} reservas programadas`, 'var(--reservada-borde)']
    ];
    $('#kpis-vivo').innerHTML = items.map(([t, v, s, c]) =>
        `<div class="kpi"><dt>${c ? `<i style="background:${c}"></i>` : ''}${t}</dt><dd>${num(v)}<small>${esc(s)}</small></dd></div>`).join('');
}

function pintarLotesAdmin(lotes) {
    if (!lotes.length) { $('#lotes-admin').innerHTML = '<div class="panel vacio">No hay nodos registrados.</div>'; return; }
    $('#lotes-admin').innerHTML = lotes.map(l => {
        const total = l.bahias.length, libres = l.bahias.filter(b => estadoBahia(b) === 'libre').length;
        const est = libres === 0 ? insignia('ocupada', 'Lleno') : insignia('libre', `${libres} libres`);
        return `<article class="lote-admin">
            <div class="fila-1"><div><h3>${esc(l.node_id)}</h3><div class="senal">Última señal ${haceCuanto(l.last_connection)}</div></div>${est}</div>
            <div class="medidor" aria-hidden="true"><span class="m-ocupada" style="width:${total ? 100 * (total - libres) / total : 0}%"></span><span class="m-libre" style="flex:1"></span></div>
            <div class="mini-bahias">${l.bahias.map(b => {
                const e = estadoBahia(b);
                return `<div class="mini ${e}" title="${esc(b.space_id)} · ${NOMBRE_ESTADO[e]}">${ICONO_ESTADO[e]}${esc(b.space_id)}</div>`;
            }).join('')}</div>
        </article>`;
    }).join('');
}

function pintarReservas() {
    const historial = filtroReservas === 'cancelled';
    const filas = historial ? reservasCanceladas
        : reservasVivas.filter(r => filtroReservas === 'todas' || r.status === filtroReservas);
    $('#t-reservas').textContent = historial ? 'Reservas canceladas' : 'Reservas en curso';
    $('#nota-reservas-vivo').textContent = historial
        ? `Canceladas por el usuario o desde este panel · ${num(filas.length)}${filas.length === 200 ? '+' : ''} en total`
        : 'Programadas, vigentes (bahía apartada) y con el carro adentro';
    $('#th-accion').textContent = historial ? 'Creada' : '';
    if (!filas.length) {
        $('#tabla-reservas').innerHTML = `<tr><td colspan="7" class="vacio">No hay reservas en este estado.</td></tr>`;
        return;
    }
    $('#tabla-reservas').innerHTML = filas.map(r => `<tr>
        <td style="font-family:ui-monospace,Menlo,monospace">${esc(r.reservation_id)}</td>
        <td>${esc(r.node_id)}</td><td>${esc(r.space_id)}</td><td><strong>${esc(r.plate)}</strong></td>
        <td>${insigniaReserva(r.status)}</td>
        <td>${esc(franja(r.starts_at, r.ends_at))}</td>
        <td class="num">${historial ? `<span class="nota" title="${esc(r.created_at)}">${esc(haceCuanto(r.created_at))}</span>`
            : ['reserved', 'active'].includes(r.status) ? `<button class="boton chico peligro" data-cancelar="${esc(r.reservation_id)}">Cancelar</button>` : ''}</td>
    </tr>`).join('');
}

$('#filtro-reservas').onclick = e => {
    const b = e.target.closest('[data-f]');
    if (!b) return;
    filtroReservas = b.dataset.f;
    $$('#filtro-reservas .chip').forEach(c => c.setAttribute('aria-pressed', c === b));
    pintarReservas();
};

let porCancelar = null;
$('#tabla-reservas').onclick = e => {
    const b = e.target.closest('[data-cancelar]');
    if (!b) return;
    porCancelar = reservasVivas.find(r => r.reservation_id === b.dataset.cancelar);
    $('#cancelar-texto').textContent = `${porCancelar.reservation_id} · placa ${porCancelar.plate} · ${porCancelar.node_id} ${porCancelar.space_id}, ${franja(porCancelar.starts_at, porCancelar.ends_at)}.`;
    $('#d-cancelar').showModal();
};
$('#b-confirmar-cancelar').onclick = async () => {
    const r = await api(`/reservas/${encodeURIComponent(porCancelar.reservation_id)}`, { method: 'DELETE' });
    $('#d-cancelar').close();
    toast(r.ok ? 'Reserva cancelada' : (r.data?.detail || 'No se pudo cancelar'));
    refrescarVivo();
};
$$('dialog [data-cerrar]').forEach(b => b.onclick = () => b.closest('dialog').close());

// ======================= ANÁLISIS =======================
let analisisIniciado = false;
let nodoActual = TODOS;
let nodos = [];
let horasTodos = [];

const hora = h => h === null || h === undefined ? '–' : `${h}:00`;
const fechaCorta = iso => {
    const t = new Intl.DateTimeFormat('es-CO', { weekday: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(iso + 'T12:00:00Z'));
    return t.replace('.', '');
};
const fechaLarga = iso => new Intl.DateTimeFormat('es-CO', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(iso + 'T12:00:00Z'));
const nombreNodo = id => id === TODOS ? 'Todos' : id;

async function apiAnalisis(ruta) {
    const r = await api(`/api/${ruta}`);
    if (!r.ok) throw new Error(`/api/${ruta} respondió ${r.status}`);
    return r.data || [];
}

async function iniciarAnalisis() {
    analisisIniciado = true;
    try {
        [nodos, horasTodos] = await Promise.all([apiAnalisis('nodos'), apiAnalisis(`horas/${TODOS}`)]);
    } catch (e) {
        console.error(e);
        $('#aviso-global').innerHTML = `${ICONOS.alerta}<span>No se pudo leer la API de análisis. Revisa que Node-RED esté corriendo.</span>`;
        $('#aviso-global').hidden = false;
        analisisIniciado = false;
        return;
    }
    elegirNodo(TODOS);
}

function pintarSelector() {
    $('#nodos').innerHTML = [TODOS, ...nodos.map(n => n.node_id)].map(id =>
        `<button type="button" class="chip" data-nodo="${esc(id)}" aria-pressed="${id === nodoActual}">${esc(nombreNodo(id))}</button>`).join('');
}
$('#nodos').onclick = e => { const b = e.target.closest('[data-nodo]'); if (b) elegirNodo(b.dataset.nodo); };

async function elegirNodo(id) {
    nodoActual = id;
    pintarSelector();
    pintarTablaNodos();
    let resumen, horas, dias, categorias;
    try {
        [resumen, horas, dias, categorias] = await Promise.all(
            ['resumen', 'horas', 'dias', 'categorias'].map(r => apiAnalisis(`${r}/${encodeURIComponent(id)}`)));
    } catch (e) { console.error(e); return; }

    const vacio = !resumen.length;
    $('#analisis-vacio').hidden = !vacio;
    $('#analisis-contenido').hidden = vacio;
    if (vacio) { $('#periodo').textContent = 'Sin datos'; return; }
    if (id === TODOS) horasTodos = horas;

    const r = resumen[0];
    $('#periodo').textContent = `Del ${fechaLarga(r.period_from)} al ${fechaLarga(r.period_to)}`;
    pintarKpisAnalisis(r);
    graficaHoras(horas);
    graficaDias(dias);
    graficaReservas(categorias);
    graficaCategoria('g-acceso', categorias, 'modo_acceso', { qr: 'Con QR (reserva)', placa: 'Digitando la placa' }, 'entradas');
    graficaCategoria('g-estadia', categorias, 'tipo_estadia', {}, 'estadías');
}

function pintarKpisAnalisis(r) {
    const items = [
        ['Ocupación promedio', `${num(r.occupancy_pct, 1)} %`, `de ${num(r.bays)} bahías`],
        ['Entradas por día', num(r.entries_per_day, 1), `${num(r.entries)} en el periodo`],
        ['Estadía media', duracionTexto(r.avg_duration_min), `mediana ${duracionTexto(r.median_duration_min)}`],
        ['Hora de mayor ocupación', hora(r.peak_hour), 'promedio del periodo'],
        ['Veces que se llenó', num(r.times_full), r.times_full > 0 ? `${duracionTexto(r.minutes_full)} lleno en total` : 'nunca se llenó'],
        ['Reservas sin llegada', r.no_show_pct === null ? '–' : `${num(r.no_show_pct, 1)} %`, `de ${num(r.reservations)} reservas`]
    ];
    $('#kpis-analisis').innerHTML = items.map(([t, v, s]) =>
        `<div class="kpi"><dt>${t}</dt><dd>${v}<small>${esc(s)}</small></dd></div>`).join('');
}

// ---------- Chart.js: opciones comunes ----------
function base() {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    Chart.defaults.color = css('--texto-3');
    return {
        responsive: true, maintainAspectRatio: false, animation: { duration: 350 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { position: 'top', align: 'end', labels: { boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3, color: css('--texto-2') } },
            tooltip: { backgroundColor: css('--texto'), titleColor: css('--panel'), bodyColor: css('--panel'), padding: 10, cornerRadius: 8, boxPadding: 4 }
        }
    };
}
const ejeX = () => ({ grid: { display: false }, border: { color: css('--borde-fuerte') }, ticks: { maxRotation: 0, autoSkipPadding: 10 } });
const ejeY = extra => ({ beginAtZero: true, grid: { color: css('--rejilla') }, border: { display: false }, ...extra });
function dibujar(id, config) {
    if (graficas[id]) graficas[id].destroy();
    // sin filas: se muestra un mensaje en vez de unos ejes vacíos
    const vacia = !config.data.datasets.some(d => d.data.some(v => v !== null && Number(v) > 0));
    const caja = document.getElementById(id).parentElement;
    if (vacia) caja.dataset.vacio = 'Sin datos en el periodo'; else delete caja.dataset.vacio;
    graficas[id] = new Chart(document.getElementById(id), config);
}

function graficaHoras(horas) {
    const rango = h => h.hour >= 5 && h.hour <= 22;
    const series = [{
        label: nodoActual === TODOS ? 'Todos los parqueaderos' : nodoActual,
        data: horas.filter(rango).map(h => h.occupancy_pct),
        borderColor: css('--serie-1'), backgroundColor: css('--serie-1') + '22', fill: true,
        borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.35
    }];
    if (nodoActual !== TODOS) {
        series.push({
            label: 'Todos (referencia)', data: horasTodos.filter(rango).map(h => h.occupancy_pct),
            borderColor: css('--referencia'), backgroundColor: css('--referencia'),
            borderWidth: 2, borderDash: [6, 4], pointRadius: 0, pointHoverRadius: 4, tension: 0.35
        });
    }
    const o = base();
    o.plugins.legend.display = series.length > 1;
    o.plugins.tooltip.callbacks = { label: c => ` ${c.dataset.label}: ${num(c.parsed.y, 1)} %` };
    o.scales = { x: ejeX(), y: ejeY({ max: 100, ticks: { stepSize: 25, callback: v => v + ' %' } }) };
    dibujar('g-horas', { type: 'line', data: { labels: horas.filter(rango).map(h => hora(h.hour)), datasets: series }, options: o });
}

function graficaDias(dias) {
    const serie = (label, campo, color, arriba) => ({
        label, data: dias.map(d => d[campo]), backgroundColor: css(color),
        borderColor: css('--panel'), borderWidth: { top: arriba ? 0 : 2 },
        borderRadius: arriba ? { topLeft: 4, topRight: 4 } : 0, borderSkipped: false, maxBarThickness: 40
    });
    const o = base();
    o.scales = { x: { ...ejeX(), stacked: true }, y: ejeY({ stacked: true, ticks: { precision: 0 } }) };
    dibujar('g-dias', {
        type: 'bar',
        data: { labels: dias.map(d => fechaCorta(d.day)), datasets: [serie('Por placa', 'entries_plate', '--serie-1', false), serie('Con QR', 'entries_qr', '--serie-2', true)] },
        options: o
    });
}

function barrasH(id, filas, unidad) {
    const o = base();
    o.indexAxis = 'y';
    o.plugins.legend.display = false;
    o.interaction = { mode: 'nearest', intersect: true, axis: 'y' };
    o.plugins.tooltip.callbacks = { label: c => ` ${num(c.parsed.x)} ${unidad} · ${num(filas[c.dataIndex].pct, 1)} %` };
    o.scales = {
        x: ejeY({ ticks: { precision: 0 } }),
        y: { grid: { display: false }, border: { color: css('--borde-fuerte') }, ticks: { color: css('--texto-2') } }
    };
    dibujar(id, {
        type: 'bar',
        data: {
            labels: filas.map(f => `${f.nombre}  ${num(f.pct)} %`),
            datasets: [{ data: filas.map(f => f.n), backgroundColor: css('--serie-1'), borderRadius: 4, borderSkipped: 'start', maxBarThickness: 26 }]
        },
        options: o
    });
}

function graficaReservas(categorias) {
    const NOMBRES = { completed: 'Completadas', expired: 'Sin llegada', cancelled: 'Canceladas', entered: 'Carro adentro', active: 'Vigentes', reserved: 'Por empezar' };
    const filas = categorias.filter(c => c.category === 'estado_reserva').map(c => ({ ...c, nombre: NOMBRES[c.label] || c.label }));
    const total = filas.reduce((s, c) => s + Number(c.n), 0);
    $('#nota-reservas').textContent = total ? `${num(total)} reservas en el periodo` : 'No hubo reservas en el periodo';
    barrasH('g-reservas', filas, 'reservas');
}

function graficaCategoria(id, categorias, categoria, nombres, unidad) {
    const capital = t => String(t).charAt(0).toUpperCase() + String(t).slice(1).replace(/_/g, ' ');
    const filas = categorias.filter(c => c.category === categoria).map(c => ({ ...c, nombre: nombres[c.label] || capital(c.label) }));
    barrasH(id, filas, unidad);
}

function pintarTablaNodos() {
    if (!nodos.length) { $('#tabla-nodos').innerHTML = '<tr><td colspan="10" class="vacio">Sin datos de análisis</td></tr>'; return; }
    $('#tabla-nodos').innerHTML = nodos.map(n => `
        <tr class="clic ${n.node_id === nodoActual ? 'activa' : ''}" tabindex="0" data-nodo="${esc(n.node_id)}">
            <td><strong>${esc(n.node_id)}</strong></td>
            <td class="num">${num(n.bays)}</td>
            <td><div class="barra-celda"><span class="pista"><span class="relleno" style="width:${Math.min(100, n.occupancy_pct || 0)}%"></span></span><span class="num">${num(n.occupancy_pct, 1)} %</span></div></td>
            <td class="num">${num(n.entries_per_day, 1)}</td>
            <td class="num">${num(n.entries_per_bay_day, 1)}</td>
            <td class="num">${duracionTexto(n.avg_duration_min)}</td>
            <td class="num">${hora(n.peak_hour)}</td>
            <td class="num">${n.pct_qr === null ? '–' : num(n.pct_qr, 1) + ' %'}</td>
            <td class="num">${n.no_show_pct === null ? '–' : num(n.no_show_pct, 1) + ' %'}</td>
            <td class="num">${num(n.times_full)}</td>
        </tr>`).join('');
}
$('#tabla-nodos').onclick = e => { const f = e.target.closest('[data-nodo]'); if (f) elegirNodo(f.dataset.nodo); };
$('#tabla-nodos').onkeydown = e => { const f = e.target.closest('[data-nodo]'); if (f && e.key === 'Enter') elegirNodo(f.dataset.nodo); };

// si cambia el tema del sistema, se redibujan las gráficas con los colores nuevos
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (analisisIniciado) elegirNodo(nodoActual); });

// ======================= ARRANQUE =======================
$('#pie-api').textContent = `API: ${NODE_RED}`;
abrir(location.hash === '#analisis' ? 'analisis' : 'vivo');
refrescarVivo();
setInterval(() => { if (!document.hidden && !$('#vista-vivo').hidden) refrescarVivo(); }, REFRESCO_MS);
