/* eslint-disable no-undef */
(() => {
  const POLL_MS = 5000;          // frontend polls /api/stats; backend handles upstream rate-limiting
  const $ = (id) => document.getElementById(id);

  const fmtRel = (iso) => {
    if (!iso) return "—";
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return "—";
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60)   return `${s}s ago`;
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
  };

  const fmtJobCategory = (cat) =>
    (cat || "").replace(/^(Building deployment|Retraining|Training|Building) ?/i, (m) => m.toLowerCase());

  function setLED(el, kind) {
    el.classList.remove("go", "warn", "fail");
    if (kind) el.classList.add(kind);
  }

  function renderEi(ei) {
    if (!ei || !ei.configured) {
      $("totalCount").textContent = "—";
      $("projectName").textContent = "EI not configured";
      $("eiJobLabel").textContent = "EI not configured";
      setLED(document.querySelector("#eiJobStatus .dot-led"), null);
      $("eiJobList").innerHTML = "";
      return;
    }
    if (ei.error) {
      $("projectName").textContent = `error: ${ei.error}`;
      return;
    }
    $("totalCount").textContent = ei.totalCount?.toLocaleString() ?? "—";
    $("trainCount").textContent = ei.trainCount ?? "—";
    $("testCount").textContent  = ei.testCount  ?? "—";
    $("projectName").textContent = `${ei.projectName} · #${ei.projectId}`;

    const led = document.querySelector("#eiJobStatus .dot-led");
    if (ei.runningJob) {
      $("eiJobLabel").textContent = `${ei.runningJob.category} (started ${fmtRel(ei.runningJob.started)})`;
      setLED(led, "go");
    } else {
      $("eiJobLabel").textContent = "no job currently running";
      setLED(led, null);
    }

    const list = $("eiJobList");
    list.innerHTML = "";
    (ei.recentJobs || []).forEach((j) => {
      const li = document.createElement("li");
      const lbl = document.createElement("span");
      lbl.textContent = j.category || "?";
      const right = document.createElement("span");
      right.className = "muted mono";
      right.textContent = j.finished
        ? (j.successful ? `ok · ${fmtRel(j.finished)}` : `failed · ${fmtRel(j.finished)}`)
        : `running · ${fmtRel(j.started)}`;
      li.appendChild(lbl);
      li.appendChild(right);
      list.appendChild(li);
    });
  }

  function renderGithub(gh) {
    const list = $("ghRunList");
    list.innerHTML = "";
    if (!gh || gh.error) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = gh?.error || "github not loaded";
      list.appendChild(li);
      return;
    }
    (gh.recentRuns || []).forEach((r) => {
      const li = document.createElement("li");
      const left = document.createElement("span");
      left.textContent = r.name;
      const right = document.createElement("span");
      const cls = (r.conclusion || r.status || "idle").replace(/[^a-z_]/gi, "_");
      right.className = `run-status ${cls}`;
      right.textContent = r.conclusion || r.status || "?";
      li.appendChild(left);
      li.appendChild(right);
      list.appendChild(li);
    });
    if (gh.recentTags?.length) {
      $("latestTag").textContent = gh.recentTags[0].name;
    }
    $("repoName").textContent = gh.repo || "";
  }

  function renderFoundries(fnd) {
    if (!fnd || !fnd.configured) {
      $("factoryName").textContent = "not configured";
      $("targetCount").textContent = "—";
      $("deviceCount").textContent = "—";
      $("targetList").innerHTML = "";
      return;
    }
    if (fnd.error) {
      $("factoryName").textContent = `error: ${fnd.error}`;
      return;
    }
    $("factoryName").textContent = fnd.factory;
    $("targetCount").textContent = fnd.targetCount;
    $("deviceCount").textContent = fnd.deviceCount;

    const tlist = $("targetList");
    tlist.innerHTML = "";
    (fnd.latestTargets || []).forEach((name) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="mono">${name}</span>`;
      tlist.appendChild(li);
    });

    const dlist = $("deviceList");
    dlist.innerHTML = "";
    if (!fnd.devices || fnd.devices.length === 0) {
      const li = document.createElement("li");
      li.className = "empty muted";
      li.textContent = "no devices registered yet — see scripts/register-device.sh";
      dlist.appendChild(li);
    } else {
      fnd.devices.forEach((d) => {
        const li = document.createElement("li");
        const left = document.createElement("span");
        left.innerHTML = `<strong>${d.name}</strong> <span class="muted mono">· ${d.hardwareId || "?"}</span>`;
        const right = document.createElement("span");
        right.className = "muted mono";
        right.textContent = `${d.targetName || "—"} · seen ${fmtRel(d.lastSeen)}`;
        li.appendChild(left);
        li.appendChild(right);
        dlist.appendChild(li);
      });
    }
  }

  function setupRunner(runnerUrl) {
    const iframe = $("runnerIframe");
    const fallback = $("runnerFallback");
    if (runnerUrl) {
      iframe.src = runnerUrl;
      iframe.style.display = "block";
      fallback.style.display = "none";
    } else {
      iframe.style.display = "none";
      fallback.style.display = "flex";
    }
  }

  let runnerSetUp = false;

  async function poll() {
    try {
      const r = await fetch("/api/stats", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const s = await r.json();

      if (!runnerSetUp) {
        setupRunner(s.config?.runnerUrl);
        runnerSetUp = true;
      }

      renderEi(s.ei);
      renderGithub(s.github);
      renderFoundries(s.foundries);

      $("lastUpdated").textContent = s.lastUpdated
        ? `last refreshed ${fmtRel(new Date(s.lastUpdated * 1000).toISOString())}`
        : "waiting on first refresh…";
    } catch (err) {
      $("lastUpdated").textContent = `dashboard offline: ${err.message}`;
    }
  }

  poll();
  setInterval(poll, POLL_MS);
})();
