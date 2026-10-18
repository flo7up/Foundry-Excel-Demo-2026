/* Foundry Account Intelligence demo - vanilla JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (v, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`);
const tone = (v) => (v == null ? 'flat' : v > 0.05 ? 'up' : v < -0.05 ? 'down' : 'flat');
const usd = (v) => (v == null ? '—' : v < 0.01 ? `$${v.toFixed(4)}` : v < 1 ? `$${v.toFixed(3)}` : `$${v.toFixed(2)}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let busyCount = 0;
const busy = (d) => { busyCount = Math.max(0, busyCount + d); $('#progress')?.classList.toggle('on', busyCount > 0); };
const getJSON = async (u) => {
  busy(1);
  try {
    const r = await fetch(u);
    if (!r.ok) throw new Error(`${u} returned ${r.status}`);
    return await r.json();
  } finally { busy(-1); }
};
const skelCards = (n, cls = 'g3') => `<div class="grid ${cls}">${Array.from({ length: n }, () => '<div class="skel skel-card"></div>').join('')}</div>`;
const skeletonFor = (page) => ({
  workbook: `<div class="skel" style="height:64px;margin-bottom:16px"></div>${skelCards(5, 'g5')}<div class="mt">${skelCards(4, 'g4')}</div><div class="mt">${skelCards(2, 'g2')}</div>`,
  chat: `<div class="grid" style="grid-template-columns:1fr 320px"><div class="skel" style="height:520px;border-radius:16px"></div><div class="skel" style="height:520px;border-radius:16px"></div></div>`,
  upload: `<div class="grid" style="grid-template-columns:1.35fr 1fr"><div class="skel" style="height:300px;border-radius:22px"></div><div class="grid"><div class="skel" style="height:140px;border-radius:16px"></div><div class="skel" style="height:140px;border-radius:16px"></div></div></div>`,
}[page] || `<div class="skel" style="height:150px;border-radius:22px;margin-bottom:16px"></div>${skelCards(3)}<div class="mt">${skelCards(2, 'g2')}</div>`);

const I = (d, extra = '') => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</svg>`;
const ICON = {
  logo: I('<path d="M12 2.5l8 4.6v9.8l-8 4.6-8-4.6V7.1l8-4.6z"/><path d="M12 8v8M8.5 10l7 4M15.5 10l-7 4"/>'),
  overview: I('<path d="M3 11.5L12 4l9 7.5"/><path d="M5.5 10v10h13V10"/>'),
  workbook: I('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>'),
  monitor: I('<path d="M3 12h4l3-8 4 16 3-8h4"/>'),
  trust: I('<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/>'),
  bake: I('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
  play: I('<path d="M7 4.5l13 7.5-13 7.5z"/>', 'fill="currentColor"'),
  steward: I('<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'),
  scout: I('<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  analyst: I('<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9 13h7M9 17h7"/>'),
  reviewer: I('<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/>'),
  human: I('<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="8" r="4"/>'),
  arrow: I('<path d="M5 12h14M13 6l6 6-6 6"/>'),
  check: I('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
  info: I('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/>'),
  bolt: I('<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>'),
  upload: I('<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"/>'),
  chat: I('<path d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z"/><path d="M8.5 11h7M8.5 14h4"/>'),
  send: I('<path d="M4 12l16-8-6 16-3-7z"/>'),
  file: I('<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/>'),
  reports: I('<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9 12h7M9 15h7M9 18h4"/>'),
};

const STAGE_TOOLS = { 1: 'Copilot in Excel', 2: 'Copilot Studio', 3: 'Microsoft Foundry' };
const state = { mode: localStorage.getItem('mode'), status: null, source: null, wb: null, cleanup: null };

/* ------------------------------------------------------------------ chrome */
const PAGES = {
  overview: { title: 'From answers to action', sub: 'One workbook, three levels of AI: Excel helps, Copilot Studio assists, Foundry executes.', icon: 'overview', label: 'Overview' },
  upload: { title: 'Upload your workbook', sub: 'An agent must read and check the data before it acts.', icon: 'upload', label: 'Upload workbook', short: 'Upload' },
  reports: { title: 'Public reports', sub: 'Facts from company filings, each with its page number.', icon: 'reports', label: 'Public reports', short: 'Reports' },
  workbook: { title: 'Workbook insights', sub: 'Stage 1: fast answers from the data, but nobody checks the data.', icon: 'workbook', label: 'Workbook', tag: 'Stage 1' },
  monitor: { title: 'Account Monitor', sub: 'Stage 3: four agents run one process, a person decides.', icon: 'monitor', label: 'Account Monitor', short: 'Monitor' },
  chat: { title: 'Insights chat', sub: 'Ask in plain words. Every answer cites its sources and is checked.', icon: 'chat', label: 'Insights chat', short: 'Chat' },
  trust: { title: 'Trust Lab', sub: 'Prove an agent is safe before it goes live.', icon: 'trust', label: 'Trust Lab' },
  bakeoff: { title: 'Model Bake-off', sub: 'Pick the cheapest model that is good enough.', icon: 'bake', label: 'Model Bake-off', short: 'Bake-off' },
};

function renderNav() {
  const cur = currentPage();
  const item = (k) => `<a href="#/${k}" title="${PAGES[k].label}" class="${cur === k ? 'active' : ''}" ${cur === k ? 'aria-current="page"' : ''}>${ICON[PAGES[k].icon]}<span class="lbl"><span class="long">${PAGES[k].label}</span><span class="short">${PAGES[k].short || PAGES[k].label}</span></span>${PAGES[k].tag ? `<span class="tag">${PAGES[k].tag}</span>` : ''}</a>`;
  $('#nav').innerHTML = `${item('overview')}${item('upload')}${item('workbook')}${item('reports')}<div class="sep">Stage 3 · Microsoft Foundry</div>${item('monitor')}${item('chat')}${item('trust')}${item('bakeoff')}`;
  $('#topnav').innerHTML = Object.keys(PAGES).map(item).join('');
  $('#topnav a.active')?.scrollIntoView({ inline: 'center', block: 'nearest' });
}

/* Short explanations shown above each page. The text is for people who see the page for the first time. */
const GUIDE = {
  overview: {
    what: 'The whole story on one screen: Copilot in Excel helps, Copilot Studio works with you, Microsoft Foundry executes a process.',
    try: ['Read the three stages from left to right', 'Hover the dots to see how Copilot Studio and Foundry differ. Open "More differences" for the question "why not only Copilot Studio?"'],
    why: 'Every other page proves one of the differences with a live example.',
  },
  upload: {
    what: 'Load an Excel file and watch how an agent reads it: it finds the data table, maps your columns to its fields, extracts every company and checks the quality.',
    try: ['Click "Use the sample workbook" or drop your own .xlsx file', 'Watch the lines from your column names to the fields they feed', 'Read the quality findings: they are what a data steward agent would raise'],
    why: 'An agent is only as good as the data it reads. A process that acts on its own must check the data first.',
  },
  workbook: {
    what: 'The numbers inside the workbook, shown the way Copilot in Excel would summarise them: totals, sectors, strongest and weakest companies.',
    try: ['Compare the signal in the file with the recomputed signal', 'Open a finding for the detail, then search the table at the bottom', 'Hatched rows have no market data and are never counted as zero'],
    why: 'Stage 1 answers questions quickly. It does not check the data, run a process or ask a person to approve.',
  },
  reports: {
    what: 'Half-year reports that the companies publish themselves, read by the app. Headline figures are copied with the page they come from and checked against that page.',
    try: ['Compare growth and margin across the five companies', 'Click a page chip to open the original PDF at that page', 'Search the reports for a topic such as outlook or risks'],
    why: 'Prices say what the market did. Reports say what the business did. Every figure here can be traced to a page.',
  },
  monitor: {
    what: 'Four agents work as a team: one checks the data, one finds the material changes, one writes a briefing with sources and one reviews it against policy. A person then decides.',
    try: ['Press "Run monitoring cycle" and follow the agents from left to right', 'Open the agent trace on the right to see every tool call and model call', 'Approve, request changes or reject at the end: the decision is logged'],
    why: 'This is Stage 3: an end-to-end process with the right model per job, a full trace, a policy check and a human decision.',
  },
  chat: {
    what: 'Ask about companies, their peers (same sector) and what changed. Click companies in the Peer explorer to attach them to your question. The assistant looks things up in tools before it answers.',
    try: ['Click a peer in the Peer explorer, then "Compare"', 'Click a company code such as NOVN in an answer to attach it too', 'Open "How I got this answer", then try the trap question'],
    why: 'The selection is part of our own interface, which a standard chat canvas does not offer. Answers stay grounded: every figure is checked against the tool results and shown with its source.',
  },
  trust: {
    what: 'A test bench for the agent. 15 test cases, including traps, are sent to a basic agent and a governed agent. Rules and a judge model grade every answer.',
    try: ['Press "Run evaluation" and watch both scores climb', 'Click a cell to read both answers and the grading', 'Look at the red cells: failures tell the team what to fix before go-live'],
    why: 'Foundry lets you prove quality and safety before users see the agent. A passing score is evidence, not a promise.',
  },
  bakeoff: {
    what: 'The same task, written by three models of different size. A senior judge model scores each result. Cost and speed are measured, not guessed.',
    try: ['Press "Run bake-off"', 'Find the model with the lowest cost that still clears the quality bar', 'Look at the scatter chart: up and to the left is better'],
    why: 'The model catalogue lets you choose per task. The biggest model is rarely needed for every job.',
  },
};

const GLOSSARY = {
  momentum: 'Momentum score: a weighted mix of the 1-day, 3-month, 6-month and 1-year returns (5%, 20%, 30%, 45%), in percentage points.',
  signal: 'Signal: Positive at 20 points or more, Negative at -10 or less, otherwise Mixed. Computed from the momentum score.',
  feed: 'Public feed: real closing prices from Yahoo Finance and news headlines from public media, downloaded once and stored with the app. Headlines are reports, not verified facts.',
  evaluation: 'Evaluation: a repeatable test run. The same questions are asked every time and the answers are graded, so quality can be compared over time.',
  judge: 'Judge model: a second, stronger model that grades answers against a rubric. Rule checks run alongside it.',
  tokens: 'Tokens: the pieces of text a model reads (in) and writes (out). Model cost is based on them.',
  hypothesis: 'Hypothesis: an idea that might explain a change. It is not a fact and must be validated.',
  guardrail: 'Guardrail: a rule or filter that stops unsafe or off-policy output before it reaches a person.',
  grounded: 'Grounded: every claim can be traced to a row in the workbook or another named source.',
};
const gl = (key, label) => `<span class="gl" tabindex="0" role="note" data-tip="${esc(GLOSSARY[key])}">${esc(label)}</span>`;

/* The guide is closed by default. The (i) button next to the page title opens it; the choice is remembered per page. */
const guideOpen = (page) => localStorage.getItem(`guide2-${page}`) === 'open';
function renderGuide(page) {
  const g = GUIDE[page];
  const box = $('#guide'), btn = $('#guide-toggle');
  btn.hidden = !g;
  if (!g) { box.innerHTML = ''; return; }
  const list = (a) => `<ul>${a.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
  box.innerHTML = `<div class="guide-grid"><div><h5>What it shows</h5><p>${esc(g.what)}</p></div><div><h5>Try this</h5>${list(g.try)}</div><div><h5>Why it matters</h5><p>${esc(g.why)}</p></div></div>`;
  const set = (open, remember = true) => {
    box.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', String(open));
    btn.classList.toggle('on', open);
    if (remember) localStorage.setItem(`guide2-${page}`, open ? 'open' : 'closed');
  };
  set(guideOpen(page), false);
  btn.onclick = () => set(!box.classList.contains('open'));
}

/* Small building blocks used by several pages */
const disc = (summary, body, { open = false, cls = '' } = {}) => `<details class="disc ${cls}" ${open ? 'open' : ''}><summary>${summary}</summary><div class="disc-b">${body}</div></details>`;
const meter = (n, of = 3, label = '') => `<span class="meter" role="img" aria-label="${esc(label)} ${n} of ${of}" title="${esc(label)}">${Array.from({ length: of }, (_, i) => `<i class="${i < n ? 'on' : ''}"></i>`).join('')}</span>`;
const sevTone = (s) => (s === 'critical' ? 'bad' : s === 'warning' ? 'warn' : 'info');
const sevCounts = (items) => ['critical', 'warning', 'info'].map((s) => [s, items.filter((x) => x.severity === s || x.sev === s).length]).filter(([, n]) => n);
const sevPills = (items) => sevCounts(items).map(([s, n]) => `<span class="chip ${sevTone(s)}">${n} ${s}</span>`).join('');
/* One finding as a compact tile: severity and title first, the detail and the fix only on click. */
const findingTile = (f, cls = '') => {
  const sev = f.severity || f.sev;
  return `<details class="ftile ${esc(sev)} ${cls}"><summary><i class="sevbar"></i><span class="ft-t">${esc(f.title)}</span><span class="chip ${sevTone(sev)}">${esc(sev)}</span></summary>
    <div class="ft-b"><p>${esc(f.detail)}</p><div class="fix">↳ ${esc(f.action)}</div></div></details>`;
};

/* Presenter run-book: the demo in the order that tells the story best. */
const DEMO_STEPS = [
  { page: 'overview', min: 2, title: 'Set the scene', do: 'Walk through the three stages, then hover the dots in the comparison.', say: 'One Excel file, three levels of AI. The question is not which tool is better, but which job each one does.' },
  { page: 'upload', min: 2, wait: 'The animation takes about 8 seconds. Skip it if you are short on time.', title: 'Load the workbook', do: 'Click "Use the sample workbook" and let the animation run, or drop your own file.', say: 'Before an agent acts, someone has to read the data properly. Watch the columns being mapped and the quality being checked.' },
  { page: 'workbook', min: 2, title: 'Stage 1: AI helps', do: 'Show the KPIs, the sector chart and the signal comparison.', say: 'This is what Copilot in Excel gives every user: fast answers. It does not check the data or run a process.' },
  { page: 'reports', min: 2, wait: 'Search works offline with keywords and live with embeddings.', title: 'Bring in public reports', do: 'Show growth and margin, click a page chip to open the PDF, then search for a topic.', say: 'Prices show what the market did. Reports show what the business did, and every figure has its page.' },
  { page: 'monitor', min: 4, wait: 'A live cycle takes about 20 seconds. Talk through the agents while it runs.', title: 'Stage 3: AI executes', do: 'Press "Run monitoring cycle", open the agent trace, then approve the briefing.', say: 'Four agents, a model chosen for each job, a policy check and a person who decides. Every step is traced.' },
  { page: 'chat', min: 2, wait: 'Each answer takes 3 to 8 seconds live.', title: 'Ask about peers', do: 'Press "Discuss this briefing in chat" under the briefing. Then click Novartis and two peers in the Peer explorer, press "Compare", and finish with the trap question "Should I buy...".', say: 'The peer selection is our own screen, built around the agent. The agent answers from tools, every number has a source, and advice is held back.' },
  { page: 'trust', min: 3, wait: 'Live takes about 20 seconds. Explain the test cases while it runs.', title: 'Prove it is safe', do: 'Press "Run evaluation". Click one red cell and the shield cell.', say: 'Before go-live you can show evidence. Failures are useful: they say what to fix.' },
  { page: 'bakeoff', min: 2, wait: 'Live takes about 1 minute: talk through the three models while it runs, or switch to Offline replay (8 seconds).', title: 'Choose the right model', do: 'Press "Run bake-off" and point to the cheapest model above the quality bar.', say: 'Not every job needs the biggest model. Foundry lets you decide with data.' },
  { page: 'overview', min: 1, title: 'Close: better together', do: 'Scroll to "Better together".', say: 'Copilot Studio is the front door for people. Foundry runs the agents that do the work behind it.' },
];

function renderDrawer() {
  const d = $('#dg');
  const idx = Number(sessionStorage.getItem('demoStep') || -1);
  const total = DEMO_STEPS.reduce((s, x) => s + x.min, 0);
  d.innerHTML = `<div class="dg-h"><div><b>Demo guide</b><small>${DEMO_STEPS.length} steps · about ${total} minutes</small></div><button class="x" id="dg-x" aria-label="Close the demo guide">✕</button></div>
    <div class="dg-b">${DEMO_STEPS.map((s, i) => `<a class="dstep ${i === idx ? 'cur' : ''} ${i < idx ? 'past' : ''}" href="#/${s.page}" data-i="${i}">
      <span class="n">${i < idx ? '✓' : i + 1}</span><div><b>${esc(s.title)}</b><span class="min">${s.min} min · ${esc(PAGES[s.page].label)}</span>
      <p><em>Do:</em> ${esc(s.do)}</p><p><em>Say:</em> ${esc(s.say)}</p>${s.wait ? `<p class="wait"><em>Timing:</em> ${esc(s.wait)}</p>` : ''}</div></a>`).join('')}</div>
    <div class="dg-f"><button class="btn ghost sm" id="d-prev" ${idx <= 0 ? 'disabled' : ''}>Back</button><button class="btn sm" id="d-next">${idx < 0 ? 'Start the demo' : idx >= DEMO_STEPS.length - 1 ? 'Finish' : 'Next step'}</button></div>`;
  $('#dg-x').onclick = () => toggleDrawer(false);
  $$('.dstep', d).forEach((a) => a.addEventListener('click', () => { sessionStorage.setItem('demoStep', a.dataset.i); renderDrawer(); }));
  const go = (i) => {
    if (i >= DEMO_STEPS.length) { sessionStorage.removeItem('demoStep'); renderDrawer(); toast('Demo finished'); return; }
    sessionStorage.setItem('demoStep', i);
    if (DEMO_STEPS[i].page !== currentPage()) location.hash = `#/${DEMO_STEPS[i].page}`;
    renderDrawer();
  };
  $('#d-next').onclick = () => go(idx + 1);
  $('#d-prev').onclick = () => go(Math.max(0, idx - 1));
  $('.dstep.cur', d)?.scrollIntoView({ block: 'nearest' });
}
function toggleDrawer(force) {
  const d = $('#dg');
  const open = force ?? d.hidden;
  d.hidden = !open;
  document.body.classList.toggle('dg-open', open);
  $('#guide-btn')?.setAttribute('aria-expanded', String(open));
  if (open) renderDrawer();
}

function renderTop() {
  const s = state.status;
  const liveOk = s?.live_available;
  const live = state.mode === 'live';
  const src = state.source;
  $('#top-actions').innerHTML = `<div class="ta-row">
    <a class="chip file" href="#/upload" title="Change the Excel workbook">${ICON.file}<span class="nm">${esc(src?.name || 'No workbook')}</span><span class="muted">${src?.is_sample ? '· sample' : '· your file'}</span></a>
    <span class="chip snap" title="Date of the market data in the workbook">Data of ${esc(src?.snapshot || '')}</span>
    <span class="chip ${live ? 'good' : ''}" title="${live ? esc(s.endpoint || '') : 'No Azure calls are made'}"><span class="dot ${live ? 'on' : ''}"></span>${live ? 'Foundry connected' : 'Recorded results'}</span></div>
    <div class="ta-row"><div class="seg" id="mode-seg" role="group" aria-label="Run mode">
      <button data-mode="live" class="${live ? 'on' : ''} ${liveOk ? '' : 'disabled'}" aria-pressed="${live}" title="${liveOk ? 'Call real models in Microsoft Foundry' : 'Run az login and set FOUNDRY_ENDPOINT in .env'}">Live · Foundry</button>
      <button data-mode="offline" class="${live ? '' : 'on'}" aria-pressed="${!live}" title="Replay recorded results, no Azure needed">Offline replay</button>
    </div>
    <button class="btn ghost sm" id="guide-btn" aria-expanded="${!$('#dg').hidden}" title="Open the presenter run-book">${ICON.play}Demo guide</button>
    <button class="btn ghost sm" id="zoom-btn" aria-pressed="${document.body.classList.contains('big')}" title="Larger text and spacing for presenting on a projector">A+</button></div>`;
  $('#guide-btn').onclick = () => toggleDrawer();
  $('#zoom-btn').onclick = () => {
    const on = document.body.classList.toggle('big');
    localStorage.setItem('big', on ? '1' : '0');
    $('#zoom-btn').setAttribute('aria-pressed', String(on));
    setTimeout(() => { syncTopbarHeight(); window.dispatchEvent(new Event('resize')); }, 50);
  };
  $('#rail-foot').innerHTML = `Data: <b>${esc(src?.name || 'none')}</b>${src?.snapshot ? ` (as of ${esc(src.snapshot)})` : ''}. Monitoring uses <b>real</b> public quotes and headlines. Not investment advice.`;
  $$('#mode-seg button').forEach((b) => (b.onclick = () => {
    if (b.classList.contains('disabled')) return;
    state.mode = b.dataset.mode;
    localStorage.setItem('mode', state.mode);
    renderTop();
    document.dispatchEvent(new CustomEvent('modechange'));
  }));
}

const currentPage = () => (PAGES[(location.hash || '').replace('#/', '')] ? location.hash.replace('#/', '') : 'overview');

function serverDown(err) {
  return `<div class="card empty rise"><div class="big bad">${ICON.info}</div><h3>The demo server is not running</h3>
    <p>This page is open, but the app behind it cannot be reached. Open a terminal in the project folder, run <code>.\\start.ps1</code>, then press Retry.</p>
    <p style="margin-top:16px"><button class="btn" onclick="location.reload()">Retry</button></p>
    <p class="muted" style="margin-top:14px;font-size:12px">${esc(err?.message || err || '')}</p></div>`;
}

const syncTopbarHeight = () => document.documentElement.style.setProperty('--topbar-h', `${$('.topbar')?.offsetHeight || 100}px`);

async function route() {
  state.cleanup?.();
  state.cleanup = null;
  const page = currentPage();
  $('#page-title').textContent = PAGES[page].title;
  $('#page-sub').textContent = PAGES[page].sub;
  document.title = `${PAGES[page].label} · Foundry Account Intelligence`;
  renderNav();
  renderGuide(page);
  if (!$('#dg').hidden) renderDrawer();
  syncTopbarHeight();
  const view = $('#view');
  view.innerHTML = skeletonFor(page);
  window.scrollTo(0, 0);
  try {
    const cleanup = await VIEWS[page](view);
    if (currentPage() !== page) { cleanup?.(); return; }
    state.cleanup = cleanup || null;
  } catch (err) {
    console.error(err);
    view.innerHTML = serverDown(err);
  }
}

function stream(url, onEvent, onEnd) {
  const es = new EventSource(url);
  let finished = false;
  busy(1);
  const finish = (err) => { if (finished) return; finished = true; busy(-1); es.close(); onEnd?.(err); };
  es.onmessage = (e) => onEvent(JSON.parse(e.data));
  es.addEventListener('end', () => finish(false));
  es.onerror = () => finish(true);
  return () => { if (!finished) { finished = true; busy(-1); } es.close(); };
}

function toast(msg) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.setAttribute('role', 'status');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

function countUp(el, to, { d = 0, dur = 900, prefix = '', suffix = '' } = {}) {
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur);
    const v = to * (1 - Math.pow(1 - k, 3));
    el.textContent = `${prefix}${v.toFixed(d)}${suffix}`;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ------------------------------------------------------------------ overview */
async function overview(el) {
  state.wb ??= await getJSON('/api/workbook');
  const prompts = state.wb.prompts;
  const pick = (stage, tool) => prompts.find((p) => p.stage.startsWith(stage) && (!tool || p.tool === tool))?.prompt || '';
  const stages = [
    { n: 1, h: 'AI helps', tool: 'Copilot in Excel', ic: 'workbook', line: 'Ask questions about data you already have.', auto: 1, who: 'Every business user', q: pick('1'), href: '#/workbook', cta: 'See the workbook insights' },
    { n: 2, h: 'AI works with you', tool: 'Copilot Studio', ic: 'human', line: 'Low-code assistants and simple flows.', auto: 2, who: 'Business makers and IT', q: pick('2', 'Copilot Studio Agent'), href: null, cta: 'Shown in Copilot Studio, not in this app' },
    { n: 3, h: 'AI executes', tool: 'Microsoft Foundry', ic: 'bolt', line: 'Governed agents that run a whole process.', auto: 3, who: 'Developers and AI engineers', q: pick('3'), href: '#/monitor', cta: 'Run the Account Monitor' },
  ];
  // Positions are illustrative: they show where each product sits between two ends, not a score.
  const spectra = [
    { label: 'Built by', l: 'Business makers', r: 'Developers', cs: 22, fd: 82, csTip: 'Business makers and IT, low-code', fdTip: 'Developers and AI engineers, pro-code' },
    { label: 'Autonomy', l: 'Guided flows', r: 'Runs on its own', cs: 28, fd: 88, csTip: 'Guided topics, flows and triggers', fdTip: 'Multi-step, multi-agent agents that use tools and run on their own' },
    { label: 'Models', l: 'Managed for you', r: 'Choose per task', cs: 14, fd: 90, csTip: 'Models are managed for you', fdTip: 'Model catalogue: choose and compare models per task' },
    { label: 'Testing', l: 'Try it in the canvas', r: 'Evaluations and tracing', cs: 25, fd: 90, csTip: 'Test and iterate in the authoring canvas', fdTip: 'Evaluations, red-teaming and tracing before and after go-live' },
    { label: 'Interface', l: 'Ready-made chat', r: 'Your own app', cs: 20, fd: 92, csTip: 'A ready-made chat canvas with cards and suggested replies', fdTip: 'Any front end you build, such as the clickable peer explorer in the Insights chat' },
  ];
  const table = `<table class="cmp">
    <tr><th></th><th>Copilot Studio</th><th>Microsoft Foundry</th></tr>
    <tr><td>Typical result</td><td>Assistants in Teams, Microsoft 365 and the web</td><td>Autonomous agents, workflows and APIs inside your own processes and apps</td></tr>
    <tr><td>Governance</td><td>Power Platform admin controls and data policies</td><td>Entra identity, content safety guardrails, RBAC and your Azure policies</td></tr>
    <tr><td>Best for</td><td>Fast departmental assistants</td><td>Core, differentiating or high-volume AI processes</td></tr>
  </table>`;
  const tiles = [['monitor', 'monitor', 'Account Monitor', 'Agents run a process'], ['trust', 'trust', 'Trust Lab', 'Test before go-live'], ['bakeoff', 'bake', 'Model Bake-off', 'Cheapest good-enough model']];

  el.innerHTML = `
    <div class="hero rise"><h2>One workbook. <span>Three levels of AI.</span></h2></div>
    <div class="start rise">
      <div class="xl-icon">XLSX</div>
      <div><b>Start: upload your Excel workbook</b><p>Loaded: <b>${esc(state.source.name)}</b> · ${state.source.rows} securities</p></div>
      <a class="btn" href="#/upload">${ICON.upload}Upload workbook</a>
    </div>
    <div class="ladder">
      ${stages.map((s) => `
        <div class="card step ${s.n === 3 ? 'hl' : ''} rise" style="animation-delay:${s.n * 0.08}s">
          <div class="num">Stage ${s.n}</div>
          <h3>${s.h}</h3>
          <div class="tool"><i>${ICON[s.ic]}</i>${s.tool}</div>
          <p>${s.line}</p>
          <div class="step-meta"><span>Autonomy</span>${meter(s.n, 3, 'Autonomy')}</div>
          <div class="step-meta"><span>Built by</span><b>${s.who}</b></div>
          ${s.q ? disc('Example prompt', `<div class="quote">“${esc(s.q)}”</div>`, { cls: 'flat' }) : ''}
          ${s.href ? `<a class="btn ${s.n === 3 ? '' : 'ghost'} sm" href="${s.href}">${s.cta}</a>` : `<div class="step-note">${s.cta}</div>`}
          ${s.n < 3 ? `<span class="arrow">${ICON.arrow}</span>` : ''}
        </div>`).join('')}
    </div>

    <div class="card mt rise">
      <div class="row spread" style="flex-wrap:wrap;gap:10px"><div><h3>Copilot Studio vs. Microsoft Foundry</h3><div class="sub" style="margin:0">Where each one sits. Not either/or. Hover a dot for details.</div></div>
        <div class="spec-legend"><span><i class="pin cs">S</i>Copilot Studio</span><span><i class="pin fd">F</i>Foundry</span></div></div>
      <div class="spectra">${spectra.map((r) => `<div class="spec"><div class="spec-h">${r.label}</div>
        <span class="end l">${r.l}</span>
        <div class="line"><b class="pin cs" style="left:${r.cs}%" tabindex="0" data-tip="Copilot Studio: ${esc(r.csTip)}">S</b><b class="pin fd" style="left:${r.fd}%" tabindex="0" data-tip="Foundry: ${esc(r.fdTip)}">F</b></div>
        <span class="end r">${r.r}</span></div>`).join('')}</div>
      ${disc('More differences', table, { cls: 'flat' })}
    </div>

    <div class="card mt rise">
      <h3>Better together</h3>
      <div class="sub">Copilot Studio can call Foundry agents: one familiar front door for users.</div>
      <div class="flow">
        <div class="node"><b>People</b><small>Teams · Copilot</small></div><div class="ar">→</div>
        <div class="node"><b>Copilot Studio</b><small>Front door</small></div><div class="ar">→</div>
        <div class="node f"><b>Foundry agents</b><small>Models · tools · tests</small></div><div class="ar">→</div>
        <div class="node"><b>Your data</b><small>Excel · reports · CRM</small></div>
      </div>
    </div>

    <div class="grid g3 mt">
      ${tiles.map(([k, ic, t, d]) => `<a class="card cta rise" href="#/${k}"><div class="ico">${ICON[ic]}</div><b>${t}</b><span>${d}</span></a>`).join('')}
    </div>`;
}

/* ------------------------------------------------------------------ workbook */
async function workbookView(el) {
  state.wb ??= await getJSON('/api/workbook');
  const wb = state.wb, k = wb.kpis, src = wb.source;
  const charts = [];
  const hasWbSignals = k.wb_positive + k.wb_mixed + k.wb_negative > 0;
  el.innerHTML = `
    <div class="card row spread rise" style="padding:12px 18px;margin-bottom:16px">
      <div class="row" style="gap:12px;min-width:0"><div class="xl-icon sm">XLSX</div><div style="min-width:0"><b class="ell">${esc(src.name)}</b><div class="muted" style="font-size:12.5px">Sheet '${esc(src.sheet)}' · ${src.rows} securities · snapshot ${esc(src.snapshot)} · ${src.is_sample ? 'sample file' : 'your file'}</div></div></div>
      <a class="btn ghost sm" href="#/upload">${ICON.upload}Change file</a>
    </div>
    <div class="grid g5">
      <div class="card kpi rise"><div class="label">Securities</div><div class="value" id="k1">0</div><div class="hint">${k.complete} with data · ${k.distinct_companies} companies</div></div>
      <div class="card kpi rise"><div class="label">Avg 3M</div><div class="value ${tone(k.avg_m3)}" id="k2">0</div><div class="hint">${k.complete} rows</div></div>
      <div class="card kpi rise"><div class="label">Avg 6M</div><div class="value ${tone(k.avg_m6)}" id="k3">0</div><div class="hint">${k.complete} rows</div></div>
      <div class="card kpi rise"><div class="label">Avg 1Y</div><div class="value ${tone(k.avg_y1)}" id="k4">0</div><div class="hint">${k.complete} rows</div></div>
      <div class="card kpi rise"><div class="label">Signals (corrected)</div><div class="value"><span class="up">${k.positive}</span> <span class="muted" style="font-size:20px">/</span> <span class="flat">${k.mixed}</span> <span class="muted" style="font-size:20px">/</span> <span class="down">${k.negative}</span></div><div class="hint">positive / mixed / negative</div></div>
    </div>

    <div class="sec-h mt" style="margin-top:22px"><i>!</i>What a Data Steward agent notices <span class="sev-row" style="margin-left:6px">${sevPills(wb.findings)}</span></div>
    <div class="grid g2">${wb.findings.map((f) => findingTile(f)).join('')}</div>

    <div class="grid g2 mt">
      <div class="card rise"><h3>Sector momentum</h3><div class="sub">Average return by sector</div><div style="height:300px"><canvas id="sector"></canvas></div></div>
      <div class="card rise">
        <h3>${hasWbSignals ? 'Same data, two answers' : 'Signals calculated from your data'}</h3><div class="sub">${hasWbSignals ? "Workbook signal vs. corrected signal" : 'No Signal column found, so the app calculates one'}</div>
        ${hasWbSignals ? `<div class="muted" style="font-size:12px;margin-bottom:6px">As calculated in the workbook</div><div class="stack" id="st-wb"></div>` : ''}
        <div class="muted" style="font-size:12px;margin:${hasWbSignals ? '16px' : '0'} 0 6px">${hasWbSignals ? 'After rescaling to percentage points' : 'Momentum signal per security'}</div>
        <div class="stack" id="st-fix"></div>
        <div class="row" style="gap:14px;font-size:12px;margin-top:12px"><span><span class="dot" style="background:var(--good)"></span> Positive</span><span><span class="dot" style="background:#5a6590"></span> Mixed</span><span><span class="dot" style="background:var(--bad)"></span> Negative</span><span><span class="dot" style="background:#444c6a"></span> No data</span></div>
        ${disc(hasWbSignals ? 'Why do they differ?' : 'How is the signal calculated?', hasWbSignals
          ? 'The Momentum Score multiplies decimal returns but compares them with thresholds written in percentage points. An analyst could miss this; an agent that validates the data first does not.'
          : 'Momentum blends the 1-day, 3-month, 6-month and 1-year returns (5%, 20%, 30%, 45%). 20 points or more is Positive, -10 or less is Negative.', { cls: 'flat' })}
      </div>
    </div>

    <div class="grid g2 mt">
      <div class="card rise"><h3>Strongest momentum</h3><div class="sub">Points, by company</div><div class="bars" id="top"></div></div>
      <div class="card rise"><h3>Weakest momentum</h3><div class="sub">Points, by company</div><div class="bars" id="bottom"></div></div>
    </div>

    <div class="card mt rise">
      <h3>All securities</h3><div class="sub">Hatched rows have no market data</div>
      <div class="toolbar">
        <input type="search" id="q" placeholder="Search company or ticker" style="min-width:240px">
        <select id="sf"><option value="">All sectors</option>${[...new Set(wb.rows.map((r) => r.sector))].sort().map((s) => `<option>${esc(s)}</option>`).join('')}</select>
        <select id="sg"><option value="">All signals</option><option>Positive</option><option>Mixed</option><option>Negative</option><option>Data missing</option></select>
      </div>
      <div class="table-wrap"><table class="data"><thead><tr id="thead"></tr></thead><tbody id="tbody"></tbody></table></div>
      <div class="more-row"><button class="btn ghost sm" id="more"></button></div>
    </div>`;

  countUp($('#k1'), k.securities);
  countUp($('#k2'), k.avg_m3, { d: 1, suffix: '%' });
  countUp($('#k3'), k.avg_m6, { d: 1, suffix: '%' });
  countUp($('#k4'), k.avg_y1, { d: 1, suffix: '%' });

  const seg = (items) => items.filter((i) => i[1] > 0).map(([c, n, label]) => `<div class="${c}" style="width:${(n / k.securities) * 100}%" title="${label}">${n}</div>`).join('');
  const naCount = k.securities - k.complete;
  if (hasWbSignals) $('#st-wb').innerHTML = seg([['seg-pos', k.wb_positive, 'Positive'], ['seg-mix', k.wb_mixed, 'Mixed'], ['seg-neg', k.wb_negative, 'Negative'], ['seg-na', naCount, 'No data']]);
  $('#st-fix').innerHTML = seg([['seg-pos', k.positive, 'Positive'], ['seg-mix', k.mixed, 'Mixed'], ['seg-neg', k.negative, 'Negative'], ['seg-na', naCount, 'No data']]);

  Chart.defaults.color = '#8d97b8';
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  charts.push(new Chart($('#sector'), {
    type: 'bar',
    data: {
      labels: wb.sectors.map((s) => s.sector.replace('Communication services', 'Comm. services').replace('Information technology', 'IT').replace('Retail discretionary', 'Retail discr.')),
      datasets: [
        { label: '3M', data: wb.sectors.map((s) => s.avg_m3), backgroundColor: '#7c5cff', borderRadius: 5 },
        { label: '6M', data: wb.sectors.map((s) => s.avg_m6), backgroundColor: '#27b4ff', borderRadius: 5 },
        { label: '1Y', data: wb.sectors.map((s) => s.avg_y1), backgroundColor: '#2fd69a', borderRadius: 5 },
      ],
    },
    options: {
      maintainAspectRatio: false, animation: { duration: 900 },
      scales: { x: { grid: { display: false }, ticks: { maxRotation: 40, minRotation: 40, font: { size: 10.5 } } }, y: { grid: { color: 'rgba(255,255,255,.06)' }, ticks: { callback: (v) => v + '%' } } },
      plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}%` } } },
    },
  }));

  const byCompany = new Map();
  wb.rows.filter((r) => r.complete).forEach((r) => { if (!byCompany.has(r.company) || r.score > byCompany.get(r.company).score) byCompany.set(r.company, r); });
  const ranked = [...byCompany.values()].sort((a, b) => b.score - a.score);
  const maxAbs = Math.max(...ranked.map((r) => Math.abs(r.score)));
  const bar = (r) => {
    const w = (Math.abs(r.score) / maxAbs) * 50;
    return `<div class="bar-row"><div class="name" title="${esc(r.company)}">${esc(r.company.replace(/ (AG|SA|Ltd\.?|Group|Holding)\b.*$/i, ''))}</div>
      <div class="bar-track"><div class="bar-fill" style="${r.score >= 0 ? `left:50%;background:var(--good)` : `right:50%;background:var(--bad)`};width:0" data-w="${w}"></div></div>
      <div class="val ${tone(r.score)}">${r.score > 0 ? '+' : ''}${r.score.toFixed(1)}</div></div>`;
  };
  $('#top').innerHTML = ranked.slice(0, 7).map(bar).join('');
  $('#bottom').innerHTML = ranked.slice(-7).reverse().map(bar).join('');
  requestAnimationFrame(() => setTimeout(() => $$('.bar-fill').forEach((b) => (b.style.width = b.dataset.w + '%')), 60));

  const cols = [['company', 'Company'], ['sector', 'Sector'], ['price', 'Price CHF'], ['d1', '1D'], ['m3', '3M'], ['m6', '6M'], ['y1', '1Y'], ['score', 'Momentum'], ['signal', 'Signal'], ['signal_workbook', 'In workbook']];
  let sort = { key: 'score', dir: -1 };
  const colLabel = (k2, l) => (k2 === 'score' ? gl('momentum', l) : k2 === 'signal' ? gl('signal', l) : esc(l));
  $('#thead').innerHTML = cols.map(([k2, l]) => `<th data-k="${k2}" class="${['price', 'd1', 'm3', 'm6', 'y1', 'score'].includes(k2) ? 'num' : ''}">${colLabel(k2, l)}</th>`).join('');
  const PREVIEW_ROWS = 10;
  let showAll = false;
  const draw = () => {
    const q = $('#q').value.toLowerCase(), sf = $('#sf').value, sg = $('#sg').value;
    const filtering = Boolean(q || sf || sg);
    let rows = wb.rows.filter((r) => (!q || r.company.toLowerCase().includes(q) || r.ticker.toLowerCase().includes(q)) && (!sf || r.sector === sf) && (!sg || r.signal === sg));
    rows = rows.sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sort.dir;
    });
    const total = rows.length;
    const collapsed = !filtering && !showAll && total > PREVIEW_ROWS;
    if (collapsed) rows = rows.slice(0, PREVIEW_ROWS);
    const more = $('#more');
    more.hidden = filtering || total <= PREVIEW_ROWS;
    more.textContent = showAll ? 'Show fewer' : `Show all ${total} securities`;
    const p = (v) => (v == null ? '<span class="muted">n/a</span>' : `<span class="${tone(v)}">${pct(v)}</span>`);
    $('#tbody').innerHTML = rows.map((r) => `<tr class="${r.complete ? '' : 'nodata'}">
      <td><b>${esc(r.company)}</b> <span class="muted mono" style="font-size:11px">${esc(r.ticker)}</span></td><td>${esc(r.sector)}</td>
      <td class="num">${r.price ?? '—'}</td><td class="num">${p(r.d1)}</td><td class="num">${p(r.m3)}</td><td class="num">${p(r.m6)}</td><td class="num">${p(r.y1)}</td>
      <td class="num">${r.score == null ? '—' : `<b class="${tone(r.score)}">${r.score.toFixed(1)}</b>`}</td>
      <td><span class="sig ${r.signal.split(' ')[0]}">${esc(r.signal)}</span></td><td><span class="sig ${(r.signal_workbook || '').split(' ')[0]}" style="opacity:.55">${esc(r.signal_workbook || '')}</span></td></tr>`).join('') || `<tr><td colspan="10" class="muted" style="padding:20px">No security matches.</td></tr>`;
  };
  $('#more').onclick = () => { showAll = !showAll; draw(); };
  $$('#thead th').forEach((th) => (th.onclick = () => { sort = { key: th.dataset.k, dir: sort.key === th.dataset.k ? -sort.dir : -1 }; draw(); }));
  ['#q', '#sf', '#sg'].forEach((s) => ($(s).oninput = draw));
  draw();
  return () => charts.forEach((c) => c.destroy());
}

/* ------------------------------------------------------------------ public reports */
const fmtM = (v) => (Math.abs(v) >= 1000 || Number.isInteger(v) ? Math.round(v).toLocaleString('en-US') : v.toFixed(1));
const growthChip = (g) => (g == null ? '' : `<span class="gchip ${tone(g)}">${g > 0 ? '▲' : g < 0 ? '▼' : '■'} ${pct(g)}</span>`);
const shortCo = (name) => name.replace(/ (AG|SA|Ltd\.?|Group|Holding|Inc\.?)\b.*$/i, '');

async function reportsView(el) {
  const data = await getJSON('/api/reports');
  const docs = data.documents.filter((d) => d.available);
  const withFin = docs.filter((d) => d.financials);
  const pagesTotal = docs.reduce((s, d) => s + d.pages, 0);
  const by = (d, k) => d.financials?.items.find((i) => i.key === k);
  const pageLink = (d, page, text) => `<a class="src report" href="${d.file_url}#page=${page}" target="_blank" rel="noopener" title="Open the report at page ${page}">${text ?? `p.${page}`}</a>`;
  const live = () => state.mode === 'live' && state.status.live_available;

  const card = (d) => {
    const f = d.financials;
    const stat = (key, fallback) => {
      const i = by(d, key);
      return i ? `<div class="rep-stat"><small>${esc(i.label)}</small><b>${fmtM(i.h1_2026)}</b>${growthChip(i.growth_pct)}${pageLink(d, i.page)}</div>`
        : `<div class="rep-stat"><small>${fallback}</small><b class="muted">n/a</b></div>`;
    };
    const mg = f?.margins.operating_margin_pct;
    return `<div class="card rep rise">
      <div class="row spread"><h3>${esc(d.company)}</h3><span class="chip">${esc(d.standard)} · ${esc(d.currency)} m</span></div>
      ${f ? `<div class="rep-stats">${stat('revenue', 'Revenue')}${stat('operating_profit', 'Operating profit')}${stat('net_income', 'Net income')}</div>
        ${mg ? `<div class="mrg"><span>Operating margin</span><b>${mg.h1_2026}%</b><em>${mg.h1_2025}% a year earlier</em></div>` : ''}`
        : '<p class="muted" style="margin:12px 0">Figures show when this company is in the loaded workbook.</p>'}
      ${disc('About this report', `<div>${esc(d.title)}</div><div class="muted">Period ended ${esc(d.period_end)} · ${d.pages} pages</div>
        <div class="row" style="gap:14px;margin-top:8px"><a href="${d.file_url}" target="_blank" rel="noopener">Open the PDF</a><a href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">Company website</a></div>
        ${d.note ? `<div class="chip warn" style="margin-top:8px;white-space:normal">${esc(d.note)}</div>` : ''}`, { cls: 'flat' })}
    </div>`;
  };

  const bars = (rows, { diverging }) => {
    const max = Math.max(...rows.map((r) => Math.abs(r.v)), 1);
    return rows.map((r) => {
      const w = diverging ? (Math.abs(r.v) / max) * 50 : (r.v / max) * 100;
      const pos = diverging ? (r.v >= 0 ? 'left:50%;background:var(--good)' : 'right:50%;background:var(--bad)') : 'left:0;background:var(--accent-2)';
      return `<div class="bar-row"><div class="name">${esc(r.name)}</div><div class="bar-track"><div class="bar-fill" style="${pos};width:0" data-w="${w}"></div></div>
        <div class="val ${diverging ? tone(r.v) : ''}">${diverging ? pct(r.v) : r.v.toFixed(1) + '%'}</div></div>`;
    }).join('');
  };

  el.innerHTML = `
    <div class="card row spread rise" style="flex-wrap:wrap;gap:10px">
      <div class="row" style="gap:8px;flex-wrap:wrap"><b>${docs.length} public reports</b><span class="chip">${pagesTotal} pages</span><span class="chip accent">Reports: first half 2026</span><span class="chip">Prices: ${esc(data.prices_date)}</span></div>
      <span class="chip ${live() ? 'good' : ''}" id="rep-mode">${live() ? 'Search with embeddings' : 'Search with keywords'}</span>
    </div>
    ${withFin.length ? `<div class="grid g2 mt">
      <div class="card rise"><h3>Revenue growth</h3><div class="sub">H1 2026 versus H1 2025</div><div class="bars" id="b-growth">${bars(withFin.map((d) => ({ name: shortCo(d.company), v: by(d, 'revenue')?.growth_pct })).filter((r) => r.v != null), { diverging: true })}</div></div>
      <div class="card rise"><h3>Operating margin</h3><div class="sub">Share of revenue, H1 2026</div><div class="bars" id="b-margin">${bars(withFin.map((d) => ({ name: shortCo(d.company), v: d.financials.margins.operating_margin_pct?.h1_2026 })).filter((r) => r.v != null), { diverging: false })}</div></div>
    </div>` : ''}
    <div class="grid g3 mt">${docs.map(card).join('')}</div>
    <div class="card mt rise">
      <h3>Search the reports</h3><div class="sub">Find the passage behind an answer.</div>
      <div class="row" style="gap:10px;flex-wrap:wrap"><input type="search" id="rq" placeholder="For example: outlook, risks, net debt" style="flex:1;min-width:220px" maxlength="300">
        <select id="rt"><option value="">All reports</option>${docs.map((d) => `<option value="${esc(d.ticker)}">${esc(shortCo(d.company))}</option>`).join('')}</select>
        <button class="btn" id="rgo">Search</button></div>
      <div class="chips-row">${['outlook', 'risks and uncertainties', 'net debt', 'exchange rates', 'dividend'].map((q) => `<button class="sugg" data-q="${esc(q)}"><i></i>${esc(q)}</button>`).join('')}</div>
      <div id="rres" class="mt"></div>
    </div>`;

  requestAnimationFrame(() => setTimeout(() => $$('.bar-fill', el).forEach((b) => (b.style.width = `${b.dataset.w}%`)), 60));

  const hilite = (text, q) => {
    const words = [...new Set(q.toLowerCase().split(/\W+/).filter((w) => w.length > 2))];
    const safe = esc(text);
    return words.length ? safe.replace(new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi'), '<mark>$1</mark>') : safe;
  };
  const search = async (q) => {
    q = (q || '').trim();
    if (!q) return;
    $('#rq').value = q;
    const t = $('#rt').value;
    $('#rres').innerHTML = '<div class="skel" style="height:90px"></div>';
    let res;
    try { res = await getJSON(`/api/reports/search?q=${encodeURIComponent(q)}&mode=${state.mode}${t ? `&ticker=${t}` : ''}`); }
    catch (err) { $('#rres').innerHTML = `<p class="down">Search failed: ${esc(err.message)}</p>`; return; }
    const cut = (s) => (s.length > 420 ? `${s.slice(0, 420).replace(/\s+\S*$/, '')}…` : s);
    $('#rres').innerHTML = `<div class="row" style="gap:8px;margin-bottom:8px"><span class="chip">${res.passages.length} passages</span><span class="chip ${res.search === 'hybrid' ? 'good' : ''}">${res.search === 'hybrid' ? 'keywords + embeddings' : 'keywords'}</span></div>`
      + res.passages.map((p) => `<div class="passage"><div class="row spread"><span class="chip">${esc(p.company)}</span><a class="src report" href="${esc(p.url)}" target="_blank" rel="noopener">p.${p.page}</a></div><p>${hilite(cut(p.text), q)}</p></div>`).join('');
  };
  $('#rgo').onclick = () => search($('#rq').value);
  $('#rq').addEventListener('keydown', (e) => { if (e.key === 'Enter') search($('#rq').value); });
  el.addEventListener('click', (e) => { const b = e.target.closest('.sugg[data-q]'); if (b) search(b.dataset.q); });
  const onMode = () => { const m = $('#rep-mode'); if (m) { m.textContent = live() ? 'Search with embeddings' : 'Search with keywords'; m.className = `chip ${live() ? 'good' : ''}`; } };
  document.addEventListener('modechange', onMode);
  return () => document.removeEventListener('modechange', onMode);
}

/* ------------------------------------------------------------------ monitor */
const AGENT_INFO = {
  steward: { name: 'Data Steward', role: 'Validates the workbook before anyone relies on it' },
  scout: { name: 'Signal Scout', role: 'Compares new signals with the workbook baseline' },
  analyst: { name: 'Account Analyst', role: 'Drafts a source-grounded briefing with tools' },
  reviewer: { name: 'Compliance Reviewer', role: 'Checks sources, facts and policy' },
};

async function monitorView(el) {
  const signals = await getJSON('/api/signals');
  let stop = null, running = false, timer = null;
  el.innerHTML = `
    <div class="mon-top">
      <div class="card ctl" style="padding:16px">
        <div>
          <div class="muted" style="font-size:12px;margin-bottom:6px">Focus company</div>
          <select id="focus" style="width:100%;margin-bottom:12px"><option value="">Auto: highest materiality</option>${[['Material changes', true], ['Other changes', false]].map(([label, mat]) => { const list = signals.filter((c) => c.material === mat); return list.length ? `<optgroup label="${label}">${list.map((c) => `<option value="${c.ticker}">${esc(c.company)} (${c.ticker})${c.price_delta_pct != null ? ' ' + pct(c.price_delta_pct) : ''}</option>`).join('')}</optgroup>` : ''; }).join('')}</select>
          <button class="btn" id="run" style="width:100%">${ICON.play}Run monitoring cycle</button>
          <div class="pline" id="pl"><i></i></div><div class="ptext"><span id="pl-text">Ready to run</span><span id="pl-pct">0%</span></div>
        </div>
        <div style="margin-top:12px">
          <div class="stat"><span class="muted">Mode</span><b id="s-mode">—</b></div>
          <div class="stat"><span class="muted">Elapsed</span><b id="s-time">0.0 s</b></div>
          <div class="stat"><span class="muted">${gl('tokens', 'Tokens')} in / out</span><b id="s-tok">—</b></div>
          <div class="stat"><span class="muted">Model cost</span><b id="s-cost">—</b></div>
        </div>
      </div>
      <div class="card" style="padding:14px">
        <div class="sec-h" style="margin:2px 4px 10px">Agent team · one model per job</div>
        <div class="pipeline" id="agents">${Object.entries(AGENT_INFO).map(([k, a]) => `<div class="agent" id="ag-${k}"><div class="ic">${ICON[k]}</div><div><b>${a.name}</b><small>${a.role}</small><div class="meta"><span class="chip mono">${esc(state.mode === 'live' ? state.status.models[k] : 'template')}</span></div><div class="state"></div></div></div>`).join('')}
          <div class="agent" id="ag-human"><div class="ic">${ICON.human}</div><div><b>Account team</b><small>Approves before anything is used</small><div class="meta"><span class="chip">human</span></div><div class="state" id="st-human">waiting</div></div></div>
        </div>
      </div>
    </div>
    <div class="mon-body mt">
      <div id="results">
        <div class="card empty" id="empty"><div class="big">${ICON.monitor}</div><h3>Ready to monitor ${state.source.rows} securities</h3>
          <p class="steps-line">Check data <span>→</span> Find changes <span>→</span> Write briefing <span>→</span> Review <span>→</span> You decide</p></div>
      </div>
      <div class="trace-col"><div class="trace"><div class="trace-h"><b>Agent trace</b><span class="row" style="gap:10px"><span id="tr-live"></span><span id="tr-count">0 steps</span></span></div><div class="trace-body" id="trace"></div></div></div>
    </div>`;

  const results = $('#results'), trace = $('#trace');
  const syncChips = () => Object.keys(AGENT_INFO).forEach((k) => { $(`#ag-${k} .meta .chip`).textContent = state.mode === 'live' ? state.status.models[k] : 'template'; });
  document.addEventListener('modechange', syncChips);
  let steps = 0, lastLLM = null;
  const addTrace = (html, t) => {
    const d = document.createElement('div');
    d.className = 'tr';
    d.innerHTML = `<div class="t">${t != null ? t.toFixed(1) + 's' : ''}</div><div>${html}</div>`;
    trace.appendChild(d);
    trace.scrollTop = trace.scrollHeight;
    $('#tr-count').textContent = `${++steps} steps`;
    return d;
  };
  const addSection = (num, title, html, extra = '') => {
    $('#empty')?.remove();
    $('.skel-wrap', results)?.remove();
    const s = document.createElement('div');
    s.className = 'sec rise';
    s.innerHTML = `<div class="sec-h"><i>${num}</i>${title}</div>${html}${extra}`;
    results.appendChild(s);
    s.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return s;
  };
  const setAgent = (key, cls, stateText) => {
    const a = $('#ag-' + key);
    if (!a) return;
    a.classList.remove('running', 'done');
    if (cls) a.classList.add(cls);
    $('.state', a).innerHTML = stateText || '';
  };

  let agentsDone = 0;
  const setProgress = (pctDone, text) => {
    $('#pl i').style.width = `${pctDone}%`;
    $('#pl-pct').textContent = `${Math.round(pctDone)}%`;
    if (text) $('#pl-text').textContent = text;
  };
  const skeletonResults = () => `<div class="skel-wrap"><div class="waiting"><span class="dots"><i></i><i></i><i></i></span><span id="wait-text">Starting the agent team…</span></div>
    ${[0, 1, 2].map((i) => `<div class="skel-block"><div class="skel skel-line s"></div><div class="skel skel-line"></div><div class="skel skel-line m"></div><div class="skel" style="height:${60 + i * 20}px;margin-top:10px"></div></div>`).join('')}</div>`;

  function handle(e) {
    switch (e.type) {
      case 'cycle_start':
        $('#s-mode').textContent = e.mode === 'live' ? 'Live · Foundry' : 'Offline';
        e.agents.forEach((a) => {
          const c = $('#ag-' + a.key);
          $('b', c).textContent = a.name; $('small', c).textContent = a.role;
          $('.meta', c).innerHTML = `<span class="chip mono">${esc(e.mode === 'live' ? a.model : 'template')}</span>`;
        });
        if (e.note) toast(e.note);
        break;
      case 'agent_start': {
        setAgent(e.agent, 'running', `<span class="spin"></span>${esc(e.task)}`);
        const name = $('#ag-' + e.agent + ' b').textContent;
        addTrace(`<div class="agent-h">${esc(name)}</div>`, e.t);
        setProgress((agentsDone / 4) * 100 + 4, `Step ${agentsDone + 1} of 4 · ${name}: ${e.task}`);
        const w = $('#wait-text');
        if (w) w.textContent = `${name} is working: ${e.task.toLowerCase()}…`;
        break;
      }
      case 'agent_done':
        setAgent(e.agent, 'done', `${ICON.check.replace('<svg', '<svg width="13" height="13"')} ${esc(e.summary)}`);
        agentsDone += 1;
        setProgress((agentsDone / 4) * 100);
        break;
      case 'tool_call':
        addTrace(`<div class="call">▸ ${esc(e.tool)}<em>(${esc(JSON.stringify(e.args)).slice(0, 90)})</em></div>`, e.t);
        break;
      case 'tool_result': {
        const d = addTrace(`<div class="res">✓ ${esc(e.summary)}</div><details><summary>result</summary><pre>${esc(JSON.stringify(e.data, null, 1)).slice(0, 1800)}</pre></details>`, e.t);
        d.scrollIntoView({ block: 'nearest' });
        break;
      }
      case 'llm_call':
        lastLLM = addTrace(`<div class="llm"><span class="spin"></span><span class="chip mono">${esc(e.model)}</span><span class="muted">${esc(e.purpose)}</span></div>`, e.t);
        break;
      case 'llm_result':
        if (lastLLM) lastLLM.lastElementChild.innerHTML = `<div class="llm"><span class="chip mono">${esc(e.model)}</span><span>${e.tokens_in}→${e.tokens_out} tok</span><span class="muted">${e.latency}s · ${usd(e.cost)}</span></div>`;
        if (e.totals) { $('#s-tok').textContent = `${e.totals.tokens_in.toLocaleString()} / ${e.totals.tokens_out.toLocaleString()}`; $('#s-cost').textContent = usd(e.totals.cost); }
        break;
      case 'warning':
        addTrace(`<div class="warn">⚠ ${esc(e.message)}</div>`, e.t);
        break;
      case 'findings':
        addSection(1, `Data quality <span class="sev-row" style="margin-left:6px">${sevPills(e.findings)}</span>`, `<div class="grid g2">${e.findings.map((f) => findingTile(f)).join('')}</div>
          ${disc('Steward note', esc(e.note), { cls: 'flat' })}`);
        break;
      case 'changes': {
        const row = (c) => `<div class="chg ${c.material ? 'mat' : ''} ${c.ticker === e.focus ? 'focus' : ''}" title="${esc(c.material ? (c.why || c.reasons.join('; ')) : 'Below the materiality threshold')}">
          <span class="sevdot s${c.max_severity}"></span>
          <div><b>${esc(c.company)}</b> <span class="muted mono" style="font-size:11px">${esc(c.ticker)}</span>${c.ticker === e.focus ? ' <span class="chip accent">briefing</span>' : ''}
            ${c.top ? `<div class="chg-top"><a href="${esc(c.top.url)}" target="_blank" rel="noopener">${esc(c.top.headline)}</a> <span>${esc(c.top.source)} · ${esc(c.top.date)}</span></div>` : ''}</div>
          <span class="chip ${c.material ? 'warn' : ''}">${c.material ? 'material' : 'minor'}</span>
          <span class="delta ${tone(c.price_delta_pct)}">${c.price_delta_pct == null ? 'no price' : pct(c.price_delta_pct)}</span></div>`;
        const ordered = [...e.changes].sort((a, b) => Number(b.ticker === e.focus) - Number(a.ticker === e.focus) || Number(b.material) - Number(a.material));
        const head = ordered.slice(0, 3), rest = ordered.slice(3);
        const matCount = e.changes.filter((c) => c.material).length;
        addSection(2, `Changes since snapshot <span class="chip warn" style="text-transform:none;letter-spacing:0">${matCount} material</span> <span class="chip" style="text-transform:none;letter-spacing:0">${gl('feed', 'real public feed')}</span>`,
          `<div class="card" style="padding:10px">${head.map(row).join('')}${rest.length ? disc(`${rest.length} more companies`, rest.map(row).join(''), { cls: 'flat' }) : ''}</div>`);
        break;
      }
      case 'briefing': renderBriefing(e.briefing); break;
      case 'review': {
        const passed = e.checks.filter((c) => c.passed).length;
        addSection(4, 'Compliance review', `<div class="card">
          <div class="row spread" style="flex-wrap:wrap;gap:12px"><div class="row" style="gap:14px"><span class="ck-strip">${e.checks.map((c) => `<span class="ckd ${c.passed ? 'ok' : 'no'}" tabindex="0" data-tip="${esc(c.label)}: ${esc(c.detail)}">${c.passed ? '✓' : '✕'}</span>`).join('')}</span><b>${passed}/${e.checks.length} checks passed</b></div>
            <span class="chip ${e.verdict === 'approve' ? 'good' : 'bad'}">${e.verdict === 'approve' ? 'Approved for human review' : 'Needs revision'}</span></div>
          ${disc('See the checks', `<p style="margin:0 0 10px">${esc(e.summary)}</p><div class="checks">${e.checks.map((c) => `<div class="check ${c.passed ? 'ok' : 'no'}"><div class="ck">${c.passed ? '✓' : '✕'}</div><div>${esc(c.label)}<small>${esc(c.detail)}</small></div></div>`).join('')}</div>`, { cls: 'flat' })}</div>`);
        break;
      }
      case 'approval_required': renderApproval(e); break;
      case 'done':
        $('#s-time').textContent = `${e.elapsed} s`;
        $('.skel-wrap', results)?.remove();
        setProgress(100, `Finished in ${e.elapsed} s · waiting for your decision`);
        $('#pl').classList.remove('run');
        $('#tr-live').innerHTML = '';
        if (e.mode === 'live') { $('#s-tok').textContent = `${e.totals.tokens_in.toLocaleString()} / ${e.totals.tokens_out.toLocaleString()}`; $('#s-cost').textContent = usd(e.totals.cost); }
        else { $('#s-tok').textContent = 'n/a (offline)'; $('#s-cost').textContent = 'n/a (offline)'; }
        break;
      case 'error': toast(e.message); break;
    }
  }

  function renderBriefing(b) {
    const chip = (s) => srcChip(s, b.sources[s]);
    addSection(3, 'Briefing', `<div class="card brief">
      <div class="row" style="flex-wrap:wrap;gap:8px"><span class="chip">${esc(b.sector)}</span><span class="chip mono">${esc(b.ticker)}</span>
        <span class="chip ${b.generated_by === 'live' ? 'good' : ''}">${b.generated_by === 'live' ? 'Written by ' + esc(b.model) : 'Offline template'}</span><span class="chip">${gl('feed', 'Real news and prices')}</span></div>
      <h2>${esc(b.headline)}</h2><p class="lead">${esc(b.signal_summary)}</p>
      <div class="acc-list">
        ${disc(`Facts <span class="count good">${b.facts.length}</span> <span class="muted">each with a source</span>`, b.facts.map((f) => `<div class="fact"><div>${esc(f.text)}</div>${chip(f.source)}</div>`).join(''), { open: true, cls: 'acc' })}
        ${disc(`${gl('hypothesis', 'Hypotheses')} <span class="count warn">${b.hypotheses.length}</span> <span class="muted">not facts</span>`, b.hypotheses.map((h) => `<div class="hyp"><div class="tagline">Hypothesis · ${esc(h.confidence)} confidence</div>${esc(h.text)}${h.validate_by ? `<small>Validate by: ${esc(h.validate_by)}</small>` : ''}</div>`).join(''), { cls: 'acc' })}
        ${disc(`Data gaps <span class="count">${b.data_gaps.length}</span>`, `<ul class="plain">${b.data_gaps.map((g) => `<li>${esc(g)}</li>`).join('')}</ul>`, { cls: 'acc' })}
        ${disc(`Open questions <span class="count">${b.open_questions.length}</span>`, `<ul class="plain">${b.open_questions.map((g) => `<li>${esc(g)}</li>`).join('')}</ul>`, { cls: 'acc' })}
      </div>
      <h4>Proposed next step</h4><p style="margin:0">${esc(b.next_step)}</p>
      <div class="row" style="margin-top:16px;gap:10px;flex-wrap:wrap"><button class="btn ghost sm" id="discuss">${ICON.chat}Discuss this briefing in chat</button><span class="muted" style="font-size:12px">The chat assistant can read this briefing and cite its sources.</span></div></div>`);
    $('#discuss')?.addEventListener('click', () => { sessionStorage.setItem('chatPrompt', `Give me the briefing for ${b.ticker}`); location.hash = '#/chat'; });
  }

  function renderApproval(e) {
    setAgent('human', 'running', `<span class="spin"></span>awaiting decision`);
    const s = addSection(5, 'Human in the loop', `<div class="card approve" id="appr">
      <div class="row spread"><div><b>Route to ${esc(e.owner_team)}?</b><div class="muted" style="font-size:12.5px;margin-top:2px">Nothing happens without your decision.</div></div>
        <div class="row"><button class="btn good" data-d="approved">Approve and route</button><button class="btn ghost" data-d="changes_requested">Request changes</button><button class="btn ghost" data-d="rejected">Reject</button></div></div></div>`);
    $$('button', s).forEach((b) => (b.onclick = async () => {
      $$('button', s).forEach((x) => (x.disabled = true));
      b.innerHTML = `<span class="spin"></span>Saving…`;
      busy(1);
      let r;
      try {
        r = await fetch('/api/approvals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ briefing_id: e.briefing_id, decision: b.dataset.d, company: e.company, owner_team: e.owner_team }) }).then((x) => x.json());
      } catch (err) {
        $$('button', s).forEach((x) => (x.disabled = false));
        b.textContent = 'Try again'; toast('Could not save the decision'); return;
      } finally { busy(-1); }
      const label = { approved: 'Approved and routed to', changes_requested: 'Changes requested from', rejected: 'Rejected, not routed to' }[r.decision];
      const good = r.decision === 'approved';
      $('#appr').innerHTML = `<div class="row" style="gap:14px"><div class="ok-pop" style="width:40px;height:40px;border-radius:50%;display:grid;place-items:center;flex:none;background:${good ? 'rgba(47,214,154,.2)' : 'rgba(255,181,71,.2)'};color:${good ? 'var(--good)' : 'var(--warn)'}"><svg class="check-draw" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>
        <div><b>${label} ${esc(r.owner_team)}</b><div class="muted" style="font-size:12.5px">Logged ${esc(r.at)} · briefing ${esc(r.briefing_id)} · demo only: no message was actually sent</div></div></div>`;
      setAgent('human', 'done', `${esc(r.decision.replace('_', ' '))}`);
      setProgress(100, 'Decision logged');
    }));
  }

  function reset() {
    results.innerHTML = skeletonResults(); trace.innerHTML = ''; steps = 0; agentsDone = 0; $('#tr-count').textContent = '0 steps';
    ['steward', 'scout', 'analyst', 'reviewer', 'human'].forEach((k) => setAgent(k, '', k === 'human' ? 'waiting' : ''));
    ['#s-tok', '#s-cost'].forEach((s) => ($(s).textContent = '—'));
    $('#pl').classList.add('run'); setProgress(2, 'Starting…');
    $('#tr-live').innerHTML = '<span class="live-dot">live</span>';
  }

  $('#run').onclick = () => {
    if (running) return;
    running = true; reset();
    $('#run').classList.add('busy'); $('#run').innerHTML = `<span class="spin"></span>Running…`;
    const t0 = performance.now();
    timer = setInterval(() => ($('#s-time').textContent = ((performance.now() - t0) / 1000).toFixed(1) + ' s'), 200);
    const focus = $('#focus').value;
    stop = stream(`/api/monitor/stream?mode=${state.mode}${focus ? `&focus=${focus}` : ''}`, handle, (err) => {
      clearInterval(timer); running = false;
      $('#run').classList.remove('busy'); $('#run').innerHTML = `${ICON.play}Run again`;
      $('#pl').classList.remove('run'); $('#tr-live').innerHTML = ''; $('.skel-wrap', results)?.remove();
      if (err) toast('Stream interrupted');
    });
  };
  return () => { stop?.(); clearInterval(timer); document.removeEventListener('modechange', syncChips); };
}

/* ------------------------------------------------------------------ trust lab */
async function trustView(el) {
  const { cases, configs } = await getJSON('/api/trustlab/cases');
  const results = {}; let stop = null, running = false, recordedAt = null;
  el.innerHTML = `
    <div class="card row spread rise">
      <div style="flex:1;min-width:0">
        <div class="row" style="gap:8px;flex-wrap:wrap"><b>15 test cases</b><span class="chip">2 agents</span><span class="chip">rules + ${gl('judge', 'judge model')}</span>${state.source.is_sample ? '' : '<span class="chip warn">always the sample workbook</span>'}</div>
        <div class="note" style="margin-top:6px"><span id="lab-note"></span></div>
        <div class="pline" id="lab-pl" style="max-width:520px"><i></i></div><div class="ptext" style="max-width:520px"><span id="lab-pt">Ready to evaluate 30 answers</span><span id="lab-pp"></span></div></div>
      <button class="btn" id="run">${ICON.play}Run evaluation</button>
    </div>
    <div class="grid mt" style="grid-template-columns:1fr auto 1fr;align-items:stretch">
      <div class="card ring-card bad-c rise"><div class="ring" id="ring-basic" style="--p:0"><span>0</span></div><div><h3>${esc(configs[0].name)}</h3><div class="big">${esc(configs[0].desc)}</div><div class="chip mono" style="margin-top:8px">${esc(configs[0].model)}</div></div></div>
      <div class="delta-badge"><div id="delta">±0<small>test cases</small></div></div>
      <div class="card ring-card good-c rise"><div class="ring" id="ring-governed" style="--p:0"><span>0</span></div><div><h3>${esc(configs[1].name)}</h3><div class="big">${esc(configs[1].desc)}</div><div class="chip mono" style="margin-top:8px">${esc(configs[1].model)}</div></div></div>
    </div>
    <div class="card mt rise"><div class="row spread" style="flex-wrap:wrap;gap:8px"><div><h3>Results per test case</h3><div class="sub" style="margin:0">Click a cell to read both answers.</div></div>
      <div class="heat-legend"><span><i class="hc pass">✓</i>pass</span><span><i class="hc fail">✕</i>fail</span><span><i class="hc blocked">🛡</i>blocked</span></div></div>
      <div class="heat" id="heat"></div>
      ${disc('All 15 questions', `<div class="case head"><div>ID</div><div>Risk area</div><div>Question</div><div>${esc(configs[0].name.split(' ')[0])}</div><div>${esc(configs[1].name.split(' ')[0])}</div></div><div id="cases"></div>`, { cls: 'flat' })}
    </div>
    <div class="grid g2 mt">
      <div class="card rise"><h3>Pass rate by risk area</h3><div class="sub"><span class="dot" style="background:var(--bad)"></span> basic &nbsp; <span class="dot" style="background:var(--good)"></span> governed</div><div id="cats"></div></div>
      <div class="card rise"><h3>What the governed agent adds</h3><div class="sub">Same model, same data. The difference is engineering.</div>
        <div class="ind-list">
          <div class="ind" tabindex="0" data-tip="A data steward corrected the signal column before use"><i>${ICON.check}</i>Checked data</div>
          <div class="ind" tabindex="0" data-tip="Explicit policies: no investment advice, no demand claims from share price"><i>${ICON.check}</i>Clear policies</div>
          <div class="ind" tabindex="0" data-tip="Missing data is reported, never treated as zero"><i>${ICON.check}</i>Missing is not zero</div>
          <div class="ind" tabindex="0" data-tip="Every answer must cite workbook rows"><i>${ICON.check}</i>Cited answers</div>
          <div class="ind" tabindex="0" data-tip="Foundry content safety screens jailbreak attempts on both agents"><i>${ICON.check}</i>Content safety (both agents)</div>
        </div></div>
    </div>`;

  const cell = (id, cfg) => {
    const r = results[id]?.[cfg];
    if (!r) return running ? `<div class="res-cell wait"><span class="spin"></span>testing</div>` : `<div class="res-cell wait">—</div>`;
    return `<div class="res-cell ${r.passed ? 'pass' : 'fail'}"><span class="badge">${r.blocked ? '🛡' : r.passed ? '✓' : '✕'}</span>${r.blocked ? 'blocked' : r.passed ? 'pass' : 'fail'}</div>`;
  };
  const drawHeat = () => {
    const cats = [];
    cases.forEach((c) => { const last = cats[cats.length - 1]; if (last && last.name === c.category) last.n += 1; else cats.push({ name: c.category, n: 1 }); });
    let col = 2;
    const heads = cats.map((c) => { const h = `<div class="cat-h" style="grid-column:${col} / span ${c.n}" title="${esc(c.name)}">${esc(c.name)}</div>`; col += c.n; return h; }).join('');
    const hc = (c, cfg) => {
      const r = results[c.id]?.[cfg];
      const st = r ? (r.blocked ? 'blocked' : r.passed ? 'pass' : 'fail') : running ? 'wait run' : 'wait';
      return `<button class="hc ${st}" data-id="${c.id}" title="${esc(c.id)} ${esc(cfg)}: ${esc(c.prompt.slice(0, 90))}" aria-label="${esc(c.id)} ${esc(cfg)} ${r ? (r.passed ? 'pass' : 'fail') : 'not run'}">${r ? (r.blocked ? '🛡' : r.passed ? '✓' : '✕') : ''}</button>`;
    };
    $('#heat').style.gridTemplateColumns = `76px repeat(${cases.length}, minmax(0, 1fr))`;
    $('#heat').innerHTML = `<span></span>${heads}<span class="row-l bad">${esc(configs[0].name.split(' ')[0])}</span>${cases.map((c) => hc(c, 'basic')).join('')}<span class="row-l good">${esc(configs[1].name.split(' ')[0])}</span>${cases.map((c) => hc(c, 'governed')).join('')}`;
    $$('#heat .hc').forEach((b) => (b.onclick = () => openDrawer(b.dataset.id)));
  };
  const drawCases = () => {
    drawHeat();
    $('#cases').innerHTML = cases.map((c) => `<div class="case ${running && !(results[c.id]?.basic && results[c.id]?.governed) ? 'scanning' : ''}" data-id="${c.id}"><div class="mono muted">${c.id}</div><div><span class="chip">${esc(c.category)}</span></div><div>${esc(c.prompt.length > 110 ? c.prompt.slice(0, 107) + '…' : c.prompt)}</div>${cell(c.id, 'basic')}${cell(c.id, 'governed')}</div>`).join('');
    $$('#cases .case').forEach((row) => (row.onclick = () => openDrawer(row.dataset.id)));
  };
  const score = (cfg) => cases.filter((c) => results[c.id]?.[cfg]?.passed).length;
  const drawScore = () => {
    const b = score('basic'), g = score('governed'), n = cases.length;
    $('#ring-basic').style.setProperty('--p', (b / n) * 100); $('#ring-basic span').textContent = `${b}/${n}`;
    $('#ring-governed').style.setProperty('--p', (g / n) * 100); $('#ring-governed span').textContent = `${g}/${n}`;
    $('#delta').innerHTML = `${g - b >= 0 ? '+' : ''}${g - b}<small>test cases</small>`;
    const cats = [...new Set(cases.map((c) => c.category))];
    $('#cats').innerHTML = cats.map((cat) => {
      const ids = cases.filter((c) => c.category === cat).map((c) => c.id);
      const f = (cfg) => ids.filter((id) => results[id]?.[cfg]?.passed).length / ids.length * 100;
      return `<div class="cat"><div>${esc(cat)}</div>
        <div class="pair"><div class="bar-track"><div class="bar-fill" style="left:0;width:${f('basic')}%;background:var(--bad)"></div></div><em>${Math.round(f('basic'))}%</em></div>
        <div class="pair"><div class="bar-track"><div class="bar-fill" style="left:0;width:${f('governed')}%;background:var(--good)"></div></div><em>${Math.round(f('governed'))}%</em></div></div>`;
    }).join('');
  };
  function openDrawer(id) {
    const c = cases.find((x) => x.id === id), r = results[id] || {};
    const block = (cfg, name) => { const x = r[cfg]; if (!x) return `<h4>${esc(name)}</h4><p class="muted">Not evaluated yet.</p>`;
      return `<h4 class="row" style="margin:18px 0 8px">${esc(name)} <span class="chip ${x.passed ? 'good' : 'bad'}">${x.blocked ? 'blocked by platform' : x.passed ? 'pass' : 'fail'}</span></h4>
        <div class="ans ${x.passed ? 'pass' : 'fail'}">${esc(x.answer || '(no answer)')}</div>
        <div class="muted" style="font-size:12.5px;margin-top:8px">Rules: ${esc(x.rules.detail)} · Judge: ${esc(x.judge.reason)}</div>
        ${x.latency ? `<div class="muted" style="font-size:12px;margin-top:4px">${x.latency}s · ${x.tokens_in + x.tokens_out} tokens · ${usd(x.cost)}</div>` : ''}`; };
    const bg = document.createElement('div'); bg.className = 'drawer-bg';
    const dr = document.createElement('div'); dr.className = 'drawer';
    dr.innerHTML = `<div class="row spread"><span class="chip">${esc(c.category)}</span><button class="btn ghost sm" id="x">Close</button></div><h3>${esc(c.prompt)}</h3>
      <div class="muted" style="font-size:12.5px">Pass criterion: ${esc(c.criterion)}</div>${block('basic', configs[0].name)}${block('governed', configs[1].name)}`;
    document.body.append(bg, dr);
    const close = () => { bg.remove(); dr.remove(); };
    bg.onclick = close; $('#x', dr).onclick = close;
  }
  const note = async () => {
    const s = state.status;
    $('#lab-note').innerHTML = state.mode === 'live' && s.live_available ? `${ICON.info}Live: about 20 seconds, 60 model calls.`
      : s.recordings.trust_lab ? `${ICON.info}Replay of a recorded live run.` : `${ICON.info}No recording found. Run python -m app.record once.`;
  };
  document.addEventListener('modechange', note);
  note(); drawCases(); drawScore();

  const labProgress = (done, total, text) => {
    $('#lab-pl i').style.width = `${(done / total) * 100}%`;
    $('#lab-pp').textContent = total ? `${done} / ${total}` : '';
    if (text) $('#lab-pt').textContent = text;
  };

  $('#run').onclick = () => {
    if (running) return;
    running = true; Object.keys(results).forEach((k) => delete results[k]);
    $('#run').classList.add('busy'); $('#run').innerHTML = `<span class="spin"></span>Evaluating…`;
    $('#lab-pl').classList.add('run'); labProgress(0, cases.length * 2, 'Asking both agents and judging every answer…');
    drawCases(); drawScore();
    let done = 0;
    stop = stream(`/api/trustlab/stream?mode=${state.mode}`, (e) => {
      if (e.type === 'lab_result') { (results[e.case_id] ??= {})[e.config] = e.result; done += 1; labProgress(done, cases.length * 2); drawCases(); drawScore(); }
      if (e.type === 'lab_start' && e.recorded_at) recordedAt = e.recorded_at;
      if (e.type === 'error') toast(e.message);
    }, () => {
      running = false; drawCases(); drawScore();
      $('#lab-pl').classList.remove('run'); labProgress(done, cases.length * 2, done ? 'Evaluation finished' : 'Evaluation stopped');
      $('#run').classList.remove('busy'); $('#run').innerHTML = `${ICON.play}Run again`;
      if (recordedAt && state.mode !== 'live') toast(`Replayed run recorded ${recordedAt}`);
    });
  };
  return () => { stop?.(); document.removeEventListener('modechange', note); $$('.drawer,.drawer-bg').forEach((x) => x.remove()); };
}

/* ------------------------------------------------------------------ bake-off */
async function bakeView(el) {
  const st = state.status, models = st.bakeoff_models;
  const colors = ['#7c5cff', '#27b4ff', '#2fd69a', '#ffb547'];
  const runs = {}; models.forEach((m) => (runs[m] = []));
  let stop = null, running = false, chart = null, tickers = [], bar = st.quality_bar ?? 4.7, lastSum = null;
  const avg = (a, k) => (a.length ? a.reduce((s, x) => s + x[k], 0) / a.length : null);

  el.innerHTML = `
    <div class="card row spread rise">
      <div style="flex:1;min-width:0"><div class="row" style="gap:8px;flex-wrap:wrap"><b>One task</b><span class="chip">${models.length} models</span><span class="chip">5 companies</span><span class="chip">scored by a ${gl('judge', 'judge model')}</span>${state.source.is_sample ? '' : '<span class="chip warn">always the sample workbook</span>'}</div><div class="note" style="margin-top:6px"><span id="bk-note"></span></div>
        <div class="pline" id="bk-pl" style="max-width:520px"><i></i></div><div class="ptext" style="max-width:520px"><span id="bk-pt">Ready to run 15 briefings</span><span id="bk-pp"></span></div></div>
      <button class="btn" id="run">${ICON.play}Run bake-off</button>
    </div>
    <div class="grid g3 mt" id="cards"></div>
    <div id="reco" class="mt"></div>
    <div class="grid g2 mt">
      <div class="card rise"><h3>Quality versus cost</h3><div class="sub">Up and to the left is better.</div><div style="height:300px"><canvas id="scatter"></canvas></div></div>
      <div class="card rise"><h3>Quality by company</h3><div class="sub">Judge score, 1 to 5</div><div id="matrix"></div></div>
    </div>`;

  const price = (m) => st.prices[m] || { in: 0, out: 0 };
  function drawCards(rec) {
    const total = models.length * (tickers.length || 5);
    $('#cards').innerHTML = models.map((m, i) => {
      const r = runs[m], q = avg(r, 'quality'), c = avg(r, 'cost'), l = avg(r, 'latency');
      const wait = running && !r.length;
      const val = (v, f) => (v != null ? f(v) : wait ? '<span class="skel skel-text"></span>' : '—');
      return `<div class="card model-card ${rec === m ? 'rec' : ''}">
        <div class="row spread"><h3>${esc(m)}</h3><span class="chip" style="color:${colors[i]}">${esc(st.tiers[m] || '')}</span></div>
        <div class="muted" style="font-size:12px">$${price(m).in.toFixed(2)} in · $${price(m).out.toFixed(2)} out per 1M ${gl('tokens', 'tokens')}</div>
        <div class="metrics">
          <div class="metric"><small>Quality</small><b>${val(q, (v) => v.toFixed(2) + '<span class="muted" style="font-size:12px"> /5</span>')}</b></div>
          <div class="metric"><small>Latency</small><b>${val(l, (v) => v.toFixed(1) + ' s')}</b></div>
          <div class="metric"><small>Cost / briefing</small><b>${val(c, usd)}</b></div>
          <div class="metric"><small>Cost / 1,000</small><b>${val(c, (v) => usd(v * 1000))}</b></div>
        </div>
        <div class="pips">${(tickers.length ? tickers : [1, 2, 3, 4, 5]).map((_, j) => `<div class="pip ${j < r.length ? 'done' : ''}"></div>`).join('')}</div>
        ${running ? `<div class="ptext" style="margin-top:8px"><span>${r.length < (tickers.length || 5) ? 'Writing and judging briefings…' : 'Done'}</span><span>${r.length} / ${tickers.length || 5}</span></div>` : ''}
        ${rec === m ? `<div class="chip good" style="margin-top:12px">Recommended</div>` : ''}</div>`;
    }).join('');
    void total;
  }
  function drawMatrix() {
    if (!tickers.length) { $('#matrix').innerHTML = `<p class="muted">Run the bake-off to see scores.</p>`; return; }
    $('#matrix').innerHTML = `<table class="cmp" style="font-size:12.5px"><tr><th>Company</th>${models.map((m) => `<th style="background:none;font-family:var(--mono)">${esc(m.replace('gpt-', ''))}</th>`).join('')}</tr>
      ${tickers.map((t) => `<tr><td style="width:auto"><b>${esc(t.company.replace(/ (AG|SA|Ltd\.?|Group|Holding)\b.*$/i, ''))}</b></td>${models.map((m) => {
        const r = runs[m].find((x) => x.ticker === t.ticker);
        return `<td style="background:none">${r ? `<div class="qmini" title="${esc(r.comment)}">${[1, 2, 3, 4, 5].map((n) => `<i class="${r.quality >= n - 0.25 ? 'on' : ''}"></i>`).join('')}</div><span class="muted">${r.quality.toFixed(2)}</span>` : '<span class="muted">…</span>'}</td>`;
      }).join('')}</tr>`).join('')}</table>`;
  }
  function drawChart() {
    const pts = models.map((m, i) => { const r = runs[m]; return r.length ? { label: m, data: [{ x: avg(r, 'cost') * 1000, y: avg(r, 'quality') }], backgroundColor: colors[i], pointRadius: 11, pointHoverRadius: 13 } : null; }).filter(Boolean);
    const allx = pts.map((p) => p.data[0].x), lo = Math.min(...allx, 1) * 0.6, hi = Math.max(...allx, 40) * 1.6;
    const lineDs = { label: `Quality bar (${bar.toFixed(2)})`, type: 'line', data: [{ x: lo, y: bar }, { x: hi, y: bar }], borderColor: 'rgba(255,181,71,.7)', borderDash: [6, 5], pointRadius: 0, borderWidth: 1.5 };
    if (!chart) {
      chart = new Chart($('#scatter'), {
        type: 'scatter', data: { datasets: [...pts, lineDs] },
        options: { maintainAspectRatio: false, animation: { duration: 600 },
          scales: { x: { type: 'logarithmic', min: lo, max: hi, title: { display: true, text: 'Cost per 1,000 briefings (USD)' }, grid: { color: 'rgba(255,255,255,.06)' }, ticks: { maxRotation: 0, callback: (v) => ([1, 2, 5, 10, 20, 50, 100].includes(v) ? '$' + v : '') } },
            y: { min: 3.5, max: 5.2, title: { display: true, text: 'Quality (1–5)' }, grid: { color: 'rgba(255,255,255,.06)' } } },
          plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8 } } } },
      });
    } else { chart.data.datasets = [...pts, lineDs]; chart.options.scales.x.min = lo; chart.options.scales.x.max = hi; chart.update(); }
  }
  const note = () => {
    $('#bk-note').innerHTML = state.mode === 'live' && st.live_available ? `${ICON.info}Live: about a minute.` : st.recordings.bakeoff ? `${ICON.info}Replay of a recorded live run.` : `${ICON.info}No recording found. Run python -m app.record once.`;
  };
  document.addEventListener('modechange', note);
  note(); drawCards(); drawMatrix(); drawChart();

  function recommend(sum) {
    const ok = sum.models.filter((s) => s.avg_quality >= bar && s.check_rate >= 0.8);
    if (ok.length) return { model: ok.reduce((a, b) => (a.avg_cost <= b.avg_cost ? a : b)).model, reason: `Cheapest model that clears the quality bar of ${bar.toFixed(2)} out of 5 and passes the policy checks.` };
    return { model: sum.models.reduce((a, b) => (a.avg_quality >= b.avg_quality ? a : b)).model, reason: `No model clears a quality bar of ${bar.toFixed(2)}; showing the highest quality.` };
  }
  function paintReco() {
    const sum = lastSum, rec = recommend(sum), ms = sum.models, r = ms.find((x) => x.model === rec.model), top = [...ms].sort((a, b) => b.avg_cost - a.avg_cost)[0];
    const n = state.source.companies;
    const yearly = (x) => x.avg_cost * n * 250;
    drawCards(rec.model);
    $('#reco-h').textContent = `${rec.model} is the right fit for this task`;
    const saving = rec.model !== top.model ? `${(top.avg_cost / r.avg_cost).toFixed(0)}×` : null;
    $('#reco-p').innerHTML = `<div class="reco-stats"><div><b>${r.avg_quality.toFixed(2)}</b><span>quality, of 5</span></div>${saving ? `<div><b>${saving}</b><span>cheaper than ${esc(top.model)}</span></div>` : ''}<div><b>${usd(yearly(r))}</b><span>per year, ${n} companies daily</span></div></div>
      ${disc('Why this model?', `${esc(rec.reason)}${rec.model !== top.model ? ` ${esc(top.model)} scores ${top.avg_quality.toFixed(2)} but would cost about <b>${usd(yearly(top))}</b> per year.` : ''}`, { cls: 'flat' })}`;
    $('#qbar-v').textContent = bar.toFixed(2);
    drawChart();
  }
  function showReco(sum) {
    lastSum = sum;
    $('#reco').innerHTML = `<div class="reco rise"><div class="ic">${ICON.check}</div><div style="flex:1"><b id="reco-h"></b><div id="reco-p"></div>
      <div class="row" style="margin-top:12px;flex-wrap:wrap"><span class="muted" style="font-size:12px">Quality bar</span><input type="range" id="qbar" min="4" max="5" step="0.05" value="${bar}" style="accent-color:#7c5cff;width:200px"><b id="qbar-v" style="font-variant-numeric:tabular-nums"></b>
      <span class="muted" style="font-size:12px">Drag to set the quality you need</span></div></div></div>`;
    $('#qbar').oninput = (e) => { bar = +e.target.value; paintReco(); };
    paintReco();
  }

  $('#run').onclick = () => {
    if (running) return;
    running = true; models.forEach((m) => (runs[m] = [])); $('#reco').innerHTML = ''; lastSum = null;
    $('#run').classList.add('busy'); $('#run').innerHTML = `<span class="spin"></span>Running…`;
    const totalRuns = models.length * 5;
    const bkProgress = (n, text) => { $('#bk-pl i').style.width = `${(n / totalRuns) * 100}%`; $('#bk-pp').textContent = `${n} / ${totalRuns}`; if (text) $('#bk-pt').textContent = text; };
    $('#bk-pl').classList.add('run'); bkProgress(0, 'Three models are writing and being judged in parallel…');
    drawCards(); drawMatrix();
    let n = 0;
    stop = stream(`/api/bakeoff/stream?mode=${state.mode}`, (e) => {
      if (e.type === 'bake_start') { tickers = e.tickers; drawCards(); drawMatrix(); }
      if (e.type === 'bake_result') { (runs[e.result.model] ??= []).push(e.result); n += 1; bkProgress(n); drawCards(); drawMatrix(); drawChart(); }
      if (e.type === 'bake_done') showReco(e.summary);
      if (e.type === 'error') toast(e.message);
    }, () => {
      running = false; $('#run').classList.remove('busy'); $('#run').innerHTML = `${ICON.play}Run again`;
      $('#bk-pl').classList.remove('run'); bkProgress(n, n ? 'Bake-off finished' : 'Bake-off stopped');
      drawCards(lastSum ? recommend(lastSum).model : undefined);
    });
  };
  return () => { stop?.(); chart?.destroy(); document.removeEventListener('modechange', note); };
}

/* ------------------------------------------------------------------ chat */
const TOOL_LABEL = {
  find_company: 'company lookup', get_company: 'company profile', get_peers: 'peers in the same sector', compare_companies: 'side-by-side comparison',
  rank_companies: 'ranking', sector_summary: 'sector overview', recent_changes: 'changes since the snapshot', get_briefing: 'account briefing',
  data_quality: 'data quality findings', list_missing_data: 'companies without data',
};
const argText = (a) => Object.values(a || {}).map((v) => (Array.isArray(v) ? v.join(', ') : v)).filter((v) => v !== '' && v != null).join(', ');

/* A source chip. Report, news and quote chips link to their source; the others only explain themselves. */
const srcChip = (id, m) => {
  if (m?.kind === 'report') {
    const mm = id.match(/^REP-([A-Z]+)-p(\d+)$/);
    return `<a class="src report" href="${esc(m.url)}" target="_blank" rel="noopener" title="${esc(`${m.label} · ${m.detail}`)}">${mm ? `${mm[1]} p.${mm[2]}` : esc(id)}</a>`;
  }
  if ((m?.kind === 'news' || m?.kind === 'quote') && m.url) {
    return `<a class="src ${m.kind}" href="${esc(m.url)}" target="_blank" rel="noopener" title="${esc(`${m.label} · ${m.detail}`)}">${esc(id)}</a>`;
  }
  return `<span class="src ${m ? '' : 'unknown'}" title="${esc(m ? `${m.label} · ${m.detail}` : 'Not found in the tool results')}">${esc(id)}</span>`;
};

function mdLite(text, sources = {}, tickers = null) {
  const chip = (id) => srcChip(id, sources[id]);
  // A known ticker becomes a chip, written "(NOVN)" or bare ("UBSG"). Two-letter codes such as RO are only recognised in brackets.
  const tk = (m, a, b) => { const t = a || b; return tickers?.has(t) ? `<button type="button" class="cref" data-t="${t}" title="Click to add to your question">${t}</button>` : m; };
  let html = '', inList = false;
  for (const raw of String(text).split('\n')) {
    const m = raw.match(/^\s*[-*•]\s+(.*)$/);
    // One pass, citations first: otherwise the NOVN inside [REP-NOVN-p3] becomes a company chip and the report link is lost.
    const t = esc(m ? m[1] : raw).replace(/\[((?:SEC|SIG)-\d+|REP-[A-Z]+-p\d+)\]|\(([A-Z]{2,5})\)|\b([A-Z]{3,5})\b/g, (x, id, a, b) => (id ? chip(id) : tk(x, a, b))).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    if (m) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${t}</li>`; }
    else { if (inList) { html += '</ul>'; inList = false; } if (t.trim()) html += `<p>${t}</p>`; }
  }
  return html + (inList ? '</ul>' : '');
}

async function streamPost(url, body, onEvent, signal) {
  busy(1);
  try {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
    if (!res.ok) throw new Error(`The server answered ${res.status}`);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const line = block.split('\n').find((l) => l.startsWith('data: '));
        if (line && line !== 'data: {}') onEvent(JSON.parse(line.slice(6)));
      }
    }
  } finally { busy(-1); }
}

async function chatView(el) {
  const info = await getJSON('/api/chat/suggestions');
  state.source = info.source;
  const PLACEHOLDER = 'Ask about companies, peers, sectors or what changed…';
  const s = info.source, history = [], ctl = new AbortController();
  let context = [], working = false, typer = null, flush = null, xSector = null;
  const refs = [];
  const coOf = new Map();
  info.companies.forEach((c) => c.tickers.forEach((t) => coOf.set(t, c)));
  const known = new Set(coOf.keys());
  const liveOn = () => state.mode === 'live' && state.status.live_available;
  const modeText = () => (liveOn() ? `Live · ${state.status.models.assistant} + ${info.tools} tools` : 'Offline · rule-based router');
  const sugg = (x, cls = '') => `<button class="sugg ${esc(x.kind)} ${cls}" data-p="${esc(x.prompt)}"><i></i>${esc(cls ? x.prompt : x.label)}</button>`;

  el.innerHTML = `
    <div class="chat-layout">
      <div class="card chat rise">
        <div class="chat-head"><span class="avatar" style="width:30px;height:30px;border-radius:10px">${ICON.chat}</span><b>Insights Assistant</b>
          <span class="chip ${liveOn() ? 'good' : ''}" id="modechip">${esc(modeText())}</span>
          <span class="chip info ell" style="max-width:190px" title="${esc(s.name)}">${ICON.file.replace('<svg', '<svg width="13" height="13" style="flex:none"')}<span class="nm">${esc(s.name)}</span></span>
          <button class="btn ghost sm" id="newchat" style="margin-left:auto">New chat</button></div>
        <div class="chat-scroll" id="msgs"></div>
        <div class="ref-tray" id="tray" hidden><div class="pills" id="pills"></div><div class="acts" id="acts"></div></div>
        <div class="chat-input"><textarea id="q" rows="1" placeholder="${PLACEHOLDER}" maxlength="1000"></textarea><button class="btn" id="send">${ICON.send}Send</button></div>
      </div>
      <aside class="chat-side">
        <div class="card rise" id="explorer"><h3>Peer explorer</h3>
          <select id="xco" aria-label="Show the peers of">${info.companies.map((c) => `<option value="${esc(c.ticker)}">${esc(c.short)}</option>`).join('')}</select>
          <div class="peers" id="xpeers" aria-live="polite"></div>
          <small class="peer-hint">Click a company to add it to your question</small></div>
        <div class="card rise"><h3>What it can see</h3>
          <div class="mini-stats">
            <div><b>${s.rows}</b><span>securities</span></div><div><b>${s.complete}</b><span>with data</span></div>
            <div><b>${info.reports}</b><span>reports</span></div><div><b id="nbrief">${info.briefings.length}</b><span>briefings</span></div>
          </div>
          <div class="chip-line"><span class="chip">${info.events} real news and price events</span></div>
          ${disc('What is a competitor here?', 'Peers in the same sector. The workbook has no market share or product data. Revenue and profit come from the public reports, where one is loaded.', { cls: 'flat' })}</div>
        <div class="card rise"><h3>Every answer is checked</h3>
          <div class="ind-list">
            <div class="ind" tabindex="0" data-tip="Facts come from tools that read your workbook and the public reports, never from memory"><i>${ICON.check}</i>Sources cited</div>
            <div class="ind" tabindex="0" data-tip="Every figure is matched against the tool results"><i>${ICON.check}</i>Figures matched</div>
            <div class="ind" tabindex="0" data-tip="Advice-like wording is held back"><i>${ICON.check}</i>No investment advice</div>
          </div></div>
      </aside>
    </div>`;

  const msgs = $('#msgs'), input = $('#q'), sendBtn = $('#send');
  const scroll = () => { msgs.scrollTop = msgs.scrollHeight; };
  const add = (cls, html) => { const d = document.createElement('div'); d.className = `msg ${cls}`; d.innerHTML = html; msgs.appendChild(d); scroll(); return d; };
  const welcome = () => {
    add('bot', `<div class="avatar">${ICON.chat}</div><div class="bubble"><p><b>Hi, I'm the Insights Assistant.</b> Ask me about companies, their peers and what changed.</p>
      <div class="chips-row">${info.suggestions.map((x) => sugg(x)).join('')}</div></div>`);
  };
  welcome();

  /* The peer explorer and the reference tray: companies the user clicks travel with the next questions. */
  const short = (t) => coOf.get(t)?.short || t;
  const syncRefs = () => {
    const withReport = refs.some((t) => coOf.get(t)?.has_report);
    $('#tray').hidden = !refs.length;
    $('#pills').innerHTML = refs.map((t) => `<span class="pill"><b>${esc(short(t))}</b><button type="button" data-rm="${esc(t)}" aria-label="Remove ${esc(short(t))}">×</button></span>`).join('');
    const acts = !refs.length ? [] : [refs.length > 1 ? ['Compare', 'Compare these companies'] : ['Peers', 'Who are the closest competitors?'], ['What changed', 'What changed since the snapshot?'], ...(withReport ? [['H1 results', 'What were the H1 2026 results?']] : [])];
    $('#acts').innerHTML = acts.map(([label, q]) => `<button type="button" class="sugg next" data-p="${esc(q)}"><i></i>${label}</button>`).join('') + (refs.length ? '<button type="button" class="linkbtn" data-clear>Clear</button>' : '');
    $$('.peer', el).forEach((b) => { const on = refs.includes(b.dataset.t); b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); $('.pplus', b).textContent = on ? '✓' : '+'; });
    $$('.cref', msgs).forEach((b) => b.classList.toggle('on', refs.includes(coOf.get(b.dataset.t)?.ticker)));
    input.placeholder = refs.length ? `Ask about ${refs.length > 1 ? 'these companies' : short(refs[0])}…` : PLACEHOLDER;
  };
  const toggleRef = (t) => {
    const c = coOf.get(t);
    if (!c) return;
    const i = refs.indexOf(c.ticker);
    if (i >= 0) refs.splice(i, 1);
    else if (refs.length >= 5) { toast('You can attach up to five companies'); return; }
    else refs.push(c.ticker);
    syncRefs();
  };
  const sigClass = (c) => (!c.has_data ? 'none' : c.signal === 'Positive' ? 'pos' : c.signal === 'Negative' ? 'neg' : 'mix');
  const peerRow = (c, self, maxAbs) => {
    const on = refs.includes(c.ticker);
    const tip = `${c.company} · ${c.has_data ? `momentum ${c.score > 0 ? '+' : ''}${c.score} pts, ${c.signal}` : 'no market data'}${c.has_report ? ' · half-year report loaded' : ''}${c.events ? ` · ${c.events} news or price events` : ''}`;
    return `<button type="button" class="peer ${self ? 'self' : ''} ${on ? 'on' : ''}" data-t="${esc(c.ticker)}" aria-pressed="${on}" title="${esc(tip)}">
      <span class="sg ${sigClass(c)}"></span><span class="pn">${esc(c.short)}</span>
      <span class="pbar">${c.has_data ? `<i class="${c.score < 0 ? 'neg' : ''}" style="width:${Math.max(5, Math.abs(c.score) / maxAbs * 100).toFixed(0)}%"></i>` : ''}</span>
      <span class="pdoc">${c.has_report ? ICON.file : ''}</span><span class="pplus">${on ? '✓' : '+'}</span></button>`;
  };
  let xToken = 0;
  async function loadPeers(ticker) {
    const box = $('#xpeers'), token = ++xToken;
    if (!box) return;
    box.innerHTML = '<div class="skel" style="height:150px"></div>';
    let d;
    try { d = await getJSON(`/api/chat/peers?ticker=${encodeURIComponent(ticker)}`); } catch { if (token === xToken && $('#xpeers')) $('#xpeers').innerHTML = '<p class="muted" style="font-size:12.5px">Could not load the peers.</p>'; return; }
    if (token !== xToken || !$('#xco')) return;
    xSector = d.sector;
    $('#xco').value = d.company.ticker;
    const maxAbs = Math.max(10, ...[d.company, ...d.peers].map((c) => Math.abs(c.score ?? 0)));
    const rows = d.peers.map((c) => peerRow(c, false, maxAbs));
    const hidden = d.more + d.without_data;
    const rest = rows.slice(5).join('') + (hidden ? `<div class="pdiv"><span>${hidden} more without data or not shown</span></div>` : '');
    box.innerHTML = `${peerRow(d.company, true, maxAbs)}<div class="pdiv"><span>${esc(d.sector)} peers</span></div>${rows.slice(0, 5).join('') || '<p class="muted" style="font-size:12.5px">No peers with market data.</p>'}${rows.length > 5 ? disc(`${rows.length - 5} more peers`, rest, { cls: 'flat' }) : ''}`;
  }
  $('#xco').onchange = (e) => loadPeers(e.target.value);
  el.addEventListener('click', (e) => {
    const peer = e.target.closest('.peer'), tk = e.target.closest('.cref'), rm = e.target.closest('[data-rm]');
    if (peer) toggleRef(peer.dataset.t);
    else if (tk) toggleRef(tk.dataset.t);
    else if (rm) toggleRef(rm.dataset.rm);
    else if (e.target.closest('[data-clear]')) { refs.length = 0; syncRefs(); }
  });
  syncRefs();
  loadPeers(info.companies.find((c) => c.ticker === 'NOVN')?.ticker || info.companies[0]?.ticker);

  const setWorking = (on) => {
    working = on; input.disabled = on; sendBtn.disabled = on;
    sendBtn.innerHTML = on ? '<span class="spin"></span>Working…' : `${ICON.send}Send`;
    if (!on) input.focus({ preventScroll: true });
  };

  const badges = (c, blocked, hadTools) => {
    const out = [];
    if (blocked) out.push(['bad', 'Held back by the policy check']);
    else {
      out.push(c.cited.length ? ['good', `${c.cited.length} source${c.cited.length > 1 ? 's' : ''} cited`] : [hadTools ? 'warn' : '', hadTools ? 'No sources cited' : 'No data lookup needed']);
      if (c.figures) out.push(c.ungrounded.length ? ['warn', `⚠ ${c.ungrounded.length} figure${c.ungrounded.length > 1 ? 's' : ''} not found in the tool results`] : ['good', `✓ ${c.figures} figures match the tool results`]);
      if (c.unknown_sources.length) out.push(['warn', `⚠ cites ${c.unknown_sources.join(', ')} without looking it up`]);
      out.push(['good', '✓ no investment advice']);
    }
    return out.map(([cl, t], i) => `<span class="chip ${cl}" style="animation-delay:${i * 0.12}s">${esc(t)}</span>`).join('');
  };

  function finish(shell, a) {
    $('.working', shell)?.remove();
    const stepsEl = $('.steps', shell), ans = $('.ans', shell), bubble = $('.bubble', shell);
    if (a.steps.length) {
      const d = document.createElement('details');
      d.className = 'how';
      d.innerHTML = `<summary>How I got this answer · ${a.steps.length} step${a.steps.length > 1 ? 's' : ''}</summary>`;
      d.appendChild(stepsEl);
      bubble.insertBefore(d, ans);
    } else stepsEl.remove();
    const parts = a.text.split(/(\s+)/);
    let i = 0;
    ans.classList.add('cursor');
    const complete = () => {
      clearTimeout(typer);
      ans.innerHTML = mdLite(a.text, a.sources, known);
      ans.classList.remove('cursor');
      syncRefs();
      const meta = a.live ? `${esc(state.status.models.assistant)} · ${a.tokens_in.toLocaleString()} → ${a.tokens_out.toLocaleString()} tokens · ${usd(a.cost)} · ${a.elapsed}s` : `Offline · rule-based · ${a.elapsed}s`;
      if (!$('.badges', bubble)) bubble.insertAdjacentHTML('beforeend', `<div class="badges">${badges(a.checks, a.blocked, a.steps.length > 0)}</div><div class="meta-line">${meta}</div>${a.followups?.length ? `<div class="follow"><span class="muted">Ask next</span><div class="chips-row">${a.followups.map((q) => sugg({ kind: 'next', prompt: q, label: q })).join('')}</div></div>` : ''}`);
      flush = null;
      scroll();
    };
    flush = complete;
    const tick = () => {
      i = Math.min(parts.length, i + 4);
      ans.innerHTML = mdLite(parts.slice(0, i).join(''), a.sources, known);
      scroll();
      if (i < parts.length) typer = setTimeout(tick, 22);
      else complete();
    };
    tick();
    history.push({ role: 'assistant', content: a.text });
    if (a.context?.length) {
      context = a.context;
      const co = coOf.get(a.context[0]);
      if (co && co.sector !== xSector) loadPeers(co.ticker);
    }
  }

  async function send(text) {
    text = (text || '').trim();
    if (!text || working) return;
    setWorking(true);
    flush?.();
    $$('.follow', msgs).forEach((x) => x.remove());
    input.value = ''; input.style.height = 'auto';
    const attached = refs.slice();
    add('user', `<div class="avatar">You</div><div class="bubble">${esc(text).replace(/\n/g, '<br>')}${attached.length ? `<div class="msg-refs">${attached.map((t) => `<span class="pill sm">${esc(short(t))}</span>`).join('')}</div>` : ''}</div>`);
    history.push({ role: 'user', content: text });
    const shell = add('bot', `<div class="avatar">${ICON.chat}</div><div class="bubble"><div class="steps"></div><div class="working"><span class="dots"><i></i><i></i><i></i></span><span class="wtxt">Reading your question…</span></div><div class="ans"></div></div>`);
    const stepsEl = $('.steps', shell), wtxt = $('.wtxt', shell);
    let pending = null, answered = false;
    try {
      await streamPost('/api/chat/stream', { message: text, history: history.slice(0, -1).slice(-8), context, mode: state.mode, references: attached }, (e) => {
        if (e.type === 'start') wtxt.textContent = e.mode === 'live' ? `Asking ${e.model}…` : 'Working out which data to look at…';
        else if (e.type === 'thinking') wtxt.textContent = 'Deciding what to look up…';
        else if (e.type === 'tool_call') {
          wtxt.textContent = `Looking up: ${TOOL_LABEL[e.tool] || e.tool}…`;
          const c = document.createElement('div');
          c.className = 'step-chip';
          c.innerHTML = `<span class="spin"></span><b>${esc(TOOL_LABEL[e.tool] || e.tool)}</b><code>${esc(e.tool)}(${esc(argText(e.args))})</code><span class="sum">working…</span>`;
          stepsEl.appendChild(c); pending = c; scroll();
        } else if (e.type === 'tool_result' && pending) {
          pending.classList.add('done');
          $('.spin', pending).outerHTML = '<span class="tick">✓</span>';
          $('.sum', pending).textContent = e.summary;
          pending = null; wtxt.textContent = 'Putting the answer together…';
        } else if (e.type === 'warning') toast(e.message);
        else if (e.type === 'error') { $('.working', shell)?.remove(); $('.ans', shell).innerHTML = `<p class="down">${esc(e.message)}</p>`; answered = true; }
        else if (e.type === 'answer') { answered = true; finish(shell, e); }
      }, ctl.signal);
      if (!answered) $('.ans', shell).innerHTML = '<p class="down">No answer came back. Please try again.</p>';
    } catch (err) {
      if (err.name === 'AbortError') return;
      $('.working', shell)?.remove();
      $('.ans', shell).innerHTML = `<p class="down">Could not reach the server. Is it still running? (${esc(err.message)})</p>`;
    } finally {
      if (!ctl.signal.aborted) setWorking(false);
    }
  }

  el.addEventListener('click', (e) => { const b = e.target.closest('.sugg'); if (b) send(b.dataset.p); });
  sendBtn.onclick = () => send(input.value);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = `${Math.min(140, input.scrollHeight)}px`; });
  $('#newchat').onclick = () => { if (working) return; flush = null; clearTimeout(typer); history.length = 0; context = []; refs.length = 0; msgs.innerHTML = ''; welcome(); syncRefs(); input.focus({ preventScroll: true }); };
  const onMode = () => { const m = $('#modechip'); if (m) { m.textContent = modeText(); m.className = `chip ${liveOn() ? 'good' : ''}`; } };
  document.addEventListener('modechange', onMode);
  input.focus({ preventScroll: true });
  const preset = sessionStorage.getItem('chatPrompt');
  let presetTimer = null;
  if (preset) { sessionStorage.removeItem('chatPrompt'); presetTimer = setTimeout(() => send(preset), 500); }
  return () => { ctl.abort(); clearTimeout(typer); clearTimeout(presetTimer); document.removeEventListener('modechange', onMode); };
}

/* ------------------------------------------------------------------ upload and ingest */
const SECTOR_COLORS = ['#7c5cff', '#27b4ff', '#2fd69a', '#ffb547', '#ff5d73', '#c77dff', '#4dd0e1', '#a3e635', '#f472b6', '#94a3b8'];
const STEPS = ['Read file', 'Find data', 'Map columns', 'Extract companies', 'Check quality'];

async function uploadView(el) {
  let run = 0;
  const info = await getJSON('/api/workbook/ingest');
  state.source = info.source;
  renderTop();

  el.innerHTML = `
    <div class="up-top">
      <label class="drop rise" id="drop" tabindex="0">
        <input type="file" id="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden>
        <div class="drop-ic">${ICON.upload}</div>
        <h2>Upload your Excel workbook</h2>
        <p>Drag a <b>.xlsx</b> file onto this box or <u>click to choose a file</u></p>
        <small>The file is read in memory only. It is never changed and it is forgotten when the app restarts.</small>
      </label>
      <div class="up-side">
        <div class="card rise" id="current"></div>
        <div class="card rise"><h3>What the file needs</h3><div class="sub">One sheet, one header row. Column names can vary, e.g. “Kurs”.</div><div class="reqs" id="reqs"></div></div>
      </div>
    </div>
    <div id="ingest" class="mt"></div>`;

  const drop = $('#drop'), input = $('#file'), ing = $('#ingest');
  const renderCurrent = () => {
    const s = state.source;
    $('#current').innerHTML = `<div class="row" style="gap:14px"><div class="xl-icon">XLSX</div>
      <div style="min-width:0;flex:1"><div class="muted" style="font-size:11px;text-transform:uppercase;letter-spacing:1px">Currently loaded</div><b class="ell" style="font-size:15px">${esc(s.name)}</b>
        <div class="muted" style="font-size:12.5px">${s.rows} securities · ${s.complete} with market data · snapshot ${esc(s.snapshot)}</div></div>
      <span class="chip ${s.is_sample ? 'accent' : 'good'}">${s.is_sample ? 'sample file' : 'your file'}</span></div>
      <div class="row mt-s" style="flex-wrap:wrap"><button class="btn ghost sm" id="use-sample">Use the sample workbook</button><a class="btn ghost sm" href="/api/workbook/template" download>Download the sample file</a></div>`;
    $('#use-sample').onclick = useSample;
  };
  const renderReqs = (fields) => {
    $('#reqs').innerHTML = fields.map((f) => `<span class="chip ${f.required ? 'accent' : 'opt'}" title="${esc(f.desc)}">${esc(f.label)}${f.required ? '' : ' (optional)'}</span>`).join('');
  };
  const applySource = (source, report) => { state.source = source; state.wb = null; renderTop(); renderCurrent(); renderReqs(report.fields); };

  async function send(promise, file) {
    drop.classList.add('busy');
    busy(1);
    let res, data;
    try {
      const request = promise.then(async (r) => [r, await r.json()]);
      [[res, data]] = await Promise.all([request, sleep(700)]);
    } catch (err) {
      ing.innerHTML = serverDown(err);
      return;
    } finally { drop.classList.remove('busy'); busy(-1); }
    if (res.ok) { applySource(data.source, data.report); await play(data.report); }
    else { if (data.report) renderReqs(data.report.fields); await play(data.report, { errors: data.errors, file }); }
  }
  const sendFile = (file) => {
    if (!file) return;
    if (!/\.xlsx$/i.test(file.name)) return play(null, { errors: [`“${file.name}” is not an .xlsx file. In Excel use File > Save As > Excel Workbook (.xlsx).`], file });
    return send(fetch('/api/workbook/upload', { method: 'POST', headers: { 'X-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' }, body: file }), file);
  };
  const useSample = () => send(fetch('/api/workbook/reset', { method: 'POST' }));

  const stopDefault = (e) => e.preventDefault();
  window.addEventListener('dragover', stopDefault);
  window.addEventListener('drop', stopDefault);
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); sendFile(e.dataTransfer.files[0]); });
  drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', () => { sendFile(input.files[0]); input.value = ''; });

  const relayout = () => $$('.map', ing).forEach((m) => m._redraw?.());
  window.addEventListener('resize', relayout);

  async function play(report, { instant = false, errors = null, file = null } = {}) {
    const my = ++run;
    let fast = instant;
    const alive = () => my === run;
    const wait = async (ms) => { if (!fast) await sleep(ms); return alive(); };
    ing.innerHTML = `<div class="stepper" id="stepper">${STEPS.map((s, i) => `<div class="st" data-i="${i}"><span class="c">${i + 1}</span><span class="lbl">${s}</span></div>`).join('')}${instant ? '' : '<button class="btn ghost sm skip">Skip animation</button>'}</div><div id="panels"></div>`;
    $('.skip', ing)?.addEventListener('click', () => { fast = true; $('.skip', ing)?.remove(); });
    const mark = (i, s) => { const st = $(`.st[data-i="${i}"]`, ing); if (!st) return; st.className = `st ${s}`; $('.c', st).innerHTML = s === 'done' ? '✓' : s === 'err' ? '✕' : s === 'active' ? '<span class="spin"></span>' : String(i + 1); };
    const panels = $('#panels', ing);
    const panel = (n, title, sub, cls = '') => {
      const p = document.createElement('section');
      p.className = `panel rise ${cls}`;
      p.innerHTML = `<div class="panel-h"><i>${n}</i><div><b>${title}</b><small>${sub}</small></div></div><div class="panel-b"></div>`;
      panels.appendChild(p);
      if (!instant) p.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return $('.panel-b', p);
    };
    /* A finished step shrinks to its title and a one-line result. Click the header to open it again. */
    const fold = (body, summary) => {
      const p = body.closest('.panel');
      if (!p) return;
      $('small', p).textContent = summary;
      p.classList.add('done');
      const h = $('.panel-h', p);
      h.setAttribute('role', 'button'); h.tabIndex = 0; h.setAttribute('aria-expanded', 'false');
      const toggle = () => { const open = p.classList.toggle('open'); h.setAttribute('aria-expanded', String(open)); if (open) $$('.map', p).forEach((m) => m._redraw?.()); };
      h.onclick = toggle;
      h.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } };
    };
    const failAt = !errors ? -1 : !report ? 0 : report.fields.some((f) => f.required && !f.column) ? 2 : 3;
    const failPanel = (n) => {
      $('.skip', ing)?.remove();
      const b = panel('!', 'We could not use this file', 'Nothing was loaded. The previous workbook is still active.', 'fail');
      b.innerHTML = `<ul class="plain">${errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>
        <p class="muted" style="margin:12px 0 0;font-size:13px">Row 1 (or one of the first 10 rows) needs column names such as Company, Ticker, Sector, Price (CHF), Daily Perf., 3M Perf., 6M Perf. and 1Y Perf.</p>
        <div class="row mt-s" style="flex-wrap:wrap"><button class="btn sm" id="again">Choose another file</button><a class="btn ghost sm" href="/api/workbook/template" download>Download the sample as a template</a><button class="btn ghost sm" id="fallback">Use the sample workbook</button></div>`;
      $('#again', b).onclick = () => input.click();
      $('#fallback', b).onclick = useSample;
    };

    // 1 - read the file
    mark(0, 'active');
    const f = report?.file || { name: file?.name || 'file', size_kb: file ? (file.size / 1024).toFixed(1) : '?', sha: '' };
    let b = panel(1, 'Reading the file', 'Is it a real Excel workbook? Which sheets?');
    b.innerHTML = `<div class="file-card"><div class="xl-icon">XLSX</div><div style="min-width:0"><b class="ell">${esc(f.name)}</b><div class="meta">${esc(f.size_kb)} KB${f.sha ? ` · fingerprint ${esc(f.sha)}` : ''}</div></div>
      ${failAt === 0 ? '<span class="chip bad" style="margin-left:auto">✕ not usable</span>' : '<span class="chip good" style="margin-left:auto">✓ valid Excel workbook</span>'}<div class="bar-load"></div></div><div class="sheet-chips" id="sheets"></div>`;
    requestAnimationFrame(() => requestAnimationFrame(() => { const bar = $('.bar-load', b); if (bar) bar.style.width = '100%'; }));
    if (failAt === 0) { mark(0, 'err'); failPanel(2); return; }
    const sheetChips = [];
    for (const s of report.sheets) {
      const c = document.createElement('span');
      c.className = 'chip sheet pop';
      c.textContent = `Sheet “${s.name}” · ${s.rows} × ${s.cols}`;
      $('#sheets', b).appendChild(c); sheetChips.push([c, s]);
      requestAnimationFrame(() => c.classList.add('in'));
      if (!await wait(260)) return;
    }
    if (!await wait(700)) return;
    mark(0, 'done');
    fold(b, `${f.name} · ${f.size_kb} KB · valid Excel workbook`);

    // 2 - find the table
    mark(1, 'active');
    b = panel(2, 'Finding the data table', 'Looking for the header row');
    const pv = report.preview;
    const letters = report.mapping.map((m) => m.letter);
    b.innerHTML = `<div class="xl-wrap"><table class="xl"><thead><tr><th></th>${pv.columns.map((_c, i) => `<th>${esc(letters[i] || '')}</th>`).join('')}</tr></thead><tbody>
      <tr class="rowfade hdr"><td class="rn">${report.header_row}</td>${pv.columns.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>
      ${pv.rows.map((r, i) => `<tr class="rowfade"><td class="rn">${report.header_row + 1 + i}</td>${r.map((v) => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="badge-note" id="found"></div>`;
    for (const tr of $$('tr.rowfade', b)) {
      tr.classList.add('scan', 'in');
      if (!await wait(260)) return;
      tr.classList.remove('scan');
    }
    sheetChips.forEach(([c, s]) => { c.classList.add(s.chosen ? 'chosen' : 'skipped'); if (!s.chosen) c.title = 'No matching header row on this sheet'; });
    $('#found', b).innerHTML = `${ICON.check.replace('<svg', '<svg width="15" height="15"')} Using sheet “${esc(report.sheet)}”. Header found in row ${report.header_row}, with ${report.data_rows} data rows below it.`;
    if (!await wait(900)) return;
    mark(1, 'done');
    fold(b, `Sheet “${report.sheet}” · header in row ${report.header_row} · ${report.data_rows} data rows`);

    // 3 - map the columns
    mark(2, 'active');
    b = panel(3, 'Mapping columns to app fields', 'Matching your column names to what the app needs');
    const mapped = new Set(report.mapping.filter((x) => x.field).map((x) => x.field));
    const right = [];
    report.mapping.forEach((x) => { if (x.field) right.push({ key: x.field, label: x.label, req: x.required, from: x.column, sample: x.samples[0] || '' }); });
    report.fields.filter((x) => !mapped.has(x.key)).sort((a, z) => Number(z.required) - Number(a.required)).forEach((x) => right.push({ key: x.key, label: x.label, req: x.required, from: null }));
    b.innerHTML = `<div class="map"><div class="map-col"><div class="map-head">Columns in your Excel</div>${report.mapping.map((x) => {
        const to = x.field || (x.how === 'recomputed' ? 'derived:Momentum score' : '');
        return `<div class="map-src how-${esc(x.how)}" data-to="${esc(to)}" data-how="${esc(x.how)}"><span class="letter">${esc(x.letter)}</span><div><b>${esc(x.column)}</b><small>${esc(x.samples.join(' · ') || 'empty column')}</small></div><span class="kind">${esc(x.kind)}</span></div>`;
      }).join('')}</div>
      <svg class="map-svg"></svg>
      <div class="map-col"><div class="map-head">What the app needs</div>${right.map((r) => `<div class="map-dst ${r.from ? '' : 'empty'} ${r.req ? 'req' : ''}" data-key="${esc(r.key)}" data-from="${esc(r.from || '')}" data-sample="${esc(r.sample || '')}"><div><b>${esc(r.label)}${r.req ? '<span class="tag">required</span>' : ''}</b><small>${r.from ? 'waiting…' : r.req ? 'No matching column found' : 'Not in your file (optional)'}</small></div></div>`).join('')}
        <div class="map-head">Calculated by the app</div>${report.derived.map((c) => `<div class="map-dst calc" data-key="derived:${esc(c.label)}"><div><b>${esc(c.label)}</b><small>${esc(c.how)}</small></div></div>`).join('')}</div></div>
      <div class="map-legend"><span><i style="background:var(--good)"></i>matched by name</span><span><i style="background:var(--accent-2)"></i>matched by a name variant</span><span><i style="background:var(--warn)"></i>recomputed by the app</span><span style="opacity:.6">grey = not used</span></div>
      ${report.notes.length ? disc(`Reading notes <span class="count">${report.notes.length}</span>`, `<ul class="plain">${report.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>`, { cls: 'flat' }) : ''}`;
    const mapEl = $('.map', b);
    const svg = $('.map-svg', mapEl);
    const drawLines = (animate) => {
      const sr = svg.getBoundingClientRect();
      svg.setAttribute('viewBox', `0 0 ${sr.width} ${sr.height}`);
      svg.innerHTML = '';
      const out = [];
      $$('.map-src', mapEl).forEach((src) => {
        const key = src.dataset.to;
        if (!key) return;
        const dst = mapEl.querySelector(`.map-dst[data-key="${CSS.escape(key)}"]`);
        if (!dst) return;
        const a = src.getBoundingClientRect(), z = dst.getBoundingClientRect();
        const y1 = a.top + a.height / 2 - sr.top, y2 = z.top + z.height / 2 - sr.top, w = sr.width;
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M0,${y1} C${w * 0.55},${y1} ${w * 0.45},${y2} ${w},${y2}`);
        path.setAttribute('class', `ln ${src.dataset.how}`);
        svg.appendChild(path);
        if (src.dataset.how !== 'recomputed') { const len = path.getTotalLength(); path.style.strokeDasharray = len; path.style.strokeDashoffset = animate ? len : 0; }
        else path.style.opacity = animate ? 0 : 1;
        out.push({ src, dst, path });
      });
      return out;
    };
    mapEl._redraw = () => drawLines(false);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const lines = drawLines(!fast);
    for (const { src, dst, path } of lines) {
      src.classList.add('on');
      path.style.transition = fast ? 'none' : 'stroke-dashoffset .55s ease, opacity .55s ease';
      path.style.strokeDashoffset = 0; path.style.opacity = 1;
      dst.classList.add('filled');
      const sm = $('small', dst);
      if (dst.dataset.from) sm.textContent = `from “${dst.dataset.from}”${dst.dataset.sample ? ` · e.g. ${dst.dataset.sample}` : ''}`;
      if (!await wait(190)) return;
    }
    $$('.map-src', mapEl).forEach((s) => { if (s.dataset.how === 'ignored') { s.classList.add('unused'); $('.kind', s).textContent = 'not used'; } });
    if (!await wait(700)) return;
    if (failAt === 2) { mark(2, 'err'); failPanel(4); return; }
    mark(2, 'done');
    fold(b, `${report.mapping.filter((x) => x.field).length} of ${report.mapping.length} columns mapped to app fields`);
    if (failAt === 3) { mark(3, 'err'); failPanel(4); return; }

    // 4 - extract the companies
    mark(3, 'active');
    const c = report.counts, co = report.companies;
    b = panel(4, 'Extracting the companies', 'One security per row, gaps flagged, never filled with zeros');
    const sectors = [...new Set(co.map((x) => x.sector))];
    const colour = (s) => SECTOR_COLORS[sectors.indexOf(s) % SECTOR_COLORS.length];
    const shown = co.slice(0, 300);
    b.innerHTML = `<div class="counters">${[['Rows read', c.rows_read, ''], ['Securities', c.companies, ''], ['With market data', c.with_data, 'up'], ['Incomplete data', c.no_data, c.no_data ? 'warn' : ''], ['Share-class groups', c.share_class_groups, '']]
        .map(([l, v, cl], i) => `<div class="counter"><b class="${cl === 'warn' ? '' : cl}" style="${cl === 'warn' ? 'color:var(--warn)' : ''}" id="cn${i}" data-v="${v}">0</b><small>${l}</small></div>`).join('')}</div>
      <div class="sector-legend">${sectors.map((s) => `<span class="chip" data-s="${esc(s)}" style="--sc:${colour(s)}"><i></i>${esc(s)} · ${co.filter((x) => x.sector === s).length}</span>`).join('')}</div>
      <div class="co-grid">${shown.map((x) => `<div class="co ${esc(x.status)} ${x.share_classes.length > 1 ? 'share' : ''}" data-s="${esc(x.sector)}" style="--sc:${colour(x.sector)}" title="${esc(x.company)} · row ${x.xl_row}${x.share_classes.length > 1 ? ' · share classes: ' + esc(x.share_classes.join(', ')) : ''}">
        <span class="tk">${esc(x.ticker)}</span><span class="pr">${x.price == null ? 'no data' : x.status === 'partial' ? 'partial' : esc(String(x.price))}</span><span class="nm">${esc(x.company)}</span></div>`).join('')}${co.length > shown.length ? `<div class="co in"><span class="nm">+ ${co.length - shown.length} more</span></div>` : ''}</div>`;
    const delay = Math.min(45, 2400 / Math.max(1, shown.length));
    $$('.counter b', b).forEach((n) => countUp(n, Number(n.dataset.v), { dur: fast ? 1 : Math.max(500, delay * shown.length) }));
    $$('.sector-legend .chip', b).forEach((chip) => (chip.onclick = () => {
      const on = !chip.classList.contains('sel');
      $$('.sector-legend .chip', b).forEach((x) => { x.classList.toggle('sel', on && x === chip); x.classList.toggle('off', on && x !== chip); });
      $$('.co', b).forEach((x) => x.classList.toggle('dim', on && x.dataset.s !== chip.dataset.s));
    }));
    for (const x of $$('.co:not(.in)', b)) {
      x.classList.add('in');
      if (!fast && !await wait(delay)) return;
    }
    if (!await wait(600)) return;
    mark(3, 'done');
    fold(b, `${c.companies} securities · ${c.with_data} with market data`);

    // 5 - check quality
    mark(4, 'active');
    b = panel(5, 'Checking data quality', 'What a Data Steward agent finds first');
    let summary = null;
    try { summary = await getJSON('/api/workbook'); state.wb = summary; } catch { /* the page still works without the findings */ }
    const items = [...(summary?.findings || []).map((x) => ({ sev: x.severity, title: x.title, detail: x.detail, action: x.action })),
      ...report.warnings.map((w) => ({ sev: 'warning', title: 'Reading note', detail: w, action: 'The value was treated as missing, not as zero.' }))];
    b.innerHTML = `<div class="sev-row" style="margin-bottom:10px">${sevPills(items)}</div><div class="grid g2">${items.map((x) => findingTile(x, 'pop')).join('')}</div>`;
    for (const x of $$('.ftile', b)) {
      x.classList.add('in');
      if (!await wait(320)) return;
    }
    mark(4, 'done');
    $('.skip', ing)?.remove();
    const done = document.createElement('div');
    done.className = 'ready rise';
    done.innerHTML = `<div class="ic">${ICON.check}</div><div style="flex:1"><b>Ready: ${c.companies} securities loaded</b><p>${c.with_data} with market data · the other pages now use “${esc(f.name)}”</p></div>
      <div class="row" style="flex-wrap:wrap;justify-content:flex-end"><button class="btn ghost sm" id="replay">Replay animation</button><a class="btn ghost sm" href="#/workbook">Workbook insights</a><a class="btn good" href="#/monitor">Run the Account Monitor</a></div>`;
    panels.appendChild(done);
    $('#replay', done).onclick = () => play(report);
    if (!instant) done.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  renderCurrent();
  renderReqs(info.report.fields);
  await play(info.report, { instant: true });
  return () => { run++; window.removeEventListener('dragover', stopDefault); window.removeEventListener('drop', stopDefault); window.removeEventListener('resize', relayout); };
}

/* ------------------------------------------------------------------ boot */
const VIEWS = { overview, upload: uploadView, workbook: workbookView, reports: reportsView, monitor: monitorView, chat: chatView, trust: trustView, bakeoff: bakeView };

(async function boot() {
  $('#logo').innerHTML = ICON.logo;
  document.body.classList.toggle('big', localStorage.getItem('big') === '1');
  window.addEventListener('hashchange', route);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#dg').hidden) toggleDrawer(false); });
  window.addEventListener('resize', syncTopbarHeight);
  // Show the page frame and a loading skeleton straight away; the server may need a moment.
  renderNav();
  $('#page-title').textContent = PAGES[currentPage()].title;
  $('#page-sub').textContent = PAGES[currentPage()].sub;
  $('#view').innerHTML = skeletonFor(currentPage());
  syncTopbarHeight();
  try {
    state.status = await getJSON('/api/status');
  } catch (err) {
    $('#view').innerHTML = serverDown(err);
    return;
  }
  state.source = state.status.source;
  if (!state.mode || (state.mode === 'live' && !state.status.live_available)) state.mode = state.status.live_available ? 'live' : 'offline';
  renderTop();
  route();
})();



