// ==========================================================================
// Parking IoT · utilidades compartidas por la página del usuario y la del admin
// ==========================================================================

// ¿Dónde está la API de Node-RED?
//  - Servida por Node-RED (http://localhost:1880/app/... o por el túnel /app/...): el mismo origen.
//  - Publicada en GitHub Pages: la URL pública del túnel, definida en config.js (PARKING_API).
//  - Abierta de otra forma (archivo suelto, Live Server…): se redirige a Node-RED local,
//    porque desde ahí el navegador bloquearía POST/DELETE (CORS).
const EN_PAGES = location.hostname.endsWith('github.io');
const NODE_RED = location.pathname.startsWith('/app') ? location.origin
    : EN_PAGES ? String(window.PARKING_API || '').replace(/\/+$/, '')
    : 'http://localhost:1880';
if (!EN_PAGES && !location.pathname.startsWith('/app')) {
    const archivo = location.pathname.split('/').pop();
    const destino = archivo === 'admin.html' ? 'admin.html' : 'index.html';
    location.replace(`${NODE_RED}/app/${destino}${location.hash}`);
}
// En la versión pública solo va la página del usuario: el panel de administración muestra
// placas y permite cancelar cualquier reserva, así que se usa en local (localhost:1880/app/admin.html).
document.addEventListener('DOMContentLoaded', () => {
    if (EN_PAGES) document.querySelectorAll('a[href="admin.html"]').forEach(a => a.remove());
});
const ZONA = '-05:00';                       // Colombia no tiene horario de verano
const REFRESCO_MS = 5000;

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------- API ----------
// Devuelve { ok, status, data }. Nunca lanza por un 4xx: la página decide qué mostrar.
async function api(ruta, opciones = {}) {
    const init = { method: opciones.method || 'GET', headers: {} };
    if (opciones.body !== undefined) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(opciones.body);
    }
    let resp;
    try {
        resp = await fetch(NODE_RED + ruta, init);
    } catch (e) {
        return { ok: false, status: 0, data: { error: 'SIN_CONEXION', detail: 'No hay conexión con Node-RED' } };
    }
    let data = null;
    try { data = await resp.json(); } catch { /* respuesta sin cuerpo JSON */ }
    return { ok: resp.ok, status: resp.status, data };
}

// ---------- Estado de una bahía ----------
// ocupada: el sensor ve un carro · reservada: tiene una reserva vigente (LED amarillo) · libre: lo demás
function estadoBahia(b) {
    if (b.sensor_status === true || b.sensor_status === 1) return 'ocupada';
    if (b.reserved_now === true || b.reserved_now === 1) return 'reservada';
    return 'libre';
}
const NOMBRE_ESTADO = { libre: 'Libre', ocupada: 'Ocupada', reservada: 'Reservada' };

// ---------- Íconos (SVG en línea, heredan el color del texto) ----------
const ICONOS = {
    carro: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 17h-1a1 1 0 0 1-1-1v-3.6a2 2 0 0 1 .4-1.2L5.7 8a2 2 0 0 1 1.6-.8h9.4a2 2 0 0 1 1.6.8l2.3 3.2a2 2 0 0 1 .4 1.2V16a1 1 0 0 1-1 1h-1"/><path d="M3.5 11.5h17"/><circle cx="7.5" cy="17" r="2"/><circle cx="16.5" cy="17" r="2"/><path d="M9.5 17h5"/></svg>',
    reloj: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    p: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18V6h4.5a3.5 3.5 0 0 1 0 7H9"/></svg>',
    equis: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    alerta: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/></svg>',
    qr: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2h-2zM18 18h2v2h-2zM14 18h2M18 14h2"/></svg>'
};
const ICONO_ESTADO = { libre: ICONOS.p, ocupada: ICONOS.carro, reservada: ICONOS.reloj };

function insignia(estado, texto) {
    const icono = { libre: ICONOS.check, ocupada: ICONOS.carro, reservada: ICONOS.reloj }[estado] || '';
    return `<span class="estado ${estado}">${icono}${esc(texto || NOMBRE_ESTADO[estado] || estado)}</span>`;
}

// Estados de una reserva, en palabras del usuario
const RESERVA = {
    reserved:  { texto: 'Programada', clase: 'info' },
    active:    { texto: 'Vigente', clase: 'reservada' },
    entered:   { texto: 'Carro adentro', clase: 'ocupada' },
    completed: { texto: 'Completada', clase: 'libre' },
    expired:   { texto: 'Sin llegada', clase: 'neutro' },
    cancelled: { texto: 'Cancelada', clase: 'neutro' }
};
function insigniaReserva(status) {
    const r = RESERVA[status] || { texto: status, clase: 'neutro' };
    return `<span class="estado ${r.clase}">${esc(r.texto)}</span>`;
}

// ---------- Fechas (siempre en hora de Colombia, sin importar el reloj del equipo) ----------
const MS_ZONA = 5 * 3600 * 1000;

// "Ahora" en Colombia como objeto con año, mes, día, hora y minuto
function ahoraColombia() {
    const d = new Date(Date.now() - MS_ZONA);
    return { anio: d.getUTCFullYear(), mes: d.getUTCMonth() + 1, dia: d.getUTCDate(), hora: d.getUTCHours(), min: d.getUTCMinutes() };
}
const dos = n => String(n).padStart(2, '0');
function hoyISO() { const a = ahoraColombia(); return `${a.anio}-${dos(a.mes)}-${dos(a.dia)}`; }

// fecha 'YYYY-MM-DD' + minutos desde medianoche -> ISO con zona
function isoColombia(fecha, minutos) {
    const base = Date.parse(`${fecha}T00:00:00${ZONA}`) + minutos * 60000;
    const d = new Date(base - MS_ZONA);
    return `${d.getUTCFullYear()}-${dos(d.getUTCMonth() + 1)}-${dos(d.getUTCDate())}T${dos(d.getUTCHours())}:${dos(d.getUTCMinutes())}:00${ZONA}`;
}

const FMT_HORA = new Intl.DateTimeFormat('es-CO', { timeZone: 'America/Bogota', hour: 'numeric', minute: '2-digit', hour12: true });
const FMT_DIA = new Intl.DateTimeFormat('es-CO', { timeZone: 'America/Bogota', weekday: 'short', day: 'numeric', month: 'short' });
const FMT_DIA_LARGO = new Intl.DateTimeFormat('es-CO', { timeZone: 'America/Bogota', weekday: 'long', day: 'numeric', month: 'long' });

const horaCorta = iso => FMT_HORA.format(new Date(iso)).replace(/\s?a\.\s?m\./, ' a. m.').replace(/\s?p\.\s?m\./, ' p. m.');
function diaRelativo(iso, largo = false) {
    const f = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Bogota' }).format(new Date(iso));
    const hoy = hoyISO();
    const manana = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Bogota' }).format(new Date(Date.now() + 86400000));
    if (f === hoy) return 'Hoy';
    if (f === manana) return 'Mañana';
    const t = (largo ? FMT_DIA_LARGO : FMT_DIA).format(new Date(iso)).replace('.', '');
    return t.charAt(0).toUpperCase() + t.slice(1);
}
function franja(ini, fin) { return `${diaRelativo(ini)} · ${horaCorta(ini)} – ${horaCorta(fin)}`; }

function haceCuanto(iso) {
    if (!iso) return 'sin datos';
    const s = Math.round((Date.now() - Date.parse(iso)) / 1000);
    if (s < 0) return 'justo ahora';
    if (s < 45) return 'hace unos segundos';
    if (s < 3600) return `hace ${Math.max(1, Math.round(s / 60))} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    const d = Math.round(s / 86400);
    return `hace ${d} día${d === 1 ? '' : 's'}`;
}

function duracionTexto(min) {
    if (min === null || min === undefined) return '–';
    const m = Math.round(min);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), r = m % 60;
    return r ? `${h} h ${r} min` : `${h} h`;
}

const num = (v, dec = 0) => v === null || v === undefined || isNaN(v) ? '–'
    : Number(v).toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec });

// ---------- Placa ----------
const normalizarPlaca = t => String(t || '').toUpperCase().replace(/[\s-]/g, '');
const placaValida = p => /^[A-Z0-9]{3,15}$/.test(p);

// ---------- Indicador "en vivo" ----------
function marcarVivo(el, ok, texto) {
    if (!el) return;
    el.classList.toggle('error', !ok);
    $('.texto', el).textContent = texto;
}

// ---------- Toast ----------
let toastTimer;
function toast(texto) {
    let t = $('#toast');
    if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
    t.textContent = texto;
    t.classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('visible'), 3200);
}
