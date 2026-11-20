/* Rubric to Checker — single-page UI (no build step, no framework). */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 }));
const ago = (t) => {
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
};

const state = { status: null, project: null, run: null, pendingFiles: { samples: [], subs: [] } };

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const type = res.headers.get("content-type") || "";
  const body = type.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = typeof body === "string" ? body : body.detail || body.problems?.join("\n") || JSON.stringify(body);
    if (Array.isArray(msg)) msg = msg.map((m) => m.msg || m).join("; ");
    const err = new Error(msg);
    err.body = body;
    throw err;
  }
  return body;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

function go(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

/* ---------------------------------------------------------------- jobs */
async function pollJob(jobId, logEl, progEl) {
  let since = 0;
  logEl.innerHTML = "";
  for (;;) {
    const j = await api(`/api/jobs/${jobId}?since=${since}`);
    for (const e of j.events) {
      const row = document.createElement("div");
      row.innerHTML = `<span class="t">${e.t.toFixed(1)}s</span><span class="m ${esc(e.level)}"></span>`;
      row.querySelector(".m").textContent = e.message;
      logEl.appendChild(row);
    }
    since = j.event_count;
    logEl.scrollTop = logEl.scrollHeight;
    if (progEl && j.progress.total) {
      progEl.hidden = false;
      progEl.firstElementChild.style.width = `${(100 * j.progress.done) / j.progress.total}%`;
    }
    if (j.status !== "running") return j;
    await sleep(700);
  }
}

function busy(btn, on, label) {
  if (on) {
    btn._label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner" aria-hidden="true"></span> ${esc(label || "Working…")}`;
  } else {
    btn.disabled = false;
    btn.innerHTML = btn._label;
  }
}

/* ---------------------------------------------------------------- rail */
async function renderRail(activeId) {
  const list = $("#projectList");
  try {
    const ps = await api("/api/projects");
    list.innerHTML = ps.length
      ? ps.map((p) => `<li><a href="#/p/${p.id}/rubric" ${p.id === activeId ? 'aria-current="page"' : ""}>${esc(p.title)}
          <small>${p.criteria} criteria · ${fmt(p.total_marks)} marks${p.current_version ? "" : " · no checker yet"}</small></a></li>`).join("")
      : `<li class="empty">Nothing here yet. Upload a rubric to start.</li>`;
  } catch (e) {
    list.innerHTML = `<li class="empty">Could not load projects.</li>`;
  }
  if (!state.status) state.status = await api("/api/status").catch(() => null);
  const s = state.status;
  $("#modeBadge").innerHTML = s
    ? s.mode === "live"
      ? `AI: <b>${esc(s.model)}</b>`
      : `<b>Demo mode.</b> Add an Anthropic API key to read any rubric. The bundled Assignment 5 works without one.`
    : "";
}

/* ---------------------------------------------------------------- router */
async function render() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const main = $("#main");
  closeDrawer();
  try {
    if (parts[0] === "p" && parts[1]) {
      await renderProject(parts[1], parts[2] || "rubric", parts[3]);
      renderRail(parts[1]);
    } else {
      renderHome();
      renderRail(null);
    }
  } catch (e) {
    main.innerHTML = `<div class="wrap"><div class="callout bad">${esc(e.message)}</div><a class="btn btn-ghost" href="#/">Back to start</a></div>`;
  }
  main.focus({ preventScroll: true });
}
window.addEventListener("hashchange", render);

/* ---------------------------------------------------------------- home */
function renderHome() {
  $("#main").innerHTML = `
  <div class="home">
    <section class="hero">
      <div>
        <h1>Turn a marking rubric into a grader.</h1>
        <p class="lede">Upload the rubric for an HTML, CSS and JavaScript assignment. An AI agent reads it,
          writes a Python script that checks each criterion, tests that script on real submissions and fixes
          its own bugs. Then it grades the whole class and explains every lost mark.</p>
        <label class="drop" id="drop">
          <input type="file" id="rubricFile" accept=".pdf,.docx,.txt,.md,.html,.htm" />
          <strong>Upload a rubric</strong>
          <span>PDF, Word, Markdown or text. Drop it here or click to choose.</span>
        </label>
        <div class="row" style="margin-top:14px">
          <button class="btn btn-ghost" id="demoBtn">Try it with a sample assignment</button>
          <a class="muted" href="/api/demo/rubric.pdf">Sample rubric (PDF)</a>
          <a class="muted" href="/api/demo/class_submissions.zip">Sample class (zip)</a>
        </div>
        <div class="log" id="homeLog" aria-live="polite"></div>
      </div>
      <figure class="specimen" aria-label="Example: a rubric line becomes a check">
        <div class="rub">“The hobbies page should include at least 3 images and one image map.”</div>
        <pre><span class="k">hob</span> = sub.html(<span class="s">"hobbies.html"</span>)
c.check(<span class="s">"hobbies.html has at least 3 images"</span>,
        len(hob.images()) &gt;= 3,
        <span class="s">f"found {len(hob.images())}"</span>)
c.check(<span class="s">"hobbies.html has an image map"</span>,
        hob.image_maps())</pre>
        <div class="out">
          <span class="grade mid">27<span class="of">/50</span></span>
          <ul><li>hobbies.html has at least 3 images: found 2</li><li class="ok">hobbies.html has an image map</li></ul>
        </div>
      </figure>
    </section>
    <ol class="how">
      <li><span class="n">1</span><b>Read the rubric</b><span>Criteria, mark bands and page requirements become structured data you can correct.</span></li>
      <li><span class="n">2</span><b>Write the checker</b><span>The agent writes Python that parses each student's HTML, CSS and JS. It never runs student code.</span></li>
      <li><span class="n">3</span><b>Test and repair</b><span>The script runs in a sandbox on an empty folder and your samples. Crashes and wrong marks go back to the agent to fix.</span></li>
      <li><span class="n">4</span><b>Grade the class</b><span>Objective checks are scored by the code. The AI scores judgement calls such as spelling. You can override any mark.</span></li>
    </ol>
  </div>`;

  const drop = $("#drop");
  const input = $("#rubricFile");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) uploadRubric(e.dataTransfer.files[0]); });
  input.addEventListener("change", () => input.files[0] && uploadRubric(input.files[0]));
  $("#demoBtn").addEventListener("click", async (e) => {
    busy(e.currentTarget, true, "Loading sample…");
    try {
      const { project_id } = await api("/api/demo", { method: "POST" });
      go(`#/p/${project_id}/grade`);
    } catch (err) {
      busy(e.currentTarget, false);
      toast(err.message);
    }
  });
}

async function uploadRubric(file) {
  const log = $("#homeLog");
  const fd = new FormData();
  fd.append("rubric", file);
  $("#drop strong").textContent = `Reading ${file.name}…`;
  try {
    const { job_id } = await api("/api/projects", { method: "POST", body: fd });
    const j = await pollJob(job_id, log);
    if (j.status === "done") go(`#/p/${j.result.project_id}/rubric`);
    else $("#drop strong").textContent = "Upload a different rubric";
  } catch (e) {
    toast(e.message);
    $("#drop strong").textContent = "Upload a rubric";
  }
}

/* ---------------------------------------------------------------- project */
const STEPS = [
  ["rubric", "Rubric"],
  ["checker", "Checker"],
  ["grade", "Grade"],
  ["results", "Results"],
];

async function renderProject(pid, tab, sub) {
  const p = await api(`/api/projects/${pid}`);
  state.project = p;
  const r = p.rubric || { criteria: [] };
  const done = { rubric: !!p.rubric, checker: !!p.current_version, grade: p.runs.length > 0, results: p.runs.length > 0 };
  $("#main").innerHTML = `
  <div class="wrap">
    <header class="phead">
      <div style="flex:1;min-width:260px">
        <h1>${esc(p.title)}</h1>
        <div class="meta">${esc(r.course || "")}${r.course ? " · " : ""}${r.criteria.length} criteria, ${fmt(r.total_marks)} marks · from ${esc(p.source_name)}</div>
      </div>
      <button class="btn btn-danger btn-sm" id="delProject">Delete</button>
    </header>
    <nav class="steps" aria-label="Steps">
      ${STEPS.map(([k, label], i) => `<a href="#/p/${pid}/${k}" class="${done[k] && k !== tab ? "done" : ""}" ${k === tab ? 'aria-current="step"' : ""}>
        <span class="n">${done[k] && k !== tab ? "✓" : i + 1}</span>${label}</a>`).join("")}
    </nav>
    <div id="tab"></div>
  </div>`;
  $("#delProject").addEventListener("click", async () => {
    if (!confirm(`Delete “${p.title}” and all its grading runs?`)) return;
    await api(`/api/projects/${pid}`, { method: "DELETE" });
    go("#/");
  });
  const el = $("#tab");
  if (tab === "rubric") renderRubric(el, p);
  else if (tab === "checker") await renderChecker(el, p);
  else if (tab === "grade") renderGrade(el, p);
  else if (tab === "results") await renderResults(el, p, sub);
}

/* ---- step 1: rubric ---- */
function renderRubric(el, p) {
  const r = p.rubric;
  const modeOpt = (m) => ["automated", "hybrid", "ai"].map((o) => `<option ${o === m ? "selected" : ""} value="${o}">${{ automated: "Code checks", hybrid: "Code + AI", ai: "AI judgement" }[o]}</option>`).join("");
  el.innerHTML = `
  <section class="panel">
    <div class="row"><h2>Check how the rubric was read</h2><span class="spacer"></span>
      <span class="muted">Sum of criteria: <b id="sumMarks"></b> of ${fmt(r.total_marks)}</span></div>
    <p class="sub">The checker is written from this table, so fix anything that was misread before you generate it.
      “How to check” is the test the agent will code, including any thresholds it chose for vague wording.</p>
    <table class="rtable">
      <thead><tr><th style="width:28%">Criterion and levels</th><th>Marks</th><th>Graded by</th><th>How to check</th></tr></thead>
      <tbody>
      ${r.criteria.map((c, i) => `<tr data-i="${i}">
        <td><input type="text" data-k="name" value="${esc(c.name)}" aria-label="Criterion name" />
          <ul class="levels">${(c.levels || []).map((l) => `<li><b>${fmt(l.min_marks)}${l.max_marks !== l.min_marks ? "–" + fmt(l.max_marks) : ""}</b> ${esc(l.label)}: ${esc(l.description)}</li>`).join("")}</ul></td>
        <td class="max"><input type="number" min="0" step="0.5" data-k="max_marks" value="${c.max_marks}" aria-label="Max marks" /></td>
        <td><select data-k="grading_mode" aria-label="Graded by">${modeOpt(c.grading_mode)}</select></td>
        <td><textarea data-k="how_to_check" aria-label="How to check">${esc(c.how_to_check)}</textarea></td>
      </tr>`).join("")}
      </tbody>
    </table>
  </section>
  <div class="cols">
    <section class="panel">
      <h2>Required files</h2>
      <p class="sub">One per line. The checker looks for these and flags wrong names.</p>
      <textarea id="reqFiles" rows="5">${esc((r.required_files || []).join("\n"))}</textarea>
    </section>
    <section class="panel">
      <h2>Requirements from the brief</h2>
      <p class="sub">One per line. These become extra checks.</p>
      <textarea id="reqs" rows="5">${esc((r.requirements || []).join("\n"))}</textarea>
    </section>
  </div>
  ${r.deductions?.length || r.notes ? `<section class="panel"><h2>Deductions and notes</h2>
    <ul class="reqs">${(r.deductions || []).map((d) => `<li>${esc(d.reason)}${d.marks ? ` (−${fmt(d.marks)})` : ""}</li>`).join("")}</ul>
    ${r.notes ? `<p class="muted">${esc(r.notes)}</p>` : ""}</section>` : ""}
  <details class="panel"><summary><b>Edit the full rubric as JSON</b> <span class="muted">(levels, ids, deductions)</span></summary>
    <textarea id="rubricJson" rows="18" class="mono" style="margin-top:12px">${esc(JSON.stringify(r, null, 2))}</textarea></details>
  <div class="row"><button class="btn" id="saveRubric">Save and continue to checker</button>
    <span class="muted">${p.current_version ? "After changing the rubric, regenerate the checker so it matches." : ""}</span></div>`;

  const sum = () => { $("#sumMarks").textContent = fmt($$("input[data-k=max_marks]", el).reduce((a, i) => a + Number(i.value || 0), 0)); };
  sum();
  el.addEventListener("input", sum);
  let jsonTouched = false;
  $("#rubricJson").addEventListener("input", () => (jsonTouched = true));

  $("#saveRubric").addEventListener("click", async (e) => {
    let next;
    try {
      next = jsonTouched ? JSON.parse($("#rubricJson").value) : structuredClone(r);
    } catch (err) {
      toast("The JSON has a syntax error: " + err.message);
      return;
    }
    if (!jsonTouched) {
      $$("tbody tr", el).forEach((tr) => {
        const c = next.criteria[+tr.dataset.i];
        $$("[data-k]", tr).forEach((inp) => { c[inp.dataset.k] = inp.dataset.k === "max_marks" ? Number(inp.value) : inp.value; });
      });
      next.required_files = $("#reqFiles").value.split("\n").map((s) => s.trim()).filter(Boolean);
      next.requirements = $("#reqs").value.split("\n").map((s) => s.trim()).filter(Boolean);
    }
    busy(e.currentTarget, true, "Saving…");
    try {
      await api(`/api/projects/${p.id}/rubric`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rubric: next }) });
      toast("Rubric saved");
      go(`#/p/${p.id}/checker`);
    } catch (err) {
      busy(e.currentTarget, false);
      toast(err.message);
    }
  });
}

/* ---- file pickers shared by checker + grade steps ---- */
function filePicker(key, label) {
  return `
  <div class="row picker" data-key="${key}">
    <label class="btn btn-ghost btn-sm">Choose a folder<input type="file" webkitdirectory directory multiple hidden data-pick="dir" /></label>
    <label class="btn btn-ghost btn-sm">Choose zip files<input type="file" accept=".zip" multiple hidden data-pick="zip" /></label>
    <span class="muted" data-count>${esc(label)}</span>
  </div>`;
}
function bindPicker(root, key, onChange) {
  const wrap = $(`.picker[data-key=${key}]`, root);
  $$("input[type=file]", wrap).forEach((inp) =>
    inp.addEventListener("change", () => {
      state.pendingFiles[key] = [...inp.files];
      const n = inp.files.length;
      const kb = [...inp.files].reduce((a, f) => a + f.size, 0) / 1024;
      $("[data-count]", wrap).textContent = n ? `${n} file${n > 1 ? "s" : ""} selected (${kb > 1024 ? (kb / 1024).toFixed(1) + " MB" : Math.round(kb) + " KB"})` : "Nothing selected";
      onChange && onChange(n);
    })
  );
}
function appendFiles(fd, files) {
  for (const f of files) {
    const rel = f.webkitRelativePath || f.name;
    fd.append("files", f, rel);
    fd.append("paths", rel);
  }
}

/* ---- step 2: checker ---- */
async function renderChecker(el, p) {
  const has = !!p.current_version;
  const code = has ? await api(`/api/projects/${p.id}/checker`) : "";
  const cur = p.versions.find((v) => v.n === p.current_version);
  const live = state.status?.mode === "live";
  el.innerHTML = `
  <section class="panel">
    <h2>${has ? "Improve the checker" : "Generate the checker"}</h2>
    <p class="sub">The agent writes a Python script for this rubric, runs it in a sandbox against an empty submission and your
      samples, and sends any crash or rubric mismatch back to itself to fix (up to ${state.status?.max_fix_attempts ?? 3} times).
      It then reviews the sample marks against the rubric.</p>
    ${!live ? `<div class="callout">Demo mode: without an API key only the bundled Assignment 5 checker is available.</div>` : ""}
    <div class="cols">
      <label class="field">Instructions for the agent <span class="hint">Optional. For example: “Accept .htm as well as .html” or “Navigation is too strict, a home link is enough”.</span>
        <textarea id="instr" rows="4"></textarea></label>
      <div class="field"><b>Sample submissions for testing</b>
        <span class="hint">Optional but recommended: 1–3 student folders or zips. The script is tested on them before you grade.</span>
        ${filePicker("samples", "Nothing selected")}
        ${has ? `<label class="row" style="font-weight:400;margin-top:6px"><input type="checkbox" id="revise" checked /> Revise the current version instead of starting over</label>` : ""}
      </div>
    </div>
    <div class="row" style="margin-top:16px"><button class="btn" id="genBtn">${has ? "Regenerate checker" : "Generate checker"}</button>
      ${has ? `<a class="btn btn-ghost" href="#/p/${p.id}/grade">Continue to grading</a>` : ""}</div>
    <div class="log" id="genLog" aria-live="polite"></div>
  </section>
  ${has ? `
  <section class="panel">
    <div class="row"><h2>Version ${cur.n}</h2>
      ${cur.validation?.ok ? `<span class="tag ok">Passes all tests</span>` : `<span class="tag bad">Has problems</span>`}
      <span class="muted">${esc(cur.origin)} · ${ago(cur.created)}${cur.validation?.attempts ? ` · fixed itself ${cur.validation.attempts}×` : ""}</span>
      <span class="spacer"></span>
      <a class="btn btn-ghost btn-sm" href="/api/projects/${p.id}/checker.py">Download .py</a>
      <button class="btn btn-sm" id="saveCode">Save edits as new version</button></div>
    ${(cur.validation?.runs || []).length ? `<p class="muted" style="margin:8px 0 0">Test runs: ${cur.validation.runs.map((r) => `${esc(r.name)} ${r.ok ? `${fmt(r.total)}/${fmt(r.max_total)}` : "failed"}`).join(" · ")}</p>` : ""}
    ${cur.validation?.problems?.length ? `<ul class="problems">${cur.validation.problems.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <div class="editor" style="margin-top:14px"><div class="gutter" id="gutter"></div><textarea id="code" spellcheck="false" aria-label="Checker code"></textarea></div>
  </section>
  <section class="panel"><h2>History</h2>
    <ul class="versions">${[...p.versions].reverse().map((v) => `<li class="${v.n === p.current_version ? "cur" : ""}">
      <span>v${v.n}</span>${v.validation?.ok ? `<span class="tag ok">passes</span>` : `<span class="tag bad">problems</span>`}
      <span>${esc(v.notes)}</span><span class="when">${esc(v.origin)} · ${ago(v.created)}</span><span class="spacer"></span>
      ${v.n === p.current_version ? `<span class="muted">in use</span>` : `<button class="btn btn-ghost btn-sm" data-use="${v.n}">Use this version</button>`}</li>`).join("")}</ul>
  </section>` : ""}`;

  bindPicker(el, "samples");
  state.pendingFiles.samples = [];

  if (has) {
    const ta = $("#code");
    const gutter = $("#gutter");
    const sync = () => {
      const n = ta.value.split("\n").length;
      gutter.textContent = Array.from({ length: n }, (_, i) => i + 1).join("\n");
      ta.style.height = "auto";
      ta.style.height = ta.scrollHeight + "px";
    };
    ta.value = code;
    ta.addEventListener("input", sync);
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Tab" && !e.shiftKey) {
        e.preventDefault();
        ta.setRangeText("    ", ta.selectionStart, ta.selectionEnd, "end");
        sync();
      }
    });
    requestAnimationFrame(sync);
    $("#saveCode").addEventListener("click", async (e) => {
      busy(e.currentTarget, true, "Testing…");
      try {
        const res = await api(`/api/projects/${p.id}/checker`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: ta.value }) });
        toast(res.ok ? `Saved as v${res.version}; tests pass` : `Saved as v${res.version} with problems`);
        render();
      } catch (err) {
        busy(e.currentTarget, false);
        toast("Not saved: " + err.message);
      }
    });
    $$("[data-use]", el).forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/projects/${p.id}/use_version/${b.dataset.use}`, { method: "POST" });
      render();
    }));
  }

  $("#genBtn").addEventListener("click", async (e) => {
    const fd = new FormData();
    fd.append("instructions", $("#instr").value);
    fd.append("revise", has && $("#revise")?.checked ? "true" : "false");
    appendFiles(fd, state.pendingFiles.samples);
    busy(e.currentTarget, true, "Agent is working…");
    try {
      const { job_id } = await api(`/api/projects/${p.id}/generate`, { method: "POST", body: fd });
      const j = await pollJob(job_id, $("#genLog"));
      if (j.status === "done") {
        toast(j.result.ok ? "Checker ready" : "Checker saved with problems");
        await sleep(600);
        render();
      } else busy(e.currentTarget, false);
    } catch (err) {
      busy(e.currentTarget, false);
      toast(err.message);
    }
  });
}

/* ---- step 3: grade ---- */
function renderGrade(el, p) {
  if (!p.current_version) {
    el.innerHTML = `<section class="panel empty-state"><h2>No checker yet</h2><p>Generate a checker from the rubric first. Grading uses the current checker version.</p>
      <a class="btn" href="#/p/${p.id}/checker">Go to checker</a></section>`;
    return;
  }
  el.innerHTML = `
  <section class="panel">
    <h2>Grade submissions</h2>
    <p class="sub">Choose the folder that holds every student's work, or one or more zips. Each sub-folder or zip is treated as
      one student. Zips inside student folders, such as an LMS export, are unpacked automatically. A folder with HTML files
      at the top level is graded as a single submission.</p>
    ${filePicker("subs", "Nothing selected")}
    <div class="row" style="margin-top:16px">
      <button class="btn" id="gradeBtn" disabled>Grade submissions</button>
      ${p.demo ? `<button class="btn btn-ghost" id="gradeSamples">Grade the 3 sample students</button>
        <a class="muted" href="/api/demo/class_submissions.zip">Download the sample class zip</a>` : ""}
      <span class="muted">Using checker v${p.current_version}</span>
    </div>
    <div class="progress" id="prog" hidden><span style="width:0"></span></div>
    <div class="log" id="gradeLog" aria-live="polite"></div>
  </section>
  ${p.runs.length ? `<section class="panel"><h2>Earlier runs</h2><ul class="versions">${p.runs.map((r) => `<li>
    <a href="#/p/${p.id}/results/${r.id}">${ago(r.created)}</a><span>${r.students} students</span>
    <span class="muted">${r.stats?.mean !== undefined ? `average ${fmt(r.stats.mean)}` : esc(r.status)} · checker v${r.checker_version}</span></li>`).join("")}</ul></section>` : ""}`;

  state.pendingFiles.subs = [];
  bindPicker(el, "subs", (n) => ($("#gradeBtn").disabled = !n));
  const run = async (btn, start) => {
    busy(btn, true, "Grading…");
    try {
      const { job_id } = await start();
      const j = await pollJob(job_id, $("#gradeLog"), $("#prog"));
      if (j.status === "done") {
        await sleep(500);
        go(`#/p/${p.id}/results/${j.result.run_id}`);
      } else busy(btn, false);
    } catch (err) {
      busy(btn, false);
      toast(err.message);
    }
  };
  $("#gradeBtn").addEventListener("click", (e) => run(e.currentTarget, () => {
    const fd = new FormData();
    appendFiles(fd, state.pendingFiles.subs);
    return api(`/api/projects/${p.id}/grade`, { method: "POST", body: fd });
  }));
  $("#gradeSamples")?.addEventListener("click", (e) => run(e.currentTarget, () => api(`/api/projects/${p.id}/grade_samples`, { method: "POST" })));
}

/* ---- step 4: results ---- */
async function renderResults(el, p, rid) {
  if (!p.runs.length) {
    el.innerHTML = `<section class="panel empty-state"><h2>No results yet</h2><p>Grade a set of submissions and the marks appear here.</p>
      <a class="btn" href="#/p/${p.id}/grade">Grade submissions</a></section>`;
    return;
  }
  rid = rid || p.runs[0].id;
  const run = await api(`/api/runs/${rid}`);
  state.run = run;
  const crit = p.rubric.criteria;
  const st = run.stats || {};
  el.innerHTML = `
  <section class="panel">
    <div class="row">
      <select id="runPick" aria-label="Grading run" style="width:auto">${p.runs.map((r) => `<option value="${r.id}" ${r.id === rid ? "selected" : ""}>Run from ${ago(r.created)} (${r.students} students)</option>`).join("")}</select>
      <span class="spacer"></span>
      <a class="btn btn-ghost btn-sm" href="/api/runs/${rid}/feedback.zip">Download feedback (.md per student)</a>
      <a class="btn btn-sm" href="/api/runs/${rid}/grades.csv">Download grades (CSV)</a>
    </div>
    <div class="stats" style="margin-top:16px">
      <div><b>${st.graded ?? 0}</b>graded${st.failed ? `, <span style="color:var(--red)">${st.failed} failed</span>` : ""}</div>
      <div><b>${fmt(st.mean)}</b>average</div>
      <div><b>${fmt(st.median)}</b>median</div>
      <div><b>${fmt(st.min)}–${fmt(st.max)}</b>range, out of ${fmt(p.rubric.total_marks)}</div>
    </div>
    ${run.llm_mode !== "ai" ? `<div class="callout">AI-judged criteria in this run used heuristic scores (no API key). Check them, or override below.</div>` : ""}
    <div class="gtable-wrap"><table class="gtable">
      <thead><tr><th>Student</th>${crit.map((c) => `<th title="${esc(c.name)}">${esc(shortName(c.name))}<small>/${fmt(c.max_marks)}</small></th>`).join("")}<th>Deductions</th><th>Total<small>/${fmt(p.rubric.total_marks)}</small></th></tr></thead>
      <tbody>${run.students.map((s, i) => {
        if (!s.ok) return `<tr data-i="${i}"><td class="sname">${esc(s.name)}</td><td colspan="${crit.length + 2}" style="text-align:left;color:var(--red)">Could not be graded: ${esc(s.error)}</td></tr>`;
        const by = Object.fromEntries(s.report.criteria.map((c) => [c.id, c]));
        return `<tr data-i="${i}" tabindex="0"><td class="sname">${esc(s.name)}${s.needs_review ? `<span class="flag">needs review</span>` : ""}</td>
          ${crit.map((c) => { const x = by[c.id]; return `<td class="${x && x.score < x.max_marks ? "lost" : ""}">${x ? fmt(x.score) + (x.overridden ? "*" : "") : "–"}</td>`; }).join("")}
          <td class="${s.report.deduction_total ? "lost" : ""}">${s.report.deduction_total ? "−" + fmt(s.report.deduction_total) : ""}</td>
          <td class="total">${fmt(s.total)}</td></tr>`;
      }).join("")}</tbody>
    </table></div>
    <p class="muted" style="margin-bottom:0">Select a student to see each check, the feedback and to override marks. * = overridden by you.</p>
  </section>`;
  $("#runPick").addEventListener("change", (e) => go(`#/p/${p.id}/results/${e.target.value}`));
  $$("tbody tr", el).forEach((tr) => {
    const open = () => openStudent(+tr.dataset.i);
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open()));
  });
}

function shortName(n) {
  const s = n.split(/[,&(]| and /)[0].trim();
  return s.length > 22 ? s.slice(0, 20) + "…" : s;
}

function gradeBadge(score, max, size) {
  return `<span class="grade ${size} ${score >= max ? "full" : ""}">${fmt(score)}<span class="of">/${fmt(max)}</span></span>`;
}

function openStudent(i) {
  const s = state.run.students[i];
  const body = $("#drawerBody");
  if (!s.ok) {
    body.innerHTML = `<div class="dhead"><h2 id="drawerTitle">${esc(s.name)}</h2></div>
      <div class="callout bad">${esc(s.error)}</div><details class="raw" open><summary>Traceback</summary><pre>${esc(s.traceback)}</pre></details>
      <details class="raw"><summary>Files</summary><pre>${esc(s.files)}</pre></details>`;
  } else {
    const rep = s.report;
    body.innerHTML = `
    <div class="dhead">${gradeBadge(rep.total, rep.max_total, "big")}<div><h2 id="drawerTitle">${esc(s.name)}</h2>
      <div class="muted">${rep.deduction_total ? `${fmt(rep.raw_total)} from criteria, minus ${fmt(rep.deduction_total)} in deductions · ` : ""}graded in ${s.seconds}s</div></div></div>
    ${rep.criteria.map((c) => `
      <section class="crit">
        <div class="crit-h"><h3>${esc(c.name)}</h3>
          ${c.ai ? `<span class="tag ai">${c.ai.result?.mode === "ai" ? "AI judged" : "heuristic"}</span>` : ""}
          ${c.level ? `<span class="tag">${esc(c.level)}</span>` : ""}
          ${c.overridden ? `<span class="tag hybrid">overridden (auto ${fmt(c.auto_score)})</span>` : ""}
          <span class="score ${c.score >= c.max_marks ? "full" : ""}">${fmt(c.score)}/${fmt(c.max_marks)}</span></div>
        ${c.checks.length ? `<ul class="checks">${c.checks.map((k) => `<li class="${k.passed ? "p" : "f"}">${esc(k.label)}${k.detail ? ` <small>${esc(k.detail)}</small>` : ""}</li>`).join("")}</ul>` : ""}
        ${c.feedback.length ? `<ul class="fb">${c.feedback.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
        ${c.error ? `<details class="raw"><summary style="color:var(--red)">This criterion's check crashed</summary><pre>${esc(c.error)}</pre></details>` : ""}
        ${c.ai?.content ? `<details class="raw"><summary>Text the AI judged</summary><pre>${esc(c.ai.content)}</pre></details>` : ""}
        <form class="ovr" data-c="${esc(c.id)}"><label>Mark <input type="number" step="0.5" min="0" max="${c.max_marks}" value="${c.score}" /></label>
          <input type="text" placeholder="Comment for the student (optional)" /><button class="btn btn-ghost btn-sm">Save mark</button></form>
      </section>`).join("")}
    ${rep.deductions.length ? `<section class="crit"><div class="crit-h"><h3>Deductions</h3></div><ul class="fb">${rep.deductions.map((d) => `<li>−${fmt(d.marks)}: ${esc(d.reason)}</li>`).join("")}</ul></section>` : ""}
    ${rep.notes.length ? `<section class="crit"><div class="crit-h"><h3>Notes</h3></div><ul class="fb">${rep.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></section>` : ""}
    <details class="raw"><summary>Submitted files</summary><pre>${esc(s.files)}</pre></details>`;
    $$("form.ovr", body).forEach((f) => f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const [num, txt] = $$("input", f);
      try {
        const run = await api(`/api/runs/${state.run.id}/override`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ student: i, criterion: f.dataset.c, score: num.value === "" ? null : Number(num.value), comment: txt.value }),
        });
        state.run = run;
        toast("Mark saved");
        const scrollTop = $(".drawer-panel").scrollTop;
        await renderResults($("#tab"), state.project, run.id);
        openStudent(i);
        $(".drawer-panel").scrollTop = scrollTop;
      } catch (err) {
        toast(err.message);
      }
    }));
  }
  const d = $("#drawer");
  d.hidden = false;
  d._return = document.activeElement;
  $(".drawer-x").focus();
}

function closeDrawer() {
  const d = $("#drawer");
  if (d.hidden) return;
  d.hidden = true;
  d._return?.focus?.();
}
$("#drawer").addEventListener("click", (e) => e.target.closest("[data-close]") && closeDrawer());
document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

render();
