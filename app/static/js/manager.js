import { api, post } from './api.js';
import { shell, escapeHTML as e, list, number, percent, icon, showError, connected, busy, toast, structuredHTML } from './ui.js';

shell('manager');
const charts = new Map();
let lastThemes = '';
let refreshing = false;

function renderMetrics(metrics = {}) {
  const items = [
    ['เวลารอ PR · ค่ากลาง', number(metrics.pr_wait_hours_median, 1), 'ชม.', 'ครึ่งหนึ่งของ PR รอไม่เกินค่านี้'],
    ['เวลารอ PR · p90', number(metrics.pr_wait_hours_p90, 1), 'ชม.', '90% ของ PR รอไม่เกินค่านี้'],
    ['งานติดขัดเฉลี่ย', number(metrics.blocked_ticket_days_avg, 1), 'วัน', 'ระยะเวลาที่งานอยู่ในสถานะติดขัด'],
    ['งานด่วนเย็นวันศุกร์', number(metrics.friday_after17_assignments_4w), 'ครั้ง', 'หลัง 17:00 · ย้อนหลัง 4 สัปดาห์'],
    ['รีวิวกระจุกตัวสูงสุด', percent(metrics.review_top_share), '', 'สัดส่วนรีวิวที่อยู่กับคนเดียว'],
  ];
  document.querySelector('#metrics').innerHTML = items.map(([label, value, unit, hint]) => `<article class="metric" title="${hint}"><h2>${label}</h2><p>${value} <small>${unit}</small></p><span>${hint}</span></article>`).join('');
}

function followupHTML(followup) {
  if (!followup) return '';
  const ready = followup.after !== null && followup.after !== undefined;
  return `<div class="followup"><div class="followup-title">${icon('chart')}<strong>ติดตามผลหลัง 2 สัปดาห์</strong>${ready ? `<span class="badge ${followup.improved ? '' : 'neutral'}">${followup.improved ? 'ดีขึ้นแล้ว' : 'ติดตามต่อ'}</span>` : '<span class="badge neutral">รอติดตามผล</span>'}</div><div class="followup-comparison"><span>${e(followup.metric_name || 'ตัวชี้วัดของทีม')}</span><div><span><small>ก่อน</small><b>${number(followup.before, 1)}</b></span>${icon('arrow')}<span><small>หลัง</small><b class="${followup.improved ? 'teal' : ''}">${ready ? number(followup.after, 1) : '—'}</b></span></div></div></div>`;
}

function themeHTML(theme) {
  const status = { open: ['รอหัวหน้าตอบ', 'amber'], responded: ['ตอบกลับแล้ว', 'neutral'], resolved: ['ปิดวงจรแล้ว', ''] }[theme.status] || ['รอหัวหน้าตอบ', 'neutral'];
  return `<article class="theme-card"><div class="theme-title"><div><h3>${e(theme.label || 'ประเด็นจากทีม')}</h3><div class="theme-badges"><span class="badge count-range">${e(theme.count_range || 'ผ่านประตูนิรนาม')}</span><span class="badge ${status[1]}">${theme.status === 'resolved' ? icon('check') : ''}${status[0]}</span></div></div>${icon('message', 'theme-icon')}</div>
    <div class="samples">${list(theme.samples).slice(0, 3).map((sample, i) => `<div class="sample"><div class="sample-label">เสียงนิรนาม${list(theme.samples).length > 1 ? ` ${i + 1}` : ''}</div>${structuredHTML(sample)}</div>`).join('') || '<p class="subtle">ยังไม่มีข้อความสรุป</p>'}</div>
    <div class="proposal"><div class="proposal-label">${icon('bridge')}<strong>ข้อเสนอจาก AI</strong></div><p>${e(theme.proposal || 'กำลังจัดทำข้อเสนอจากเสียงของทีม')}</p></div>
    ${theme.manager_reply ? `<div class="manager-reply"><span class="sample-label">คำตอบที่ส่งถึงทีมแล้ว</span><p>${e(theme.manager_reply)}</p></div>` : ''}
    ${theme.manager_reply ? '<details class="reply-details"><summary>เพิ่มเติมคำตอบถึงทีม</summary>' : ''}<form class="reply-form" data-theme-id="${e(theme.id)}"><label for="reply-${e(theme.id)}">คำตอบถึงทีม</label><textarea id="reply-${e(theme.id)}" name="text" rows="2" maxlength="3000" placeholder="ขอบคุณที่สะท้อนเรื่องนี้ เราจะ…" required></textarea><div class="reply-actions"><label class="checkbox-label"><input type="checkbox" name="accept_proposal">ยอมรับข้อเสนอ</label><button class="button primary small" type="submit">ส่งคำตอบ ${icon('arrow')}</button></div></form>${theme.manager_reply ? '</details>' : ''}
    ${followupHTML(theme.followup)}</article>`;
}

function renderThemes(themes) {
  document.querySelector('#theme-count').textContent = themes.length;
  const serialized = JSON.stringify(themes);
  if (serialized === lastThemes) return;
  // Polling must never erase a reply the manager is composing.
  const drafts = new Map([...document.querySelectorAll('.reply-form')].map(form => [form.dataset.themeId, { text: form.elements.text.value, accept: form.elements.accept_proposal.checked }]));
  if ([...drafts.values()].some(draft => draft.text || draft.accept) || document.activeElement?.closest('.reply-form')) return;
  lastThemes = serialized;
  document.querySelector('#themes').innerHTML = themes.length ? themes.map(themeHTML).join('') : `<div class="empty-state">${icon('shield')}<h3>ยังไม่มีประเด็นที่ผ่านประตูนิรนาม (k=3)</h3><p>เมื่อมีเสียงร่วมอย่างน้อย 3 คน<br>ประเด็นที่ผ่านการทดสอบนิรนามจะปรากฏที่นี่</p></div>`;
}

function renderChart(id, weeks, values, label, color) {
  const canvas = document.getElementById(id);
  const hasData = weeks.length > 0 && values.length > 0;
  document.getElementById(`${id}-empty`).hidden = hasData && !!window.Chart;
  canvas.hidden = !hasData || !window.Chart;
  if (!hasData || !window.Chart) {
    if (hasData) document.getElementById(`${id}-empty`).textContent = `${label}: ${values.map(v => number(v, 1)).join(' → ')}`;
    return;
  }
  if (charts.has(id)) {
    const chart = charts.get(id);
    chart.data.labels = weeks;
    chart.data.datasets[0].data = values;
    chart.update('none');
    return;
  }
  charts.set(id, new window.Chart(canvas, {
    type: 'line',
    data: { labels: weeks, datasets: [{ label, data: values, borderColor: color, backgroundColor: color, borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 5, tension: 0.3, fill: false }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { intersect: false, mode: 'index' }, plugins: { legend: { display: false } }, scales: { x: { border: { display: false }, grid: { display: false }, ticks: { color: '#68746f', maxTicksLimit: 6, font: { family: 'IBM Plex Sans Thai', size: 11 } } }, y: { beginAtZero: true, border: { display: false }, grid: { color: '#edf0ec' }, ticks: { color: '#68746f', maxTicksLimit: 4, precision: id === 'friday-chart' ? 0 : undefined, font: { size: 11 } } } } },
  }));
}

function renderStats(stats = {}) {
  document.querySelector('#pipeline-stats').innerHTML = [[stats.submitted, 'ความเห็นที่ส่ง'], [stats.released, 'เผยแพร่แล้ว'], [stats.blocked_by_attacker, 'หยุดเพื่อปกป้องตัวตน'], [stats.avg_attacker_rounds, 'รอบทดสอบเฉลี่ย']].map(([value, label], i) => `<div><strong>${number(value, i === 3 ? 1 : 0)}</strong><span>${label}</span></div>`).join('');
}

async function refresh() {
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    const summary = await api('/api/manager/summary');
    connected();
    document.querySelector('#week-label').textContent = summary.week_label || 'ภาพรวมประจำสัปดาห์';
    document.querySelector('#refresh-status').innerHTML = '<span class="live-dot"></span>อัปเดตอัตโนมัติทุก 5 วินาที';
    renderThemes(list(summary.themes));
    renderMetrics(summary.metrics || {});
    renderStats(summary.pipeline || {});
    const series = summary.metrics?.series || {};
    renderChart('pr-chart', list(series.weeks), list(series.pr_wait_hours), 'เวลารอ PR (ชม.)', '#17685f');
    renderChart('friday-chart', list(series.weeks), list(series.friday_after17), 'งานด่วนวันศุกร์ (ครั้ง)', '#9b7852');
  } catch (error) {
    showError(error);
    document.querySelector('#refresh-status').innerHTML = '<span class="live-dot offline"></span>เชื่อมต่อไม่ได้ · กำลังลองใหม่';
    if (!lastThemes) renderThemes([]);
  } finally { refreshing = false; }
}

document.querySelector('#themes').addEventListener('submit', event => {
  const form = event.target.closest('.reply-form');
  if (!form) return;
  event.preventDefault();
  const text = form.elements.text.value.trim();
  if (!text) { toast('กรุณาเขียนคำตอบถึงทีมก่อนส่ง', true); return; }
  busy(form.querySelector('button'), async () => {
    await post(`/api/manager/themes/${encodeURIComponent(form.dataset.themeId)}/reply`, { text, accept_proposal: form.elements.accept_proposal.checked });
    form.reset();
    form.querySelector('button').blur();
    lastThemes = '';
    toast('ส่งคำตอบถึงทีมแล้ว');
    await refresh();
  });
});

renderMetrics();
renderStats();
renderChart('pr-chart', [], [], '', '#17685f');
renderChart('friday-chart', [], [], '', '#9b7852');
refresh();
setInterval(refresh, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
