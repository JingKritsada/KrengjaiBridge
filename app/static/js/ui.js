import { api, isMock, onStaticServer } from './api.js';

export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const list = value => Array.isArray(value) ? value : [];
export const number = (value, digits = 0) => value !== null && value !== undefined && Number.isFinite(Number(value))
  ? Number(value).toLocaleString('th-TH', { maximumFractionDigits: digits }) : '—';
export const percent = value => value == null ? '—' : `${number(Number(value) * 100)}%`;

export const isRec = new URLSearchParams(location.search).get('rec') === '1';

// Motion helpers (DESIGN.md section 7). Durations come from the CSS tokens, so ?rec=1 (body.rec) slows them in one place.
export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
export function cssTime(name, el = document.body) {
  const value = getComputedStyle(el).getPropertyValue(name).trim();
  return (parseFloat(value) || 0) * (value.endsWith('ms') ? 1 : 1000);
}

// Marks freshly rendered nodes for their entrance (.kjb-enter in app.css); --i staggers siblings, capped at 6 steps.
export function enter(nodes, cls = 'kjb-enter') {
  [...nodes].forEach((node, i) => { node.style.setProperty('--i', Math.min(i, 6)); node.classList.add(...cls.split(' ')); });
}

// Counts an element's text from `from` to `to`. Small whole-number ranges step evenly (3 → 0 reads 3, 2, 1, 0 on
// video); other ranges ease out. Reduced motion, a hidden tab or a missing start value jump straight to the result.
const counting = new WeakMap();
export function countTo(el, to, { from = 0, digits = 0, duration = cssTime('--dur-count'), delay = 0 } = {}) {
  if (!el) return;
  const final = number(to, digits);
  const start = Number(from), end = Number(to);
  if (from === null || to === null || !Number.isFinite(start) || !Number.isFinite(end) || start === end || !duration || reducedMotion() || document.hidden) {
    counting.delete(el);
    el.textContent = final;
    return;
  }
  const fixed = final.includes('.') ? digits : 0;
  const format = value => value.toLocaleString('th-TH', { minimumFractionDigits: fixed, maximumFractionDigits: fixed });
  const whole = Number.isInteger(start) && Number.isInteger(end) && Math.abs(end - start) <= 12;
  const begin = performance.now() + delay;
  const token = {};
  counting.set(el, token);
  el.textContent = format(start);
  const tick = now => {
    if (counting.get(el) !== token) return;
    const t = Math.min(1, Math.max(0, (now - begin) / duration));
    if (t >= 1) { el.textContent = final; counting.delete(el); return; }
    el.textContent = format(whole
      ? start + Math.sign(end - start) * Math.floor(t * Math.abs(end - start))
      : start + (end - start) * (1 - (1 - t) ** 3));
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// Playwright clicks last about 1 ms, so :active never reaches the video: keep the pressed look for --press-hold.
function pressHold() {
  let held = null;
  document.addEventListener('pointerdown', event => {
    const el = event.target.closest?.('button, .button');
    if (!el || el.disabled) return;
    held = { el, at: performance.now() };
    el.classList.add('is-pressed');
  });
  const release = () => {
    if (!held) return;
    const { el, at } = held;
    held = null;
    setTimeout(() => el.classList.remove('is-pressed'), Math.max(0, cssTime('--press-hold') - (performance.now() - at)));
  };
  document.addEventListener('pointerup', release);
  document.addEventListener('pointercancel', release);
}

// Lucide icons (ISC licence), 24 px grid. Injected once as a <symbol> sprite by shell(); stroke styles come from .icon in app.css.
const symbols = {
  'arrow-right': '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  'arrow-up-right': '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
  'check': '<path d="M20 6 9 17l-5-5"/>',
  'x': '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  'shield-check': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  'lock': '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  'git-pull-request': '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M6 9v12"/>',
  'circle-alert': '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
  'calendar-clock': '<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h5"/><path d="M17.5 17.5 16 16.3V14"/><circle cx="16" cy="16" r="6"/>',
  'moon': '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  'flag': '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
  'users': '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  'user': '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  'fast-forward': '<path d="M13 19 22 12 13 5z"/><path d="M2 19 11 12 2 5z"/>',
  'rotate-ccw': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  'refresh-cw': '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  'chart-line': '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="m19 9-5 5-4-4-3 3"/>',
  'message-square': '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  'eye': '<path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"/><circle cx="12" cy="12" r="3"/>',
  'send': '<path d="M14.54 21.69a.5.5 0 0 0 .94-.03l6.5-19a.5.5 0 0 0-.64-.63l-19 6.5a.5.5 0 0 0-.02.93l7.93 3.18a2 2 0 0 1 1.11 1.11z"/><path d="m21.85 2.15-10.94 10.94"/>',
  'eraser': '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/>',
  'languages': '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
  'crosshair': '<circle cx="12" cy="12" r="10"/><path d="M22 12h-4"/><path d="M6 12H2"/><path d="M12 6V2"/><path d="M12 22v-4"/>',
  'list-checks': '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
  'layers': '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  'inbox': '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
};
// Older names still used by page scripts.
const aliases = { arrow: 'arrow-right', shield: 'shield-check', chart: 'chart-line', message: 'message-square', refresh: 'rotate-ccw', close: 'x', clock: 'calendar-clock' };
export const icon = (name, cls = '') => `<svg class="icon${cls ? ` ${cls}` : ''}" aria-hidden="true" focusable="false"><use href="#i-${aliases[name] || name}"/></svg>`;

function injectIcons() {
  if (document.querySelector('#kjb-icons')) return;
  document.body.insertAdjacentHTML('afterbegin', `<svg id="kjb-icons" width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>${Object.entries(symbols).map(([name, body]) => `<symbol id="i-${name}" viewBox="0 0 24 24">${body}</symbol>`).join('')}</defs></svg>`);
}

export function pageURL(name = '') {
  const path = onStaticServer ? `/${name ? `${name}.html` : 'index.html'}` : `/${name}`;
  const query = [isMock && 'mock=1', isRec && 'rec=1'].filter(Boolean).join('&');
  return path + (query ? `?${query}` : '');
}

// Recording mode: a 3 px accent ring, 4 px outside the target, shown for `ms` (Playwright video has no cursor).
function spotlight(target, ms = 1200) {
  const el = typeof target === 'string' ? document.querySelector(target) : target;
  if (!el) return false;
  const box = el.getBoundingClientRect();
  const ring = document.createElement('div');
  ring.className = 'kjb-spotlight';
  ring.setAttribute('aria-hidden', 'true');
  Object.assign(ring.style, {
    left: `${box.left + scrollX - 4}px`, top: `${box.top + scrollY - 4}px`, width: `${box.width + 8}px`, height: `${box.height + 8}px`,
    borderRadius: `${(parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0) + 4}px`,
  });
  document.body.append(ring);
  requestAnimationFrame(() => ring.classList.add('on'));
  setTimeout(() => { ring.classList.remove('on'); setTimeout(() => ring.remove(), 300); }, ms);
  return true;
}

export function shell(active) {
  injectIcons();
  pressHold();
  document.querySelectorAll('#site-header [data-nav]').forEach(a => {
    if (a.dataset.nav === active) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  document.querySelectorAll('[data-page]').forEach(a => { a.href = pageURL(a.dataset.page); });
  if (isMock) {
    document.body.classList.add('mock-mode');
    document.querySelector('#mock-badge')?.removeAttribute('hidden');
  }
  if (isRec) {
    document.body.classList.add('rec');
    document.documentElement.style.setProperty('--step-cadence', '900ms');
    window.kjbSpotlight = spotlight;
  }
  if (!document.querySelector('#toast')) {
    const toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.append(toast);
  }
  health();
}

let toastTimer;
let lastError = '';
export function toast(message, error = false) {
  const el = document.querySelector('#toast');
  if (!el) return;
  el.textContent = message;
  el.classList.toggle('error', error);
  el.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('visible'), error ? 7500 : 4500);
}
export function showError(error) {
  const message = error?.message || 'ระบบขัดข้อง กรุณาลองอีกครั้ง';
  if (lastError !== message) toast(message, true);
  lastError = message;
}
export function connected() { lastError = ''; }

export async function busy(button, task) {
  if (button.disabled) return;
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  try { return await task(); } catch (error) { showError(error); }
  finally { button.disabled = false; button.removeAttribute('aria-busy'); }
}

let healthCheck;
// Header status pill (#health). Runs once per page load; returns the /api/health payload or null.
export function health() {
  healthCheck ||= checkHealth();
  return healthCheck;
}
async function checkHealth() {
  const el = document.querySelector('#health');
  if (!el) return null;
  try {
    const data = await api('/api/health');
    el.classList.remove('unavailable');
    el.innerHTML = `<span class="dot ${data.ok ? '' : 'offline'}"></span><span class="status-main">${data.ok ? 'ระบบพร้อม' : 'ระบบยังไม่พร้อม'}</span><span class="status-detail">· <span class="mono">${escapeHTML(data.llm_model || 'ยังไม่ระบุโมเดล')}</span> · LINE ${data.line_enabled ? 'เปิด' : 'ปิด'}</span>`;
    return data;
  } catch (error) {
    el.classList.add('unavailable');
    el.innerHTML = '<span class="dot offline"></span><span class="status-main">เชื่อมต่อระบบไม่ได้</span>';
    showError(error);
    return null;
  }
}

export function structuredHTML(sample) {
  return `<dl class="structured"><div><dt>สถานการณ์</dt><dd>${escapeHTML(sample?.situation || 'ยังไม่มีข้อมูล')}</dd></div><div><dt>ผลกระทบ</dt><dd>${escapeHTML(sample?.impact || 'ยังไม่มีข้อมูล')}</dd></div><div><dt>สิ่งที่ขอ</dt><dd>${escapeHTML(sample?.request || 'ยังไม่มีข้อมูล')}</dd></div></dl>`;
}

export const kindLabel = kind => ({ pr_stale: 'PR รอรีวิวนาน', ticket_blocked: 'งานติดขัด', friday_urgent: 'งานด่วนเย็นวันศุกร์', late_night: 'ทำงานดึกต่อเนื่อง', review_concentration: 'รีวิวกระจุกตัว', sprint_end: 'เช็กอินท้ายสปรินต์' })[kind] || 'สัญญาณจากทีม';
