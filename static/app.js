(() => {
  const STORAGE_KEY = "my-playlist-settings";

  const DEFAULTS = {
    concurrency: 3,
    searchResultCount: 5,
    playlistSubfolder: true,
    filenameTemplate: "Artist - Title",
    embedMetadata: true,
    audioBitrate: 320,
    musicDir: "",
    cookieFile: "",
    checkDuplicates: true,
  };

  /** @type {ReturnType<typeof loadSettings>} */
  let settings = loadSettings();
  /** @type {Map<string, {title?: string}>} */
  const playlistCache = new Map();
  /** @type {Set<string>} */
  const activeJobs = new Set();
  /** @type {Map<string, object>} */
  const jobStore = new Map();
  let pollTimer = null;
  let panelsCollapsed = false;
  let jobFocusIndex = 0;
  let pollPaused = false;

  /** @type {'dir'|'file'} */
  let fsPickMode = "dir";
  /** @type {'music'|'cookie'|null} */
  let fsTarget = null;
  /** @type {{ path: string, parent: string|null, entries: {name:string,path:string,is_dir?:boolean}[], selectedIsDir?: boolean }} */
  let fsState = { path: "", parent: null, entries: [], selectedIsDir: true };

  /** @type {{ title: string, entries: object[] } | null} */
  let loadedPlaylist = null;

  const els = {
    statusLcd: document.getElementById("statusLcd"),
    lcdBitrate: document.getElementById("lcdBitrate"),
    plFooterTime: document.getElementById("plFooterTime"),
    viz: document.getElementById("viz"),
    panelsRoot: document.querySelector(".panels"),
    modeBtns: [...document.querySelectorAll(".mode-btn")],
    panels: {
      search: document.getElementById("panel-search"),
      link: document.getElementById("panel-link"),
      playlist: document.getElementById("panel-playlist"),
      settings: document.getElementById("panel-settings"),
    },
    searchInput: document.getElementById("searchInput"),
    searchBtn: document.getElementById("searchBtn"),
    searchDownloadBtn: document.getElementById("searchDownloadBtn"),
    searchResults: document.getElementById("searchResults"),
    linkInput: document.getElementById("linkInput"),
    linkDownloadBtn: document.getElementById("linkDownloadBtn"),
    playlistInput: document.getElementById("playlistInput"),
    playlistLoadBtn: document.getElementById("playlistLoadBtn"),
    playlistSelectAllBtn: document.getElementById("playlistSelectAllBtn"),
    playlistSelectNoneBtn: document.getElementById("playlistSelectNoneBtn"),
    playlistDownloadBtn: document.getElementById("playlistDownloadBtn"),
    playlistTitle: document.getElementById("playlistTitle"),
    playlistResults: document.getElementById("playlistResults"),
    setConcurrency: document.getElementById("setConcurrency"),
    setSearchCount: document.getElementById("setSearchCount"),
    setFilename: document.getElementById("setFilename"),
    setBitrate: document.getElementById("setBitrate"),
    setPlaylistSubfolder: document.getElementById("setPlaylistSubfolder"),
    setEmbedMetadata: document.getElementById("setEmbedMetadata"),
    setMusicDir: document.getElementById("setMusicDir"),
    setCookieFile: document.getElementById("setCookieFile"),
    setCheckDuplicates: document.getElementById("setCheckDuplicates"),
    browseMusicDirBtn: document.getElementById("browseMusicDirBtn"),
    browseCookieBtn: document.getElementById("browseCookieBtn"),
    settingsSaveBtn: document.getElementById("settingsSaveBtn"),
    settingsResetBtn: document.getElementById("settingsResetBtn"),
    jobsList: document.getElementById("jobsList"),
    listBody: document.getElementById("listBody"),
    dupModal: document.getElementById("dupModal"),
    dupList: document.getElementById("dupList"),
    dupSkipBtn: document.getElementById("dupSkipBtn"),
    dupAllBtn: document.getElementById("dupAllBtn"),
    dupCancelBtn: document.getElementById("dupCancelBtn"),
    fsModal: document.getElementById("fsModal"),
    fsList: document.getElementById("fsList"),
    fsCurrentPath: document.getElementById("fsCurrentPath"),
    fsUpBtn: document.getElementById("fsUpBtn"),
    fsSelectBtn: document.getElementById("fsSelectBtn"),
    fsCancelBtn: document.getElementById("fsCancelBtn"),
    trPrev: document.getElementById("trPrev"),
    trPlay: document.getElementById("trPlay"),
    trPause: document.getElementById("trPause"),
    trStop: document.getElementById("trStop"),
    trNext: document.getElementById("trNext"),
    trEject: document.getElementById("trEject"),
    footAdd: document.getElementById("footAdd"),
    footRem: document.getElementById("footRem"),
    footSel: document.getElementById("footSel"),
    footMisc: document.getElementById("footMisc"),
    footListOpts: document.getElementById("footListOpts"),
    winMinBtn: document.getElementById("winMinBtn"),
    winFocusBtn: document.getElementById("winFocusBtn"),
    winReadyBtn: document.getElementById("winReadyBtn"),
    plWinMinBtn: document.getElementById("plWinMinBtn"),
    plWinFocusBtn: document.getElementById("plWinFocusBtn"),
    plWinReadyBtn: document.getElementById("plWinReadyBtn"),
  };

  function loadSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { ...DEFAULTS };
      return { ...DEFAULTS, ...JSON.parse(raw) };
    } catch {
      return { ...DEFAULTS };
    }
  }

  function saveSettings(next) {
    settings = { ...DEFAULTS, ...next };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }

  function fillSettingsForm() {
    els.setConcurrency.value = String(settings.concurrency);
    els.setSearchCount.value = String(settings.searchResultCount);
    els.setFilename.value = settings.filenameTemplate;
    els.setBitrate.value = String(settings.audioBitrate);
    els.setMusicDir.value = settings.musicDir || "";
    els.setCookieFile.value = settings.cookieFile || "";
    els.setPlaylistSubfolder.checked = !!settings.playlistSubfolder;
    els.setEmbedMetadata.checked = !!settings.embedMetadata;
    els.setCheckDuplicates.checked = !!settings.checkDuplicates;
  }

  function readSettingsForm() {
    return {
      concurrency: clampInt(els.setConcurrency.value, 1, 10, DEFAULTS.concurrency),
      searchResultCount: clampInt(els.setSearchCount.value, 1, 20, DEFAULTS.searchResultCount),
      filenameTemplate: els.setFilename.value || DEFAULTS.filenameTemplate,
      audioBitrate: clampInt(els.setBitrate.value, 64, 320, DEFAULTS.audioBitrate),
      musicDir: (els.setMusicDir.value || "").trim(),
      cookieFile: (els.setCookieFile.value || "").trim(),
      playlistSubfolder: els.setPlaylistSubfolder.checked,
      embedMetadata: els.setEmbedMetadata.checked,
      checkDuplicates: els.setCheckDuplicates.checked,
    };
  }

  function clampInt(value, min, max, fallback) {
    const n = Number.parseInt(String(value), 10);
    if (Number.isNaN(n)) return fallback;
    return Math.min(max, Math.max(min, n));
  }

  function setLcd(text) {
    els.statusLcd.innerHTML = `<span class="lcd-line">${escapeHtml(text)}</span>`;
  }

  function syncBitrateDisplay() {
    if (els.lcdBitrate) els.lcdBitrate.textContent = String(settings.audioBitrate);
  }

  function updateFooterTime() {
    if (!els.plFooterTime) return;
    let total = 0;
    let done = 0;
    for (const job of jobStore.values()) {
      total += job.items.length;
      done += job.items.filter((i) => i.status === "done").length;
    }
    els.plFooterTime.textContent = `${done}:00 / ${total}:00`;
  }

  function startVisualizer() {
    const canvas = els.viz;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const bars = 16;
    const values = Array.from({ length: bars }, () => Math.random());

    function frame() {
      const busy = activeJobs.size > 0 && !pollPaused;
      for (let i = 0; i < bars; i++) {
        const target = busy ? 0.2 + Math.random() * 0.8 : 0.05 + Math.random() * 0.25;
        values[i] += (target - values[i]) * 0.35;
      }
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      const gap = 1;
      const w = (canvas.width - gap * (bars - 1)) / bars;
      for (let i = 0; i < bars; i++) {
        const h = Math.max(1, Math.floor(values[i] * canvas.height));
        ctx.fillStyle = "#00ef00";
        ctx.fillRect(i * (w + gap), canvas.height - h, w, h);
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function formatDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return "--:--";
    const s = Math.max(0, Math.floor(Number(seconds)));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok) {
      const detail = data && (data.detail || data.message);
      throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
    }
    return data;
  }

  function switchMode(mode) {
    els.modeBtns.forEach((btn) => {
      const active = btn.dataset.mode === mode;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    Object.entries(els.panels).forEach(([key, panel]) => {
      const show = key === mode;
      panel.hidden = !show;
      panel.classList.toggle("active", show);
    });
    if (panelsCollapsed && els.panelsRoot) {
      panelsCollapsed = false;
      els.panelsRoot.classList.remove("collapsed");
    }
  }

  function cookiePayload() {
    return settings.cookieFile || null;
  }

  function downloadPayload(items, outputSubdir) {
    return {
      items,
      output_subdir: outputSubdir || null,
      concurrency: settings.concurrency,
      embed_metadata: settings.embedMetadata,
      audio_bitrate: settings.audioBitrate,
      filename_template: settings.filenameTemplate,
      cookiefile: cookiePayload(),
    };
  }

  function hideDupModal() {
    els.dupModal.hidden = true;
  }

  function confirmDuplicates(duplicates) {
    return new Promise((resolve) => {
      els.dupList.innerHTML = duplicates
        .map((d) => {
          const name = d.title || d.url;
          return `<li><span>${escapeHtml(name)}</span><span class="dup-path">${escapeHtml(
            d.existing.path
          )}</span></li>`;
        })
        .join("");
      els.dupModal.hidden = false;
      setLcd(`DUPLICATES · ${duplicates.length} FOUND`);

      const cleanup = () => {
        els.dupSkipBtn.removeEventListener("click", onSkip);
        els.dupAllBtn.removeEventListener("click", onAll);
        els.dupCancelBtn.removeEventListener("click", onCancel);
        hideDupModal();
      };
      const onSkip = () => {
        cleanup();
        resolve("skip");
      };
      const onAll = () => {
        cleanup();
        resolve("all");
      };
      const onCancel = () => {
        cleanup();
        resolve("cancel");
      };
      els.dupSkipBtn.addEventListener("click", onSkip);
      els.dupAllBtn.addEventListener("click", onAll);
      els.dupCancelBtn.addEventListener("click", onCancel);
    });
  }

  async function queueDownload(items, outputSubdir, label) {
    if (!items.length) {
      setLcd("NOTHING TO DOWNLOAD");
      return;
    }
    setLcd(`QUEUING · ${items.length} TRACK(S)`);
    try {
      const data = await api("/api/download", {
        method: "POST",
        body: JSON.stringify(downloadPayload(items, outputSubdir)),
      });
      activeJobs.add(data.job_id);
      playlistCache.set(data.job_id, { title: label || "Download" });
      setLcd(`JOB STARTED · ${data.job_id.slice(0, 8)}`);
      ensurePolling();
      await refreshJob(data.job_id);
    } catch (err) {
      setLcd(`ERROR · ${err.message}`);
    }
  }

  async function startDownload(items, outputSubdir, label) {
    if (!items.length) return;

    if (settings.checkDuplicates) {
      setLcd("CHECKING LIBRARY…");
      try {
        const check = await api("/api/check-duplicates", {
          method: "POST",
          body: JSON.stringify({
            items,
            music_dir: settings.musicDir || null,
          }),
        });
        if (check.duplicates && check.duplicates.length) {
          const choice = await confirmDuplicates(check.duplicates);
          if (choice === "cancel") {
            setLcd("DOWNLOAD CANCELLED");
            return;
          }
          if (choice === "skip") {
            const dupUrls = new Set(check.duplicates.map((d) => d.url));
            items = items.filter((it) => !dupUrls.has(it.url));
            if (!items.length) {
              setLcd("ALL SKIPPED · DUPES ONLY");
              return;
            }
          }
        }
      } catch (err) {
        setLcd(`DUP CHECK ERROR · ${err.message}`);
        return;
      }
    }

    await queueDownload(items, outputSubdir, label);
  }

  function ensurePolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      if (pollPaused) return;
      if (!activeJobs.size) {
        clearInterval(pollTimer);
        pollTimer = null;
        return;
      }
      for (const jobId of [...activeJobs]) {
        await refreshJob(jobId);
      }
    }, 900);
  }

  async function refreshJob(jobId) {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      jobStore.set(jobId, job);
      renderJobs();
      if (job.status === "done" || job.status === "failed") {
        activeJobs.delete(jobId);
        const failed = job.items.filter((i) => i.status === "failed").length;
        const done = job.items.filter((i) => i.status === "done").length;
        setLcd(
          job.status === "failed"
            ? `JOB FAILED · ${failed} ERROR(S)`
            : `DONE · ${done} OK${failed ? ` · ${failed} FAIL` : ""}`
        );
      }
    } catch (err) {
      setLcd(`JOB ERROR · ${err.message}`);
    }
  }

  function isUnavailableError(error) {
    return /video unavailable/i.test(error || "");
  }

  function isForbiddenError(error) {
    return /403|forbidden/i.test(error || "");
  }

  async function retrySameUrl(item) {
    await startDownload([{ url: item.url, title: item.title || null }], null, "Retry");
  }

  async function retryViaSearch(item) {
    const query = (item.title || "").trim();
    if (!query) {
      setLcd("NO TITLE TO SEARCH");
      return;
    }
    setLcd(`RESEARCH · ${query.slice(0, 28)}`);
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({
          queries: [query],
          limit: 1,
          cookiefile: cookiePayload(),
        }),
      });
      const first = data.results?.[0]?.candidates?.[0];
      if (!first) {
        setLcd("NO SEARCH MATCH");
        return;
      }
      setLcd(`FOUND · ${first.title.slice(0, 28)}`);
      await startDownload(
        [{ url: first.url, title: first.title }],
        null,
        "Retry search"
      );
    } catch (err) {
      setLcd(`SEARCH RETRY · ${err.message}`);
    }
  }

  function renderJobs() {
    if (!jobStore.size) {
      els.jobsList.innerHTML = `<p class="empty-hint">0. — empty list —</p>`;
      updateFooterTime();
      return;
    }
    const blocks = [...jobStore.entries()]
      .reverse()
      .map(([jobId, job], blockIdx) => {
        const meta = playlistCache.get(jobId);
        const head = meta?.title || `Job ${jobId.slice(0, 8)}`;
        const itemsHtml = job.items
          .map((item, idx) => {
            const title = item.title || item.url;
            const pct = Math.round(item.progress || 0);
            const failed = item.status === "failed";
            const actions = failed
              ? `<div class="job-actions">
                  <button type="button" class="bevel-btn retry-same" data-job="${escapeHtml(
                    jobId
                  )}" data-idx="${idx}">RETRY</button>
                  <button type="button" class="bevel-btn retry-search" data-job="${escapeHtml(
                    jobId
                  )}" data-idx="${idx}" title="Find another YouTube upload">RE-SEARCH</button>
                </div>`
              : "";
            const hint =
              failed && isForbiddenError(item.error)
                ? `<div class="error-text">Tip: set cookies.txt in EQ for 403s</div>`
                : failed && isUnavailableError(item.error)
                  ? `<div class="error-text">Tip: use RE-SEARCH for a new upload</div>`
                  : "";
            return `
              <div class="job-item">
                <div class="job-item-top">
                  <span>${idx + 1}. ${escapeHtml(title)}</span>
                  <span class="status-${item.status}">${item.status.toUpperCase()}${
              item.status === "downloading" ? ` ${pct}%` : ""
            }</span>
                </div>
                <div class="progress"><span style="width:${pct}%"></span></div>
                ${item.error ? `<div class="error-text">${escapeHtml(item.error)}</div>` : ""}
                ${hint}
                ${actions}
              </div>
            `;
          })
          .join("");
        const activeClass = blockIdx === jobFocusIndex ? " active-job" : "";
        return `
          <div class="job-block${activeClass}" data-job="${escapeHtml(jobId)}">
            <div class="job-head">
              <span>${escapeHtml(head)}</span>
              <span>${job.status.toUpperCase()}</span>
            </div>
            ${itemsHtml}
          </div>
        `;
      })
      .join("");
    els.jobsList.innerHTML = blocks;
    updateFooterTime();

    els.jobsList.querySelectorAll(".retry-same").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const job = jobStore.get(btn.dataset.job);
        const item = job?.items?.[Number(btn.dataset.idx)];
        if (item) await retrySameUrl(item);
      });
    });
    els.jobsList.querySelectorAll(".retry-search").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const job = jobStore.get(btn.dataset.job);
        const item = job?.items?.[Number(btn.dataset.idx)];
        if (item) await retryViaSearch(item);
      });
    });
  }

  function focusJobList() {
    els.listBody?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    highlightJobBlock(jobFocusIndex);
    setLcd("JOB LIST FOCUSED");
  }

  function highlightJobBlock(index) {
    const blocks = [...els.jobsList.querySelectorAll(".job-block")];
    if (!blocks.length) {
      setLcd("NO JOBS");
      return;
    }
    jobFocusIndex = ((index % blocks.length) + blocks.length) % blocks.length;
    blocks.forEach((el, i) => el.classList.toggle("active-job", i === jobFocusIndex));
    blocks[jobFocusIndex].scrollIntoView({ behavior: "smooth", block: "nearest" });
    const label = blocks[jobFocusIndex].querySelector(".job-head span")?.textContent || "JOB";
    setLcd(`JOB · ${label}`);
  }

  function clearSettledJobs() {
    for (const [jobId, job] of [...jobStore.entries()]) {
      if (job.status === "done" || job.status === "failed") {
        jobStore.delete(jobId);
        playlistCache.delete(jobId);
        activeJobs.delete(jobId);
      }
    }
    jobFocusIndex = 0;
    renderJobs();
    setLcd("CLEARED SETTLED JOBS");
  }

  function togglePanels() {
    panelsCollapsed = !panelsCollapsed;
    els.panelsRoot?.classList.toggle("collapsed", panelsCollapsed);
    setLcd(panelsCollapsed ? "PANELS HIDDEN" : "PANELS SHOWN");
  }

  function selectAllPlaylist() {
    if (els.playlistResults.hidden) {
      setLcd("NO PLAYLIST LOADED");
      return;
    }
    els.playlistResults.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.checked = true;
    });
    switchMode("playlist");
    setLcd("SELECTED ALL TRACKS");
  }

  // --- Search ---
  els.searchBtn.addEventListener("click", async () => {
    const lines = els.searchInput.value
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    if (!lines.length) {
      setLcd("ENTER AT LEAST ONE SONG");
      return;
    }
    els.searchBtn.disabled = true;
    setLcd(`SEARCHING · ${lines.length} QUER${lines.length === 1 ? "Y" : "IES"}`);
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({
          queries: lines,
          limit: settings.searchResultCount,
          cookiefile: cookiePayload(),
        }),
      });
      renderSearchResults(data.results);
      setLcd(`FOUND · PICK MATCHES`);
    } catch (err) {
      setLcd(`SEARCH ERROR · ${err.message}`);
    } finally {
      els.searchBtn.disabled = false;
    }
  });

  function renderSearchResults(results) {
    if (!results.length) {
      els.searchResults.hidden = true;
      els.searchDownloadBtn.disabled = true;
      return;
    }
    els.searchResults.hidden = false;
    els.searchResults.innerHTML = results
      .map((result, qi) => {
        if (result.error) {
          return `<div class="track-group"><p class="track-group-title">${escapeHtml(
            result.query
          )}</p><div class="error-text">${escapeHtml(result.error)}</div></div>`;
        }
        if (!result.candidates.length) {
          return `<div class="track-group"><p class="track-group-title">${escapeHtml(
            result.query
          )}</p><div class="error-text">No matches</div></div>`;
        }
        const options = result.candidates
          .map((c, ci) => {
            const checked = ci === 0 ? "checked" : "";
            return `
              <label class="track-row">
                <input type="radio" name="q${qi}" value="${escapeHtml(c.url)}" data-title="${escapeHtml(
              c.title
            )}" ${checked} />
                <span>
                  ${ci + 1}. ${escapeHtml(c.channel || "Unknown").toUpperCase()} - ${escapeHtml(
              c.title
            ).toUpperCase()}
                </span>
                <span class="meta">${formatDuration(c.duration)}</span>
              </label>
            `;
          })
          .join("");
        return `<div class="track-group"><p class="track-group-title">${escapeHtml(
          result.query
        ).toUpperCase()}</p>${options}</div>`;
      })
      .join("");
    els.searchDownloadBtn.disabled = false;
  }

  els.searchDownloadBtn.addEventListener("click", async () => {
    const groups = [...els.searchResults.querySelectorAll(".track-group")];
    const items = [];
    groups.forEach((group) => {
      const selected = group.querySelector('input[type="radio"]:checked');
      if (selected) {
        items.push({ url: selected.value, title: selected.dataset.title || null });
      }
    });
    await startDownload(items, null, "Search download");
  });

  els.linkDownloadBtn.addEventListener("click", async () => {
    const url = els.linkInput.value.trim();
    if (!url) {
      setLcd("PASTE A URL FIRST");
      return;
    }
    await startDownload([{ url }], null, "Link download");
  });

  els.playlistLoadBtn.addEventListener("click", async () => {
    const url = els.playlistInput.value.trim();
    if (!url) {
      setLcd("PASTE A PLAYLIST URL");
      return;
    }
    els.playlistLoadBtn.disabled = true;
    setLcd("LOADING PLAYLIST…");
    try {
      const data = await api("/api/playlist", {
        method: "POST",
        body: JSON.stringify({ url, cookiefile: cookiePayload() }),
      });
      loadedPlaylist = data;
      renderPlaylist(data);
      setLcd(`PLAYLIST · ${data.entries.length} TRACKS`);
    } catch (err) {
      setLcd(`PLAYLIST ERROR · ${err.message}`);
    } finally {
      els.playlistLoadBtn.disabled = false;
    }
  });

  function renderPlaylist(data) {
    els.playlistTitle.hidden = false;
    els.playlistTitle.textContent = data.title;
    els.playlistResults.hidden = false;
    els.playlistResults.innerHTML = data.entries
      .map(
        (entry, i) => `
      <label class="track-row">
        <input type="checkbox" name="pl" value="${escapeHtml(entry.url)}" data-title="${escapeHtml(
          entry.title
        )}" checked />
        <span>
          ${i + 1}. ${escapeHtml(entry.channel || "UNKNOWN").toUpperCase()} - ${escapeHtml(
          entry.title
        ).toUpperCase()}
        </span>
        <span class="meta">${formatDuration(entry.duration)}</span>
      </label>
    `
      )
      .join("");
    els.playlistSelectAllBtn.disabled = false;
    els.playlistSelectNoneBtn.disabled = false;
    els.playlistDownloadBtn.disabled = false;
  }

  els.playlistSelectAllBtn.addEventListener("click", () => {
    els.playlistResults.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.checked = true;
    });
  });

  els.playlistSelectNoneBtn.addEventListener("click", () => {
    els.playlistResults.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.checked = false;
    });
  });

  els.playlistDownloadBtn.addEventListener("click", async () => {
    const checked = [...els.playlistResults.querySelectorAll('input[type="checkbox"]:checked')];
    if (!checked.length) {
      setLcd("CHECK AT LEAST ONE TRACK");
      return;
    }
    const items = checked.map((cb) => ({
      url: cb.value,
      title: cb.dataset.title || null,
    }));
    const subdir =
      settings.playlistSubfolder && loadedPlaylist ? loadedPlaylist.title : null;
    await startDownload(items, subdir, loadedPlaylist?.title || "Playlist");
  });

  // --- Folder / file browser ---
  async function loadFsRoots() {
    const data = await api("/api/fs/roots");
    fsState = { path: "", parent: null, entries: data.entries, selectedIsDir: true };
    renderFsList();
  }

  async function loadFsPath(path) {
    const q =
      fsPickMode === "file"
        ? `&include_files=true&file_ext=txt`
        : "";
    const data = await api(`/api/fs/list?path=${encodeURIComponent(path)}${q}`);
    fsState = {
      path: data.path,
      parent: data.parent,
      entries: data.entries,
      selectedIsDir: true,
    };
    renderFsList();
  }

  function renderFsList() {
    els.fsCurrentPath.textContent = fsState.path || "Drives / roots";
    els.fsUpBtn.disabled = !fsState.path && !fsState.parent;
    if (!fsState.entries.length) {
      els.fsList.innerHTML = `<p class="empty-hint">No entries</p>`;
      return;
    }
    els.fsList.innerHTML = fsState.entries
      .map((entry) => {
        const icon = entry.is_dir === false ? "📄" : "📁";
        return `<button type="button" class="fs-item" data-path="${escapeHtml(
          entry.path
        )}" data-isdir="${entry.is_dir !== false}">${icon} ${escapeHtml(entry.name)}</button>`;
      })
      .join("");
    els.fsList.querySelectorAll(".fs-item").forEach((btn) => {
      const isDir = btn.dataset.isdir === "true";
      btn.addEventListener("dblclick", async () => {
        if (!isDir) return;
        try {
          await loadFsPath(btn.dataset.path);
        } catch (err) {
          setLcd(`FS ERROR · ${err.message}`);
        }
      });
      btn.addEventListener("click", () => {
        els.fsList.querySelectorAll(".fs-item").forEach((el) => el.classList.remove("active"));
        btn.classList.add("active");
        fsState.path = btn.dataset.path;
        fsState.selectedIsDir = isDir;
        els.fsCurrentPath.textContent = fsState.path;
      });
    });
  }

  async function openFsBrowser(mode, target) {
    fsPickMode = mode;
    fsTarget = target;
    els.fsModal.hidden = false;
    document.getElementById("fsTitle").textContent =
      mode === "file" ? "SELECT COOKIES.TXT" : "SELECT FOLDER";
    setLcd(mode === "file" ? "SELECT COOKIE FILE" : "SELECT MUSIC FOLDER");
    try {
      const current =
        target === "cookie"
          ? (els.setCookieFile.value || "").trim()
          : (els.setMusicDir.value || "").trim();
      if (current) {
        const start = mode === "file" ? current.replace(/[/\\][^/\\]+$/, "") || current : current;
        try {
          await loadFsPath(start);
          return;
        } catch {
          // roots
        }
      }
      await loadFsRoots();
    } catch (err) {
      setLcd(`FS ERROR · ${err.message}`);
      els.fsModal.hidden = true;
    }
  }

  els.browseMusicDirBtn.addEventListener("click", () => openFsBrowser("dir", "music"));
  els.browseCookieBtn.addEventListener("click", () => openFsBrowser("file", "cookie"));

  els.fsUpBtn.addEventListener("click", async () => {
    try {
      if (fsState.parent) await loadFsPath(fsState.parent);
      else await loadFsRoots();
    } catch (err) {
      setLcd(`FS ERROR · ${err.message}`);
    }
  });

  els.fsSelectBtn.addEventListener("click", () => {
    if (!fsState.path) {
      setLcd("PICK SOMETHING FIRST");
      return;
    }
    if (fsPickMode === "file" && fsState.selectedIsDir !== false) {
      setLcd("PICK A .TXT FILE");
      return;
    }
    if (fsPickMode === "dir" && fsState.selectedIsDir === false) {
      setLcd("PICK A FOLDER");
      return;
    }
    if (fsTarget === "cookie") {
      els.setCookieFile.value = fsState.path;
      setLcd(`COOKIES · ${fsState.path}`);
    } else {
      els.setMusicDir.value = fsState.path;
      setLcd(`FOLDER · ${fsState.path}`);
    }
    els.fsModal.hidden = true;
  });

  els.fsCancelBtn.addEventListener("click", () => {
    els.fsModal.hidden = true;
    setLcd("PICK CANCELLED");
  });

  els.settingsSaveBtn.addEventListener("click", () => {
    saveSettings(readSettingsForm());
    fillSettingsForm();
    syncBitrateDisplay();
    setLcd(`1. SETTINGS SAVED <MP3 ${settings.audioBitrate}>`);
  });

  els.settingsResetBtn.addEventListener("click", () => {
    saveSettings({ ...DEFAULTS });
    fillSettingsForm();
    syncBitrateDisplay();
    setLcd("1. SETTINGS RESET <MP3 320>");
  });

  els.modeBtns.forEach((btn) => {
    btn.addEventListener("click", () => switchMode(btn.dataset.mode));
  });

  // --- Winamp chrome actions ---
  els.trPrev.addEventListener("click", () => highlightJobBlock(jobFocusIndex - 1));
  els.trNext.addEventListener("click", () => highlightJobBlock(jobFocusIndex + 1));
  els.trPlay.addEventListener("click", () => focusJobList());
  els.trPause.addEventListener("click", () => {
    pollPaused = !pollPaused;
    setLcd(pollPaused ? "POLL PAUSED" : "POLL RESUMED");
    if (!pollPaused) ensurePolling();
  });
  els.trStop.addEventListener("click", () => {
    setLcd("1. READY — MP3 320 <0:00>");
  });
  els.trEject.addEventListener("click", () => {
    switchMode("link");
    els.linkInput.focus();
    setLcd("LINK MODE");
  });

  els.footAdd.addEventListener("click", () => {
    switchMode("search");
    els.searchInput.focus();
    setLcd("SEARCH MODE");
  });
  els.footRem.addEventListener("click", () => clearSettledJobs());
  els.footSel.addEventListener("click", () => selectAllPlaylist());
  els.footMisc.addEventListener("click", () => {
    switchMode("settings");
    setLcd("EQ / SETTINGS");
  });
  els.footListOpts.addEventListener("click", () => {
    switchMode("settings");
    setLcd("LIST OPTS → EQ");
  });

  function wireChrome(minBtn, focusBtn, readyBtn) {
    minBtn?.addEventListener("click", () => togglePanels());
    focusBtn?.addEventListener("click", () => focusJobList());
    readyBtn?.addEventListener("click", () => setLcd("1. READY — MP3 320 <0:00>"));
  }
  wireChrome(els.winMinBtn, els.winFocusBtn, els.winReadyBtn);
  wireChrome(els.plWinMinBtn, els.plWinFocusBtn, els.plWinReadyBtn);

  fillSettingsForm();
  syncBitrateDisplay();
  startVisualizer();
  setLcd("1. READY — MP3 320 <0:00>");
})();
