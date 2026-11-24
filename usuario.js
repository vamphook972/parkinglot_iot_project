// ==========================================================================
// Parking IoT · página del usuario
// Estado en vivo de parqueaderos y bahías + reservas (crear, ver, cancelar).
// API usada: GET /parqueaderos, GET /parqueaderos/:id/bahias[?desde&hasta],
//            GET /parqueaderos/:id/agenda?fecha=  (línea de tiempo, sin placas),
//            POST /reservas, DELETE /reservas/:id, GET /reservas/:id, GET /reservas?placa=
// ==========================================================================

const GUARDADAS = 'parkingiot.misReservas';          // ids de reservas hechas en este equipo
const DURACIONES = [30, 60, 120, 180, 240, 480];       // minutos

const estado = {
    lotes: [],               // GET /parqueaderos
    lote: null,              // node_id elegido
    bahiasAhora: [],         // estado en vivo del lote elegido
    bahiasFranja: [],        // disponibilidad para la franja del formulario
    vistaMapa: 'ahora',      // 'ahora' (estado en vivo) o 'linea' (línea de tiempo del día)
    agendaHoy: [],           // reservas vivas de hoy en el lote elegido
    agendaDia: [],           // las del día elegido en el formulario
    fechaAgenda: null,
    firmaLinea: '',
    claveScroll: '',
    bahia: null,             // space_id elegido para reservar
    duracion: 60,
    previas: new Map(),      // estado anterior de cada bahía, para animar los cambios
    enviando: false
};

// ---------- Persistencia local (solo comodidad: si falla, la página sigue igual) ----------
function leerGuardadas() {
    try { return JSON.parse(localStorage.getItem(GUARDADAS)) || []; } catch { return []; }
}
function guardar(id) {
    try {
        const ids = [id, ...leerGuardadas().filter(x => x !== id)].slice(0, 20);
        localStorage.setItem(GUARDADAS, JSON.stringify(ids));
    } catch { /* sin almacenamiento */ }
}

// ---------- Franja elegida en el formulario ----------
function franjaElegida() {
    const fecha = $('#f-fecha').value;
    const hora = $('#f-hora').value;
    if (!fecha || hora === '') return null;
    let desde;
    if (hora === 'ahora') {
        const a = ahoraColombia();
        desde = isoColombia(hoyISO(), a.hora * 60 + a.min);
    } else {
        desde = isoColombia(fecha, Number(hora));
    }
    return { desde, hasta: isoDesdeMs(Date.parse(desde) + estado.duracion * 60000) };
}
function isoDesdeMs(ms) {
    const d = new Date(ms - MS_ZONA);
    return `${d.getUTCFullYear()}-${dos(d.getUTCMonth() + 1)}-${dos(d.getUTCDate())}T${dos(d.getUTCHours())}:${dos(d.getUTCMinutes())}:00${ZONA}`;
}

// ---------- Formulario: día, hora y duración ----------
function prepararFormulario() {
    const hoy = hoyISO();
    const f = $('#f-fecha');
    f.min = hoy;
    const max = new Date(Date.parse(`${hoy}T12:00:00${ZONA}`) + 13 * 86400000);
    f.max = isoDesdeMs(max.getTime()).slice(0, 10);
    f.value = hoy;
    llenarHoras();

    $('#f-duracion').innerHTML = DURACIONES.map(m =>
        `<button type="button" class="chip" data-min="${m}" aria-pressed="${m === estado.duracion}">${duracionTexto(m)}</button>`).join('');
    $('#f-duracion').onclick = e => {
        const b = e.target.closest('[data-min]');
        if (!b) return;
        estado.duracion = Number(b.dataset.min);
        $$('#f-duracion .chip').forEach(c => c.setAttribute('aria-pressed', c === b));
        franjaCambio();
    };

    f.onchange = () => { if (f.value < hoy) f.value = hoy; llenarHoras(); franjaCambio(); };
    $('#f-hora').onchange = franjaCambio;
    $('#f-lote').onchange = () => elegirLote($('#f-lote').value);

    const placa = $('#f-placa');
    placa.oninput = () => {
        const limpio = normalizarPlaca(placa.value);
        if (placa.value !== limpio) placa.value = limpio;
        $('#campo-placa').classList.remove('invalido');
        $('#ayuda-placa').textContent = 'Letras y números, sin espacios ni guiones.';
        actualizarResumen();
    };
    $('#form-reserva').onsubmit = e => { e.preventDefault(); reservar(); };
}

// Horas de llegada cada 15 min. Para hoy solo las que no han pasado, más "Ahora".
function llenarHoras() {
    const sel = $('#f-hora');
    const previo = sel.value;
    const esHoy = $('#f-fecha').value === hoyISO();
    const a = ahoraColombia();
    const desde = esHoy ? Math.ceil((a.hora * 60 + a.min + 1) / 15) * 15 : 0;
    const opciones = [];
    if (esHoy) opciones.push(`<option value="ahora">Ahora mismo</option>`);
    for (let m = desde; m < 24 * 60; m += 15) {
        const etiqueta = horaCorta(isoColombia(hoyISO(), m));
        opciones.push(`<option value="${m}">${etiqueta}</option>`);
    }
    sel.innerHTML = opciones.join('');
    if ([...sel.options].some(o => o.value === previo)) sel.value = previo;
    else if (!esHoy) sel.value = String(8 * 60);
}

function franjaCambio() {
    estado.vistaMapa = 'linea';
    pintarVistaMapa();
    cargarFranja();
    if (estado.fechaAgenda !== $('#f-fecha').value) cargarAgenda();
}

// ---------- Datos en vivo ----------
async function cargarLotes() {
    const r = await api('/parqueaderos');
    if (!r.ok) {
        marcarVivo($('#vivo'), false, 'Sin conexión');
        const aviso = $('#aviso-global');
        aviso.innerHTML = `${ICONOS.alerta}<span>No pudimos conectarnos con el sistema de parqueaderos. Reintentamos automáticamente.</span>`;
        aviso.hidden = false;
        return false;
    }
    $('#aviso-global').hidden = true;
    marcarVivo($('#vivo'), true, 'En vivo');
    estado.lotes = r.data || [];
    if (!estado.lote && estado.lotes.length) {
        // por defecto, el parqueadero con más bahías libres
        estado.lote = [...estado.lotes].sort((a, b) => b.free_now - a.free_now)[0].node_id;
    }
    pintarLotes();
    return true;
}

function pintarLotes() {
    const libres = estado.lotes.reduce((s, l) => s + Number(l.free_now || 0), 0);
    const total = estado.lotes.reduce((s, l) => s + Number(l.total_bays || 0), 0);
    $('#resumen-total').innerHTML = `<strong class="tabular">${libres}</strong><span>de ${total} bahías libres ahora</span>`;

    if (!estado.lotes.length) {
        $('#lotes').innerHTML = `<div class="panel vacio"><strong>Todavía no hay parqueaderos</strong>Cuando un nodo se registre aparecerá aquí.</div>`;
        return;
    }
    $('#lotes').innerHTML = estado.lotes.map(l => {
        const total = Number(l.total_bays) || 0, libres = Number(l.free_now) || 0;
        const pctLibre = total ? (libres / total) * 100 : 0;
        const est = libres === 0 ? insignia('ocupada', 'Lleno') : libres / total <= 0.25 ? insignia('reservada', 'Casi lleno') : insignia('libre', 'Disponible');
        return `<button type="button" class="lote" data-lote="${esc(l.node_id)}" aria-pressed="${l.node_id === estado.lote}">
            <div class="fila-1"><span class="nombre">${esc(l.node_id)}</span>${est}</div>
            <div class="cifra tabular">${libres}<small>de ${total} libres</small></div>
            <div class="medidor" aria-hidden="true">
                <span class="m-libre" style="width:${pctLibre}%"></span><span class="m-ocupada" style="flex:1"></span>
            </div>
            <div class="senal">Última señal del nodo ${haceCuanto(l.last_connection)}</div>
        </button>`;
    }).join('');

    // selector del formulario (sin perder la elección)
    const sel = $('#f-lote');
    sel.innerHTML = estado.lotes.map(l => `<option value="${esc(l.node_id)}">${esc(l.node_id)} · ${l.free_now} libres ahora</option>`).join('');
    sel.value = estado.lote;
}

$('#lotes').addEventListener('click', e => {
    const b = e.target.closest('[data-lote]');
    if (b) elegirLote(b.dataset.lote);
});

function elegirLote(id) {
    if (id === estado.lote) return;
    estado.lote = id;
    estado.bahia = null;
    estado.bahiasAhora = [];
    estado.bahiasFranja = [];
    estado.agendaHoy = [];
    estado.agendaDia = [];
    estado.fechaAgenda = null;
    estado.previas.clear();
    pintarLotes();
    pintarMapa();
    cargarBahias();
    cargarFranja();
    cargarAgenda();
}

async function cargarBahias() {
    if (!estado.lote) return;
    const id = estado.lote;
    const r = await api(`/parqueaderos/${encodeURIComponent(id)}/bahias`);
    if (id !== estado.lote) return;              // el usuario cambió de lote mientras tanto
    if (r.ok) { estado.bahiasAhora = r.data || []; pintarMapa(); }
}

async function cargarFranja() {
    const f = franjaElegida();
    if (!estado.lote || !f) return;
    const id = estado.lote;
    const r = await api(`/parqueaderos/${encodeURIComponent(id)}/bahias?desde=${encodeURIComponent(f.desde)}&hasta=${encodeURIComponent(f.hasta)}`);
    if (id !== estado.lote) return;
    if (!r.ok) { estado.bahiasFranja = []; $('#f-bahias').innerHTML = `<span class="nota">${esc(r.data?.detail || 'No se pudo consultar')}</span>`; return; }
    estado.bahiasFranja = r.data || [];
    // si la bahía elegida dejó de estar disponible, se suelta
    if (estado.bahia && !estado.bahiasFranja.some(b => b.space_id === estado.bahia && b.available)) {
        if (estado.bahia) toast(`La bahía ${estado.bahia} ya no está disponible en ese horario`);
        estado.bahia = null;
    }
    pintarChipsBahias();
    pintarMapa();
    actualizarResumen();
}

// ---------- Agenda del día (para la línea de tiempo) ----------
// GET /parqueaderos/:id/agenda?fecha= -> reservas vivas que tocan ese día, sin placas.
async function cargarAgenda() {
    if (!estado.lote) return;
    const id = estado.lote, hoy = hoyISO(), fecha = $('#f-fecha').value || hoy;
    const pedir = f => api(`/parqueaderos/${encodeURIComponent(id)}/agenda?fecha=${f}`);
    const [rh, rd] = await Promise.all([pedir(hoy), fecha === hoy ? null : pedir(fecha)]);
    if (id !== estado.lote) return;
    if (rh.ok) estado.agendaHoy = rh.data || [];
    estado.agendaDia = fecha === hoy ? estado.agendaHoy : (rd && rd.ok ? rd.data || [] : []);
    estado.fechaAgenda = fecha;
    pintarMapa();
}

// minutos desde la medianoche (Colombia) de `fecha`; puede ser negativo o > 1440
const minDia = (iso, fecha) => (Date.parse(iso) - Date.parse(`${fecha}T00:00:00${ZONA}`)) / 60000;
function minAhora(fecha) {
    if (fecha !== hoyISO()) return null;
    const a = ahoraColombia();
    return a.hora * 60 + a.min;
}
const agendaDe = fecha => (fecha === hoyISO() ? estado.agendaHoy : estado.agendaDia);
const libreAhora = bahia => { const b = estado.bahiasAhora.find(x => x.space_id === bahia); return !!b && estadoBahia(b) === 'libre'; };

// ¿Se puede reservar `bahia` de `ini` a `ini+dur` (minutos del día)? Mismas reglas que el servidor:
// no cruzarse con otra reserva viva, y si empieza en 10 min o menos, la bahía tiene que estar libre ahora.
function franjaValida(bahia, fecha, ini, dur) {
    const choca = agendaDe(fecha).some(r => r.space_id === bahia
        && minDia(r.starts_at, fecha) < ini + dur && minDia(r.ends_at, fecha) > ini);
    if (choca) return false;
    const ahora = minAhora(fecha);
    if (ahora !== null && ini <= ahora + 10 && !libreAhora(bahia)) return false;
    return true;
}

// Primer momento libre para `bahia` desde `desde` (minutos) en pasos de 15 min. 'ahora' si sirve ya mismo.
function primerHueco(bahia, fecha, dur, desde = null) {
    const ahora = minAhora(fecha);
    if (ahora !== null && (desde === null || desde <= ahora) && franjaValida(bahia, fecha, ahora, dur)) return 'ahora';
    let t = desde ?? (ahora === null ? 6 * 60 : 0);
    if (ahora !== null) t = Math.max(t, Math.ceil((ahora + 1) / 15) * 15);
    t = Math.ceil(t / 15) * 15;
    for (; t < 24 * 60; t += 15) if (franjaValida(bahia, fecha, t, dur)) return t;
    return null;
}

// Para la vista "Ahora": hasta cuándo está tomada una bahía hoy (encadena reservas seguidas)
function libreDesde(bahia) {
    const hoy = hoyISO();
    let t = minAhora(hoy), cambio = true;
    const propias = estado.agendaHoy.filter(r => r.space_id === bahia);
    while (cambio) {
        cambio = false;
        for (const r of propias) {
            const ini = minDia(r.starts_at, hoy), fin = minDia(r.ends_at, hoy);
            if (ini <= t + 1 && fin > t) { t = fin; cambio = true; }
        }
    }
    return t > minAhora(hoy) ? t : null;
}
const horaDe = (fecha, min) => horaCorta(isoColombia(fecha, Math.round(min)));
// '5:15' / '5' (sin a. m./p. m.) para los bloques angostos de la línea de tiempo
function horaMini(fecha, min) {
    const d = new Date(Date.parse(isoColombia(fecha, Math.round(min))) - MS_ZONA);
    const h = d.getUTCHours() % 12 || 12, m = d.getUTCMinutes();
    return m ? `${h}:${dos(m)}` : `${h}`;
}

// ---------- Mapa ----------
function pintarVistaMapa() {
    $$('.vistas-mapa button').forEach(b => b.setAttribute('aria-pressed', b.dataset.vista === estado.vistaMapa));
    estado.firmaLinea = '';
    pintarMapa();
}
$$('.vistas-mapa button').forEach(b => b.onclick = () => { estado.vistaMapa = b.dataset.vista; pintarVistaMapa(); });

function pintarMapa() {
    const lote = estado.lotes.find(l => l.node_id === estado.lote);
    $('#t-mapa').textContent = lote ? `Bahías de ${lote.node_id}` : 'Bahías';
    $('#mapa').hidden = estado.vistaMapa !== 'ahora';
    $('#linea').hidden = estado.vistaMapa !== 'linea';
    if (estado.vistaMapa === 'linea') return pintarLinea(lote);
    pintarAhora(lote);
}

function pintarAhora(lote) {
    const mapa = $('#mapa');
    $('#nota-mapa').textContent = lote ? `${lote.free_now} de ${lote.total_bays} libres en este momento · toca una bahía para reservarla` : 'Elige un parqueadero';
    $('#contexto-horario').textContent = 'Se actualiza cada 5 segundos';
    $('#leyenda').innerHTML = `<span><i class="l-libre"></i>Libre</span><span><i class="l-ocupada"></i>Ocupada</span><span><i class="l-reservada"></i>Reservada</span>`;

    const lista = estado.bahiasAhora;
    if (!lista.length) {
        mapa.innerHTML = `<div class="vacio" style="grid-column:1/-1">${estado.lote ? 'Cargando bahías…' : 'Elige un parqueadero para ver sus bahías'}</div>`;
        return;
    }
    const hoy = hoyISO();
    mapa.innerHTML = lista.map(b => {
        const e = estadoBahia(b);
        const antes = estado.previas.get(b.space_id);
        const cambio = antes && antes !== e;
        estado.previas.set(b.space_id, e);
        // las reservadas dicen desde cuándo quedan libres; todas se pueden tocar
        const hasta = e === 'reservada' ? libreDesde(b.space_id) : null;
        const detalle = hasta !== null && hasta < 24 * 60 ? `<span class="detalle">Libre ${horaDe(hoy, hasta)}</span>` : '';
        const clase = `${e} elegible${cambio ? ' cambio' : ''}${b.space_id === estado.bahia ? ' elegida' : ''}`;
        const accion = e === 'libre' ? 'Reservar ahora' : 'Ver cuándo queda libre';
        return `<button type="button" class="bahia ${clase}" data-bahia="${esc(b.space_id)}" aria-label="Bahía ${esc(b.space_id)}, ${NOMBRE_ESTADO[e]}. ${accion}">
            <span class="codigo">${esc(b.space_id)}</span>
            <span class="icono">${ICONO_ESTADO[e]}</span>
            <span class="etiqueta">${NOMBRE_ESTADO[e]}</span>${detalle}
        </button>`;
    }).join('');
}

// ---------- Línea de tiempo ----------
const PX_MIN = 1.6;                                   // 96 px por hora

function pintarLinea(lote) {
    const cont = $('#linea');
    const fecha = $('#f-fecha').value || hoyISO();
    const ahora = minAhora(fecha);
    const agenda = agendaDe(fecha);
    const bahias = estado.bahiasAhora.map(b => b.space_id);
    const f = franjaElegida();

    $('#nota-mapa').textContent = `${diaRelativo(`${fecha}T12:00:00${ZONA}`, true)} · toca un espacio libre para elegir bahía y hora`;
    $('#leyenda').innerHTML = `<span><i class="l-reservada"></i>Reservada</span><span><i class="l-ocupada"></i>Con carro</span><span><i style="background:var(--marca)"></i>Tu reserva</span>`;
    $('#contexto-horario').innerHTML = f ? `Duración: <strong>${duracionTexto(estado.duracion)}</strong>` : '';

    if (!bahias.length) { cont.innerHTML = `<div class="vacio">${estado.lote ? 'Cargando…' : 'Elige un parqueadero'}</div>`; return; }
    if (estado.fechaAgenda !== fecha) { cont.innerHTML = '<div class="vacio">Cargando la agenda del día…</div>'; return; }

    // no volver a dibujar si nada cambió (evita parpadeos con el refresco de 5 s)
    const firma = JSON.stringify([fecha, ahora, agenda, estado.bahiasAhora, estado.bahia, f, estado.duracion]);
    if (firma === estado.firmaLinea) return;
    const clave = `${estado.lote}|${fecha}`;
    const primeraVez = estado.claveScroll !== clave;
    estado.claveScroll = clave;
    estado.firmaLinea = firma;

    let ini = 6 * 60;
    agenda.forEach(r => { ini = Math.min(ini, minDia(r.starts_at, fecha)); });
    if (ahora !== null) ini = Math.min(ini, ahora - 60);
    ini = Math.max(0, Math.floor(ini / 60) * 60);
    const fin = 24 * 60;
    const x = m => (Math.max(ini, Math.min(fin, m)) - ini) * PX_MIN;
    const ancho = x(fin);

    const eje = [];
    for (let h = ini / 60; h < 24; h++) {
        const etiqueta = `${h % 12 || 12} ${h < 12 ? 'a. m.' : 'p. m.'}`;
        eje.push(`<span style="left:${x(h * 60)}px">${etiqueta}</span>`);
    }
    if (ahora !== null) eje.push(`<span class="tl-ahora-etq" style="left:${x(ahora)}px">Ahora</span>`);

    const filas = bahias.map(id => {
        const bloques = [];
        if (ahora !== null) bloques.push(`<div class="tl-pasado" style="width:${x(ahora)}px"></div>`);
        agenda.filter(r => r.space_id === id).forEach(r => {
            const a = minDia(r.starts_at, fecha), b = minDia(r.ends_at, fecha);
            const carro = r.status === 'entered';
            const texto = `${carro ? 'Con carro' : 'Reservada'} · ${horaCorta(r.starts_at)} – ${horaCorta(r.ends_at)}`;
            bloques.push(`<div class="tl-bloque ${carro ? 'carro' : 'reserva'}" style="left:${x(a)}px;width:${Math.max(4, x(b) - x(a))}px" title="${texto}"><span>${horaMini(fecha, a)}–${horaMini(fecha, b)}</span></div>`);
        });
        // carro sin reserva: se marca desde ahora (no se sabe cuándo sale)
        const viva = estado.bahiasAhora.find(b => b.space_id === id);
        if (ahora !== null && viva && estadoBahia(viva) === 'ocupada' && !agenda.some(r => r.space_id === id && r.status === 'entered')) {
            bloques.push(`<div class="tl-bloque carro abierto" style="left:${x(ahora)}px;width:${15 * PX_MIN}px" title="Hay un carro en este momento"><span>Carro ahora</span></div>`);
        }
        if (f && id === estado.bahia && f.desde.slice(0, 10) === fecha) {
            const a = minDia(f.desde, fecha), b = minDia(f.hasta, fecha);
            bloques.push(`<div class="tl-bloque elegido" style="left:${x(a)}px;width:${Math.max(4, x(b) - x(a))}px"><span>Tú · ${horaMini(fecha, a)}–${horaMini(fecha, b)}</span></div>`);
        }
        if (ahora !== null) bloques.push(`<div class="tl-linea-ahora" style="left:${x(ahora)}px"></div>`);
        return `<div class="tl-fila"><div class="tl-nombre${id === estado.bahia ? ' activa' : ''}">${esc(id)}</div>
            <div class="tl-pista" data-bahia="${esc(id)}" data-ini="${ini}" style="width:${ancho}px">${bloques.join('')}<div class="tl-fantasma" hidden></div></div></div>`;
    }).join('');

    const scroll = $('.tl-scroll', cont);
    const posicion = scroll ? scroll.scrollLeft : 0;
    cont.innerHTML = `<div class="tl-scroll"><div class="tl">
        <div class="tl-fila"><div class="tl-nombre tl-esquina"></div><div class="tl-eje" style="width:${ancho}px">${eje.join('')}</div></div>
        ${filas}
    </div></div>`;
    const nuevo = $('.tl-scroll', cont);
    // la primera vez se lleva la vista a la hora actual (o a la franja elegida); después se respeta el scroll
    if (primeraVez) {
        const foco = f && f.desde.slice(0, 10) === fecha ? minDia(f.desde, fecha) : (ahora ?? 7 * 60);
        nuevo.scrollLeft = Math.max(0, x(foco) - 90);
    } else {
        nuevo.scrollLeft = posicion;
    }
}

// minuto del día bajo el puntero, redondeado hacia abajo a 15 min
function minutoEn(pista, clientX) {
    const r = pista.getBoundingClientRect();
    const m = Number(pista.dataset.ini) + (clientX - r.left) / PX_MIN;
    return Math.floor(m / 15) * 15;
}

$('#linea').addEventListener('mousemove', e => {
    const pista = e.target.closest('.tl-pista');
    $$('.tl-fantasma', $('#linea')).forEach(g => { if (!pista || g.parentElement !== pista) g.hidden = true; });
    if (!pista || e.target.closest('.tl-bloque')) { if (pista) $('.tl-fantasma', pista).hidden = true; return; }
    const fecha = $('#f-fecha').value, ahora = minAhora(fecha);
    let m = minutoEn(pista, e.clientX);
    if (ahora !== null && m < ahora) m = ahora;
    const ok = franjaValida(pista.dataset.bahia, fecha, m, estado.duracion);
    const g = $('.tl-fantasma', pista);
    g.hidden = false;
    g.className = `tl-fantasma ${ok ? 'ok' : 'mal'}`;
    g.style.left = `${(m - Number(pista.dataset.ini)) * PX_MIN}px`;
    g.style.width = `${estado.duracion * PX_MIN}px`;
    g.textContent = ok ? `${horaDe(fecha, m)} · ${duracionTexto(estado.duracion)}` : 'Ocupado';
});
$('#linea').addEventListener('mouseleave', () => $$('.tl-fantasma', $('#linea')).forEach(g => { g.hidden = true; }));

$('#linea').addEventListener('click', e => {
    const pista = e.target.closest('.tl-pista');
    if (!pista) return;
    const bahia = pista.dataset.bahia, fecha = $('#f-fecha').value, ahora = minAhora(fecha);
    let m = minutoEn(pista, e.clientX);
    if (ahora !== null && m < ahora) {
        if (ahora - m >= 15) return toast('Esa hora ya pasó');
        m = ahora;
    }
    if (franjaValida(bahia, fecha, m, estado.duracion)) return fijarReserva(bahia, ahora !== null && m <= ahora ? 'ahora' : m);
    // se cruza: se ofrece el siguiente espacio libre de esa bahía
    const sig = primerHueco(bahia, fecha, estado.duracion, m);
    if (sig === null) return toast(`${bahia} no tiene ${duracionTexto(estado.duracion)} libres después de esa hora`);
    fijarReserva(bahia, sig);
    toast(`Esa hora estaba ocupada: te propusimos ${bahia} a las ${horaDe(fecha, sig === 'ahora' ? ahora : sig)}`);
});

// Deja el formulario listo con esa bahía y esa hora (minutos del día o 'ahora')
function fijarReserva(bahia, hora) {
    if (hora !== 'ahora' && ![...$('#f-hora').options].some(o => o.value === String(hora))) llenarHoras();
    $('#f-hora').value = hora === 'ahora' ? 'ahora' : String(hora);
    estado.bahia = bahia;
    estado.vistaMapa = 'linea';
    pintarVistaMapa();
    pintarChipsBahias();
    actualizarResumen();
    cargarFranja();
    if (matchMedia('(max-width: 980px)').matches) $('#paso-3').scrollIntoView({ behavior: 'smooth', block: 'center' });
    else $('#f-placa').focus({ preventScroll: true });
}

// Vista "Ahora": tocar cualquier bahía. Libre -> reservar ya; tomada -> primer espacio libre de hoy.
$('#mapa').addEventListener('click', e => {
    const b = e.target.closest('.bahia');
    if (!b) return;
    const id = b.dataset.bahia, hoy = hoyISO();
    if ($('#f-fecha').value !== hoy) { $('#f-fecha').value = hoy; llenarHoras(); cargarAgenda(); }
    const h = primerHueco(id, hoy, estado.duracion);
    if (h === null) {
        toast(`${id} no tiene ${duracionTexto(estado.duracion)} libres hoy: prueba otro día en la línea de tiempo`);
        estado.bahia = id;
        estado.vistaMapa = 'linea';
        return pintarVistaMapa();
    }
    fijarReserva(id, h);
    if (h !== 'ahora') toast(`${id} queda libre desde las ${horaDe(hoy, h)}: te la dejamos lista a esa hora`);
});

function elegirBahia(id) {
    estado.bahia = id;
    pintarChipsBahias();
    pintarMapa();
    actualizarResumen();
}

function pintarChipsBahias() {
    const cont = $('#f-bahias');
    if (!estado.bahiasFranja.length) { cont.innerHTML = '<span class="nota">Este parqueadero no tiene bahías</span>'; return; }
    const disponibles = estado.bahiasFranja.filter(b => b.available).length;
    cont.innerHTML = estado.bahiasFranja.map(b =>
        `<button type="button" class="chip" data-bahia="${esc(b.space_id)}" aria-pressed="${b.space_id === estado.bahia}" ${b.available ? '' : 'disabled title="Ya reservada en ese horario"'}>${esc(b.space_id)}</button>`
    ).join('') + (disponibles ? '' : '<p class="nota" style="width:100%">No hay bahías libres en ese horario. Prueba otra hora u otro parqueadero.</p>');
}
$('#f-bahias').addEventListener('click', e => {
    const b = e.target.closest('[data-bahia]:not(:disabled)');
    if (b) elegirBahia(b.dataset.bahia);
});

// ---------- Resumen y envío ----------
function actualizarResumen() {
    const f = franjaElegida();
    const placa = normalizarPlaca($('#f-placa').value);
    $('#paso-1').classList.toggle('hecho', !!f);
    $('#paso-2').classList.toggle('hecho', !!estado.bahia);
    $('#paso-3').classList.toggle('hecho', placaValida(placa));

    const listo = f && estado.lote && estado.bahia && placaValida(placa);
    $('#b-reservar').disabled = !listo || estado.enviando;
    const res = $('#resumen-reserva');
    if (f && estado.bahia) {
        res.hidden = false;
        res.innerHTML = `
            <div><dt>Lugar</dt><dd>${esc(estado.lote)} · ${esc(estado.bahia)}</dd></div>
            <div><dt>Horario</dt><dd>${esc(franja(f.desde, f.hasta))}</dd></div>
            <div><dt>Placa</dt><dd>${placaValida(placa) ? esc(placa) : '—'}</dd></div>`;
    } else {
        res.hidden = true;
    }
}

const MENSAJES = {
    OVERLAP: 'Esa bahía acaba de dejar de estar disponible en ese horario. Elige otra.',
    PLATE_OVERLAP: 'Esta placa ya tiene una reserva que se cruza con ese horario. Revisa “Mis reservas”.',
    INVALID_BAY: 'Esa bahía ya no existe en el parqueadero. Recarga la página.',
    SIN_CONEXION: 'No hay conexión con el sistema. Revisa que Node-RED esté corriendo e intenta de nuevo.',
    SERVER_ERROR: 'El sistema tuvo un problema guardando la reserva. Intenta de nuevo.'
};

function nuevoCodigo() {
    const letras = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';   // sin 0/O ni 1/I para que se lea bien
    const al = crypto.getRandomValues(new Uint8Array(6));
    return 'RSV-' + [...al].map(x => letras[x % letras.length]).join('');
}

async function reservar() {
    const placa = normalizarPlaca($('#f-placa').value);
    if (!placaValida(placa)) {
        $('#campo-placa').classList.add('invalido');
        $('#ayuda-placa').textContent = 'Escribe la placa con 3 a 15 letras o números.';
        $('#f-placa').focus();
        return;
    }
    const f = franjaElegida();
    if (!f || !estado.bahia) return;

    estado.enviando = true;
    const boton = $('#b-reservar');
    boton.disabled = true;
    boton.textContent = 'Reservando…';
    $('#error-reserva').hidden = true;

    let r, cuerpo;
    for (let intento = 0; intento < 3; intento++) {        // si el código ya existe, se genera otro
        cuerpo = { reservation_id: nuevoCodigo(), node_id: estado.lote, space_id: estado.bahia, plate: placa, starts_at: f.desde, ends_at: f.hasta };
        r = await api('/reservas', { method: 'POST', body: cuerpo });
        if (r.data?.error !== 'DUPLICATE_ID') break;
    }

    estado.enviando = false;
    boton.textContent = 'Confirmar reserva';

    if (!r.ok) {
        const codigo = r.data?.error;
        $('#error-reserva').innerHTML = `${ICONOS.alerta}<span>${esc(MENSAJES[codigo] || r.data?.detail || 'No se pudo hacer la reserva.')}</span>`;
        $('#error-reserva').hidden = false;
        if (codigo === 'OVERLAP') { estado.bahia = null; cargarFranja(); }
        actualizarResumen();
        return;
    }

    const reserva = { ...cuerpo, plate: placa, status: r.data?.status || 'reserved' };
    guardar(reserva.reservation_id);
    mostrarTiquete(reserva, true);
    estado.bahia = null;
    $('#f-placa').value = '';
    actualizarResumen();
    refrescar();
    cargarMisReservas();
}

// ---------- Tiquete con QR ----------
function qrSVG(texto) {
    if (typeof qrcode !== 'function') return `<p class="codigo-grande">${esc(texto)}</p>`;
    const q = qrcode(0, 'M');
    q.addData(texto);
    q.make();
    return q.createSvgTag({ cellSize: 6, margin: 0, scalable: true });
}

function mostrarTiquete(r, recienCreada = false) {
    const d = $('#d-exito');
    $('#exito-icono').innerHTML = ICONOS.check;
    $('#exito-icono').hidden = !recienCreada;
    $('#t-exito').textContent = recienCreada ? '¡Reserva lista!' : 'Tu código de entrada';
    $('#exito-sub').textContent = recienCreada ? 'Guarda este código: lo necesitas para entrar.' : `${RESERVA[r.status]?.texto || r.status}`;
    $('#exito-qr').innerHTML = qrSVG(r.reservation_id);
    $('#exito-codigo').textContent = r.reservation_id;
    $('#exito-detalle').innerHTML = `
        <div><dt>Lugar</dt><dd>${esc(r.node_id)} · ${esc(r.space_id)}</dd></div>
        <div><dt>Horario</dt><dd>${esc(franja(r.starts_at, r.ends_at))}</dd></div>
        <div><dt>Placa</dt><dd>${esc(r.plate)}</dd></div>`;
    $('#exito-nota').textContent = r.status === 'active'
        ? `La bahía ya está apartada para ti (luz amarilla). Te espera hasta las ${horaCorta(new Date(Date.parse(r.starts_at) + 15 * 60000).toISOString())}; si no llegas, se libera.`
        : `La bahía se aparta 10 minutos antes de tu hora de llegada y te espera hasta las ${horaCorta(new Date(Date.parse(r.starts_at) + 15 * 60000).toISOString())}. Escanea el QR en la entrada.`;
    d.showModal();
}
$$('dialog [data-cerrar]').forEach(b => b.onclick = () => b.closest('dialog').close());
$$('dialog').forEach(d => d.addEventListener('click', e => { if (e.target === d) d.close(); }));

// ---------- Mis reservas ----------
let placaBuscada = '';
let misReservas = [];

async function cargarMisReservas() {
    const ids = leerGuardadas();
    const porId = await Promise.all(ids.map(id => api(`/reservas/${encodeURIComponent(id)}`)));
    // las que ya no existen en el sistema (404) se olvidan
    const vigentes = ids.filter((id, i) => porId[i].status !== 404);
    if (vigentes.length !== ids.length) {
        try { localStorage.setItem(GUARDADAS, JSON.stringify(vigentes)); } catch { /* sin almacenamiento */ }
    }
    const lista = porId.filter(r => r.ok && r.data).map(r => Array.isArray(r.data) ? r.data[0] : r.data).filter(Boolean);
    if (placaBuscada) {
        const r = await api(`/reservas?placa=${encodeURIComponent(placaBuscada)}&limit=30`);
        if (r.ok) lista.push(...(r.data || []));
    }
    const unicas = new Map();
    lista.forEach(r => unicas.set(r.reservation_id, r));
    // primero las que siguen vivas, luego por fecha
    const orden = { active: 0, entered: 1, reserved: 2 };
    misReservas = [...unicas.values()].sort((a, b) =>
        (orden[a.status] ?? 9) - (orden[b.status] ?? 9) || Date.parse(b.starts_at) - Date.parse(a.starts_at));
    pintarMisReservas();
}

function pintarMisReservas() {
    const cont = $('#lista-reservas');
    if (!misReservas.length) {
        cont.innerHTML = `<div class="panel vacio" style="grid-column:1/-1"><strong>${placaBuscada ? `No hay reservas para ${esc(placaBuscada)}` : 'Aún no tienes reservas'}</strong>Cuando reserves, tu código QR quedará guardado aquí.</div>`;
        return;
    }
    cont.innerHTML = misReservas.map(r => {
        const viva = ['reserved', 'active'].includes(r.status);
        return `<article class="tiquete">
            <div class="arriba"><span class="codigo">${esc(r.reservation_id)}</span>${insigniaReserva(r.status)}</div>
            <div>
                <div class="lugar">${esc(r.node_id)} · ${esc(r.space_id)}</div>
                <div class="cuando">${esc(franja(r.starts_at, r.ends_at))} · ${esc(r.plate)}</div>
            </div>
            ${viva ? `<div class="acciones">
                <button type="button" class="boton chico" data-qr="${esc(r.reservation_id)}">Ver QR</button>
                <button type="button" class="boton chico peligro" data-cancelar="${esc(r.reservation_id)}">Cancelar</button>
            </div>` : ''}
        </article>`;
    }).join('');
}

$('#lista-reservas').addEventListener('click', e => {
    const qr = e.target.closest('[data-qr]');
    if (qr) return mostrarTiquete(misReservas.find(r => r.reservation_id === qr.dataset.qr));
    const c = e.target.closest('[data-cancelar]');
    if (c) pedirCancelacion(misReservas.find(r => r.reservation_id === c.dataset.cancelar));
});

let porCancelar = null;
function pedirCancelacion(r) {
    porCancelar = r;
    $('#cancelar-texto').textContent = `${r.node_id} · ${r.space_id}, ${franja(r.starts_at, r.ends_at)}. Si la cancelas, la bahía queda libre para otras personas.`.replace('m..', 'm.');
    $('#d-cancelar').showModal();
}
$('#b-confirmar-cancelar').onclick = async () => {
    if (!porCancelar) return;
    const b = $('#b-confirmar-cancelar');
    b.disabled = true;
    const r = await api(`/reservas/${encodeURIComponent(porCancelar.reservation_id)}`, { method: 'DELETE' });
    b.disabled = false;
    $('#d-cancelar').close();
    if (r.ok) toast('Reserva cancelada');
    else toast(r.data?.error === 'NOT_CANCELLABLE' ? 'Esa reserva ya no se puede cancelar' : (r.data?.detail || 'No se pudo cancelar'));
    porCancelar = null;
    cargarMisReservas();
    refrescar();
};

$('#form-buscar').onsubmit = e => {
    e.preventDefault();
    const p = normalizarPlaca($('#b-placa').value);
    $('#b-placa').value = p;
    if (p && !placaValida(p)) { toast('Escribe una placa válida'); return; }
    placaBuscada = p;
    cargarMisReservas();
};
$('#b-placa').oninput = e => { e.target.value = normalizarPlaca(e.target.value); };

// ---------- Ciclo de actualización ----------
async function refrescar() {
    const ok = await cargarLotes();
    if (!ok) return;
    await Promise.all([cargarBahias(), cargarAgenda(), estado.vistaMapa === 'linea' ? cargarFranja() : null]);
}

async function iniciar() {
    prepararFormulario();
    pintarMapa();
    await refrescar();
    cargarFranja();
    cargarMisReservas();
    setInterval(() => { if (!document.hidden) refrescar(); }, REFRESCO_MS);
    setInterval(() => { if (!document.hidden) { llenarHoras(); cargarMisReservas(); } }, 60000);
}
iniciar();
