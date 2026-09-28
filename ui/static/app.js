/* Maximo Delivery AI Suite — control surface.
   Vanilla JS, no build step, no framework. */

'use strict';

// ------------------------------------------------------------------ state
const S = {
  view: 'dashboard',
  runId: localStorage.getItem('mx.runId') || null,
  status: null,
  health: null,
  files: [],
  processes: [],
  ptab: 'rail',
  busy: false,
};

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ------------------------------------------------------------- utilities
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function bytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}

function when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  if (mins < 1440) return Math.floor(mins / 60) + 'h ago';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function toast(message, kind = 'info', title = '', fix = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.innerHTML = `<div class="tmsg">${title ? `<div class="ttitle">${esc(title)}</div>` : ''}
    ${esc(message)}${fix ? `<div class="tfix">${esc(fix)}</div>` : ''}</div>`;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 250); }, kind === 'error' ? 8500 : 4200);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  let payload = null;
  const text = await res.text();
  if (text) { try { payload = JSON.parse(text); } catch { payload = { message: text }; } }
  if (!res.ok) {
    const d = (payload && payload.detail) || payload || {};
    const err = new Error(d.message || `Request failed (${res.status})`);
    err.remedy = d.remedy || '';
    err.code = d.code || String(res.status);
    throw err;
  }
  return payload;
}

function fail(err) {
  console.error(err);
  toast(err.message || String(err), 'error', err.code || 'Error', err.remedy || '');
}

// --------------------------------------------------------- tiny markdown
function markdown(src) {
  const lines = String(src || '').replace(/\r\n/g, '\n').split('\n');
  const out = [];
  let i = 0, inList = null;

  const closeList = () => { if (inList) { out.push(`</${inList}>`); inList = null; } };

  const inline = t => esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|\W)\*([^*\n]+)\*/g, '$1<em>$2</em>');

  while (i < lines.length) {
    const line = lines[i];

    if (/^\s*```/.test(line)) {
      closeList();
      const body = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(body.join('\n'))}</code></pre>`);
      continue;
    }

    // GFM table
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
      closeList();
      const cells = r => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
      const header = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push('<table><thead><tr>' + header.map(h => `<th>${inline(h)}</th>`).join('') + '</tr></thead><tbody>'
        + rows.map(r => '<tr>' + r.map(c => `<td>${inline(c)}</td>`).join('') + '</tr>').join('')
        + '</tbody></table>');
      continue;
    }

    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }

    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { closeList(); out.push('<hr>'); i++; continue; }

    if (/^\s*>/.test(line)) {
      closeList();
      const body = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push(`<blockquote>${inline(body.join(' '))}</blockquote>`);
      continue;
    }

    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const want = ul ? 'ul' : 'ol';
      if (inList !== want) { closeList(); out.push(`<${want}>`); inList = want; }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
      i++;
      continue;
    }

    if (!line.trim()) { closeList(); i++; continue; }

    closeList();
    const para = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !/^(\s*([-*+]|\d+[.)])\s|#{1,6}\s|\s*>|\s*```|\|)/.test(lines[i])) {
      para.push(lines[i++].trim());
    }
    out.push(`<p>${inline(para.join(' '))}</p>`);
  }
  closeList();
  return out.join('\n');
}

// ------------------------------------------------------------ navigation
/** Deep links: #/pipeline/RUN-abc123 so a run can be bookmarked or shared. */
function syncHash() {
  const hash = S.view === 'pipeline' && S.runId ? `#/pipeline/${S.runId}` : `#/${S.view}`;
  if (location.hash !== hash) history.replaceState(null, '', hash);
}

function readHash() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (!parts.length) return null;
  const [view, runId] = parts;
  if (runId) setRun(runId);
  return view;
}

function go(view) {
  S.view = view;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === view));
  $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + view));
  const titles = {
    dashboard: 'Dashboard', 'new-run': 'New run', pipeline: 'Pipeline',
    brain: 'AI Brain', maximo: 'Maximo', settings: 'Settings',
  };
  $('#pageTitle').textContent = titles[view] || view;
  $('#pageCrumb').textContent = (view === 'pipeline' && S.status) ? S.status.title : '';
  syncHash();
  const loaders = {
    dashboard: loadDashboard, pipeline: () => S.runId ? loadPipeline() : renderPipeline(),
    brain: loadBrain, maximo: loadMaximo, settings: loadSettings,
  };
  if (loaders[view]) loaders[view]();
}

// ---------------------------------------------------------------- health
async function loadHealth() {
  try {
    const h = await api('/api/system/health');
    S.health = h;
    $('#brandSub').textContent = `v${h.version} · ${h.maximo_version}`;

    $('#valModel').textContent = h.model.label;
    $('#dotModel').className = 'dot ' + (h.model.available ? 'ok' : 'warn');
    $('#valMaximo').textContent = h.maximo.label;
    $('#dotMaximo').className = 'dot ' + (h.maximo.configured ? 'ok' : 'warn');
    $('#valBrain').textContent = `${h.brain.documents} docs`;
    $('#dotBrain').className = 'dot ' + (h.brain.documents ? 'ok' : 'warn');
  } catch (e) { fail(e); }
}

// ------------------------------------------------------------- dashboard
async function loadDashboard() {
  try {
    const [runs, health] = await Promise.all([api('/api/runs'), api('/api/system/health')]);
    S.health = health;

    const awaiting = runs.filter(r => r.awaiting && r.awaiting.length).length;
    const artifacts = runs.reduce((a, r) => a + (r.artifacts || 0), 0);
    const cards = [
      { label: 'Runs', value: runs.length, sub: runs.length ? `${runs.filter(r => r.current_phase === 'done').length} complete` : 'none yet' },
      { label: 'Awaiting review', value: awaiting, sub: awaiting ? 'gates need a decision' : 'nothing blocked' },
      { label: 'Artifacts', value: artifacts, sub: 'generated across all runs' },
      { label: 'AI Brain', value: health.brain.documents, sub: `duplicate threshold ${health.brain.threshold}` },
    ];
    $('#statCards').innerHTML = cards.map(c => `
      <div class="card stat">
        <div class="stat-label">${esc(c.label)}</div>
        <div class="stat-value">${esc(c.value)}</div>
        <div class="stat-sub">${esc(c.sub)}</div>
      </div>`).join('');

    const badge = $('#gateBadge');
    badge.hidden = awaiting === 0;
    badge.textContent = awaiting;

    const tbody = $('#runsTable tbody');
    if (!runs.length) {
      tbody.innerHTML = `<tr><td colspan="6"><div class="empty">
        <div class="big">No runs yet</div>Create one from <strong>New run</strong>.</div></td></tr>`;
      return;
    }
    tbody.innerHTML = runs.map(r => {
      const blocked = r.awaiting && r.awaiting.length;
      const badgeHtml = r.current_phase === 'done'
        ? '<span class="badge badge-ok">complete</span>'
        : blocked ? '<span class="badge badge-warn">awaiting review</span>'
                  : '<span class="badge badge-info">in progress</span>';
      return `<tr class="clickable" data-run="${esc(r.run_id)}">
        <td><strong>${esc(r.title)}</strong><br><span class="faint mono small">${esc(r.run_id)}</span></td>
        <td><span class="badge">${esc(r.business_process)}</span></td>
        <td class="small">${esc(r.current_phase)}</td>
        <td class="small mono">${esc(r.artifacts)}</td>
        <td>${badgeHtml}</td>
        <td class="small faint">${esc(when(r.updated))}</td>
      </tr>`;
    }).join('');
    $$('#runsTable tbody tr.clickable').forEach(tr =>
      tr.onclick = () => { setRun(tr.dataset.run); go('pipeline'); });
  } catch (e) { fail(e); }
}

function setRun(id) {
  S.runId = id;
  if (id) localStorage.setItem('mx.runId', id); else localStorage.removeItem('mx.runId');
}

// --------------------------------------------------------------- new run
async function loadProcesses() {
  try {
    const meta = await api('/api/runs/meta/processes');
    S.processes = meta.processes;
    $('#nrProcess').innerHTML = meta.processes.map(p =>
      `<option value="${esc(p.name)}" ${p.name === meta.default ? 'selected' : ''}>${esc(p.label)} (${esc(p.name)})</option>`
    ).join('');
    $('#nrFormats').textContent = 'Supported: ' + meta.supported_files.join('  ');
  } catch (e) { fail(e); }
}

const SAMPLES = {
  uc1: {
    title: 'Add CU Comment field and propagate to Work Order',
    text: `# Use Case 1 - Add CU Comment field

- The system shall add a new CUCOMMENT attribute to the CUJP object through Database Configuration, type ALN, length 100, not mandatory.
- The CU Comment field must be visible on the CU Header application in Application Designer, on the main tab, labelled "CU Comment".
- On Work Order generation from a CU record, an automation script shall copy CUJP.CUCOMMENT into WORKORDER.DESCRIPTION.
- Empty CUCOMMENT must not overwrite an existing Work Order description.
- The field shall be granted to the security groups that already have access to the CU Header application.`,
  },
  uc2: {
    title: 'CU outbound interface to AUD external system',
    text: `# Use Case 2 - CU outbound to AUD

- The system shall trigger a CU outbound message to the AUD external system when the CUE Status changes to ACCEPTED.
- A Publish Channel named CUACCEPTED_PC shall be defined against the CUJP object structure for the outbound interface.
- An External System AUD_EXTSYS shall be configured with an HTTP endpoint and credentials held in the End Point definition.
- The outbound message shall carry the CU record key fields: CUJPNUM, STATUS, CUCOMMENT and SITEID.
- No message shall be generated for any status change other than ACCEPTED.
- If the endpoint is unreachable the message must be retained in the error queue for reprocessing, with no data loss.`,
  },
};

function renderFileList() {
  $('#nrFileList').innerHTML = S.files.map((f, i) => `
    <div class="fileitem">
      <span class="ext badge">${esc((f.name.split('.').pop() || '').toUpperCase())}</span>
      <span class="name">${esc(f.name)}</span>
      <span class="size">${bytes(f.size)}</span>
      <button class="btn btn-ghost btn-sm" data-rm="${i}">Remove</button>
    </div>`).join('');
  $$('#nrFileList [data-rm]').forEach(b =>
    b.onclick = () => { S.files.splice(+b.dataset.rm, 1); renderFileList(); });
}

function wireNewRun() {
  const drop = $('#nrDrop'), input = $('#nrFiles');
  drop.onclick = () => input.click();
  input.onchange = () => { S.files.push(...Array.from(input.files)); input.value = ''; renderFileList(); };
  ['dragenter', 'dragover'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e => { S.files.push(...Array.from(e.dataTransfer.files)); renderFileList(); });

  $$('[data-sample]').forEach(b => b.onclick = () => {
    const s = SAMPLES[b.dataset.sample];
    $('#nrTitle').value = s.title;
    $('#nrText').value = s.text;
    toast('Sample loaded. Press "Create run".', 'info');
  });

  $('#nrStart').onclick = async () => {
    const title = $('#nrTitle').value.trim();
    if (!title) { toast('Give the run a title.', 'error'); return; }
    if (!S.files.length && !$('#nrText').value.trim()) {
      toast('Attach a file or paste some requirement text.', 'error'); return;
    }
    const btn = $('#nrStart');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Routing…';
    try {
      const fd = new FormData();
      fd.append('title', title);
      fd.append('business_process', $('#nrProcess').value);
      fd.append('text', $('#nrText').value);
      S.files.forEach(f => fd.append('files', f));

      const status = await api('/api/runs', { method: 'POST', body: fd });
      setRun(status.run_id);
      S.status = status;
      S.files = []; renderFileList();
      $('#nrTitle').value = ''; $('#nrText').value = '';
      toast(`${status.change_items.length} change item(s) identified.`, 'ok', 'Run created');

      if ($('#nrAuto').checked) {
        go('pipeline'); renderPipeline();
        await advance(true, true);
      } else {
        go('pipeline');
      }
    } catch (e) { fail(e); }
    finally {
      btn.disabled = false;
      btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l14 9-14 9V3z"/></svg> Create run';
    }
  };
}

// -------------------------------------------------------------- pipeline
async function loadPipeline() {
  if (!S.runId) { renderPipeline(); return; }
  try {
    S.status = await api(`/api/runs/${encodeURIComponent(S.runId)}`);
    renderPipeline();
  } catch (e) {
    setRun(null); S.status = null; renderPipeline(); fail(e);
  }
}

const PHASE_ICON = { fdd: '1', tdd: '2', build_config: '3A', build_integration: '3B', test: '4', deploy: '5' };

function renderPipeline() {
  const has = !!(S.runId && S.status);
  $('#pipelineEmpty').hidden = has;
  $('#pipelineBody').hidden = !has;
  if (!has) return;

  const s = S.status;
  $('#pageCrumb').textContent = s.title;
  $('#plTitle').textContent = s.title;
  $('#plMeta').textContent = `${s.run_id} · ${s.business_process} · updated ${when(s.updated)}`;

  const done = s.phases.filter(p => p.status === 'approved').length;
  const active = s.phases.filter(p => p.status !== 'skipped').length;
  $('#plStats').innerHTML = [
    { l: 'Progress', v: `${done}/${active}`, s: 'gates approved' },
    { l: 'Change items', v: s.change_items.length, s: `${s.requirements.length} requirement(s)` },
    { l: 'Artifacts', v: s.total_artifacts, s: 'produced' },
    { l: 'Flags', v: s.total_flags, s: 'awaiting review' },
  ].map(c => `<div class="card stat"><div class="stat-label">${c.l}</div>
      <div class="stat-value">${esc(c.v)}</div><div class="stat-sub">${esc(c.s)}</div></div>`).join('');

  $('#plAdvance').disabled = !s.next_phase || S.busy;
  $('#plRunAll').disabled = !s.next_phase || S.busy;
  $('#plAdvance').textContent = s.next_phase ? 'Run next phase' : (s.finished ? 'Run complete' : 'Blocked at gate');

  renderRail(s);
  renderItems(s);
  renderFlags(s);
}

function renderRail(s) {
  $('#ptab-rail').innerHTML = s.phases.map(p => {
    const cls = p.status === 'approved' ? 'done'
      : p.status === 'awaiting_review' || p.status === 'revision_requested' ? 'active'
      : p.status === 'skipped' ? 'skipped'
      : (p.error ? 'failed' : '');

    const badge = {
      approved: '<span class="badge badge-ok">approved</span>',
      awaiting_review: '<span class="badge badge-warn">awaiting review</span>',
      revision_requested: '<span class="badge badge-warn">revision requested</span>',
      skipped: '<span class="badge">not applicable</span>',
      not_ready: '<span class="badge">pending</span>',
    }[p.status] || '';

    let panel = '';
    if (p.artifacts.length) {
      panel += `<div class="rail-panel"><div class="rail-panel-head">${p.artifacts.length} artifact(s)</div>
        ${p.artifacts.map(a => `
          <div class="artifact-row">
            <span class="ext">${esc(a.kind)}</span>
            <span class="aname">${esc(a.name)}<div class="adesc">${esc(a.description || '')}</div></span>
            <span class="faint small mono">${bytes(a.bytes)}</span>
            <button class="btn btn-sm" data-view-art="${esc(a.path)}" data-name="${esc(a.name)}">View</button>
            <a class="btn btn-sm" href="/api/runs/${encodeURIComponent(s.run_id)}/artifact?path=${encodeURIComponent(a.path)}&download=true">Download</a>
          </div>`).join('')}
      </div>`;
    }

    if (p.duplicate && p.duplicate.found && p.duplicate.best) {
      const d = p.duplicate;
      panel += `<div class="dup-box">
        <strong>Prior art found in the AI Brain</strong> — cosine ${d.similarity.toFixed(3)} ≥ threshold ${d.threshold}.<br>
        <span class="muted">${esc(d.best.title)} (${esc(d.best.doc_type)} v${d.best.version})</span><br>
        <span class="small faint">Choose <em>Update</em> to version that document, or <em>New</em> to create a separate one.</span>
      </div>`;
    }

    if (p.error) {
      panel += `<div class="gate-box" style="border-color:var(--danger);background:var(--danger-soft)">
        <div class="gate-title">Phase failed — ${esc(p.error.code || 'error')}</div>
        <div class="small" style="margin-top:5px">${esc(p.error.message || '')}</div>
        <div class="small muted" style="margin-top:5px">${esc(p.error.remedy || '')}</div>
      </div>`;
    }

    if (p.status === 'awaiting_review') {
      const dupChoice = (p.duplicate && p.duplicate.found)
        ? `<select data-dup="${esc(p.phase)}" style="max-width:150px">
             <option value="new">Create new</option><option value="update">Update existing</option></select>` : '';
      panel += `<div class="gate-box">
        <div class="gate-title">User gate — ${esc(p.role)}</div>
        <div class="small" style="margin-top:4px">Nothing downstream runs until this is approved.</div>
        <div class="gate-actions">
          <input type="text" placeholder="Your name" data-by="${esc(p.phase)}">
          <input type="text" placeholder="Comment (required to request a revision)" data-cm="${esc(p.phase)}" style="flex:1;min-width:180px;max-width:none">
          ${dupChoice}
          <button class="btn btn-ok btn-sm" data-gate="approve" data-phase="${esc(p.phase)}">Approve</button>
          <button class="btn btn-warn btn-sm" data-gate="revise" data-phase="${esc(p.phase)}">Request revision</button>
          <button class="btn btn-ghost btn-sm" data-gate="skip" data-phase="${esc(p.phase)}">Skip</button>
        </div>
      </div>`;
    } else if (p.status === 'approved' && p.decided_by) {
      panel += `<div class="gate-box approved"><div class="gate-title">Approved by ${esc(p.decided_by)}</div>
        <div class="small muted">${esc(p.decided_at || '')}${p.comment ? ' — ' + esc(p.comment) : ''}</div></div>`;
    } else if (p.status === 'revision_requested') {
      panel += `<div class="gate-box"><div class="gate-title">Revision requested by ${esc(p.decided_by || '—')}</div>
        <div class="small" style="margin-top:4px">${esc(p.comment || '')}</div>
        <div class="small muted" style="margin-top:4px">Press "Run next phase" to regenerate.</div></div>`;
    }

    return `<div class="rail-step ${cls}">
      <div><div class="rail-node">${PHASE_ICON[p.phase] || '·'}</div><div class="rail-line"></div></div>
      <div class="rail-body">
        <div class="rail-head"><span class="rail-title">${esc(p.label)}</span>${badge}
          ${p.flags.length ? `<span class="badge badge-warn">${p.flags.length} flag(s)</span>` : ''}
          <span class="rail-role">${esc(p.role)}</span></div>
        ${p.summary ? `<div class="rail-summary">${esc(p.summary)}</div>` : ''}
        ${panel}
      </div>
    </div>`;
  }).join('');

  $$('[data-view-art]').forEach(b => b.onclick = () => showArtifact(b.dataset.viewArt, b.dataset.name));
  $$('[data-gate]').forEach(b => b.onclick = () => decideGate(b.dataset.phase, b.dataset.gate));
}

function renderItems(s) {
  const el = $('#ptab-items');
  if (!s.change_items.length) { el.innerHTML = '<div class="empty">No change items.</div>'; return; }
  el.innerHTML = `<div class="card"><div class="table-wrap"><table class="tbl">
    <thead><tr><th>ID</th><th>Change</th><th>Type</th><th>Owner</th><th>Object</th><th>Attribute</th>
      <th>Effort</th><th>Skill</th><th>Risk</th></tr></thead>
    <tbody>${s.change_items.map(i => `<tr>
      <td class="mono small">${esc(i.id)}</td>
      <td>${esc(i.title)}</td>
      <td><span class="badge">${esc(i.change_type)}</span></td>
      <td class="small">Agent ${esc(i.build_owner)}</td>
      <td class="mono small">${esc(i.maximo_object || '—')}</td>
      <td class="mono small">${esc(i.maximo_attribute || '—')}</td>
      <td class="mono small">${i.effort_hours ? i.effort_hours + 'h' : '—'}</td>
      <td class="small">${esc(i.skill_level)}</td>
      <td><span class="badge ${i.risk === 'high' ? 'badge-danger' : i.risk === 'medium' ? 'badge-warn' : 'badge-ok'}">${esc(i.risk)}</span></td>
    </tr>`).join('')}</tbody></table></div></div>`;
}

function renderFlags(s) {
  const el = $('#ptab-flags');
  const flags = s.phases.flatMap(p => p.flags.map(f => ({ ...f, phase: p.label })));
  if (!flags.length) {
    el.innerHTML = '<div class="empty"><div class="big">No flags</div>Nothing fell below the confidence threshold.</div>';
    return;
  }
  flags.sort((a, b) => a.confidence - b.confidence);
  el.innerHTML = `<div class="card"><div class="table-wrap"><table class="tbl">
    <thead><tr><th>Phase</th><th>Section</th><th>Item</th><th>Confidence</th><th>Severity</th><th>Reason</th><th>Suggestion</th></tr></thead>
    <tbody>${flags.map(f => {
      const cls = f.confidence < 0.4 ? 'low' : f.confidence < 0.7 ? 'mid' : 'high';
      return `<tr class="flagrow">
        <td class="small">${esc(f.phase)}</td>
        <td class="small">${esc(f.section)}</td>
        <td class="small">${esc(f.item)}</td>
        <td><span class="conf ${cls}">${f.confidence.toFixed(2)}</span></td>
        <td><span class="badge ${f.severity === 'block' ? 'badge-danger' : 'badge-warn'}">${esc(f.severity)}</span></td>
        <td class="small">${esc(f.reason)}</td>
        <td class="small muted">${esc(f.suggestion || '—')}</td>
      </tr>`;
    }).join('')}</tbody></table></div></div>`;
}

async function advance(all = false, auto = false) {
  if (!S.runId || S.busy) return;
  S.busy = true;
  const btn = all ? $('#plRunAll') : $('#plAdvance');
  const original = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Running…';
  try {
    const res = await api(`/api/runs/${encodeURIComponent(S.runId)}/advance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ all, auto }),
    });
    S.status = res.status;
    const ran = res.steps.filter(s => s.ran);
    const failed = ran.find(s => s.ok === false);
    if (failed) toast(failed.summary || 'Phase failed.', 'error', failed.phase_label);
    else if (ran.length) toast(ran[ran.length - 1].message || 'Phase complete.', 'ok', ran[ran.length - 1].phase_label);
    else toast(res.steps[0] ? res.steps[0].message : 'Nothing to run.', 'info');
    renderPipeline();
  } catch (e) { fail(e); }
  finally { S.busy = false; btn.disabled = false; btn.textContent = original; loadHealth(); }
}

async function decideGate(phase, decision) {
  const by = ($(`[data-by="${phase}"]`) || {}).value || '';
  const comment = ($(`[data-cm="${phase}"]`) || {}).value || '';
  const dupEl = $(`[data-dup="${phase}"]`);
  if (decision === 'revise' && !comment.trim()) {
    toast('Say what needs to change before requesting a revision.', 'error'); return;
  }
  try {
    S.status = await api(`/api/runs/${encodeURIComponent(S.runId)}/gate/${phase}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, by, comment, duplicate_action: dupEl ? dupEl.value : '' }),
    });
    toast(`Gate ${decision === 'approve' ? 'approved' : decision === 'skip' ? 'skipped' : 'sent back'}.`, 'ok');
    renderPipeline();
    loadHealth();
  } catch (e) { fail(e); }
}

async function showArtifact(path, name) {
  openModal(name, '<div class="empty"><span class="spinner"></span> Loading…</div>',
    `<a class="btn" href="/api/runs/${encodeURIComponent(S.runId)}/artifact?path=${encodeURIComponent(path)}&download=true">Download</a>`);
  try {
    const p = await api(`/api/runs/${encodeURIComponent(S.runId)}/preview?path=${encodeURIComponent(path)}`);
    let html;
    if (p.kind === 'text') {
      html = /\.(md|markdown)$/i.test(name)
        ? `<div class="doc-view">${markdown(p.content)}</div>`
        : `<div class="logbox">${esc(p.content)}</div>`;
    } else if (p.kind === 'html') {
      html = `<div class="doc-view">${p.content}</div>`;
    } else if (p.kind === 'table') {
      html = (p.content.sheets || []).map(sh => `
        <div class="section-title">${esc(sh.name)}</div>
        <div class="table-wrap"><table class="tbl">
          <thead><tr>${(sh.rows[0] || []).map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
          <tbody>${sh.rows.slice(1).map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>
        </table></div>
        ${sh.truncated ? '<div class="small faint">Preview truncated — download for the full sheet.</div>' : ''}`).join('');
    } else {
      html = '<div class="empty">Binary file — use Download.</div>';
    }
    $('#modalBody').innerHTML = html;
  } catch (e) { $('#modalBody').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

// ----------------------------------------------------------------- brain
async function loadBrain() {
  try {
    const [status, docs] = await Promise.all([api('/api/brain/status'), api('/api/brain/documents')]);
    $('#brStats').innerHTML = [
      { l: 'Documents', v: status.documents, s: Object.entries(status.by_type).map(([k, v]) => `${k}=${v}`).join(', ') || '—' },
      { l: 'Index', v: status.index_chunks, s: `${status.index_backend} · ${status.embed_backend}` },
      { l: 'Duplicate threshold', v: status.duplicate_threshold, s: 'cosine similarity' },
    ].map(c => `<div class="card stat"><div class="stat-label">${c.l}</div>
        <div class="stat-value">${esc(c.v)}</div><div class="stat-sub">${esc(c.s)}</div></div>`).join('');

    const tbody = $('#brDocs tbody');
    tbody.innerHTML = docs.documents.length ? docs.documents.map(d => `
      <tr class="clickable" data-doc="${esc(d.path)}">
        <td><strong>${esc(d.title)}</strong></td>
        <td><span class="badge">${esc(d.doc_type)}</span></td>
        <td class="small">${esc(d.business_process)}</td>
        <td class="mono small">v${d.version}</td>
        <td class="small">${esc(d.agent || '—')}</td>
        <td class="small faint">${esc(when(d.updated))}</td>
      </tr>`).join('')
      : `<tr><td colspan="6"><div class="empty"><div class="big">AI Brain is empty</div>
         Approved artifacts are written here automatically.</div></td></tr>`;
    $$('#brDocs tbody tr.clickable').forEach(tr => tr.onclick = () => showBrainDoc(tr.dataset.doc));
  } catch (e) { fail(e); }
}

async function brainSearch() {
  const q = $('#brSearch').value.trim();
  if (!q) return;
  const box = $('#brResults');
  box.hidden = false;
  box.innerHTML = '<div class="empty"><span class="spinner"></span> Searching…</div>';
  try {
    const params = new URLSearchParams({ q, top: '8' });
    if ($('#brType').value) params.set('doc_type', $('#brType').value);
    const r = await api('/api/brain/search?' + params);
    if (!r.hits.length) {
      box.innerHTML = `<div class="empty"><div class="big">No matches</div>${esc(r.note || '')}</div>`;
      return;
    }
    box.innerHTML = `<div class="card-head"><h3>${r.hits.length} result(s)</h3>
        <span class="spacer"></span><span class="small faint">tier: ${esc(r.stopped_at)}</span></div>`
      + r.hits.map(h => {
        const over = h.semantic >= (S.health ? S.health.brain.threshold : 0.85);
        return `<div class="hit">
          <div class="hit-head">
            <span class="hit-title" data-doc="${esc(h.path)}">${esc(h.title)}</span>
            <span class="badge">${esc(h.doc_type)}</span>
            <span class="badge">v${h.version}</span>
            ${over ? '<span class="badge badge-warn">duplicate</span>' : ''}
            <span class="spacer" style="margin-left:auto"></span>
            <div class="score-bar ${over ? 'over' : ''}"><i style="width:${Math.round(h.semantic * 100)}%"></i></div>
            <span class="hit-meta">cos ${h.semantic.toFixed(3)}</span>
          </div>
          <div class="hit-excerpt">${esc(h.excerpt)}</div>
        </div>`;
      }).join('');
    $$('#brResults [data-doc]').forEach(el => el.onclick = () => showBrainDoc(el.dataset.doc));
  } catch (e) { fail(e); box.hidden = true; }
}

async function showBrainDoc(path) {
  openModal('Loading…', '<div class="empty"><span class="spinner"></span></div>', '');
  try {
    const d = await api('/api/brain/document?path=' + encodeURIComponent(path));
    $('#modalTitle').textContent = `${d.title}  ·  ${d.doc_type} v${d.version}`;
    $('#modalBody').innerHTML = `<div class="doc-view">${markdown(d.body)}</div>`;
    $('#modalFoot').innerHTML = `<span class="small faint" style="margin-right:auto">
      ${esc(d.business_process)} · ${esc(d.agent || '')} · updated ${esc(d.updated)}</span>`;
  } catch (e) { $('#modalBody').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

// ---------------------------------------------------------------- maximo
async function loadMaximo() {
  try {
    const health = await api('/api/system/health');
    $('#mxConn').innerHTML = `<dl class="kvlist">
      <dt>Configured</dt><dd>${health.maximo.configured ? 'yes' : 'no'}</dd>
      <dt>Route</dt><dd>/${esc(health.maximo.route)}/</dd>
      <dt>Base URL</dt><dd>${esc(health.maximo.base_url || '(not set)')}</dd>
      <dt>Catalogue</dt><dd>${health.maximo.catalogue} object structures</dd>
    </dl>
    <div class="small muted" style="margin-top:12px">
      ${health.maximo.configured
        ? 'Validation prefers the live environment and falls back to the bundled catalogue.'
        : 'No live environment configured — every name is validated against the bundled catalogue of real MAS object structures.'}
    </div>`;
  } catch (e) { fail(e); }
}

async function maximoValidate() {
  const name = $('#mxName').value.trim();
  if (!name) return;
  const box = $('#mxResult');
  box.innerHTML = '<div class="empty"><span class="spinner"></span></div>';
  try {
    const r = await api('/api/system/maximo/validate?name=' + encodeURIComponent(name));
    let html = r.results.map(x => `
      <div style="display:flex;gap:9px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--border)">
        <span class="badge ${x.exists ? 'badge-ok' : 'badge-danger'}">${x.exists ? 'confirmed' : 'not found'}</span>
        <div style="flex:1">
          <div class="mono"><strong>${esc(x.name)}</strong> <span class="faint">(${esc(x.kind)})</span></div>
          <div class="small muted">${esc(x.detail)}</div>
          ${x.suggestions.length ? `<div class="chips" style="margin-top:6px">${x.suggestions.map(s => `<span class="chip">${esc(s)}</span>`).join('')}</div>` : ''}
        </div>
        <span class="badge">${esc(x.source)}</span>
      </div>`).join('');

    const os = r.detail.object_structure;
    if (os) {
      html += `<div class="section-title">Object structure ${esc(os.os_name)}</div>
        <dl class="kvlist">
          <dt>Business object</dt><dd>${esc(os.mbo)}</dd>
          <dt>Primary keys</dt><dd>${esc(os.primary_keys.join(', '))}</dd>
          <dt>Unique id</dt><dd>${esc(os.unique_id)}</dd>
          <dt>Fields</dt><dd>${os.attribute_count}</dd>
        </dl>
        <div class="section-title">Sample attributes</div>
        <div class="chips">${os.sample_attributes.map(a => `<span class="chip">${esc(a)}</span>`).join('')}</div>`;
    }
    const attr = r.detail.attribute;
    if (attr) {
      html += `<div class="section-title">Attribute specification</div>
        <dl class="kvlist">
          <dt>Title</dt><dd>${esc(attr.title)}</dd>
          <dt>Type</dt><dd>${esc(attr.type)}</dd>
          <dt>Length</dt><dd>${esc(attr.length ?? '—')}</dd>
          <dt>Persistent</dt><dd>${attr.persistent ? 'yes' : 'no'}</dd>
        </dl>
        ${attr.remarks ? `<div class="small muted" style="margin-top:8px">${esc(attr.remarks)}</div>` : ''}`;
    }
    box.innerHTML = html;
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

async function maximoSearch() {
  const q = $('#mxSearch').value.trim();
  if (!q) return;
  try {
    const r = await api('/api/system/maximo/search?q=' + encodeURIComponent(q) + '&top=25');
    $('#mxTable tbody').innerHTML = r.hits.length ? r.hits.map(h => `<tr>
      <td class="mono"><strong>${esc(h.os_name)}</strong></td>
      <td class="mono small">${esc(h.mbo)}</td>
      <td class="mono small">${h.attributes}</td>
      <td class="mono small">${esc(h.primary_keys.join(', '))}</td>
      <td class="small">${esc(h.use_with || '—')}</td>
    </tr>`).join('') : `<tr><td colspan="5"><div class="empty">No object structure matches "${esc(q)}".</div></td></tr>`;
  } catch (e) { fail(e); }
}

// -------------------------------------------------------------- settings
async function loadSettings() {
  try {
    const cfg = await api('/api/system/config');
    const card = (title, rows) => `<div class="card"><div class="card-head"><h3>${esc(title)}</h3></div>
      <div class="card-pad"><dl class="kvlist">${rows.map(([k, v]) =>
        `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl></div></div>`;

    $('#setCards').innerHTML =
      card('Suite', [
        ['Project', cfg.project_name], ['Version', cfg.version],
        ['Maximo', cfg.maximo_version], ['Default process', cfg.default_process],
        ['Confidence threshold', cfg.confidence_threshold],
        ['Processes', cfg.processes.join(', ')],
      ])
      + card('Model', [
        ['Provider', cfg.llm.provider], ['Model', cfg.llm.model || '—'],
        ['Endpoint', cfg.llm.base_url || '—'], ['API key set', cfg.llm.api_key_set ? 'yes' : 'no'],
      ])
      + card('Maximo', [
        ['Route', '/' + cfg.maximo.route + '/'], ['Base URL', cfg.maximo.base_url || '—'],
        ['Verify TLS', cfg.maximo.verify_tls], ['API key set', cfg.maximo.api_key_set ? 'yes' : 'no'],
        ['MAXAUTH set', cfg.maximo.maxauth_set ? 'yes' : 'no'],
        ['Schema catalogue', cfg.maximo.schema_catalogue],
      ])
      + card('AI Brain', [
        ['Store', cfg.brain.store_dir], ['Embedding model', cfg.brain.embed_model],
        ['Duplicate threshold', cfg.brain.duplicate_threshold],
      ])
      + card('Templates', Object.entries(cfg.templates))
      + card('Optional packages', Object.entries(cfg.packages).map(([k, v]) => [k, v ? 'installed' : 'absent']))
      + `<div class="card"><div class="card-head"><h3>Skills</h3></div><div class="card-pad">
          <div class="chips">${cfg.skills.map(s => `<span class="chip">${esc(s)}</span>`).join('')}</div></div></div>`
      + `<div class="card"><div class="card-head"><h3>Actions</h3></div><div class="card-pad">
          <p class="small muted" style="margin-top:0">Re-read <code>config/suite.yaml</code> and <code>.env</code>
             without restarting the server.</p>
          <button class="btn" id="setReload">Reload configuration</button></div></div>`;

    $('#setReload').onclick = async () => {
      try { await api('/api/system/reload', { method: 'POST' }); toast('Configuration reloaded.', 'ok'); loadHealth(); loadSettings(); }
      catch (e) { fail(e); }
    };
  } catch (e) { fail(e); }
}

// ----------------------------------------------------------------- modal
function openModal(title, body, foot) {
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = body;
  $('#modalFoot').innerHTML = foot || '';
  $('#modalBack').classList.add('open');
}
function closeModal() { $('#modalBack').classList.remove('open'); }

// ------------------------------------------------------------------ boot
function wire() {
  $$('.nav-item').forEach(n => n.onclick = () => go(n.dataset.view));

  $('#themeBtn').onclick = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('mx.theme', next);
  };
  $('#refreshBtn').onclick = () => { loadHealth(); go(S.view); };

  $('#plAdvance').onclick = () => advance(false, false);
  $('#plRunAll').onclick = () => advance(true, false);
  $('#plLog').onclick = async () => {
    openModal('Run log', '<div class="empty"><span class="spinner"></span></div>', '');
    try {
      const r = await api(`/api/runs/${encodeURIComponent(S.runId)}/log?lines=300`);
      $('#modalBody').innerHTML = `<div class="logbox">${esc(r.lines.join('\n')) || 'No log yet.'}</div>`;
    } catch (e) { $('#modalBody').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };

  $$('[data-ptab]').forEach(t => t.onclick = () => {
    S.ptab = t.dataset.ptab;
    $$('[data-ptab]').forEach(x => x.classList.toggle('active', x === t));
    ['rail', 'items', 'flags'].forEach(k => $('#ptab-' + k).hidden = (k !== S.ptab));
  });

  $('#brGo').onclick = brainSearch;
  $('#brSearch').onkeydown = e => { if (e.key === 'Enter') brainSearch(); };
  $('#brReindex').onclick = async () => {
    try {
      const r = await api('/api/brain/reindex', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rebuild: true }),
      });
      toast(`Indexed ${r.documents} document(s) into ${r.chunks} chunk(s).`, 'ok', 'AI Brain');
      loadBrain();
    } catch (e) { fail(e); }
  };

  $('#mxGo').onclick = maximoValidate;
  $('#mxName').onkeydown = e => { if (e.key === 'Enter') maximoValidate(); };
  $('#mxSearchGo').onclick = maximoSearch;
  $('#mxSearch').onkeydown = e => { if (e.key === 'Enter') maximoSearch(); };
  $('#mxPing').onclick = async () => {
    try {
      const r = await api('/api/system/maximo/ping');
      toast(r.detail || (r.reachable ? 'Connected.' : 'Not reachable.'), r.reachable ? 'ok' : 'error', 'Maximo');
      loadMaximo();
    } catch (e) { fail(e); }
  };

  $('#modalClose').onclick = closeModal;
  $('#modalBack').onclick = e => { if (e.target === $('#modalBack')) closeModal(); };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  wireNewRun();
}

(function boot() {
  document.documentElement.dataset.theme = localStorage.getItem('mx.theme') || 'light';
  wire();
  loadHealth();
  loadProcesses();

  const VIEWS = ['dashboard', 'new-run', 'pipeline', 'brain', 'maximo', 'settings'];
  const wanted = readHash();
  go(VIEWS.includes(wanted) ? wanted : 'dashboard');

  window.addEventListener('hashchange', () => {
    const v = readHash();
    if (VIEWS.includes(v) && v !== S.view) go(v);
  });

  setInterval(() => { if (!S.busy && S.view === 'dashboard') loadDashboard(); }, 20000);
})();
