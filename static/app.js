(() => {
  const STORAGE_KEY = "my-playlist-settings";
  const MIGRATED_KEY = "my-playlist-settings-migrated";

  const DEFAULTS = {
    concurrency: 3,
    searchResultCount: 5,
    playlistSubfolder: true,
    filenameTemplate: "Artist - Title",
    embedMetadata: true,
    audioBitrate: 320,
    musicDir: "D:\\music",
    cookieFile: "",
    cookiesFromBrowser: "",
    checkDuplicates: true,
    syncIntervalDays: 7,
  };

  /** @type {typeof DEFAULTS} */
  let settings = { ...DEFAULTS };
  /** @type {Map<string, {title?: string}>} */
  const playlistCache = new Map();
  /** @type {Set<string>} */
  const activeJobs = new Set();
  /** @type {Map<string, object>} */
  const jobStore = new Map();
  let pollTimer = null;

  /** @type {'dir'|'file'} */
  let fsPickMode = "dir";
  /** @type {'music'|'cookie'|null} */
  let fsTarget = null;
  /** @type {{ path: string, parent: string|null, entries: object[], selectedIsDir?: boolean }} */
  let fsState = { path: "", parent: null, entries: [], selectedIsDir: true };

  /** @type {object[]} */
  let savedPlaylists = [];
  /** @type {object[]} */
  let syncQueue = [];
  /** @type {object|null} */
  let lastImportResult = null;
  /** @type {{ title: string, entries: object[] } | null} */
  let loadedPlaylist = null;
  /** @type {string} */
  let currentScreen = "home";

  const $ = (id) => document.getElementById(id);

  const els = {
    brandHomeBtn: $("brandHomeBtn"),
    navHomeBtn: $("navHomeBtn"),
    jobsToggleBtn: $("jobsToggleBtn"),
    jobsBadge: $("jobsBadge"),
    jobsPanel: $("jobsPanel"),
    jobsBackdrop: $("jobsBackdrop"),
    jobsCloseBtn: $("jobsCloseBtn"),
    jobsStatusLine: $("jobsStatusLine"),
    jobsList: $("jobsList"),
    clearJobsBtn: $("clearJobsBtn"),
    homeDuePill: $("homeDuePill"),
    homeQueuePill: $("homeQueuePill"),
    searchInput: $("searchInput"),
    searchBtn: $("searchBtn"),
    searchDownloadBtn: $("searchDownloadBtn"),
    searchResults: $("searchResults"),
    searchAlert: $("searchAlert"),
    linkInput: $("linkInput"),
    linkDownloadBtn: $("linkDownloadBtn"),
    linkAlert: $("linkAlert"),
    plDlInput: $("plDlInput"),
    plDlLoadBtn: $("plDlLoadBtn"),
    plDlSelectAllBtn: $("plDlSelectAllBtn"),
    plDlSelectNoneBtn: $("plDlSelectNoneBtn"),
    plDlDownloadBtn: $("plDlDownloadBtn"),
    plDlTitle: $("plDlTitle"),
    plDlResults: $("plDlResults"),
    plDlAlert: $("plDlAlert"),
    syncAlert: $("syncAlert"),
    syncDueHint: $("syncDueHint"),
    syncAddInput: $("syncAddInput"),
    syncAddBtn: $("syncAddBtn"),
    syncDueBtn: $("syncDueBtn"),
    syncAllBtn: $("syncAllBtn"),
    savedPlaylists: $("savedPlaylists"),
    syncQueueResults: $("syncQueueResults"),
    syncSelectAllBtn: $("syncSelectAllBtn"),
    syncSelectNoneBtn: $("syncSelectNoneBtn"),
    syncDownloadSelectedBtn: $("syncDownloadSelectedBtn"),
    syncDownloadAllBtn: $("syncDownloadAllBtn"),
    syncDismissBtn: $("syncDismissBtn"),
    libAlert: $("libAlert"),
    libDryRunBtn: $("libDryRunBtn"),
    libApplyBtn: $("libApplyBtn"),
    libraryReport: $("libraryReport"),
    settingsAlert: $("settingsAlert"),
    setConcurrency: $("setConcurrency"),
    setSearchCount: $("setSearchCount"),
    setFilename: $("setFilename"),
    setBitrate: $("setBitrate"),
    setSyncInterval: $("setSyncInterval"),
    setMusicDir: $("setMusicDir"),
    setCookieFile: $("setCookieFile"),
    setCookiesBrowser: $("setCookiesBrowser"),
    setPlaylistSubfolder: $("setPlaylistSubfolder"),
    setEmbedMetadata: $("setEmbedMetadata"),
    setCheckDuplicates: $("setCheckDuplicates"),
    browseMusicDirBtn: $("browseMusicDirBtn"),
    browseCookieBtn: $("browseCookieBtn"),
    settingsSaveBtn: $("settingsSaveBtn"),
    settingsResetBtn: $("settingsResetBtn"),
    dupModal: $("dupModal"),
    dupList: $("dupList"),
    dupSkipBtn: $("dupSkipBtn"),
    dupAllBtn: $("dupAllBtn"),
    dupCancelBtn: $("dupCancelBtn"),
    fsModal: $("fsModal"),
    fsList: $("fsList"),
    fsCurrentPath: $("fsCurrentPath"),
    fsUpBtn: $("fsUpBtn"),
    fsSelectBtn: $("fsSelectBtn"),
    fsCancelBtn: $("fsCancelBtn"),
  };

  function clampInt(value, min, max, fallback) {
    const n = Number.parseInt(String(value), 10);
    if (Number.isNaN(n)) return fallback;
    return Math.min(max, Math.max(min, n));
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

  function showAlert(el, message, kind = "info") {
    if (!el) return;
    el.hidden = !message;
    el.classList.remove("is-error", "is-ok", "is-info");
    if (!message) return;
    el.textContent = message;
    el.classList.add(kind === "error" ? "is-error" : kind === "ok" ? "is-ok" : "is-info");
  }

  function goHome() {
    showScreen("home");
    refreshHomeBadges();
  }

  function showScreen(name) {
    currentScreen = name;
    document.querySelectorAll(".screen").forEach((screen) => {
      const match = screen.dataset.screen === name;
      screen.hidden = !match;
      screen.classList.toggle("active", match);
    });
    if (name === "sync") {
      renderSavedPlaylists();
      renderSyncQueue();
    } else if (name === "library") {
      renderLibraryReport();
    } else if (name === "settings") {
      fillSettingsForm();
    } else if (name === "home") {
      refreshHomeBadges();
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openJobsPanel(open = true) {
    els.jobsPanel.hidden = !open;
    els.jobsBackdrop.hidden = !open;
    els.jobsToggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
    els.jobsToggleBtn.classList.toggle("is-active", open);
    if (open) renderJobs();
  }

  function authPayload() {
    return {
      cookiefile: settings.cookieFile || null,
      cookies_from_browser: settings.cookiesFromBrowser || null,
    };
  }

  function downloadPayload(items, outputSubdir) {
    return {
      items,
      output_subdir: outputSubdir || null,
      concurrency: settings.concurrency,
      embed_metadata: settings.embedMetadata,
      audio_bitrate: settings.audioBitrate,
      filename_template: settings.filenameTemplate,
      ...authPayload(),
    };
  }

  function fillSettingsForm() {
    els.setConcurrency.value = String(settings.concurrency);
    els.setSearchCount.value = String(settings.searchResultCount);
    els.setFilename.value = settings.filenameTemplate;
    els.setBitrate.value = String(settings.audioBitrate);
    els.setSyncInterval.value = String(settings.syncIntervalDays || 7);
    els.setMusicDir.value = settings.musicDir || "";
    els.setCookieFile.value = settings.cookieFile || "";
    els.setCookiesBrowser.value = settings.cookiesFromBrowser || "";
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
      syncIntervalDays: clampInt(els.setSyncInterval.value, 1, 365, DEFAULTS.syncIntervalDays),
      musicDir: (els.setMusicDir.value || "").trim(),
      cookieFile: (els.setCookieFile.value || "").trim(),
      cookiesFromBrowser: (els.setCookiesBrowser.value || "").trim(),
      playlistSubfolder: els.setPlaylistSubfolder.checked,
      embedMetadata: els.setEmbedMetadata.checked,
      checkDuplicates: els.setCheckDuplicates.checked,
    };
  }

  async function loadSettingsFromServer() {
    const remote = await api("/api/settings");
    settings = { ...DEFAULTS, ...remote };
  }

  async function saveSettingsToServer(next) {
    const remote = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ ...DEFAULTS, ...next }),
    });
    settings = { ...DEFAULTS, ...remote };
  }

  async function migrateLocalStorageIfNeeded() {
    if (localStorage.getItem(MIGRATED_KEY) === "1") return;
    let local = null;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) local = JSON.parse(raw);
    } catch {
      local = null;
    }
    if (local && typeof local === "object") {
      const remote = await api("/api/settings");
      const looksDefault =
        (!remote.musicDir || remote.musicDir === DEFAULTS.musicDir) &&
        !remote.cookieFile &&
        !remote.cookiesFromBrowser;
      if (looksDefault) {
        await saveSettingsToServer({ ...DEFAULTS, ...remote, ...local });
      }
    }
    localStorage.setItem(MIGRATED_KEY, "1");
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

      const cleanup = () => {
        els.dupSkipBtn.removeEventListener("click", onSkip);
        els.dupAllBtn.removeEventListener("click", onAll);
        els.dupCancelBtn.removeEventListener("click", onCancel);
        els.dupModal.hidden = true;
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

  async function queueDownload(items, outputSubdir, label, alertEl) {
    if (!items.length) {
      showAlert(alertEl, "Nothing to download.", "error");
      return;
    }
    showAlert(alertEl, `Queuing ${items.length} track(s)…`, "info");
    try {
      const data = await api("/api/download", {
        method: "POST",
        body: JSON.stringify(downloadPayload(items, outputSubdir)),
      });
      activeJobs.add(data.job_id);
      playlistCache.set(data.job_id, { title: label || "Download" });
      updateJobsChrome();
      openJobsPanel(true);
      ensurePolling();
      await refreshJob(data.job_id);
      showAlert(alertEl, `Download started (${items.length} track(s)).`, "ok");
    } catch (err) {
      showAlert(alertEl, err.message, "error");
    }
  }

  async function startDownload(items, outputSubdir, label, alertEl) {
    if (!items.length) return;

    if (settings.checkDuplicates) {
      showAlert(alertEl, "Checking library for duplicates…", "info");
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
            showAlert(alertEl, "Download cancelled.", "info");
            return;
          }
          if (choice === "skip") {
            const dupUrls = new Set(check.duplicates.map((d) => d.url));
            items = items.filter((it) => !dupUrls.has(it.url));
            if (!items.length) {
              showAlert(alertEl, "All selected tracks were duplicates — nothing to download.", "info");
              return;
            }
          }
        }
      } catch (err) {
        showAlert(alertEl, `Duplicate check failed: ${err.message}`, "error");
        return;
      }
    }

    await queueDownload(items, outputSubdir, label, alertEl);
  }

  function ensurePolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      if (!activeJobs.size) {
        clearInterval(pollTimer);
        pollTimer = null;
        updateJobsChrome();
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
      updateJobsChrome();
      if (job.status === "done" || job.status === "failed") {
        activeJobs.delete(jobId);
        updateJobsChrome();
      }
    } catch (err) {
      els.jobsStatusLine.textContent = `Job error: ${err.message}`;
    }
  }

  function updateJobsChrome() {
    const active = activeJobs.size;
    const totalItems = [...jobStore.values()].reduce((n, j) => n + j.items.length, 0);
    const doneItems = [...jobStore.values()].reduce(
      (n, j) => n + j.items.filter((i) => i.status === "done").length,
      0
    );

    if (active > 0) {
      els.jobsBadge.hidden = false;
      els.jobsBadge.textContent = String(active);
      els.jobsToggleBtn.classList.add("has-active-jobs");
      els.jobsStatusLine.textContent = `${active} job(s) running · ${doneItems}/${totalItems} tracks done`;
    } else {
      els.jobsBadge.hidden = totalItems === 0;
      if (totalItems > 0) {
        els.jobsBadge.hidden = false;
        els.jobsBadge.textContent = String(jobStore.size);
      }
      els.jobsToggleBtn.classList.remove("has-active-jobs");
      els.jobsStatusLine.textContent =
        totalItems > 0
          ? `${doneItems}/${totalItems} tracks finished · ${jobStore.size} job(s) in list`
          : "No active downloads.";
    }
  }

  function isUnavailableError(error) {
    return /video unavailable/i.test(error || "");
  }

  function isForbiddenError(error) {
    return /403|forbidden/i.test(error || "");
  }

  function isAgeGateError(error) {
    return /sign in to confirm your age|age.restricted|confirm your age/i.test(
      String(error || "")
    );
  }

  async function retrySameUrl(item) {
    openJobsPanel(true);
    await startDownload([{ url: item.url, title: item.title || null }], null, "Retry", null);
  }

  async function retryViaSearch(item) {
    const query = (item.title || "").trim();
    if (!query) {
      els.jobsStatusLine.textContent = "No title to search.";
      return;
    }
    els.jobsStatusLine.textContent = `Re-searching: ${query.slice(0, 40)}…`;
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ queries: [query], limit: 5, ...authPayload() }),
      });
      const first = data.results?.[0]?.candidates?.[0];
      if (!first) {
        els.jobsStatusLine.textContent = "No search match.";
        return;
      }
      await startDownload([{ url: first.url, title: first.title }], null, "Retry search", null);
    } catch (err) {
      els.jobsStatusLine.textContent = `Search retry failed: ${err.message}`;
    }
  }

  function renderJobs() {
    if (!jobStore.size) {
      els.jobsList.innerHTML = `<p class="empty">No jobs yet.</p>`;
      return;
    }
    els.jobsList.innerHTML = [...jobStore.entries()]
      .reverse()
      .map(([jobId, job]) => {
        const meta = playlistCache.get(jobId);
        const head = meta?.title || `Job ${jobId.slice(0, 8)}`;
        const itemsHtml = job.items
          .map((item, idx) => {
            const title = item.title || item.url;
            const pct = Math.round(item.progress || 0);
            const failed = item.status === "failed";
            const actions = failed
              ? `<div class="job-actions">
                  <button type="button" class="btn btn-secondary retry-same" data-job="${escapeHtml(
                    jobId
                  )}" data-idx="${idx}">Retry</button>
                  <button type="button" class="btn btn-secondary retry-search" data-job="${escapeHtml(
                    jobId
                  )}" data-idx="${idx}">Re-search</button>
                </div>`
              : "";
            const hint =
              failed && isAgeGateError(item.error)
                ? `<div class="error-text">Tip: Settings → cookies from browser (logged into YouTube), then Retry</div>`
                : failed && isForbiddenError(item.error)
                  ? `<div class="error-text">Tip: set cookies in Settings, then Retry</div>`
                  : failed && isUnavailableError(item.error)
                    ? `<div class="error-text">Tip: use Re-search for another upload</div>`
                    : "";
            return `
              <div class="job-item">
                <div class="job-item-top">
                  <span>${idx + 1}. ${escapeHtml(title)}</span>
                  <span class="status-${item.status}">${item.status}${
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
        return `
          <div class="job-block">
            <div class="job-head">
              <span>${escapeHtml(head)}</span>
              <span>${job.status}</span>
            </div>
            ${itemsHtml}
          </div>
        `;
      })
      .join("");

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

  function clearSettledJobs() {
    for (const [jobId, job] of [...jobStore.entries()]) {
      if (job.status === "done" || job.status === "failed") {
        jobStore.delete(jobId);
        playlistCache.delete(jobId);
        activeJobs.delete(jobId);
      }
    }
    renderJobs();
    updateJobsChrome();
  }

  async function refreshHomeBadges() {
    try {
      const status = await api("/api/sync/status");
      if (status.dueCount > 0) {
        els.homeDuePill.hidden = false;
        els.homeDuePill.textContent = `${status.dueCount} due`;
      } else {
        els.homeDuePill.hidden = true;
      }
      if (status.queueCount > 0) {
        els.homeQueuePill.hidden = false;
        els.homeQueuePill.textContent = `${status.queueCount} in queue`;
      } else {
        els.homeQueuePill.hidden = true;
      }
    } catch {
      /* ignore on home */
    }
  }

  function daysSince(iso) {
    if (!iso) return Infinity;
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return Infinity;
    return (Date.now() - t) / 86400000;
  }

  function playlistDue(pl) {
    return daysSince(pl.lastSyncedAt) >= (settings.syncIntervalDays || 7);
  }

  async function refreshPlaylists() {
    savedPlaylists = await api("/api/playlists");
    if (currentScreen === "sync") renderSavedPlaylists();
    updateSyncDueHint();
  }

  async function refreshSyncQueue() {
    syncQueue = await api("/api/sync/queue");
    if (currentScreen === "sync") renderSyncQueue();
    updateSyncQueueButtons();
  }

  function updateSyncDueHint() {
    const due = savedPlaylists.filter(playlistDue).length;
    if (!els.syncDueHint) return;
    els.syncDueHint.textContent =
      savedPlaylists.length === 0
        ? "Add a playlist URL to monitor."
        : `${savedPlaylists.length} saved · ${due} due (every ${settings.syncIntervalDays} days) · ${syncQueue.length} missing in queue`;
  }

  function updateSyncQueueButtons() {
    const has = syncQueue.length > 0;
    els.syncSelectAllBtn.disabled = !has;
    els.syncSelectNoneBtn.disabled = !has;
    els.syncDownloadSelectedBtn.disabled = !has;
    els.syncDownloadAllBtn.disabled = !has;
    els.syncDismissBtn.disabled = !has;
  }

  function renderSavedPlaylists() {
    updateSyncDueHint();
    if (!savedPlaylists.length) {
      els.savedPlaylists.innerHTML = `<p class="empty">No saved playlists yet.</p>`;
      return;
    }
    els.savedPlaylists.innerHTML = savedPlaylists
      .map((pl) => {
        const due = playlistDue(pl);
        const last = pl.lastSyncedAt
          ? new Date(pl.lastSyncedAt).toLocaleDateString()
          : "never";
        return `
          <div class="saved-row">
            <div>
              <strong>${escapeHtml(pl.title || "Playlist")}</strong>
              <div class="meta">${escapeHtml(pl.source || "?")} · last sync ${escapeHtml(last)}${
          due ? ` <span class="due-tag">due</span>` : ""
        }</div>
            </div>
            <div class="saved-row-actions">
              <button type="button" class="btn btn-secondary pl-sync-one" data-id="${escapeHtml(
                pl.id
              )}">Sync</button>
              <button type="button" class="btn btn-ghost pl-remove" data-id="${escapeHtml(
                pl.id
              )}">Remove</button>
            </div>
          </div>
        `;
      })
      .join("");

    els.savedPlaylists.querySelectorAll(".pl-sync-one").forEach((btn) => {
      btn.addEventListener("click", () => runSync({ playlistIds: [btn.dataset.id] }));
    });
    els.savedPlaylists.querySelectorAll(".pl-remove").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/playlists/${encodeURIComponent(btn.dataset.id)}`, {
            method: "DELETE",
          });
          showAlert(els.syncAlert, "Playlist removed.", "ok");
          await refreshPlaylists();
          await refreshSyncQueue();
          refreshHomeBadges();
        } catch (err) {
          showAlert(els.syncAlert, err.message, "error");
        }
      });
    });
  }

  function renderSyncQueue() {
    updateSyncQueueButtons();
    if (!syncQueue.length) {
      els.syncQueueResults.innerHTML = `<p class="empty">Queue is empty. Run Sync due or Sync all after saving playlists.</p>`;
      return;
    }
    els.syncQueueResults.innerHTML = syncQueue
      .map((item, i) => {
        const label = [item.artists, item.title].filter(Boolean).join(" - ") || item.url;
        const pl = item.playlistTitle ? ` · ${item.playlistTitle}` : "";
        return `
          <label class="track-row">
            <input type="checkbox" name="syncq" value="${escapeHtml(item.id)}" checked />
            <span>${i + 1}. ${escapeHtml(label)}<span class="meta">${escapeHtml(pl)}</span></span>
            <span></span>
          </label>
        `;
      })
      .join("");
  }

  function flashSyncQueue() {
    const section = document.querySelector(".sync-section-queue");
    if (!section) return;
    section.classList.remove("is-updated");
    void section.offsetWidth;
    section.classList.add("is-updated");
  }

  async function runSync({ playlistIds = null, onlyDue = false } = {}) {
    showAlert(els.syncAlert, onlyDue ? "Syncing due playlists…" : "Syncing playlists…", "info");
    try {
      const result = await api("/api/playlists/sync", {
        method: "POST",
        body: JSON.stringify({
          onlyDue: !!onlyDue,
          playlistIds: playlistIds || null,
          ...authPayload(),
        }),
      });
      syncQueue = result.queue || [];
      await refreshPlaylists();
      renderSyncQueue();
      flashSyncQueue();
      refreshHomeBadges();
      const errN = (result.errors || []).length;
      showAlert(
        els.syncAlert,
        `Found ${result.missingCount} missing track(s). Queue now has ${syncQueue.length}.${
          errN ? ` ${errN} playlist error(s).` : ""
        }`,
        errN ? "error" : "ok"
      );
    } catch (err) {
      showAlert(els.syncAlert, err.message, "error");
    }
  }

  async function downloadFromSync({ all = false } = {}) {
    let ids = null;
    if (!all) {
      ids = [...els.syncQueueResults.querySelectorAll('input[type="checkbox"]:checked')].map(
        (cb) => cb.value
      );
      if (!ids.length) {
        showAlert(els.syncAlert, "Select at least one track.", "error");
        return;
      }
    }
    showAlert(els.syncAlert, all ? "Starting download for all…" : "Starting download…", "info");
    try {
      const data = await api("/api/sync/download", {
        method: "POST",
        body: JSON.stringify({
          all: !!all,
          ids,
          concurrency: settings.concurrency,
          embed_metadata: settings.embedMetadata,
          audio_bitrate: settings.audioBitrate,
          filename_template: settings.filenameTemplate,
          ...authPayload(),
        }),
      });
      activeJobs.add(data.job_id);
      playlistCache.set(data.job_id, { title: "Sync download" });
      await refreshSyncQueue();
      refreshHomeBadges();
      openJobsPanel(true);
      ensurePolling();
      await refreshJob(data.job_id);
      showAlert(els.syncAlert, "Download started from sync queue.", "ok");
    } catch (err) {
      showAlert(els.syncAlert, err.message, "error");
    }
  }

  function renderLibraryReport() {
    if (!lastImportResult) {
      els.libraryReport.innerHTML = `<p class="empty">Run a dry run to preview moves into your music folder.</p>`;
      els.libApplyBtn.disabled = true;
      return;
    }
    const c = lastImportResult.counts || {};
    const summary = Object.entries(c)
      .map(([k, v]) => `${k}: ${v}`)
      .join(" · ");
    const mode = lastImportResult.dry_run ? "Dry run" : "Applied";
    const lines = (lastImportResult.lines || []).slice(-100);
    els.libraryReport.innerHTML = `
      <div class="track-group">
        <p class="track-group-title">${mode} · ${escapeHtml(summary)}</p>
        <pre class="import-log">${escapeHtml(lines.join("\n"))}</pre>
      </div>
    `;
    els.libApplyBtn.disabled = !lastImportResult.dry_run || !(c.scanned > 0);
  }

  async function runLibraryImport(dryRun) {
    showAlert(els.libAlert, dryRun ? "Running dry run…" : "Applying import…", "info");
    els.libDryRunBtn.disabled = true;
    els.libApplyBtn.disabled = true;
    try {
      const result = await api("/api/library/import", {
        method: "POST",
        body: JSON.stringify({
          dryRun: !!dryRun,
          musicDir: settings.musicDir || null,
        }),
      });
      lastImportResult = result;
      renderLibraryReport();
      const c = result.counts || {};
      showAlert(
        els.libAlert,
        `${dryRun ? "Dry run" : "Apply"} complete — moved ${c.moved || 0}, dupes ${
          c.deleted_dupe || 0
        }, failed ${c.failed || 0}.`,
        "ok"
      );
    } catch (err) {
      showAlert(els.libAlert, err.message, "error");
    } finally {
      els.libDryRunBtn.disabled = false;
      els.libApplyBtn.disabled = !(lastImportResult && lastImportResult.dry_run);
    }
  }

  // --- Search ---
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
          )}</p><div class="error-text" style="padding:0.5rem 0.9rem">${escapeHtml(
            result.error
          )}</div></div>`;
        }
        if (!result.candidates.length) {
          return `<div class="track-group"><p class="track-group-title">${escapeHtml(
            result.query
          )}</p><div class="error-text" style="padding:0.5rem 0.9rem">No matches</div></div>`;
        }
        const options = result.candidates
          .map((c, ci) => {
            const checked = ci === 0 ? "checked" : "";
            return `
              <label class="track-row">
                <input type="radio" name="q${qi}" value="${escapeHtml(c.url)}" data-title="${escapeHtml(
              c.title
            )}" ${checked} />
                <span>${escapeHtml(c.channel || "Unknown")} — ${escapeHtml(c.title)}</span>
                <span class="meta">${formatDuration(c.duration)}</span>
              </label>
            `;
          })
          .join("");
        return `<div class="track-group"><p class="track-group-title">${escapeHtml(
          result.query
        )}</p>${options}</div>`;
      })
      .join("");
    els.searchDownloadBtn.disabled = false;
  }

  els.searchBtn.addEventListener("click", async () => {
    const lines = els.searchInput.value
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    if (!lines.length) {
      showAlert(els.searchAlert, "Enter at least one song.", "error");
      return;
    }
    els.searchBtn.disabled = true;
    showAlert(els.searchAlert, `Searching ${lines.length}…`, "info");
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({
          queries: lines,
          limit: settings.searchResultCount,
          ...authPayload(),
        }),
      });
      renderSearchResults(data.results);
      showAlert(els.searchAlert, "Pick a match for each song, then download.", "ok");
    } catch (err) {
      showAlert(els.searchAlert, err.message, "error");
    } finally {
      els.searchBtn.disabled = false;
    }
  });

  els.searchDownloadBtn.addEventListener("click", async () => {
    const groups = [...els.searchResults.querySelectorAll(".track-group")];
    const items = [];
    groups.forEach((group) => {
      const selected = group.querySelector('input[type="radio"]:checked');
      if (selected) {
        items.push({ url: selected.value, title: selected.dataset.title || null });
      }
    });
    await startDownload(items, null, "Search download", els.searchAlert);
  });

  // --- Link ---
  els.linkDownloadBtn.addEventListener("click", async () => {
    const url = els.linkInput.value.trim();
    if (!url) {
      showAlert(els.linkAlert, "Paste a URL first.", "error");
      return;
    }
    await startDownload([{ url }], null, "Link download", els.linkAlert);
  });

  // --- Playlist one-shot download ---
  function renderPlaylistDl(data) {
    loadedPlaylist = data;
    els.plDlTitle.hidden = false;
    els.plDlTitle.textContent = data.title;
    els.plDlResults.hidden = false;
    els.plDlResults.innerHTML = data.entries
      .map(
        (entry, i) => `
      <label class="track-row">
        <input type="checkbox" name="pldl" value="${escapeHtml(entry.url)}" data-title="${escapeHtml(
          entry.title
        )}" checked />
        <span>${i + 1}. ${escapeHtml(entry.channel || "Unknown")} — ${escapeHtml(entry.title)}</span>
        <span class="meta">${formatDuration(entry.duration)}</span>
      </label>
    `
      )
      .join("");
    els.plDlSelectAllBtn.disabled = false;
    els.plDlSelectNoneBtn.disabled = false;
    els.plDlDownloadBtn.disabled = false;
  }

  els.plDlLoadBtn.addEventListener("click", async () => {
    const url = els.plDlInput.value.trim();
    if (!url) {
      showAlert(els.plDlAlert, "Paste a playlist URL.", "error");
      return;
    }
    els.plDlLoadBtn.disabled = true;
    showAlert(els.plDlAlert, "Loading playlist…", "info");
    try {
      const data = await api("/api/playlist", {
        method: "POST",
        body: JSON.stringify({ url, ...authPayload() }),
      });
      renderPlaylistDl(data);
      showAlert(
        els.plDlAlert,
        `Loaded ${data.entries.length} tracks. Select and download — this playlist is not saved for sync.`,
        "ok"
      );
    } catch (err) {
      showAlert(els.plDlAlert, err.message, "error");
    } finally {
      els.plDlLoadBtn.disabled = false;
    }
  });

  els.plDlSelectAllBtn.addEventListener("click", () => {
    els.plDlResults.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.checked = true;
    });
  });
  els.plDlSelectNoneBtn.addEventListener("click", () => {
    els.plDlResults.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.checked = false;
    });
  });
  els.plDlDownloadBtn.addEventListener("click", async () => {
    const checked = [...els.plDlResults.querySelectorAll('input[type="checkbox"]:checked')];
    if (!checked.length) {
      showAlert(els.plDlAlert, "Select at least one track.", "error");
      return;
    }
    const items = checked.map((cb) => ({
      url: cb.value,
      title: cb.dataset.title || null,
    }));
    const subdir =
      settings.playlistSubfolder && loadedPlaylist ? loadedPlaylist.title : null;
    await startDownload(items, subdir, loadedPlaylist?.title || "Playlist", els.plDlAlert);
  });

  // --- Sync ---
  els.syncAddBtn.addEventListener("click", async () => {
    const url = els.syncAddInput.value.trim();
    if (!url) {
      showAlert(els.syncAlert, "Paste a playlist URL to save.", "error");
      return;
    }
    els.syncAddBtn.disabled = true;
    showAlert(els.syncAlert, "Saving playlist…", "info");
    try {
      await api("/api/playlists", {
        method: "POST",
        body: JSON.stringify({ url, ...authPayload() }),
      });
      els.syncAddInput.value = "";
      await refreshPlaylists();
      refreshHomeBadges();
      showAlert(els.syncAlert, "Playlist saved for sync.", "ok");
    } catch (err) {
      showAlert(els.syncAlert, err.message, "error");
    } finally {
      els.syncAddBtn.disabled = false;
    }
  });

  els.syncDueBtn.addEventListener("click", () => runSync({ onlyDue: true }));
  els.syncAllBtn.addEventListener("click", () => runSync({}));
  els.syncSelectAllBtn.addEventListener("click", () => {
    els.syncQueueResults.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.checked = true;
    });
  });
  els.syncSelectNoneBtn.addEventListener("click", () => {
    els.syncQueueResults.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.checked = false;
    });
  });
  els.syncDownloadSelectedBtn.addEventListener("click", () => downloadFromSync({ all: false }));
  els.syncDownloadAllBtn.addEventListener("click", () => downloadFromSync({ all: true }));
  els.syncDismissBtn.addEventListener("click", async () => {
    const ids = [...els.syncQueueResults.querySelectorAll('input[type="checkbox"]:checked')].map(
      (cb) => cb.value
    );
    try {
      if (ids.length && ids.length < syncQueue.length) {
        await api("/api/sync/dismiss", { method: "POST", body: JSON.stringify({ ids }) });
      } else {
        await api("/api/sync/dismiss", { method: "POST", body: JSON.stringify({ all: true }) });
      }
      await refreshSyncQueue();
      renderSyncQueue();
      refreshHomeBadges();
      showAlert(els.syncAlert, "Queue updated.", "ok");
    } catch (err) {
      showAlert(els.syncAlert, err.message, "error");
    }
  });

  // --- Library ---
  els.libDryRunBtn.addEventListener("click", () => runLibraryImport(true));
  els.libApplyBtn.addEventListener("click", () => runLibraryImport(false));

  // --- Settings ---
  els.settingsSaveBtn.addEventListener("click", async () => {
    try {
      await saveSettingsToServer(readSettingsForm());
      fillSettingsForm();
      showAlert(els.settingsAlert, "Settings saved.", "ok");
    } catch (err) {
      showAlert(els.settingsAlert, err.message, "error");
    }
  });
  els.settingsResetBtn.addEventListener("click", async () => {
    try {
      await saveSettingsToServer({ ...DEFAULTS });
      fillSettingsForm();
      showAlert(els.settingsAlert, "Defaults restored.", "ok");
    } catch (err) {
      showAlert(els.settingsAlert, err.message, "error");
    }
  });

  // --- FS browser ---
  async function loadFsRoots() {
    const data = await api("/api/fs/roots");
    fsState = { path: "", parent: null, entries: data.entries, selectedIsDir: true };
    renderFsList();
  }

  async function loadFsPath(path) {
    const q = fsPickMode === "file" ? `&include_files=true&file_ext=txt` : "";
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
      els.fsList.innerHTML = `<p class="empty">No entries</p>`;
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
          els.fsCurrentPath.textContent = err.message;
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
    $("fsTitle").textContent = mode === "file" ? "Select cookies.txt" : "Select folder";
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
          /* roots */
        }
      }
      await loadFsRoots();
    } catch (err) {
      els.fsCurrentPath.textContent = err.message;
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
      els.fsCurrentPath.textContent = err.message;
    }
  });
  els.fsSelectBtn.addEventListener("click", () => {
    if (!fsState.path) return;
    if (fsPickMode === "file" && fsState.selectedIsDir !== false) return;
    if (fsPickMode === "dir" && fsState.selectedIsDir === false) return;
    if (fsTarget === "cookie") els.setCookieFile.value = fsState.path;
    else els.setMusicDir.value = fsState.path;
    els.fsModal.hidden = true;
  });
  els.fsCancelBtn.addEventListener("click", () => {
    els.fsModal.hidden = true;
  });

  // --- Navigation ---
  document.querySelectorAll(".home-card[data-go]").forEach((card) => {
    card.addEventListener("click", () => showScreen(card.dataset.go));
  });
  els.brandHomeBtn.addEventListener("click", () => goHome());
  els.navHomeBtn.addEventListener("click", () => goHome());
  els.jobsToggleBtn.addEventListener("click", () => {
    openJobsPanel(els.jobsPanel.hidden);
  });
  els.jobsCloseBtn.addEventListener("click", () => openJobsPanel(false));
  els.jobsBackdrop.addEventListener("click", () => openJobsPanel(false));
  els.clearJobsBtn.addEventListener("click", () => clearSettledJobs());

  async function boot() {
    showScreen("home");
    try {
      await migrateLocalStorageIfNeeded();
      await loadSettingsFromServer();
      fillSettingsForm();
      await refreshPlaylists();
      await refreshSyncQueue();
      await refreshHomeBadges();
      updateJobsChrome();
    } catch (err) {
      fillSettingsForm();
      console.warn("Boot warning", err);
    }
  }

  boot();
})();
