"use strict";
const $ = (s) => document.querySelector(s);
const H = { "Content-Type": "application/json", "X-Campus-Assistant": "1" };

function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function md(s) {
  // tiny, safe markdown: escape first, then **bold**, bullets and [n] citations
  const lines = esc(s).split("\n");
  let out = "", inList = false;
  for (const raw of lines) {
    const l = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[(\d+)\]/g, '<sup class="cite">[$1]</sup>');
    if (/^\s*[-*] /.test(raw)) { if (!inList) { out += "<ul>"; inList = true; } out += "<li>" + l.replace(/^\s*[-*] /, "") + "</li>"; continue; }
    if (inList) { out += "</ul>"; inList = false; }
    out += l + "\n";
  }
  return out + (inList ? "</ul>" : "");
}
async function post(url, data) {
  const r = await fetch(url, { method: "POST", headers: H, body: JSON.stringify(data) });
  const j = await r.json().catch(() => ({ error: "bad response" }));
  if (!r.ok) throw new Error(j.error + (j.hint ? " — " + j.hint : ""));
  return j;
}
function lang() { return $("#lang").value; }
function card(target, question, res) {
  const div = document.createElement("div");
  div.className = "ans";
  let html = question ? `<div class="q">${esc(question)}</div>` : "";
  html += `<div class="a">${md(res.answer)}</div>`;
  const srcs = (res.sources || []).filter(() => res.kind === "faq" || res.kind === "notes_qa");
  if (srcs.length) html += `<div class="src">${srcs.map((s, i) => `<div><b>[${i + 1}]</b> ${esc(s.ref)} <span class="tag">score ${s.score}</span></div>`).join("")}</div>`;
  html += `<div class="meta"><span class="tag kind">${esc(res.kind)}</span><span class="tag">${esc(res.backend)} · ${esc(res.model)}</span>`;
  if (res.redactions && Object.keys(res.redactions).length) html += `<span class="tag red">redacted ${esc(Object.entries(res.redactions).map(([k, v]) => k + "×" + v).join(", "))}</span>`;
  if (res.usage && res.usage.totalTokenCount) html += `<span class="tag">${res.usage.totalTokenCount} tokens</span>`;
  html += "</div>";
  div.innerHTML = html;
  target.prepend(div);
}
function fail(target, e) { const d = document.createElement("div"); d.className = "ans err"; d.textContent = e.message; target.prepend(d); }
async function run(btn, fn) { btn.disabled = true; try { await fn(); } finally { btn.disabled = false; refreshQuota(); } }

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + t.dataset.tab));
}));

// Ask
async function ask(q) {
  const out = $("#ask-out");
  try { card(out, q, await post("/api/ask", { question: q, lang: lang() })); } catch (e) { fail(out, e); }
}
$("#ask-go").addEventListener("click", () => run($("#ask-go"), () => ask($("#ask-q").value)));
$("#ask-q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#ask-go").click(); });
document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { $("#ask-q").value = c.textContent; $("#ask-go").click(); }));

// Timetable
async function loadTimetable() {
  const r = await fetch("/api/timetable"); const t = await r.json();
  if (!r.ok) { $("#tt-grid").textContent = t.error; return; }
  $("#tt-now").innerHTML = `<b>${esc(t.now)}</b> <span class="muted">(Asia/Kolkata)</span>`;
  const isNow = (s) => t.current && s.day === t.current.day && s.start === t.current.start;
  $("#tt-grid").innerHTML = t.days.map((d) => `<div class="day ${d === t.today ? "today" : ""}"><h3>${d}</h3>` +
    t.slots.filter((s) => s.day === d).map((s) => `<div class="slot ${esc(s.type)} ${isNow(s) ? "now" : ""}"><b>${esc(s.start)}–${esc(s.end)} ${esc(s.code)}</b>${esc(s.course)}<br><span class="muted">${esc(s.type)} · ${esc(s.room)}</span></div>`).join("") + "</div>").join("");
  const next = t.next ? `<div class="big">${esc(t.next.course)}</div>${esc(t.next.starts)} · ${esc(t.next.room)} · ${esc(t.next.faculty)}` : "No upcoming class";
  const cur = t.current ? `<div class="big">${esc(t.current.course)}</div>till ${esc(t.current.end)} · ${esc(t.current.room)}` : "Free right now";
  const cards = `<div class="card"><h4>Now</h4>${cur}</div><div class="card"><h4>Next class</h4>${next}</div><div class="card"><h4>Free today (09:00–17:00)</h4><div class="big">${esc(t.free_today.join(", ") || "none")}</div></div>`;
  $("#nextcard").innerHTML = cards;
  const hours = Object.entries(t.hours).map(([k, v]) => `${esc(k)} ${v.toFixed(1)} h`).join(" · ");
  $("#tt-side").innerHTML = cards + `<div class="card"><h4>Hours per week</h4>${hours}</div><div class="card"><h4>Clashes</h4>${t.clashes.length ? t.clashes.map((c) => esc(c[0].day + " " + c[0].course + " ↔ " + c[1].course)).join("<br>") : "None 🎉"}</div>`;
}
$("#tt-file").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try { const r = await post("/api/timetable/upload", { csv: await f.text() }); alert(`Loaded ${r.classes} classes, ${r.clashes} clash(es).`); loadTimetable(); }
  catch (err) { alert(err.message); }
});

// Notes
$("#notes-file").addEventListener("change", async (e) => { const f = e.target.files[0]; if (!f) return; $("#notes-text").value = await f.text(); $("#notes-name").value = f.name; });
function notesData(extra) { return Object.assign({ text: $("#notes-text").value, source: $("#notes-name").value, lang: lang() }, extra || {}); }
$("#notes-sum").addEventListener("click", () => run($("#notes-sum"), async () => { try { card($("#notes-out"), "Summary · " + $("#notes-name").value, await post("/api/notes/summarise", notesData())); } catch (e) { fail($("#notes-out"), e); } }));
$("#notes-cards").addEventListener("click", () => run($("#notes-cards"), async () => { try { card($("#notes-out"), "Flashcards · " + $("#notes-name").value, await post("/api/notes/flashcards", notesData())); } catch (e) { fail($("#notes-out"), e); } }));
$("#notes-ask").addEventListener("click", () => run($("#notes-ask"), async () => { const q = $("#notes-q").value; try { card($("#notes-out"), q, await post("/api/notes/ask", notesData({ question: q }))); } catch (e) { fail($("#notes-out"), e); } }));
$("#notes-q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#notes-ask").click(); });

// FAQ
$("#faq-go").addEventListener("click", () => run($("#faq-go"), async () => { const q = $("#faq-q").value; try { card($("#faq-out"), q, await post("/api/faq", { question: q, lang: lang() })); } catch (e) { fail($("#faq-out"), e); } }));
$("#faq-q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#faq-go").click(); });

async function refreshQuota() {
  const s = await (await fetch("/api/status")).json();
  $("#quota").textContent = s.backend === "gemini" ? `Gemini calls today: ${s.used_today}/${s.daily_limit || "∞"}` : `${s.classes} classes · ${s.faq_files.length} FAQ files`;
  $("#faq-src").textContent = "Indexed campus documents: " + s.faq_files.join(", ");
}
loadTimetable(); refreshQuota();
