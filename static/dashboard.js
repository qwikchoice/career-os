/* Career OS dashboard (designs/2026-10-21_job-search-dashboard.md).
 * Charts are hand-written SVG/CSS (no library). Every number or chart element carries a drill spec from
 * GET /api/metrics: clicking it opens the matching Data Browser table already filtered to those rows.
 * Relies on globals from index.html: state, viewFor, buildNav, render, loadData.
 */
let DR = [];   // drill specs for the current dashboard paint; elements point at them with data-d

function dEsc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function reg(spec) { if (!spec) return ""; DR.push(spec); return `data-d="${DR.length - 1}" role="button" tabindex="0"`; }
function shortDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function pctOf(n, total) { return total ? Math.round(100 * n / total) : 0; }

// ---- drill-down: jump to a table with the filters applied ------------------------------------------------
function drillTo(spec) {
  if (!spec) return;
  const v = viewFor(spec.table);
  v.filters = JSON.parse(JSON.stringify(spec.filters || {}));
  v.q = ""; v.sortCol = null; v.dir = 1;
  v.range = spec.range ? Object.assign({}, spec.range) : null;
  v.drill = { label: spec.label || "Dashboard selection", from: state.activeTable === "action_center" ? "action_center" : "dashboard" };
  state.activeTable = spec.table;
  buildNav(); render();
  window.scrollTo({ top: 0 });
}
function backToDashboard() {
  const v = viewFor(state.activeTable);
  state.activeTable = (v.drill && v.drill.from) || "dashboard"; buildNav(); render();
}

// ---- charts -------------------------------------------------------------------------------------------------
const STATUS_COLOR = {
  applied: "var(--c-applied)", planned: "var(--c-other)", rejected: "var(--c-reject)", closed: "#B8BCC1", withdrawn: "#B8BCC1",
  recruiter_screen: "var(--c-progress)", hiring_manager: "var(--c-progress)", interview_loop: "var(--c-progress)",
  final_round: "var(--c-progress)", offer: "var(--c-met)", referred: "var(--c-bar)", referral_requested: "var(--c-other)",
};
const OUTCOME_COLOR = { applied: "var(--c-applied)", in_process: "var(--c-progress)", rejected: "var(--c-reject)", other: "var(--c-other)" };

function weeklyChart(weekly, target) {
  const W = 620, H = 230, L = 34, R = 10, T = 18, B = 34;
  const max = Math.max(target, ...weekly.map(w => w.count), 1) * 1.12;
  const innerW = W - L - R, innerH = H - T - B, slot = innerW / weekly.length, bw = Math.min(46, slot * 0.62);
  const y = v => T + innerH - (v / max) * innerH;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Applications per week against the weekly target">`;
  const top10 = Math.ceil(max / 10) * 10, ticks = [...new Set([0, target, top10])].sort((a, b) => a - b);
  for (const t of ticks) s += `<line class="axis" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${t}</text>`;
  weekly.forEach((w, i) => {
    const x = L + slot * i + (slot - bw) / 2, h = (w.count / max) * innerH;
    const fill = w.current ? "var(--accent)" : (w.met ? "var(--c-met)" : "var(--c-bar)");
    s += `<rect class="click" ${reg(w.drill)} x="${x}" y="${y(w.count)}" width="${bw}" height="${Math.max(h, 1)}" rx="3" style="fill:${fill}"><title>${dEsc(w.drill.label)}: ${w.count} applications (click to see them)</title></rect>`;
    s += `<text x="${x + bw / 2}" y="${y(w.count) - 5}" text-anchor="middle" style="fill:var(--ink)">${w.count}</text>`;
    s += `<text x="${x + bw / 2}" y="${H - 14}" text-anchor="middle">${shortDate(w.week_start)}${w.current ? " *" : ""}</text>`;
  });
  s += `<line class="target" x1="${L}" x2="${W - R}" y1="${y(target)}" y2="${y(target)}"/><text x="${W - R}" y="${y(target) - 5}" text-anchor="end" style="fill:var(--c-target)">${target}/week target</text>`;
  return s + "</svg>";
}

function donut(statusRows) {
  const total = statusRows.reduce((a, r) => a + r.count, 0), cx = 80, cy = 80, ro = 70, ri = 44;
  let a0 = -Math.PI / 2, s = `<svg viewBox="0 0 160 160" role="img" aria-label="Opportunities by status">`;
  for (const r of statusRows) {
    const a1 = a0 + (r.count / total) * Math.PI * 2, large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (a, rad) => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
    const [x0, y0] = p(a0, ro), [x1, y1] = p(a1 - 0.0001, ro), [x2, y2] = p(a1 - 0.0001, ri), [x3, y3] = p(a0, ri);
    const d = r.count === total ? `M ${cx} ${cy - ro} A ${ro} ${ro} 0 1 1 ${cx - 0.01} ${cy - ro} L ${cx - 0.01} ${cy - ri} A ${ri} ${ri} 0 1 0 ${cx} ${cy - ri} Z`
      : `M ${x0} ${y0} A ${ro} ${ro} 0 ${large} 1 ${x1} ${y1} L ${x2} ${y2} A ${ri} ${ri} 0 ${large} 0 ${x3} ${y3} Z`;
    s += `<path class="click" ${reg(r.drill)} d="${d}" style="fill:${STATUS_COLOR[r.status] || "var(--c-applied)"}"><title>${dEsc(r.status)}: ${r.count}</title></path>`;
    a0 = a1;
  }
  s += `<text x="80" y="78" text-anchor="middle" style="font-size:22px;fill:var(--ink);font-family:Newsreader,Georgia,serif">${total}</text><text x="80" y="95" text-anchor="middle">opportunities</text></svg>`;
  const legend = statusRows.map(r => `<button type="button" class="item" ${reg(r.drill)}><span class="sw" style="background:${STATUS_COLOR[r.status] || "var(--c-applied)"}"></span>${dEsc(r.status)} ${r.count}</button>`).join("");
  return `<div style="max-width:220px;margin:0 auto">${s}</div><div class="legend">${legend}</div>`;
}

function stackedRows(items, nameKey, labelKey) {
  const max = Math.max(...items.map(i => i.total), 1);
  return items.map(it => {
    const segs = it.cells.filter(c => c.count > 0).map(c =>
      `<div class="seg" ${reg(c.drill)} style="width:${(c.count / max) * 100}%;background:${OUTCOME_COLOR[c.key]}" title="${dEsc(c.drill.label)}: ${c.count}"></div>`).join("");
    const extra = it.heard_rate !== undefined ? ` · ${Math.round(it.heard_rate)}%` : "";
    return `<div class="hrow"><div class="name" ${reg(it.drill)} title="${dEsc(it[labelKey || nameKey])}">${dEsc(it[labelKey || nameKey])}</div><div class="hbar">${segs}</div><div class="nums">${it.total}${extra}</div></div>`;
  }).join("");
}
const OUTCOME_LEGEND = `<div class="legend"><span class="item"><span class="sw" style="background:var(--c-applied)"></span>No response yet</span>
  <span class="item"><span class="sw" style="background:var(--c-progress)"></span>In process</span>
  <span class="item"><span class="sw" style="background:var(--c-reject)"></span>Rejected</span>
  <span class="item"><span class="sw" style="background:var(--c-other)"></span>Other</span></div>`;

function funnelRows(funnel) {
  const max = Math.max(funnel[0] ? funnel[0].count : 1, 1);
  return funnel.map(f => `<div class="frow" ${reg(f.drill)}><div class="fname">${dEsc(f.label)}</div>
    <div><div class="fbar" style="width:${(f.count / max) * 100}%"></div></div><div class="fnum">${f.count} · ${f.pct_of_applied}%</div></div>`).join("");
}

function companyRows(cs) {
  const max = Math.max(...cs.map(c => c.count), 1);
  return cs.map(c => `<div class="hrow"><div class="name" ${reg(c.drill)}>${dEsc(c.company)}</div>
    <div class="hbar"><div class="seg" ${reg(c.drill)} style="width:${(c.count / max) * 100}%;background:var(--c-bar)"></div></div>
    <div class="nums">${c.count}${c.rejected ? " · " + c.rejected + " rej" : ""}</div></div>`).join("");
}

function activityChart(activity, types) {
  if (!activity.length) return `<p class="dash-note">No activity logged yet.</p>`;
  const top = types.slice(0, 5).map(t => t.type), colors = ["var(--t1)", "var(--t2)", "var(--t3)", "var(--t4)", "var(--t5)", "var(--t6)"];
  const W = 1100, H = 230, L = 30, R = 8, T = 14, B = 32, innerH = H - T - B, slot = (W - L - R) / activity.length, bw = Math.min(40, slot * 0.62);
  const max = Math.max(...activity.map(a => a.total), 1) * 1.08, y = v => T + innerH - (v / max) * innerH;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Logged activity per week by type">`;
  s += `<line class="axis" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>`;
  activity.forEach((a, i) => {
    const x = L + slot * i + (slot - bw) / 2; let acc = 0;
    const groups = top.map(t => [t, a.by_type[t] || 0]);
    const other = a.total - groups.reduce((n, g) => n + g[1], 0);
    if (other > 0) groups.push(["other", other]);
    groups.forEach(([t, n], gi) => {
      if (!n) return;
      const h = (n / max) * innerH, yy = y(acc + n); acc += n;
      const spec = t === "other" ? a.drill : { table: "interactions", label: `${t}, week of ${shortDate(a.week_start)}`, filters: { activity_type: [t] }, range: a.drill.range };
      s += `<rect class="click" ${reg(spec)} x="${x}" y="${yy}" width="${bw}" height="${h}" style="fill:${colors[Math.min(gi, 5)]}"><title>${dEsc(t)}: ${n}</title></rect>`;
    });
    s += `<text x="${x + bw / 2}" y="${y(a.total) - 4}" text-anchor="middle" style="fill:var(--ink)">${a.total}</text><text x="${x + bw / 2}" y="${H - 12}" text-anchor="middle">${shortDate(a.week_start)}</text>`;
  });
  s += "</svg>";
  const legend = top.map((t, i) => `<button type="button" class="item" ${reg({ table: "interactions", label: "Activity type: " + t, filters: { activity_type: [t] } })}><span class="sw" style="background:${colors[i]}"></span>${dEsc(t.replace(/_/g, " "))}</button>`).join("")
    + `<span class="item"><span class="sw" style="background:${colors[5]}"></span>other</span>`;
  return s + `<div class="legend">${legend}</div>`;
}

// priority -> CSS class for the colored left edge on list rows
function priClass(p) { return p === "Top priority" ? "pri-top" : (p === "Medium priority" ? "pri-med" : (p === "Low priority" ? "pri-low" : "")); }

// ---- lists -----------------------------------------------------------------------------------------------------
function badge(text, kind) { return `<span class="badge ${kind || ""}">${dEsc(text)}</span>`; }
function outcomeBadge(o) {
  const t = (o || "").toLowerCase();
  if (!t) return badge("pending");
  if (t.startsWith("scheduled")) return badge("scheduled", "warn");
  if (t.startsWith("not") || t.includes("reject")) return badge("not advanced", "bad");
  if (t.startsWith("completed")) return badge("completed", "good");
  return badge(o);
}
function interviewList(rows) {
  if (!rows.length) return `<p class="dash-note">No interviews logged.</p>`;
  return `<ul class="dlist">` + rows.map(i => `<li data-role="${i.role_id}" tabindex="0" role="button">
    <div class="l"><b>${dEsc(i.company)}</b> · ${dEsc(i.title)}<span>${dEsc(i.date || "date unknown")} · ${dEsc(i.stage)}${i.signals ? " · " + dEsc(i.signals) : ""}</span></div>
    <div class="r">${i.upcoming ? badge("upcoming", "warn") + " " : ""}${outcomeBadge(i.outcome)}</div></li>`).join("") + `</ul>`;
}
function attentionList(block, emptyText) {
  if (!block.items.length) return `<p class="dash-note">${dEsc(emptyText)}</p>`;
  const more = block.count > block.items.length ? `<div class="more"><a ${reg(block.drill)}>See all ${block.count} rows in the table &rarr;</a></div>` : "";
  return `<ul class="dlist">` + block.items.map(i => `<li class="${priClass(i.priority)}" data-role="${i.role_id}" tabindex="0" role="button"><div class="l"><b>${dEsc(i.company)}</b> · ${dEsc(i.title)}<span>${dEsc(i.why)}</span></div><div class="r">${dEsc(i.priority)}</div></li>`).join("") + `</ul>` + more;
}

// ---- main paint --------------------------------------------------------------------------------------------------
function renderDashboard() {
  const root = document.createElement("div");
  root.className = "dash";
  root.innerHTML = `<div class="empty-state">Loading metrics…</div>`;
  fetch("/api/metrics").then(r => r.json()).then(m => paintDashboard(root, m))
    .catch(e => { root.innerHTML = `<div class="empty-state">Could not load metrics: ${dEsc(e.message)}</div>`; });
  root.addEventListener("click", dashClick);
  root.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { if (e.target.closest("[data-d],[data-role]")) { e.preventDefault(); dashClick(e); } } });
  return root;
}
function dashClick(e) {
  const d = e.target.closest("[data-d]");
  if (d) { drillTo(DR[Number(d.dataset.d)]); return; }
  const r = e.target.closest("[data-role]");
  if (r) openRoleDrawer(Number(r.dataset.role));
}

function paintDashboard(root, m) {
  DR = [];
  const q = m.quota, pct = Math.min(100, pctOf(q.count, q.target));
  const kpiHtml = Object.entries(m.kpis).map(([k, v]) => {
    const val = v.value === null || v.value === undefined ? "n/a" : v.value;
    const unit = v.unit ? `<small>${dEsc(v.unit)}</small>` : "";
    const frac = v.numerator !== undefined ? `<div class="frac">${v.numerator} of ${v.denominator}</div>` : "";
    const attrs = v.drill ? reg(v.drill) : "";
    return `<div class="kpi ${v.drill ? "" : "static"}" ${attrs}><div class="val">${dEsc(val)}${unit}</div><div class="lab">${dEsc(v.label)}</div>${frac}</div>`;
  }).join("");

  root.innerHTML = `
    <p class="dash-note">As of ${dEsc(m.as_of)} · weeks run Monday to Sunday · click any number, bar, or label to see the exact rows behind it · lanes are model inference, not verified facts.</p>
    <div class="panel"><div class="quota">
      <div class="quota-main">${q.count}<small> of ${q.target} applications this week</small></div>
      <div class="quota-bar" ${reg(q.drill)} title="Applications this week"><div class="quota-fill ${q.count >= q.target ? "met" : ""}" style="width:${pct}%"></div></div>
      <div class="quota-text">${q.count >= q.target ? "Weekly goal met." : `${q.remaining} to go · ${q.days_left} day${q.days_left === 1 ? "" : "s"} left`} (target: ${q.target} a week)</div>
    </div></div>
    <div class="kpis">${kpiHtml}</div>
    <div class="dash-grid">
      <div class="panel span-7"><h3>Applications per week</h3><p class="sub">Against the 10-a-week target. Green = target met. Click a bar for that week's applications.</p><div class="chart wide">${weeklyChart(m.weekly, m.weekly_target)}</div></div>
      <div class="panel span-5"><h3>Where applications stand</h3><p class="sub">Furthest stage reached, cumulative. Click a stage.</p><div class="chart">${funnelRows(m.funnel)}</div></div>
      <div class="panel span-4"><h3>Status mix</h3><p class="sub">All opportunities.</p><div class="chart">${donut(m.status)}</div></div>
      <div class="panel span-8"><h3>Which channels get responses</h3><p class="sub">Submitted applications by channel and outcome. "Heard" = a reply beyond an automatic acknowledgment.</p><div class="chart">${stackedRows(m.channels, "channel")}${OUTCOME_LEGEND}</div></div>
      <div class="panel span-6"><h3>Role lanes (model inference)</h3><p class="sub">A: TPM, B: AI product, C: AI quality. Archetype comes from the classifier, not from you.</p><div class="chart">${stackedRows(m.lanes, "lane", "label")}${OUTCOME_LEGEND}</div></div>
      <div class="panel span-6"><h3>Top companies</h3><p class="sub">Submitted applications per company (agencies count only if you applied through them).</p><div class="chart">${companyRows(m.companies)}</div></div>
      <div class="panel span-12"><h3>Logged activity by week</h3><p class="sub">Acknowledgments, outreach, interviews, rejections, follow-ups. Click a segment for those rows.</p><div class="chart wide">${activityChart(m.activity, m.activity_types)}</div></div>
      <div class="panel span-6"><h3>Interviews</h3><p class="sub">Click one to open the role.</p>${interviewList(m.interviews)}</div>
      <div class="panel span-6"><h3>Upcoming</h3><p class="sub">Scheduled interviews.</p>${interviewList(m.attention.upcoming_interviews)}
        <h3 style="margin-top:18px">Applied, no activity for 7+ days</h3><p class="sub">Follow up or move on. Top priority first.</p>${attentionList(m.attention.stale_applied, "Nothing stale.")}</div>
      <div class="panel span-6"><h3>Ready to apply</h3><p class="sub">Planned roles not yet submitted, best priority first. Good candidates for this week's quota.</p>${attentionList(m.attention.ready_to_apply, "No planned roles.")}</div>
      <div class="panel span-6"><h3>Data quality</h3><p class="sub">Gaps that make the charts less accurate. Click to see the rows and fix them.</p>
        <ul class="dlist">${m.data_quality.map(d => `<li ${reg(d.drill)}><div class="l">${dEsc(d.issue)}</div><div class="r">${d.count}</div></li>`).join("")}</ul></div>
    </div>`;
}

// ---- role drawer -------------------------------------------------------------------------------------------------
let drawerEls = null;
function closeDrawer() { if (drawerEls) { drawerEls.back.remove(); drawerEls.panel.remove(); drawerEls = null; } }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

async function openRoleDrawer(roleId) {
  closeDrawer();
  const back = document.createElement("div"); back.className = "drawer-back"; back.onclick = closeDrawer;
  const panel = document.createElement("aside"); panel.className = "drawer"; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Role detail");
  panel.innerHTML = `<button type="button" class="close">Close</button><p class="note">Loading…</p>`;
  panel.querySelector(".close").onclick = closeDrawer;
  document.body.appendChild(back); document.body.appendChild(panel);
  drawerEls = { back, panel };
  try {
    const res = await fetch("/api/role/" + roleId);
    const d = await res.json();
    if (d.error) throw new Error(d.error);
    const r = d.role || {}, a = d.application || {};
    const kv = (pairs) => `<div class="kv">` + pairs.filter(p => p[1] !== null && p[1] !== undefined && p[1] !== "")
      .map(p => `<div>${dEsc(p[0])}</div><div>${dEsc(p[1])}</div>`).join("") + `</div>`;
    const ivs = (d.interviews || []).map(i => `<div class="ev"><div class="d">${dEsc(i.date || "date unknown")}</div><b>${dEsc(i.stage || "interview")}</b> ${outcomeBadge(i.outcome)}<div class="note">${dEsc(i.notes || "")}</div></div>`).join("") || `<p class="note">None logged.</p>`;
    const ints = (d.interactions || []).map(i => `<div class="ev"><div class="d">${dEsc(String(i.date || "").slice(0, 21))}${i.contact_name ? " · " + dEsc(i.contact_name) : ""}</div>${dEsc(i.summary)}</div>`).join("") || `<p class="note">None logged.</p>`;
    panel.innerHTML = `<button type="button" class="close">Close</button>
      <h3>${dEsc(r.title)}</h3><div class="co">${dEsc(d.company || "")}</div>
      ${kv([["Status", a.status || "planned"], ["Applied", a.date_applied], ["Channel", a.channel], ["Next action", a.next_action],
            ["Requisition", r.job_code], ["Location", r.location], ["Pay", r.compensation_text], ["Type", r.employment_type], ["Found via", r.source],
            ["Lane (model inference)", r.archetype]])}
      <h4>Interviews</h4>${ivs}
      <h4>Activity (newest first)</h4>${ints}
      ${(d.gaps || []).length ? `<h4>Requirement gaps (no linked evidence)</h4><p class="note">${dEsc(d.gaps.join(", "))}</p>` : ""}
      <p class="more"><a id="drawerRow">Open this role in the Roles table &rarr;</a></p>`;
    panel.querySelector(".close").onclick = closeDrawer;
    panel.querySelector("#drawerRow").onclick = () => { closeDrawer(); drillTo({ table: "roles", label: `Role ${roleId}`, filters: { id: [String(roleId)] } }); };
  } catch (e) {
    panel.innerHTML = `<button type="button" class="close">Close</button><p class="note">Could not load role ${dEsc(roleId)}: ${dEsc(e.message)}</p>`;
    panel.querySelector(".close").onclick = closeDrawer;
  }
}


// ---- Action Center (designs/2026-11-02_action-center.md) -----------------------------------------------------------
function tagBadge(i) {
  const kind = i.level === "overdue" || i.level === "urgent" ? "bad" : (i.level === "soon" ? "warn" : "");
  return badge(i.tag, kind);
}
function acList(items, emptyText, right) {
  if (!items.length) return `<p class="dash-note">${dEsc(emptyText)}</p>`;
  return `<ul class="dlist">` + items.map(i => `<li class="${priClass(i.priority)}" data-role="${i.role_id}" tabindex="0" role="button"><div class="l"><b>${dEsc(i.company)}</b> · ${dEsc(i.title)}<span>${dEsc(i.why)}</span></div><div class="r">${right(i)}</div></li>`).join("") + `</ul>`;
}
function acMore(block, text) {
  return block.drill && block.count > block.items.length ? `<div class="more"><a ${reg(block.drill)}>${dEsc(text)} (${block.count}) &rarr;</a></div>` : "";
}
function avoidList(items) {
  return `<ul class="dlist avoid">` + items.map(i => {
    const attrs = i.role_id ? `data-role="${i.role_id}" tabindex="0" role="button"` : (i.drill ? reg(i.drill) : "");
    const who = i.company ? `<b>${dEsc(i.company)}</b> · ${dEsc(i.title)}: ` : "";
    return `<li ${attrs}><div class="l">${who}${dEsc(i.rule)}<span>${dEsc(i.why)}${i.source ? " (" + dEsc(i.source) + ")" : ""}</span></div><div class="r">${i.kind === "standing" ? badge("standing") : badge("this week", "warn")}</div></li>`;
  }).join("") + `</ul>`;
}

function renderActionCenter() {
  const root = document.createElement("div");
  root.className = "dash";
  root.innerHTML = `<div class="empty-state">Loading actions…</div>`;
  fetch("/api/actions").then(r => r.json()).then(a => paintActionCenter(root, a))
    .catch(e => { root.innerHTML = `<div class="empty-state">Could not load actions: ${dEsc(e.message)}</div>`; });
  root.addEventListener("click", dashClick);
  root.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { if (e.target.closest("[data-d],[data-role]")) { e.preventDefault(); dashClick(e); } } });
  return root;
}

function paintActionCenter(root, a) {
  DR = [];
  const strip = a.strip.map(s => `<div class="kpi" ${reg(s.drill)}><div class="val">${dEsc(s.value)}</div><div class="lab">${dEsc(s.label)}</div><div class="frac">${dEsc(s.detail)}</div></div>`).join("");
  root.innerHTML = `
    <p class="dash-note">As of ${dEsc(a.as_of)} · week ${dEsc(shortDate(a.week_start))} to ${dEsc(shortDate(a.week_end))} (Monday to Sunday) · click a number or a row to open it. See the <a class="inline" id="toDash">Dashboard</a> for trends.</p>
    <div class="kpis">${strip}</div>
    <div class="dash-grid">
      <div class="panel span-12"><h3>Do now</h3><p class="sub">Next actions, soonest first. Set with "next action" on a role.</p>
        ${acList(a.do_now.items, "No next actions set.", tagBadge)}${acMore(a.do_now, "See all roles with a next action")}</div>
      <div class="panel span-6"><h3>Interviews and scheduling</h3><p class="sub">Upcoming, pending, or being rescheduled.</p>
        ${acList(a.interviews.items, "Nothing scheduled or pending.", i => badge(i.date || "date pending", "warn") + " " + badge(i.outcome.split(";")[0].slice(0, 40)))}</div>
      <div class="panel span-6"><h3>Waiting on others</h3><p class="sub">No activity for 7+ days. Follow up or move on.</p>
        ${acList(a.waiting.items, "Nothing stale.", i => dEsc(i.priority))}${acMore(a.waiting, "See all in the table")}</div>
      <div class="panel span-12"><h3>Recent rejections</h3><p class="sub">Last 7 days. Worth a short note on what to learn; no follow-up needed.</p>
        ${acList(a.rejections.items, "No rejections in the last 7 days.", i => badge(i.date, "bad"))}</div>
      <div class="panel span-12 avoid-panel"><h3>What not to do</h3><p class="sub">Guardrails from your own data and past feedback. Click one to open the role.</p>${avoidList(a.avoid)}</div>
      <div class="panel span-12"><h3>Fix your data</h3><p class="sub">Gaps that make the numbers less accurate.</p>
        <ul class="dlist">${a.data_quality.map(d => `<li ${reg(d.drill)}><div class="l">${dEsc(d.issue)}</div><div class="r">${d.count}</div></li>`).join("")}</ul></div>
    </div>`;
  const link = root.querySelector("#toDash");
  if (link) link.onclick = () => { state.activeTable = "dashboard"; buildNav(); render(); };
}
