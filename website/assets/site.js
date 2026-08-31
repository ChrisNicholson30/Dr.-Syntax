const UI = ["bg", "editor", "elevated", "titlebar", "tabbar", "tabactive", "tabinactive", "statusbar", "border", "borderv", "text", "muted", "fg", "linenum", "activelinenum", "activeline", "indentguide", "match", "accent", "error", "warning", "success", "added", "modified", "vcdeleted", "terminalbg", "terminalfg", "vimnormal-bg", "vimnormal-fg"], SYN = ["kw", "fn", "str", "typ", "num", "prop", "cmt", "punc", "tag"];
const root = document.documentElement;

function applyVariant(key){
  const v = DATA[key];
  if (!v) return;
  for (const [n, c] of Object.entries(v.ui))  root.style.setProperty("--e-" + n, c);
  for (const [n, c] of Object.entries(v.syn)) root.style.setProperty("--e-" + n, c);

  document.querySelectorAll("[data-stat]").forEach(el => {
    const raw = v[el.dataset.stat];
    const fmt = el.dataset.fmt;
    el.textContent = fmt === "ratio" ? raw.toFixed(2) + ":1"
                   : fmt === "plane" ? "L " + raw.toFixed(3)
                   : String(raw);
  });
  document.querySelectorAll("[data-swatch]").forEach(el => {
    const c = (v.style && v.style[el.dataset.swatch]) || (v.syntaxAll && v.syntaxAll[el.dataset.swatch]);
    if (c) el.style.background = c;
  });
  document.querySelectorAll("[data-hex]").forEach(el => {
    const c = (v.style && v.style[el.dataset.hex]) || (v.syntaxAll && v.syntaxAll[el.dataset.hex]);
    if (c) el.textContent = c;
  });
  const hueBody = document.getElementById("hue-body");
  if (hueBody) hueBody.innerHTML = v.hues.map(h =>
    `<tr><td><span class="chip"><i style="background:${h.hex}"></i>` +
    `<span class="role">${h.label}</span></span></td>` +
    `<td class="mono">${h.role}</td><td class="mono num">${h.angle}\u00b0</td>` +
    `<td class="mono num">${h.chroma.toFixed(3)}</td>` +
    `<td class="mono num">${h.ratio.toFixed(2)}:1</td></tr>`).join("");
  const vimBody = document.getElementById("vim-body");
  if (vimBody) vimBody.innerHTML = v.vim.map(m =>
    `<tr><td><span class="chip"><i style="background:${m.bg}"></i>` +
    `<code style="background:${m.bg};color:${m.fg}">${m.mode.replace(/_/g," ").toUpperCase()}</code>` +
    `</span></td><td class="mono">${m.bg.slice(0,7)}</td><td class="mono">${m.fg.slice(0,7)}</td>` +
    `<td class="mono num">${m.ratio.toFixed(2)}:1</td></tr>`).join("");
  ["ansi","ansiBright"].forEach(kind => {
    const g = document.getElementById(kind);
    if (g) g.innerHTML = v[kind].map(c => `<i style="background:${c}" title="${c}"></i>`).join("");
  });
  document.querySelectorAll("[data-variant-tabs] .tab-btn").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.key === key)));
  try { localStorage.setItem("drsyntax-variant", key); } catch (e) {}
}

document.querySelectorAll("[data-variant-tabs] .tab-btn").forEach(b =>
  b.addEventListener("click", () => applyVariant(b.dataset.key)));

function applyLang(lang){
  document.querySelectorAll("[data-lang-panel]").forEach(el => {
    el.hidden = el.dataset.langPanel !== lang;
  });
  document.querySelectorAll("[data-lang-tabs] .tab-btn").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.lang === lang)));
}
document.querySelectorAll("[data-lang-tabs] .tab-btn").forEach(b =>
  b.addEventListener("click", () => applyLang(b.dataset.lang)));

let start = "dark";
try { start = localStorage.getItem("drsyntax-variant") || "dark"; } catch (e) {}
applyVariant(DATA[start] ? start : "dark");
if (document.querySelector("[data-lang-tabs]")) applyLang("typescript");
