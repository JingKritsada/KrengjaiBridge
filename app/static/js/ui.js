import { api, isMock } from './api.js';

export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const list = value => Array.isArray(value) ? value : [];
export const number = (value, digits = 0) => value !== null && value !== undefined && Number.isFinite(Number(value))
  ? Number(value).toLocaleString('th-TH', { maximumFractionDigits: digits }) : '—';
export const percent = value => value == null ? '—' : `${number(Number(value) * 100)}%`;

const paths = {
  bridge: '<path d="M3 18V7m18 11V7M3 12c5 0 5-7 9-7s4 7 9 7M3 18h18M8 10v8m8-8v8"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  chart: '<path d="M4 3v17h17M8 14l4-5 4 3 5-8"/>',
  message: '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z"/><path d="M7 9h9m-9 4h6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  play: '<path d="m8 5 11 7-11 7V5Z"/>',
  refresh: '<path d="M20 7a9 9 0 1 0 1 8M20 3v5h-5"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
};
export const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.message}</svg>`;

export function pageURL(name = '') {
  const staticServer = location.port === '8099' || (location.pathname.endsWith('.html') && !location.pathname.startsWith('/static/'));
  const path = staticServer ? `/${name ? `${name}.html` : 'index.html'}` : `/${name}`;
  return path + (isMock ? '?mock=1' : '');
}

export function shell(active) {
  document.querySelector('#site-header').innerHTML = `<div class="nav-inner">
    <a class="brand" href="${pageURL()}"><span class="brand-mark">${icon('bridge')}</span><span>เกรงใจบริดจ์<small>Kreng-jai Bridge</small></span></a>
    <nav aria-label="เมนูหลัก"><a href="${pageURL()}" ${active === 'home' ? 'aria-current="page"' : ''}>รู้จักเรา</a><a href="${pageURL('manager')}" ${active === 'manager' ? 'aria-current="page"' : ''}>แดชบอร์ดหัวหน้า</a><a href="${pageURL('demo')}" ${active === 'demo' ? 'aria-current="page"' : ''}>ห้องควบคุมเดโม</a></nav>
    <div class="nav-status">${isMock ? '<span class="badge mock-badge">ข้อมูลจำลอง</span>' : '<span class="live-dot"></span><span>พื้นที่ปลอดภัยของทีม</span>'}</div>
  </div>`;
  document.querySelectorAll('[data-page]').forEach(a => { a.href = pageURL(a.dataset.page); });
  if (isMock) document.body.classList.add('mock-mode');
  if (!document.querySelector('#toast')) {
    const toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.append(toast);
  }
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

export async function health() {
  const el = document.querySelector('#health');
  if (!el) return;
  try {
    const data = await api('/api/health');
    el.className = 'health-chip';
    el.innerHTML = `<span class="live-dot ${data.ok ? '' : 'offline'}"></span><span>${data.ok ? 'ระบบพร้อมใช้งาน' : 'ระบบยังไม่พร้อม'} · ${escapeHTML(data.llm_model || 'ยังไม่ได้ระบุโมเดล')} · LINE ${data.line_enabled ? 'เปิด' : 'ปิด'}</span>`;
  } catch (error) {
    el.className = 'health-chip unavailable';
    el.innerHTML = '<span class="live-dot offline"></span><span>ยังเชื่อมต่อระบบไม่ได้ · ลองรีเฟรชอีกครั้ง</span>';
    showError(error);
  }
}

export function structuredHTML(sample) {
  return `<dl class="structured"><div><dt>สถานการณ์</dt><dd>${escapeHTML(sample?.situation || 'ยังไม่มีข้อมูล')}</dd></div><div><dt>ผลกระทบ</dt><dd>${escapeHTML(sample?.impact || 'ยังไม่มีข้อมูล')}</dd></div><div><dt>สิ่งที่ขอ</dt><dd>${escapeHTML(sample?.request || 'ยังไม่มีข้อมูล')}</dd></div></dl>`;
}

export const kindLabel = kind => ({ pr_stale: 'PR รอรีวิวนาน', ticket_blocked: 'งานติดขัด', friday_urgent: 'งานด่วนเย็นวันศุกร์', late_night: 'ทำงานดึกต่อเนื่อง', review_concentration: 'รีวิวกระจุกตัว', sprint_end: 'เช็กอินท้ายสปรินต์' })[kind] || 'สัญญาณจากทีม';
