import { api, post, isMock } from './api.js';
import { shell, health, escapeHTML as e, list, number, icon, showError, connected, busy, toast, structuredHTML } from './ui.js';

const METRIC_LABELS = {
  friday_after17_assignments_4w: 'งานหลัง 17:00 วันศุกร์ (ครั้ง / 4 สัปดาห์)',
  pr_wait_hours_median: 'เวลารอรีวิว PR (ชม. ค่ากลาง)',
  blocked_ticket_days_avg: 'งานติดขัดเฉลี่ย (วัน)',
};

shell('manager');
document.querySelector('#metrics-period').textContent = `8 สัปดาห์${isMock ? ' · ข้อมูลจำลอง' : ''}`;
let lastThemes = '';
let refreshing = false;
let modelName = '';
// The AI proposal shows the model name; fetch it without holding up the first render.
health().then(data => { modelName = data?.llm_model || ''; lastThemes = ''; refresh(); });

function sparkline(values) {
  if (!values.length) return '<span class="no-spark">—</span>';
  const min = Math.min(...values), max = Math.max(...values);
  const points = values.map((value, i) => [values.length === 1 ? 56 : 4 + i * 104 / (values.length - 1), max === min ? 16 : 28 - (value - min) / (max - min) * 24]);
  const line = points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const [lastX, lastY] = points.at(-1);
  return `<svg class="spark" viewBox="0 0 112 32" width="112" height="32" aria-hidden="true"><polygon class="spark-area" points="${points[0][0]},32 ${line} ${lastX},32"/><polyline class="spark-line" points="${line}"/><circle class="spark-dot" cx="${lastX}" cy="${lastY}" r="3"/></svg>`;
}

function renderMetrics(metrics = {}) {
  const items = [
    ['เวลารอรีวิว PR<br>ค่ากลาง', 'pr_wait_hours_median', 'ชม.', 'pr_wait_hours'],
    ['งานหลัง 17:00 วันศุกร์<br>ครั้ง / 4 สัปดาห์', 'friday_after17_assignments_4w', 'ครั้ง', 'friday_after17'],
    ['งานติดขัดเฉลี่ย', 'blocked_ticket_days_avg', 'วัน', 'blocked_days'],
    ['เวลารอรีวิว PR · p90', 'pr_wait_hours_p90', 'ชม.'],
    ['รีวิวกระจุกที่คนเดียว', 'review_top_share', '%'],
  ];
  document.querySelector('#metrics').innerHTML = items.map(([label, key, unit, seriesKey]) => {
    const values = list(metrics.series?.[seriesKey]).filter(value => typeof value === 'number' && Number.isFinite(value));
    const value = key === 'review_top_share' && metrics[key] != null ? metrics[key] * 100 : metrics[key];
    const delta = values.length ? Number((values.at(-1) - values[0]).toFixed(2)) : null;
    // Every metric here is lower-is-better: only a drop gets the accent (colour means a good state).
    const change = delta === null ? 'ไม่มีรายสัปดาห์' : `<strong class="${delta < 0 ? 'better' : ''}">${delta < 0 ? '−' : delta > 0 ? '+' : ''}${number(Math.abs(delta), 2)} ${unit}</strong>จาก ${number(values[0], 2)}`;
    return `<div class="metric"><dt>${label}</dt><dd class="metric-trend">${sparkline(values)}</dd><dd class="metric-value">${number(value, key === 'review_top_share' ? 0 : 1)}<small> ${unit}</small></dd><dd class="metric-delta">${change}</dd></div>`;
  }).join('');
}

function followupHTML(followup) {
  if (!followup) return '';
  if (followup.after === null || followup.after === undefined) {
    return `<div class="followup pending">${icon('calendar-clock', 'sm')}<span>ติดตามผลหลัง 2 สัปดาห์ · รอวัดผลอีกครั้ง</span></div>`;
  }
  return `<div class="followup outcome"><div><strong class="followup-title">ติดตามผลหลัง 2 สัปดาห์</strong><span class="followup-metric">${e(METRIC_LABELS[followup.metric_name] || followup.metric_name || 'ตัวชี้วัดของทีม')}</span></div><div class="followup-comparison"><span><span class="sr-only">ก่อน </span>${number(followup.before, 1)}</span>${icon('arrow-right')}<span class="after"><span class="sr-only">หลัง </span>${number(followup.after, 1)}</span></div></div>`;
}

function replyFormHTML(theme) {
  return `<form class="reply-form" data-theme-id="${e(theme.id)}"><div class="reply-heading"><label for="reply-${e(theme.id)}">คำตอบถึงทีม</label><span class="meta">ส่งถึงผู้เขียนผ่าน token นิรนาม</span></div><textarea id="reply-${e(theme.id)}" name="text" rows="2" maxlength="3000" placeholder="ขอบคุณที่สะท้อนเรื่องนี้ เราจะ…" required></textarea><div class="reply-actions"><label class="checkbox-label"><input type="checkbox" name="accept_proposal">ยอมรับข้อเสนอ</label><button class="button primary small" type="submit">ส่งคำตอบ ${icon('arrow-right')}</button></div></form>`;
}

function themeHTML(theme) {
  const resolved = theme.status === 'resolved';
  const [status, chip] = { open: ['รอหัวหน้าตอบ', 'wait'], responded: ['ตอบกลับแล้ว', ''], resolved: ['ปิดวงจรแล้ว', 'ok'] }[theme.status] || ['รอหัวหน้าตอบ', 'wait'];
  const form = resolved ? '' : replyFormHTML(theme);
  return `<article class="theme-card">
    ${resolved ? followupHTML(theme.followup) : ''}
    <div class="theme-title"><h3>${e(theme.label || 'ประเด็นจากทีม')}</h3><span class="chip count">${icon('users', 'sm')}${e(theme.count_range || 'ผ่านประตูนิรนาม')}</span><span class="chip ${chip}">${resolved ? icon('check', 'sm') : ''}${status}</span></div>
    <div class="samples">${list(theme.samples).slice(0, 3).map(sample => `<div class="sample"><div class="voice-label">${icon('shield-check', 'sm')}เสียงนิรนาม · ผ่านการทดสอบเดาตัวตนแล้ว</div>${structuredHTML(sample)}</div>`).join('') || '<p class="subtle">ยังไม่มีข้อความสรุป</p>'}</div>
    ${resolved ? '' : `<div class="proposal"><div class="proposal-label">${icon('list-checks', 'sm')}<strong>ข้อเสนอจาก AI</strong>${modelName ? `<span class="mono">${e(modelName)} · ร่าง</span>` : ''}</div><p>${e(theme.proposal || 'กำลังจัดทำข้อเสนอจากเสียงของทีม')}</p></div>`}
    ${theme.manager_reply ? `<blockquote class="manager-reply"><span class="sample-label">คำตอบที่ส่งถึงทีมแล้ว</span><p>${e(theme.manager_reply)}</p></blockquote>` : ''}
    ${theme.manager_reply && !resolved ? `<details class="reply-details"><summary>เพิ่มเติมคำตอบถึงทีม</summary>${form}</details>` : form}
    ${resolved ? '' : followupHTML(theme.followup)}</article>`;
}

function renderThemes(themes) {
  document.querySelector('#theme-count').textContent = themes.length;
  const serialized = JSON.stringify(themes);
  if (serialized === lastThemes) return;
  // Polling must never erase a reply the manager is composing.
  const drafts = new Map([...document.querySelectorAll('.reply-form')].map(form => [form.dataset.themeId, { text: form.elements.text.value, accept: form.elements.accept_proposal.checked }]));
  if ([...drafts.values()].some(draft => draft.text || draft.accept) || document.activeElement?.closest('.reply-form')) return;
  lastThemes = serialized;
  document.querySelector('#themes').innerHTML = themes.length ? themes.map(themeHTML).join('') : `<div class="panel empty-state">${icon('shield-check')}<p>เมื่อมีเสียงร่วมอย่างน้อย 3 คน ประเด็นที่ผ่านการทดสอบนิรนามจะปรากฏที่นี่</p></div>`;
}

function renderStats(stats = {}) {
  document.querySelector('#pipeline-stats').innerHTML = [[stats.submitted, 'ความเห็นที่ส่ง'], [stats.released, 'เผยแพร่แล้ว'], [stats.blocked_by_attacker, 'หยุดเพื่อปกป้อง'], [stats.avg_attacker_rounds, 'รอบทดสอบเฉลี่ย']].map(([value, label], i) => `<div><dt>${label}</dt><dd>${number(value, i === 3 ? 1 : 0)}</dd></div>`).join('');
}

async function refresh() {
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    const summary = await api('/api/manager/summary');
    connected();
    document.querySelector('#week-label').textContent = summary.week_label || 'ภาพรวมประจำสัปดาห์';
    document.querySelector('#refresh-status').innerHTML = '<span class="dot"></span>อัปเดตทุก 5 วินาที';
    renderThemes(list(summary.themes));
    renderMetrics(summary.metrics || {});
    renderStats(summary.pipeline || {});
  } catch (error) {
    showError(error);
    document.querySelector('#refresh-status').innerHTML = '<span class="dot offline"></span>เชื่อมต่อไม่ได้ · กำลังลองใหม่';
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
refresh();
setInterval(refresh, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
