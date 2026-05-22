import { api, fmt, state } from '/web/app.js';
import { lineChart } from '/web/charts.js';

const RANGES = [
  { key: '7d', label: '7d', days: 7 },
  { key: '30d', label: '30d', days: 30 },
  { key: '90d', label: '90d', days: 90 },
  { key: 'all', label: 'All', days: null },
];
function readRange() {
  const q = (location.hash.split('?')[1] || '');
  const m = /(?:^|&)range=([^&]+)/.exec(q);
  const k = m && decodeURIComponent(m[1]);
  return RANGES.find(r => r.key === k) || RANGES[1];
}
function writeRange(key) {
  const base = (location.hash.replace(/^#/, '').split('?')[0]) || '/trends';
  location.hash = '#' + base + '?range=' + encodeURIComponent(key);
}
function sinceIso(range) {
  return range.days ? new Date(Date.now() - range.days * 86400 * 1000).toISOString() : null;
}
function withSince(url, since) {
  return since ? url + (url.includes('?') ? '&' : '?') + 'since=' + encodeURIComponent(since) : url;
}

const usd = v => v == null ? '—' : '$' + Number(v).toFixed(2);

const TYPE_COLORS = { input: '#4A9EFF', output: '#7C5CFF', cache_read: '#3FB68B', cache_create: '#E8A23B' };
const TYPE_LABELS = { input: 'input', output: 'output', cache_read: 'cache read', cache_create: 'cache create' };

function barRow(label, cost, pct, color, sensitive) {
  return `<div class="bar-row">
    <span class="bar-label${sensitive ? ' blur-sensitive' : ''}">${label}</span>
    <span class="bar-track"><span class="bar-fill" style="width:${(pct * 100).toFixed(1)}%;background:${color || 'var(--accent)'}"></span></span>
    <span class="bar-val">${usd(cost)} <span class="muted">${(pct * 100).toFixed(0)}%</span></span>
  </div>`;
}

function deltaChip(d) {
  if (d == null) return '';
  const up = d >= 0;
  return `<span class="delta ${up ? 'up' : 'down'}">${up ? '▲' : '▼'} ${Math.abs(d * 100).toFixed(0)}%</span>`;
}
function kpi(label, value, extra) {
  return `<div class="card kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${extra || ''}</div></div>`;
}
function planNote() {
  if (!state.pricing || state.plan === 'api') return '';
  const p = state.pricing.plans[state.plan];
  return (p && p.monthly) ? ` You pay $${p.monthly}/mo on ${fmt.htmlSafe(p.label)}.` : '';
}

export default async function render(root) {
  const range = readRange();
  const [t, daily, drivers] = await Promise.all([
    api('/api/trends'),
    api(withSince('/api/cost-daily', sinceIso(range))),
    api(withSince('/api/cost-drivers', sinceIso(range))),
  ]);
  const b = t.budget, p = t.periods;
  const pct = b.pct == null ? 0 : Math.min(b.pct, 1);
  const fillClass = b.status === 'over' ? 'over' : b.status === 'warn' ? 'warn' : '';
  const spentLine = b.monthly_usd == null
    ? `<b>${usd(b.spent_this_month_usd)}</b> spent this month — no budget set`
    : `<b>${usd(b.spent_this_month_usd)}</b> of <b>${usd(b.monthly_usd)}</b> (${(b.pct * 100).toFixed(0)}%)`;

  const driversCard = drivers.total_usd <= 0
    ? `<div class="card" style="margin-top:16px"><h3>Cost drivers</h3><p class="muted">No cost in this range.</p></div>`
    : `
    <div class="card" style="margin-top:16px">
      <h3>Cost drivers</h3>
      <p class="muted" style="margin:-4px 0 14px;font-size:12px">Where your ${usd(drivers.total_usd)} went in this range.</p>
      <div class="row cols-3">
        <div>
          <div class="driver-h muted">By token type</div>
          ${drivers.by_type.map(d => barRow(TYPE_LABELS[d.type] || d.type, d.cost_usd, d.pct, TYPE_COLORS[d.type])).join('')}
        </div>
        <div>
          <div class="driver-h muted">By model</div>
          ${drivers.by_model.map(d => barRow(fmt.modelShort(d.model) || d.model, d.cost_usd, d.pct, '#7C5CFF')).join('') || '<p class="muted">—</p>'}
        </div>
        <div>
          <div class="driver-h muted">By project</div>
          ${drivers.by_project.map(d => barRow(fmt.htmlSafe(d.project_name || d.project_slug), d.cost_usd, d.pct, '#3FB68B', true)).join('') || '<p class="muted">—</p>'}
        </div>
      </div>
    </div>`;

  root.innerHTML = `
    <div class="flex" style="margin-bottom:14px">
      <h2 style="margin:0;font-size:16px">Trends</h2>
      <div class="spacer"></div>
      <div class="range-tabs">${RANGES.map(r => `<button data-range="${r.key}" class="${r.key === range.key ? 'active' : ''}">${r.label}</button>`).join('')}</div>
    </div>

    <div class="card">
      <h3>Monthly budget</h3>
      <p class="muted" style="margin:-4px 0 12px;font-size:12px">API-equivalent spend this calendar month.${planNote()}</p>
      <div class="budget-bar"><div class="budget-fill ${fillClass}" style="width:${(pct * 100).toFixed(1)}%"></div></div>
      <div class="flex" style="margin-top:10px">
        <span>${spentLine}</span>
        <div class="spacer"></div>
        <input id="budget-input" type="number" min="0" step="10" placeholder="$ / mo" value="${b.monthly_usd ?? ''}" style="width:110px">
        <button class="primary" id="budget-save">Save</button>
        <span id="budget-msg" class="muted"></span>
      </div>
    </div>

    <div class="row cols-4" style="margin-top:16px">
      ${kpi('This month', usd(p.this_month.cost_usd), deltaChip(p.this_month.delta_pct) + ' <span class="muted">vs last mo</span>')}
      ${kpi('Last month', usd(p.last_month.cost_usd), '')}
      ${kpi('This week', usd(p.this_week.cost_usd), deltaChip(p.this_week.delta_pct) + ' <span class="muted">vs last wk</span>')}
      ${kpi('Last week', usd(p.last_week.cost_usd), '')}
    </div>

    <div class="card" style="margin-top:16px">
      <h3>Daily cost</h3>
      <p class="muted" style="margin:-4px 0 10px;font-size:12px">API-equivalent $ per day (local time).</p>
      <div id="ch-cost-daily" style="height:300px"></div>
    </div>
    ${driversCard}`;

  root.querySelectorAll('.range-tabs button').forEach(btn =>
    btn.addEventListener('click', () => writeRange(btn.dataset.range)));

  lineChart(document.getElementById('ch-cost-daily'), {
    x: daily.map(d => d.day),
    series: [{ name: 'cost', data: daily.map(d => d.cost_usd), color: '#3FB68B' }],
    formatter: v => '$' + Number(v).toFixed(2),
  });

  document.getElementById('budget-save').addEventListener('click', async () => {
    const val = parseFloat(document.getElementById('budget-input').value);
    const msg = document.getElementById('budget-msg');
    if (isNaN(val) || val < 0) { msg.textContent = 'enter a non-negative number'; msg.style.color = 'var(--bad)'; return; }
    await fetch('/api/budget', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ monthly_usd: val }) });
    await render(root);
  });
}
