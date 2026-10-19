import { api, post } from './api.js';
import { shell, escapeHTML as e, list, number, percent, icon, showError, busy, toast, structuredHTML, kindLabel } from './ui.js';

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
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function resetSteps() {
  document.querySelector('#pipeline-steps').innerHTML = stepNames.map((name, i) => `<li class="pipeline-step" data-step="${i + 1}"><span class="step-number">${i + 1}</span><div><h3>${name}</h3><p class="step-output">รอทดสอบ</p></div><span class="step-done"></span></li>`).join('');
  ['attacker-rounds', 'feedback-preview', 'confirm-actions', 'removed-markers'].forEach(id => { document.getElementById(id).hidden = true; });
  document.querySelector('#feedback-text').readOnly = false;
  document.querySelector('#member-select').disabled = false;
  document.querySelector('#preview').disabled = false;
}

function renderGate(gate) {
  if (!gate) return;
  const count = Number(gate.count) || 0;
  const k = Number(gate.k) || 3;
  currentTheme = gate.theme_slug || currentTheme;
  document.querySelector('#gate-count').textContent = `${count}/${k}`;
  document.querySelector('#gate-label').textContent = gate.theme_label || `ต้องมีเสียงร่วมอย่างน้อย ${k} คน`;
  document.querySelector('#gate-progress').style.transform = `scaleX(${Math.min(1, Math.max(0, count / k))})`;
  document.querySelector('#gate').classList.toggle('released', !!gate.released);
  document.querySelector('#gate-note').textContent = gate.released ? `ผ่านประตูนิรนามแล้ว · หัวหน้าเห็นจำนวนเป็นช่วง ${gate.count_range || ''}` : `รอเสียงร่วมอีก ${Math.max(0, k - count)} คน · หัวหน้ายังไม่เห็นความเห็นนี้`;
}

function renderAttacker(rounds) {
  const el = document.querySelector('#attacker-rounds');
  el.hidden = !rounds.length;
  el.innerHTML = '<h3>รอบทดสอบผู้โจมตี</h3>' + rounds.map(round => {
    const member = members.find(m => m.member_id === round.guessed_member_id);
    return `<div class="attacker-chip ${round.identified ? 'identified' : 'protected'}"><strong>รอบ ${number(round.round)} · เดา: ${e(member?.display_name || round.guessed_member_id || 'ระบุไม่ได้')}</strong><span>มั่นใจ ${percent(round.confidence)} · ${round.identified ? '✓ เดาถูก → เขียนใหม่' : '✗ ระบุตัวตนไม่ได้'}</span>${round.reason ? `<small>${e(round.reason)}</small>` : ''}</div>`;
  }).join('');
}

function highlightMarkers(text) {
  const el = document.querySelector('#removed-markers');
  el.hidden = false;
  // This stays in the browser only; the original never enters fixture storage.
  el.innerHTML = `<span class="sample-label">ร่องรอยภาษาที่ต้องตัดออก</span><p>${e(text).replace(/หนู|ค่ะ|ครับ|ดิฉัน|ผม/g, marker => `<del>${marker}</del>`)}</p>`;
}

function setPipelineStatus(text, className = '') {
  const status = document.querySelector('#pipeline-status');
  status.textContent = text;
  status.className = `pipeline-status ${className}`;
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
  document.querySelector('#member-tabs').innerHTML = members.map(m => `<button id="tab-${e(m.member_id)}" role="tab" aria-selected="${m.member_id === selectedMember}" aria-controls="inbox" data-member="${e(m.member_id)}" tabindex="${m.member_id === selectedMember ? 0 : -1}">${e(m.display_name)}${m.line_linked ? '<span class="tab-line" aria-label="เชื่อม LINE แล้ว"></span>' : ''}</button>`).join('');
  const member = members.find(m => m.member_id === selectedMember);
  document.querySelector('#inbox-name').textContent = member?.display_name || 'ยังไม่มีสมาชิก';
  document.querySelector('#inbox-avatar').textContent = member?.display_name?.slice(0, 1) || '—';
  document.querySelector('#line-badge').hidden = !member?.line_linked;
  document.querySelector('#inbox-channel').textContent = member?.line_linked ? 'ข้อความส่งไปยัง LINE ด้วย' : 'กล่องข้อความบนเว็บ';
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
    inbox.innerHTML = data.length ? data.map(message => `<article class="chat-entry"><span class="chat-agent">เกรงใจบริดจ์ · ${e(kindLabel(message.kind))}</span><div class="chat-bubble">${e(message.text || 'ยังไม่มีข้อความ')}</div><div class="quick-replies">${list(message.buttons).map(button => `<button data-outreach="${e(message.id)}" data-action="${e(button.action)}" ${message.response ? 'disabled' : ''}>${e(button.label || 'ตอบกลับ')}</button>`).join('')}</div>${message.response ? `<p class="chat-response">${icon('check')}ตอบกลับแล้ว${list(message.buttons).find(b => b.action === message.response)?.label ? ` · ${e(list(message.buttons).find(b => b.action === message.response).label)}` : ''}</p>` : ''}</article>`).join('') : '<div class="chat-empty">ยังไม่มีข้อความส่วนตัว<br>ลองเริ่มจากสถานการณ์ทางซ้าย</div>';
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
    document.querySelector('#signals').innerHTML = signals.length ? signals.map(signal => `<tr><td>${e(kindLabel(signal.kind))}</td><td class="code-ref">${e(signal.ref || '—')}</td><td>${e(signal.affected_display || '—')}${signal.target_display ? ` <span class="muted">→</span> ${e(signal.target_display)}` : ''}</td><td><span class="badge ${signal.judge_ok ? '' : 'amber'}">${signal.judge_ok ? 'ผ่าน' : 'รอตรวจสอบ'}</span>${signal.judge_reason ? `<span class="signal-reason">${e(signal.judge_reason)}</span>` : ''}</td><td>${e(({ pending: 'รอตอบรับ', sent: 'ส่งแล้ว', accepted: 'ตอบรับแล้ว', dismissed: 'ข้ามแล้ว', declined: 'ปฏิเสธแล้ว', detected: 'ตรวจพบ', nudged: 'เตือนแล้ว', responded: 'ตอบกลับแล้ว' })[signal.state] || 'กำลังดำเนินการ')}</td></tr>`).join('') : '<tr><td colspan="5" class="table-empty">ยังไม่มีสัญญาณ · เลือกสถานการณ์เพื่อเริ่มเดโม</td></tr>';
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
    setPipelineStatus('กำลังทดสอบการปกป้องตัวตน…', 'running');
    try {
      const data = await post('/api/feedback/preview', { member_id: memberID, text });
      draftID = data.draft_id || null;
      const result = data.result || {};
      const steps = list(result.steps);
      highlightMarkers(text);
      for (let i = 1; i <= 6; i++) {
        const step = steps.find(s => Number(s.step) === i);
        const el = document.querySelector(`[data-step="${i}"]`);
        el.classList.add('active');
        el.querySelector('.step-output').textContent = step?.output || (i === 5 ? 'รอยืนยันส่งก่อนนับเสียงร่วมของทีม' : 'ยังไม่มีผลจากระบบ');
        if (list(step?.notes).length) {
          const notes = document.createElement('small');
          notes.className = 'step-notes';
          notes.textContent = step.notes.join(' · ');
          el.querySelector('div').append(notes);
        }
        el.querySelector('.step-done').innerHTML = step ? icon('check') : '';
        if (i === 3) renderAttacker(list(result.attacker_rounds));
        const panel = document.querySelector('.live-pipeline');
        if (panel.scrollHeight > panel.clientHeight && el.getBoundingClientRect().bottom > panel.getBoundingClientRect().bottom - 25) {
          panel.scrollTop += el.getBoundingClientRect().bottom - panel.getBoundingClientRect().bottom + 45;
        }
        if (!matchMedia('(prefers-reduced-motion: reduce)').matches) await sleep(420);
      }
      currentTheme = result.theme_slug || currentTheme;
      document.querySelector('#feedback-preview').hidden = !result.structured && !result.final_text;
      document.querySelector('#feedback-preview').innerHTML = `<h3>ข้อความที่จะส่งแบบนิรนาม</h3>${result.structured ? structuredHTML(result.structured) : `<p>${e(result.final_text)}</p>`}`;
      setPipelineStatus(result.ok ? 'ทดสอบแล้ว · รอคุณยืนยันส่ง' : 'หยุดส่งเพื่อปกป้องตัวตน', result.ok ? 'success' : 'blocked');
      document.querySelector('#confirm-actions').hidden = !draftID;
      document.querySelector('#confirm').disabled = !result.ok;
      document.querySelector('#confirm-note').textContent = result.ok ? 'ตรวจข้อความที่ปรับแล้ว ก่อนส่งแบบนิรนาม' : result.reason_blocked || 'ยังมีร่องรอยที่เดาตัวตนได้ กรุณายกเลิกแล้วปรับข้อความ';
      const panel = document.querySelector('.live-pipeline');
      if (panel.scrollHeight > panel.clientHeight) panel.scrollTop = panel.scrollHeight;
    } catch (error) {
      document.querySelector('#feedback-text').readOnly = false;
      document.querySelector('#member-select').disabled = false;
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
    document.querySelector('#feedback-text').readOnly = false;
    document.querySelector('#member-select').disabled = false;
    renderGate(data.gate);
    setPipelineStatus('ยืนยันส่งแล้ว · เก็บเฉพาะข้อความที่ปรับแล้ว', 'success');
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
  document.querySelectorAll('[data-scenario]').forEach(b => b.classList.toggle('selected', b === button));
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
    renderGate({ count: 0, k: 3 });
    document.querySelectorAll('[data-scenario]').forEach(b => b.classList.remove('selected'));
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
loadTeam().then(() => Promise.all([loadInbox(), loadSignals()]));
setInterval(() => { if (!document.hidden) loadInbox(); }, 3000);
setInterval(() => { if (!document.hidden) { loadTeam(); loadSignals(); } }, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { loadTeam().then(loadInbox); loadSignals(); } });
