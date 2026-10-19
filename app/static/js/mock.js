// Illustrative fixtures only. No live feedback or original input is persisted.
const storageKey = 'kreng-jai-bridge-demo-v1';
const team = {
  team: { id: 'demo-team', name: 'ทีม Backend (Demo)' },
  members: [
    { member_id: 'm-mint', display_name: 'มิ้น', role: 'Junior Backend Developer', seniority: 'junior', gender: 'female', line_linked: true },
    { member_id: 'm-somchai', display_name: 'พี่สมชาย', role: 'Senior Backend Developer', seniority: 'senior', gender: 'male', line_linked: false },
    { member_id: 'm-wan', display_name: 'พี่วรรณ', role: 'Engineering Manager', seniority: 'lead', gender: 'female', line_linked: false },
    { member_id: 'm-boat', display_name: 'โบ๊ท', role: 'Backend Developer', seniority: 'mid', gender: 'male', line_linked: false },
    { member_id: 'm-fon', display_name: 'ฝน', role: 'QA Engineer', seniority: 'junior', gender: 'female', line_linked: false },
    { member_id: 'm-ton', display_name: 'ต้น', role: 'DevOps Engineer', seniority: 'mid', gender: 'male', line_linked: false },
  ],
};
const sample = {
  situation: 'มีการมอบหมายงานเร่งด่วนช่วงเย็นวันศุกร์เป็นประจำ',
  impact: 'ทีมต้องเปลี่ยนแผนส่วนตัว และมีเวลาพักฟื้นไม่เพียงพอ',
  request: 'กำหนดเวลารับงานด่วนภายใน 15:00 และตกลงข้อยกเว้นร่วมกัน',
};
const proposal = 'กำหนดเวลารับงานวันศุกร์ไม่เกิน 15:00 หากเป็นเหตุฉุกเฉิน ให้หัวหน้าช่วยจัดลำดับความสำคัญและตกลงเวลาชดเชยกับทีม';
const metric = {
  pr_wait_hours_median: 18, pr_wait_hours_p90: 32, blocked_ticket_days_avg: 1.2,
  friday_after17_assignments_4w: 0, review_top_share: .42,
  series: { weeks: ['31 ส.ค.', '7 ก.ย.', '14 ก.ย.', '21 ก.ย.', '28 ก.ย.', '5 ต.ค.', '12 ต.ค.', '19 ต.ค.'], pr_wait_hours: [47, 53, 49, 52, 46, 48, 24, 18], friday_after17: [2, 3, 3, 2, 3, 3, 1, 0], blocked_days: [3.1, 3.6, 3.2, 3.5, 3.3, 3.4, 1.9, 1.2] },
};
// Before the 2-week skip: the series ends at the current values, so sparklines and deltas agree with the numbers shown.
const seriesBefore = { weeks: ['17 ส.ค.', '24 ส.ค.', '31 ส.ค.', '7 ก.ย.', '14 ก.ย.', '21 ก.ย.', '28 ก.ย.', '5 ต.ค.'], pr_wait_hours: [44, 51, 47, 53, 49, 52, 46, 48], friday_after17: [2, 3, 2, 3, 3, 2, 3, 3], blocked_days: [2.9, 3.3, 3.1, 3.6, 3.2, 3.5, 3.3, 3.4] };
const stamp = () => new Date().toISOString();
// Same text as ACTION_REPLIES in app/outreach/channel.py.
const actionReplies = { 'nudge:accept': 'ส่งข้อความเตือนตามข้อตกลงของทีมแล้ว ในข้อความไม่มีชื่อคุณ', 'nudge:decline': 'รับทราบ ยังไม่ส่งข้อความเตือน', 'nudge:useless': 'ขอบคุณ ระบบจะปรับเกณฑ์การแจ้งเตือน', mute: 'ปิดการแจ้งเตือนประเภทนี้แล้ว' };
const actionReply = action => actionReplies[action.startsWith('mute:') ? 'mute' : action.split(':').slice(0, 2).join(':')] || 'รับทราบแล้ว';
function theme(status = 'open') {
  return { id: 'theme-friday', slug: 'friday-urgent-work', label: 'งานด่วนเย็นวันศุกร์', count_range: '3–5 คน', status, samples: [sample], proposal, manager_reply: status === 'open' ? null : 'ขอบคุณที่ช่วยสะท้อนเรื่องนี้ ตกลงใช้เวลา 15:00 เป็นจุดรับงานสุดท้ายของวันศุกร์ เริ่มสัปดาห์นี้ และกลับมาดูผลด้วยกัน', followup: status === 'resolved' ? { due_at: stamp(), metric_name: 'งานหลัง 17:00 วันศุกร์ (ครั้ง)', before: 3, after: 0, improved: true } : null, released_at: stamp() };
}
function outreach(id, memberID, kind, text, buttons = []) {
  return { id, member_id: memberID, display_name: team.members.find(m => m.member_id === memberID)?.display_name, kind, text, buttons, channel: memberID === 'm-mint' ? 'line' : 'web', created_at: stamp(), response: null, reply: null };
}
function initialState(empty = false) {
  return {
    themes: empty ? [] : [theme('resolved')], metrics: structuredClone(metric), pipeline: { submitted: empty ? 0 : 12, released: empty ? 0 : 9, blocked_by_attacker: empty ? 0 : 3, avg_attacker_rounds: empty ? 0 : 1.8 },
    gateCount: empty ? 0 : 3, confirmedMembers: [], drafts: {}, signals: [], outreach: empty ? [] : [outreach('welcome', 'm-mint', 'pr_stale', 'PR #123 รอรีวิวมา 52 ชั่วโมงแล้ว ต้องการให้ช่วยส่งคำเตือนอย่างเป็นกลางตามข้อตกลงของทีมไหม?', [{ label: 'ช่วยเตือนให้หน่อย', action: 'nudge:accept:signal-welcome' }, { label: 'ยังไม่ต้อง', action: 'nudge:decline:signal-welcome' }, { label: 'ไม่มีประโยชน์', action: 'nudge:useless:signal-welcome' }, { label: 'ปิดการแจ้งเตือนประเภทนี้', action: 'mute:pr_stale' }])],
  };
}
let memory;
function readState() {
  try {
    const stored = localStorage.getItem(storageKey);
    if (stored) return JSON.parse(stored);
  } catch { /* Storage can be disabled in private browser sessions. */ }
  return memory || initialState();
}
function save(state) {
  memory = state;
  try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch { /* In-memory fallback. */ }
}
function gate(state) {
  return { theme_slug: 'friday-urgent-work', theme_label: 'งานด่วนเย็นวันศุกร์', count: state.gateCount, k: 3, released: state.gateCount >= 3, count_range: state.gateCount >= 3 ? '3–5 คน' : 'ยังไม่เผยแพร่' };
}
function release(state) {
  if (state.gateCount >= 3 && !state.themes.some(t => t.slug === 'friday-urgent-work')) {
    state.themes.push(theme());
    state.pipeline.released += state.gateCount;
  }
}
function previewResult() {
  return {
    ok: true, final_text: `${sample.situation} ${sample.impact} ${sample.request}`, structured: sample, theme_slug: 'friday-urgent-work', theme_label: 'งานด่วนเย็นวันศุกร์',
    attacker_rounds: [
      { round: 1, guessed_member_id: 'm-mint', confidence: .78, guessed_gender: 'female', guessed_seniority: 'junior', reason: 'ร่องรอยภาษาและบริบทเฉพาะยังบ่งชี้ผู้เขียน จึงปรับข้อความอีกครั้ง', identified: true },
      { round: 2, guessed_member_id: 'm-boat', confidence: .24, guessed_gender: null, guessed_seniority: null, reason: 'ข้อความเป็นกลางและใช้บริบทระดับทีม ระบุตัวตนไม่ได้', identified: false },
    ],
    steps: [
      { step: 1, name: 'ลบข้อมูลระบุตัวตน', output: 'ตัดชื่อ บุคคล และบริบทที่เชื่อมโยงถึงผู้ส่ง', notes: ['ไม่เก็บต้นฉบับลงฐานข้อมูล'] },
      { step: 2, name: 'ปรับภาษาให้เป็นกลาง', output: 'ตัดสรรพนามและคำลงท้ายที่บ่งชี้เพศหรือระดับอาวุโส', notes: ['ลบร่องรอย: หนู · ค่ะ · พี่'] },
      { step: 3, name: 'ทดสอบการเดาตัวตน', output: 'เขียนใหม่ 2 รอบ จนผู้โจมตีไม่สามารถระบุตัวตนได้', notes: ['ความมั่นใจรอบสุดท้าย 24%'] },
      { step: 4, name: 'จัดโครงสร้างความเห็น', output: 'สถานการณ์ / ผลกระทบ / สิ่งที่ขอ', notes: ['เก็บสาระที่นำไปแก้ไขได้'] },
      { step: 5, name: 'รอประตูนิรนาม', output: 'รอยืนยันส่ง แล้วรวมเสียงให้ครบอย่างน้อย 3 คน', notes: ['หัวหน้ายังไม่เห็นข้อความนี้'] },
      { step: 6, name: 'จัดกลุ่มประเด็น', output: 'งานด่วนเย็นวันศุกร์', notes: ['เผยแพร่จำนวนเป็นช่วง 3–5 คน'] },
    ], reason_blocked: '',
  };
}

export async function mockRequest(path, method = 'GET', body = {}) {
  const state = readState();
  const url = new URL(path, location.origin);
  const route = url.pathname;
  let result;
  if (method === 'GET' && route === '/api/health') return { ok: true, llm_model: 'qwen3.5', line_enabled: true, db: 'ok', redis: 'ok' };
  if (method === 'GET' && route === '/api/team') return structuredClone(team);
  if (method === 'GET' && route === '/api/manager/summary') return structuredClone({ week_label: 'สัปดาห์ที่ 42 · 12–18 ตุลาคม 2569', themes: state.themes, metrics: state.metrics, pipeline: state.pipeline });
  if (method === 'GET' && route === '/api/manager/metrics') return structuredClone(state.metrics);
  if (method === 'GET' && route === '/api/outreach') return state.outreach.filter(message => message.member_id === url.searchParams.get('member_id'));
  if (method === 'GET' && route === '/api/signals') return state.signals;
  if (method !== 'POST') throw new Error('ไม่พบข้อมูลจำลองสำหรับหน้านี้');
  if (route === '/api/demo/reset') {
    const fresh = initialState(true);
    fresh.metrics.friday_after17_assignments_4w = 3;
    fresh.metrics.pr_wait_hours_median = 48;
    fresh.metrics.pr_wait_hours_p90 = 72;
    fresh.metrics.blocked_ticket_days_avg = 3.4;
    fresh.metrics.review_top_share = .67;
    fresh.metrics.series = structuredClone(seriesBefore);
    save(fresh);
    return { ok: true };
  }
  if (route.startsWith('/api/demo/scenario/')) {
    const name = route.split('/').pop();
    const id = `signal-${crypto.randomUUID()}`;
    const info = {
      pr_stale: ['PR #123', 'PR #123 รอรีวิวมา 52 ชั่วโมงแล้ว ต้องการให้ช่วยส่งคำเตือนอย่างเป็นกลางตามข้อตกลงของทีมไหม?'],
      ticket_blocked: ['TICKET-42', 'งาน TICKET-42 ติดขัดเกิน 2 วันแล้ว ต้องการให้ช่วยประสานหาผู้รับผิดชอบเพื่อให้งานเดินต่อไหม?'],
      friday_urgent: ['TASK-89', 'พบงานที่มอบหมายหลัง 17:00 วันศุกร์ 3 ครั้งใน 4 สัปดาห์ อยากให้ช่วยสะท้อนผลกระทบแบบนิรนามไหม?'],
      late_night: ['22:00', 'ช่วงนี้มีการทำงานหลัง 22:00 หลายวัน อยากคุยเรื่องภาระงานหรือเวลาพักไหม? ข้อมูลนี้ส่งถึงคุณคนเดียว'],
      sprint_end: ['Sprint 14', 'จบ Sprint 14 แล้ว มีอะไรที่ทำให้งานติดขัด หรืออยากให้ทีมช่วยปรับบ้างไหม?'],
    }[name];
    if (!info) throw new Error('ไม่พบสถานการณ์จำลอง');
    const signal = { id, kind: name, ref: info[0], affected_display: 'มิ้น', target_display: name === 'pr_stale' ? 'พี่สมชาย' : null, detected_at: stamp(), judge_ok: true, judge_reason: 'ตรวจบริบทแล้ว เหมาะกับการช่วยเหลือ', state: 'sent' };
    const message = outreach(`outreach-${id}`, 'm-mint', name, info[1], [{ label: name === 'pr_stale' ? 'ช่วยเตือนให้หน่อย' : 'ช่วยหน่อย', action: `nudge:accept:${id}` }, { label: 'ยังไม่ต้อง', action: `nudge:decline:${id}` }, { label: 'ไม่มีประโยชน์', action: `nudge:useless:${id}` }, { label: 'ปิดการแจ้งเตือนประเภทนี้', action: `mute:${name}` }]);
    state.signals.push(signal);
    state.outreach.push(message);
    result = { signals: [signal], outreach: [message] };
  } else if (route === '/api/feedback/preview') {
    const draftID = `draft-${crypto.randomUUID()}`;
    // The mock deliberately uses fixed neutral text, never a persisted copy of user input.
    state.drafts[draftID] = { member_id: body.member_id, result: previewResult() };
    result = { draft_id: draftID, result: state.drafts[draftID].result };
  } else if (route === '/api/feedback/confirm') {
    const draft = state.drafts[body.draft_id];
    if (!draft) throw new Error('ไม่พบร่างความเห็น กรุณาทดสอบใหม่');
    if (!state.confirmedMembers.includes(draft.member_id)) {
      state.confirmedMembers.push(draft.member_id);
      state.gateCount++;
      state.pipeline.submitted++;
      state.pipeline.avg_attacker_rounds = 2;
    }
    delete state.drafts[body.draft_id];
    release(state);
    result = { gate: gate(state) };
  } else if (route === '/api/feedback/cancel') {
    delete state.drafts[body.draft_id];
    result = { ok: true };
  } else if (route === '/api/demo/teammates') {
    const added = Math.max(0, 3 - Math.max(1, state.gateCount));
    state.gateCount += added;
    state.pipeline.submitted += added;
    release(state);
    result = { added, gate: gate(state) };
  } else if (/^\/api\/manager\/themes\/[^/]+\/reply$/.test(route)) {
    const found = state.themes.find(t => t.id === decodeURIComponent(route.split('/')[4]));
    if (!found) throw new Error('ยังไม่มีประเด็นที่เปิดให้ตอบ');
    found.manager_reply = body.text;
    found.status = 'responded';
    found.followup = { due_at: new Date(Date.now() + 14 * 86400000).toISOString(), metric_name: 'งานหลัง 17:00 วันศุกร์ (ครั้ง)', before: 3, after: null, improved: false };
    state.outreach.push(outreach(`reply-${crypto.randomUUID()}`, 'm-mint', 'friday_urgent', `หัวหน้าตอบประเด็น “งานด่วนเย็นวันศุกร์” แล้ว\n\n${body.text}`));
    result = found;
  } else if (route === '/api/demo/advance') {
    state.themes.forEach(t => {
      if (t.status === 'responded') {
        t.status = 'resolved';
        t.followup = { due_at: stamp(), metric_name: 'งานหลัง 17:00 วันศุกร์ (ครั้ง)', before: 3, after: 0, improved: true };
      }
    });
    state.metrics = structuredClone(metric);
    result = { themes: state.themes };
  } else if (/^\/api\/outreach\/[^/]+\/respond$/.test(route)) {
    const found = state.outreach.find(message => message.id === decodeURIComponent(route.split('/')[3]));
    if (!found) throw new Error('ไม่พบข้อความ');
    if (found.response) return found;
    found.response = body.action;
    found.reply = actionReply(body.action);
    const signalID = String(body.action || '').split(':').slice(2).join(':');
    const signal = state.signals.find(s => s.id === signalID);
    if (signal) signal.state = body.action.startsWith('nudge:accept:') ? 'accepted' : 'dismissed';
    if (body.action.startsWith('nudge:accept:') && found.kind === 'pr_stale') {
      state.outreach.push(outreach(`reminder-${crypto.randomUUID()}`, 'm-somchai', 'pr_stale', 'ตามข้อตกลงของทีม PR ที่เปิดเกิน 48 ชั่วโมงควรได้รับการรีวิว PR #123 พร้อมให้ช่วยตรวจแล้ว หากยังไม่สะดวก สามารถเสนอเวลาหรือผู้รีวิวทดแทนได้'));
    }
    result = found;
  } else throw new Error('ยังไม่มีข้อมูลจำลองสำหรับคำสั่งนี้');
  save(state);
  return structuredClone(result);
}
