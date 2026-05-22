import { api, fmt } from '/web/app.js';

const usd = v => v == null ? '—' : '$' + Number(v).toFixed(2);

function fmtElapsed(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(s).padStart(2, '0')}s`;
}
function agoText(sec) {
  const m = Math.round(sec / 60);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ${m % 60}m ago`;
}

export default async function render(root) {
  const d = await api('/api/live');
  const a = d.active, t = d.today;

  const activeCard = !a ? `
    <div class="card"><h3>Current session</h3>
      <p class="muted">No sessions yet — run Claude Code and it'll show up here.</p></div>`
    : `
    <div class="card">
      <div class="flex" style="gap:10px">
        <span class="live-dot ${a.is_active ? '' : 'idle'}"></span>
        <strong>${a.is_active ? 'ACTIVE' : 'IDLE'}</strong>
        <span class="muted">${a.is_active ? '' : 'last active ' + agoText(a.age_seconds)}</span>
        <div class="spacer"></div>
        <span class="muted blur-sensitive">${fmt.htmlSafe(a.project_name || a.project_slug)}
          · <span class="badge ${fmt.modelClass(a.model)}">${fmt.modelShort(a.model) || '—'}</span></span>
      </div>
      <div class="row cols-4" style="margin-top:14px">
        <div class="card kpi cost"><div class="label">Cost</div><div class="value">${usd(a.cost_usd)}</div></div>
        <div class="card kpi"><div class="label">Elapsed</div><div class="value" id="elapsed">${fmtElapsed(a.elapsed_seconds)}</div></div>
        <div class="card kpi"><div class="label">Turns</div><div class="value">${fmt.int(a.turns)}</div></div>
        <div class="card kpi"><div class="label">Burn rate</div><div class="value">${a.burn_usd_per_hr == null ? '—' : usd(a.burn_usd_per_hr) + '/hr'}</div></div>
      </div>
      <p class="muted" style="margin:10px 0 0;font-size:12px">${fmt.compact(a.tokens)} billable tokens this session.</p>
    </div>`;

  root.innerHTML = `
    <div class="flex" style="margin-bottom:14px">
      <h2 style="margin:0;font-size:16px">Live</h2>
      <div class="spacer"></div>
      <span class="muted" style="font-size:12px">updates every ~30s</span>
    </div>
    ${activeCard}
    <div class="card" style="margin-top:16px">
      <h3>Today so far</h3>
      <div class="row cols-4" style="margin-top:6px">
        <div class="card kpi cost"><div class="label">Cost</div><div class="value">${usd(t.cost_usd)}</div></div>
        <div class="card kpi"><div class="label">Tokens</div><div class="value">${fmt.compact(t.tokens)}</div></div>
        <div class="card kpi"><div class="label">Sessions</div><div class="value">${fmt.int(t.sessions)}</div></div>
        <div class="card kpi"><div class="label">Turns</div><div class="value">${fmt.int(t.turns)}</div></div>
      </div>
    </div>`;

  // Self-cleaning ticking clock — only while the session is active (an idle session's
  // duration is frozen). Clears itself when the element leaves the DOM (navigation/re-render).
  if (a && a.is_active) {
    const startMs = Date.parse(a.started);
    const el = document.getElementById('elapsed');
    const timer = setInterval(() => {
      if (!el || !document.body.contains(el)) { clearInterval(timer); return; }
      el.textContent = fmtElapsed((Date.now() - startMs) / 1000);
    }, 1000);
  }
}
