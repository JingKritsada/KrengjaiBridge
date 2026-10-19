import { api, post } from './api.js';
import { shell, escapeHTML as e, list, number, percent, icon, showError, busy, toast, structuredHTML, kindLabel, isRec } from './ui.js';

shell('demo');
const stepNames = ['ลบข้อมูลระบุตัวตน', 'ปรับภาษาให้เป็นกลาง', 'ทดสอบการเดาตัวตน', 'จัดโครงสร้างความเห็น', 'รอประตูนิรนาม (k=3)', 'จัดกลุ่มประเด็น'];
let members = [];
let selectedMember = '';
let draftID = null;
let currentTheme = '';
let inboxVersion = '';
let teamVersion = '';
let pendingPreview = false;
let inboxPending = false;
let signalsPending = false;
let llmUnavailable = false;
let pipelineFallback = false;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

const fallbackBadge = document.createElement('span');
fallbackBadge.className = 'chip wait pipeline-fallback';
fallbackBadge.textContent = 'โหมดสำรอง (ไม่มี LLM)';
fallbackBadge.setAttribute('role', 'status');
fallbackBadge.hidden = true;
document.querySelector('.live-pipeline .section-heading').append(fallbackBadge);

function renderFallback() {
  fallbackBadge.hidden = !llmUnavailable && !pipelineFallback;
}

// Polled every 15 s (health() in ui.js runs once), so the fallback chip follows the LLM going up or down.
async function loadHealth() {
  try {
    const data = await api('/api/health');
    llmUnavailable = data.llm_available === false;
    renderFallback();
  } catch { /* Keep the last known status until health is reachable. */ }
}

function resetSteps() {
  pipelineFallback = false;
  renderFallback();
  document.querySelector('#pipeline-steps').innerHTML = stepNames.map((name, i) => `<li class="pipeline-step" data-step="${i + 1}"><span class="step-number">${i + 1}</span><div class="step-line"><h3>${name}</h3><p class="step-output">รอทดสอบ</p></div><span class="step-done"></span>${i === 2 ? '<div id="attacker-rounds" class="attacker-rounds" hidden></div>' : ''}${i === 3 ? '<div id="feedback-preview" hidden></div>' : ''}</li>`).join('');
  document.querySelector('#confirm-actions').hidden = true;
  document.querySelector('#confirm-note').hidden = true;
  document.querySelector('#removed-markers').hidden = true;
  document.querySelector('#removed-markers').replaceChildren();
  document.querySelector('#feedback-text').hidden = false;
  document.querySelector('#feedback-text').readOnly = false;
  document.querySelector('#member-select').disabled = false;
  document.querySelector('#preview').hidden = false;
  document.querySelector('#preview').disabled = false;
  document.querySelector('.preview-actions').hidden = false;
}

// A blocked run returns no draft and no cancel button: give the editor back so the author can rewrite and test again.
function unlockEditor() {
  document.querySelector('#removed-markers').hidden = true;
  document.querySelector('#feedback-text').hidden = false;
  document.querySelector('#feedback-text').readOnly = false;
  document.querySelector('#member-select').disabled = false;
  document.querySelector('.preview-actions').hidden = false;
  document.querySelector('#preview').disabled = false;
}

function setPipelineStatus(text, className = '', state = 'idle') {
  const status = document.querySelector('#pipeline-status');
  status.textContent = text;
  status.className = `pipeline-status ${className}`;
  document.querySelector('.gate-bar').dataset.state = state;
  const sent = state === 'sent' || state === 'released';
  document.querySelector('#gate').hidden = !sent;
  document.querySelector('#teammates').hidden = !sent;
}

function renderGate(gate) {
  if (!gate) return;
  const count = Number(gate.count) || 0;
  const k = Number(gate.k) || 3;
  currentTheme = gate.theme_slug || currentTheme;
  document.querySelector('#gate-count').textContent = `${count}/${k}`;
  document.querySelector('#gate-label').textContent = gate.theme_label || `ต้องมีเสียงร่วมอย่างน้อย ${k} คน`;
  document.querySelector('.gate-slots').innerHTML = Array.from({ length: k }, (_, i) => `<span class="gate-slot ${i < count ? 'full' : ''}">${icon('user', 'sm')}</span>`).join('');
  document.querySelector('#gate').classList.toggle('released', !!gate.released);
  const note = gate.released ? `ผ่านประตูนิรนามแล้ว · หัวหน้าเห็นจำนวนเป็นช่วง ${gate.count_range || '3–5 คน'}` : `รอเสียงร่วมอีก ${Math.max(0, k - count)} คน · หัวหน้ายังไม่เห็นความเห็นนี้`;
  document.querySelector('#gate-note').textContent = note;
  document.querySelector('#gate-note').hidden = !!gate.released;
  document.querySelector('[data-step="5"] .step-output').textContent = gate.released ? `มีเสียงร่วมครบอย่างน้อย ${k} คน` : `ยืนยันส่งแล้ว · รอเสียงร่วมอีก ${Math.max(0, k - count)} คน`;
  document.querySelector('[data-step="6"] .step-output').textContent = gate.released ? gate.theme_label || 'จัดกลุ่มประเด็นแล้ว' : `เมื่อครบ ${k} คน`;
  setPipelineStatus(gate.released ? note : 'ยืนยันส่งแล้ว · เก็บเฉพาะข้อความที่ปรับแล้ว', 'success', gate.released ? 'released' : 'sent');
}

function renderAttacker(rounds) {
  const el = document.querySelector('#attacker-rounds');
  el.hidden = !rounds.length;
  el.innerHTML = rounds.map(round => {
    const member = members.find(m => m.member_id === round.guessed_member_id);
    return `<div class="attacker-chip" ${round.reason ? `title="${e(round.reason)}"` : ''}><strong>รอบ ${number(round.round)}</strong><span class="attacker-guess">เดา: ${e(member?.display_name || round.guessed_member_id || 'ระบุไม่ได้')} · มั่นใจ ${percent(round.confidence)}</span><span class="chip ${round.identified ? 'wait' : 'ok'}">${icon(round.identified ? 'refresh-cw' : 'shield-check', 'sm')}${round.identified ? 'เดาถูก · เขียนใหม่' : 'ระบุตัวตนไม่ได้'}</span></div>`;
  }).join('');
}

function highlightMarkers(text) {
  const el = document.querySelector('#removed-markers');
  el.hidden = false;
  document.querySelector('#feedback-text').hidden = true;
  document.querySelector('.preview-actions').hidden = true;
  // The source stays in browser memory only, never fixture storage.
  el.innerHTML = `<p>${e(text).replace(/หนู|ค่ะ|ครับ|ดิฉัน|ผม|พี่/g, marker => `<del>${marker}</del>`)}</p>`;
}

async function loadTeam() {
  try {
    const data = await api('/api/team');
    members = list(data.members);
    document.querySelector('#demo-team').textContent = data.team?.name || 'ทีมเดโม';
    if (!members.some(m => m.member_id === selectedMember)) selectedMember = members[0]?.member_id || '';
    const serialized = JSON.stringify(members);
    if (serialized !== teamVersion) {
      const select = document.querySelector('#member-select');
      const previous = select.value;
      select.innerHTML = members.map(m => `<option value="${e(m.member_id)}">${e(m.display_name)}</option>`).join('') || '<option value="">ยังไม่มีสมาชิกในทีม</option>';
      if (members.some(m => m.member_id === previous)) select.value = previous;
      teamVersion = serialized;
      renderTabs();
    }
  } catch (error) {
    if (!members.length) document.querySelector('#member-select').innerHTML = '<option value="">ยังโหลดสมาชิกไม่ได้</option>';
    showError(error);
  }
}

function renderTabs() {
  document.querySelector('#member-tabs').innerHTML = members.map(m => `<button id="tab-${e(m.member_id)}" role="tab" aria-selected="${m.member_id === selectedMember}" aria-controls="inbox" data-member="${e(m.member_id)}" tabindex="${m.member_id === selectedMember ? 0 : -1}">${e(m.display_name)}${m.line_linked ? '<span class="dot line" aria-label="เชื่อม LINE แล้ว"></span>' : ''}</button>`).join('');
  const member = members.find(m => m.member_id === selectedMember);
  document.querySelector('#inbox-name').textContent = member?.display_name || 'ยังไม่มีสมาชิก';
  document.querySelector('#inbox-avatar').textContent = member?.display_name?.slice(0, 1) || '—';
  document.querySelector('#line-badge').hidden = !member?.line_linked;
  document.querySelector('#inbox-channel').textContent = member?.role || 'กล่องข้อความบนเว็บ';
  if (member) document.querySelector('#inbox').setAttribute('aria-labelledby', `tab-${member.member_id}`);
}

async function loadInbox() {
  if (!selectedMember || inboxPending) return;
  inboxPending = true;
  const memberID = selectedMember;
  try {
    const data = list(await api(`/api/outreach?member_id=${encodeURIComponent(memberID)}`));
    if (memberID !== selectedMember) return;
    const serialized = memberID + JSON.stringify(data);
    if (serialized === inboxVersion) return;
    inboxVersion = serialized;
    const inbox = document.querySelector('#inbox');
    inbox.innerHTML = data.length ? data.map(message => `<article class="chat-entry"><span class="chat-agent">เกรงใจบริดจ์ · ${e(kindLabel(message.kind))}</span><div class="chat-bubble">${e(message.text || 'ยังไม่มีข้อความ')}</div><div class="quick-replies">${list(message.buttons).map(button => `<button class="${message.response === button.action ? 'answered' : ''}" data-outreach="${e(message.id)}" data-action="${e(button.action)}" ${message.response ? 'disabled' : ''}>${message.response === button.action ? icon('check', 'sm') : ''}${e(button.label || 'ตอบกลับ')}</button>`).join('')}</div>${message.response ? `<p class="chat-response">ตอบกลับแล้ว</p>` : ''}</article>`).join('') : '<div class="chat-empty">ยังไม่มีข้อความส่วนตัว · ลองเริ่มจากสถานการณ์ทางซ้าย</div>';
    inbox.scrollTop = inbox.scrollHeight;
  } catch (error) { showError(error); }
  finally {
    inboxPending = false;
    if (memberID !== selectedMember) loadInbox();
  }
}

async function loadSignals() {
  if (signalsPending) return;
  signalsPending = true;
  try {
    const signals = list(await api('/api/signals'));
    const stateLabels = { pending: 'รอตอบรับ', sent: 'ส่งแล้ว', accepted: 'ตอบรับแล้ว', dismissed: 'ข้ามแล้ว', declined: 'ปฏิเสธแล้ว', detected: 'ตรวจพบ', nudged: 'เตือนแล้ว', responded: 'ตอบกลับแล้ว' };
    document.querySelectorAll('[data-scenario]').forEach(button => {
      const signal = signals.filter(item => item.kind === button.dataset.scenario).at(-1);
      const trail = button.querySelector('.scenario-trail');
      trail.hidden = !signal || !button.classList.contains('selected');
      trail.innerHTML = signal ? `${icon(signal.state === 'accepted' ? 'check' : 'send', 'sm')}ส่งถึง${e(signal.affected_display || 'สมาชิก')} · ${e(stateLabels[signal.state] || 'กำลังดำเนินการ')}` : '';
    });
    document.querySelector('#signals').innerHTML = signals.length ? signals.map(signal => `<tr><td>${e(kindLabel(signal.kind))}</td><td class="code-ref">${e(signal.ref || '—')}</td><td>${e(signal.affected_display || '—')}${signal.target_display ? ` ${icon('arrow-right', 'sm')} ${e(signal.target_display)}` : ''}</td><td><span class="badge ${signal.judge_ok ? '' : 'amber'}">${signal.judge_ok ? 'ผ่าน' : 'รอตรวจสอบ'}</span>${signal.judge_reason ? `<span class="signal-reason">${e(signal.judge_reason)}</span>` : ''}</td><td>${e(stateLabels[signal.state] || 'กำลังดำเนินการ')}</td></tr>`).join('') : '<tr><td colspan="5" class="table-empty">ยังไม่มีสัญญาณ · เลือกสถานการณ์เพื่อเริ่มเดโม</td></tr>';
  } catch (error) { showError(error); }
  finally { signalsPending = false; }
}

document.querySelector('#feedback-form').addEventListener('submit', event => {
  event.preventDefault();
  if (draftID || pendingPreview) return;
  const text = document.querySelector('#feedback-text').value.trim();
  const memberID = document.querySelector('#member-select').value;
  if (!text || !memberID) { toast('กรุณาเลือกสมาชิกและเขียนความเห็นก่อนทดสอบ', true); return; }
  busy(document.querySelector('#preview'), async () => {
    pendingPreview = true;
    resetSteps();
    document.querySelector('#preview').disabled = true;
    document.querySelector('#feedback-text').readOnly = true;
    document.querySelector('#member-select').disabled = true;
    setPipelineStatus('กำลังทดสอบ… ขั้น 1/6', 'running', 'running');
    try {
      const data = await post('/api/feedback/preview', { member_id: memberID, text });
      draftID = data.draft_id || null;
      const result = data.result || {};
      const steps = list(result.steps);
      pipelineFallback = steps.some(step => list(step.notes).some(note => String(note).includes('โหมดสำรอง')));
      renderFallback();
      highlightMarkers(text);
      const cadence = getComputedStyle(document.documentElement).getPropertyValue('--step-cadence').trim();
      const delay = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : parseFloat(cadence) * (cadence.endsWith('ms') ? 1 : 1000);
      for (let i = 1; i <= 6; i++) {
        setPipelineStatus(`กำลังทดสอบ… ขั้น ${i}/6`, 'running', 'running');
        const step = steps.find(s => Number(s.step) === i);
        const el = document.querySelector(`[data-step="${i}"]`);
        el.classList.add('active');
        el.querySelector('.step-output').textContent = step?.output || (i === 5 ? 'รอยืนยันส่งก่อนนับเสียงร่วมของทีม' : 'ยังไม่มีผลจากระบบ');
        el.querySelector('.step-done').innerHTML = step ? icon('check') : '';
        if (i === 3) renderAttacker(list(result.attacker_rounds));
        if (i === 4) {
          const preview = document.querySelector('#feedback-preview');
          preview.hidden = !result.structured && !result.final_text;
          preview.innerHTML = result.structured ? structuredHTML(result.structured) : `<p>${e(result.final_text)}</p>`;
        }
        if (delay > 0) await sleep(delay);
      }
      currentTheme = result.theme_slug || currentTheme;
      setPipelineStatus(result.ok ? 'ทดสอบแล้ว · รอคุณยืนยันส่ง' : 'หยุดส่งเพื่อปกป้องตัวตน', result.ok ? 'success' : 'blocked', 'ready');
      document.querySelector('#confirm-actions').hidden = !draftID;
      document.querySelector('#confirm').disabled = !result.ok;
      document.querySelector('#confirm-note').hidden = !!result.ok;
      document.querySelector('#confirm-note').textContent = result.reason_blocked || 'ยังมีร่องรอยที่เดาตัวตนได้ ปรับข้อความแล้วทดสอบอีกครั้ง';
      if (!draftID) unlockEditor();
    } catch (error) {
      if (draftID) await post('/api/feedback/cancel', { draft_id: draftID }).catch(() => {});
      draftID = null;
      resetSteps();
      setPipelineStatus('ทดสอบยังไม่สำเร็จ · ลองอีกครั้งได้');
      throw error;
    } finally { pendingPreview = false; }
  });
});

document.querySelector('#confirm').addEventListener('click', event => {
  if (!draftID) return;
  busy(event.currentTarget, async () => {
    const data = await post('/api/feedback/confirm', { draft_id: draftID });
    draftID = null;
    document.querySelector('#confirm-actions').hidden = true;
    renderGate(data.gate);
    toast('ส่งความเห็นแบบนิรนามแล้ว');
    await loadInbox();
  });
});
document.querySelector('#cancel').addEventListener('click', event => {
  if (!draftID) return;
  busy(event.currentTarget, async () => {
    await post('/api/feedback/cancel', { draft_id: draftID });
    draftID = null;
    resetSteps();
    setPipelineStatus('ยกเลิกแล้ว · ยังไม่มีความเห็นถูกส่ง');
    toast('ยกเลิกความเห็นแล้ว');
  });
});

document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', () => busy(button, async () => {
  await post(`/api/demo/scenario/${button.dataset.scenario}`);
  document.querySelectorAll('[data-scenario]').forEach(b => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button)); });
  toast('สร้างสถานการณ์แล้ว · ดูข้อความส่วนตัวของสมาชิก');
  await Promise.all([loadInbox(), loadSignals()]);
})));
document.querySelector('#teammates').addEventListener('click', event => busy(event.currentTarget, async () => {
  const data = await post('/api/demo/teammates', currentTheme ? { theme_slug: currentTheme } : {});
  renderGate(data.gate);
  toast(`เพิ่มเสียงเพื่อนร่วมทีม ${number(data.added)} คนแล้ว`);
}));
document.querySelector('#advance').addEventListener('click', event => busy(event.currentTarget, async () => {
  await post('/api/demo/advance', { weeks: 2 });
  toast('ติดตามผลหลัง 2 สัปดาห์แล้ว · ดูผลที่แดชบอร์ดหัวหน้า');
  await loadInbox();
}));
document.querySelector('#reset').addEventListener('click', event => {
  if (pendingPreview) { toast('กรุณารอการทดสอบปกป้องตัวตนให้เสร็จก่อน'); return; }
  busy(event.currentTarget, async () => {
    await post('/api/demo/reset');
    draftID = null;
    currentTheme = '';
    inboxVersion = '';
    resetSteps();
    selectedMember = '';
    teamVersion = '';
    document.querySelector('#feedback-form').reset();
    document.querySelectorAll('[data-scenario]').forEach(b => { b.classList.remove('selected'); b.setAttribute('aria-pressed', 'false'); });
    setPipelineStatus('พร้อมทดสอบ · ความเห็นจะยังไม่ถูกส่ง');
    await loadTeam();
    await Promise.all([loadInbox(), loadSignals()]);
    toast('ล้างข้อมูลเดโมแล้ว พร้อมเริ่มเรื่องราวใหม่');
  });
});
document.querySelector('#member-tabs').addEventListener('click', event => {
  const button = event.target.closest('[data-member]');
  if (!button) return;
  selectedMember = button.dataset.member;
  document.querySelector('#inbox').innerHTML = '<div class="chat-empty">กำลังโหลดข้อความส่วนตัว…</div>';
  inboxVersion = '';
  renderTabs();
  loadInbox();
});
document.querySelector('#member-tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || !members.length) return;
  event.preventDefault();
  const index = members.findIndex(member => member.member_id === selectedMember);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? members.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + members.length) % members.length;
  selectedMember = members[next].member_id;
  document.querySelector('#inbox').innerHTML = '<div class="chat-empty">กำลังโหลดข้อความส่วนตัว…</div>';
  inboxVersion = '';
  renderTabs();
  document.querySelector('#member-tabs [aria-selected="true"]').focus();
  loadInbox();
});
document.querySelector('#inbox').addEventListener('click', event => {
  const button = event.target.closest('[data-outreach]');
  if (!button) return;
  busy(button, async () => {
    await post(`/api/outreach/${encodeURIComponent(button.dataset.outreach)}/respond`, { action: button.dataset.action });
    toast('ส่งคำตอบแล้ว');
    await Promise.all([loadInbox(), loadSignals()]);
  });
});

resetSteps();
loadHealth();
loadTeam().then(() => Promise.all([loadInbox(), loadSignals()]));
setInterval(() => { if (!document.hidden) loadInbox(); }, isRec ? 1000 : 3000);
setInterval(() => { if (!document.hidden) { loadTeam(); loadSignals(); loadHealth(); } }, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { loadTeam().then(loadInbox); loadSignals(); loadHealth(); } });
