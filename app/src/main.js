import { invoke } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { mockBackend } from "./services/mockBackend.js";
import "./styles/app.css";

const DEFAULT_SETTINGS = {
  theme: "naturalWhite",
  density: "comfortable",
  scale: 1,
  searchResultCount: 20,
  developerSearchDiagnostics: false,
};

const DEFAULT_TABS = [
  {
    id: crypto.randomUUID(),
    type: "round",
    title: "Round Prep",
    state: {},
  },
];

const commands = [
  { id: "search.evidence", title: "Search evidence", keywords: "backfile query cards" },
  { id: "document.import", title: "Add source document", keywords: "docx library" },
  { id: "browser.open", title: "Open website", keywords: "web google docs research" },
  { id: "round.start", title: "Open evidence library", keywords: "source document import prep" },
  { id: "tools.cardSeparator", title: "Card separator", keywords: "docx split cards highlights citation jsonl" },
  { id: "settings.open", title: "Open settings", keywords: "appearance developer search ai" },
];

const ROUND_VIEWS = [
  { id: "setup", label: "Library", requiresReady: false },
  { id: "cards", label: "Cards", requiresReady: false },
  { id: "evidence", label: "Search", requiresReady: false },
];

const ACTIVITY_IDS = ["round", "tools"];

const state = {
  settings: { ...DEFAULT_SETTINGS },
  workspaceName: "Default Workspace",
  tabs: [...DEFAULT_TABS],
  activeTabId: DEFAULT_TABS[0].id,
  activeActivity: "round",
  search: {
    query: "",
    results: [],
    loading: false,
    error: "",
    logs: [],
    runtime: null,
  },
  paths: null,
  commandPaletteOpen: false,
  commandText: "",
  settingsOpen: false,
  settingsCategory: "Appearance",
  layout: {
    activityWidth: 72,
    sidebarWidth: 260,
  },
  round: null,
  roundSourcePaths: { ours: "" },
  roundUploads: { ours: null },
  roundView: "setup",
  roundBuildTick: 0,
  roundEvidence: [],
  roundEvidenceFilter: "",
  roundAsk: {
    query: "",
    mode: "smart",
    loading: false,
    results: [],
    generated: null,
    error: "",
  },
  tools: {
    activeTool: "card-separator",
    cardSeparator: {
      docxPath: "",
      running: false,
      ran: false,
      rawText: "",
      error: "",
      stderr: "",
      sourceFile: "",
      executablePath: "",
      cardCount: null,
    },
  },
  cardSeparatorUpload: null,
  focusedCard: null,
};

const app = document.querySelector("#app");
const WEB_STORAGE_KEYS = {
  settings: "secret-agenda.settings",
  workspace: "secret-agenda.workspace",
};

function showStartupError(error) {
  console.error(error);
  if (!app) return;
  app.innerHTML = `
    <main class="app-shell startup-failure">
      <section>
        <h1>Secret Agenda could not finish loading.</h1>
        <p>${escapeHtml(String(error?.message || error || "Unknown startup error"))}</p>
        <button onclick="location.reload()">Reload</button>
      </section>
    </main>
  `;
}

function isTauri() {
  return Boolean(window.__TAURI_INTERNALS__);
}

async function call(command, payload = {}) {
  if (command === "run_card_separator" && !isTauri()) {
    throw new Error("Card Separator requires the Tauri desktop backend.");
  }
  if (!isTauri()) {
    return mockInvoke(command, payload);
  }
  return invoke(command, payload);
}

async function mockInvoke(command, payload) {
  if (command === "load_settings") return loadWebJson(WEB_STORAGE_KEYS.settings, DEFAULT_SETTINGS);
  if (command === "save_settings") {
    saveWebJson(WEB_STORAGE_KEYS.settings, payload.settings);
    return null;
  }
  if (command === "load_workspace") {
    return loadWebJson(WEB_STORAGE_KEYS.workspace, {
      workspaceName: "Browser Preview",
      tabs: DEFAULT_TABS,
      activeTabId: DEFAULT_TABS[0].id,
      activeActivity: "round",
    });
  }
  if (command === "save_workspace") {
    saveWebJson(WEB_STORAGE_KEYS.workspace, payload.workspace);
    return null;
  }
  if (command === "platform_paths") {
    return { appData: "Preview mode", cache: "Preview mode", documents: "Preview mode" };
  }
  if (command === "copy_evidence") {
    const card = payload.card || {};
    const plain = `${card.title || card.citation || "Evidence Card"}\n${card.tag || ""}\n\n${card.citation || ""}\n\n${card.body || card.bodyPreview || ""}`.trim();
    await navigator.clipboard?.writeText(plain);
    return null;
  }
  if (command === "open_external_url") {
    window.open(payload.url, "_blank", "noopener,noreferrer");
    return null;
  }
  if (command === "reveal_path") {
    flashStatus(`Data directory: ${payload.path}`);
    return null;
  }
  if (command === "search_evidence") {
    const query = payload.query?.text || "AI sports betting";
    const results = await mockBackend.searchRound({
      query,
      scope: "ours",
      mode: payload.query?.mode || "smart",
    });
    return results.map((result) => ({
      ...result.card,
      title: result.card.citation,
      score: result.score,
      relationship: result.relationship,
      bodyPreview: result.card.body,
      diagnostics: payload.query?.includeDiagnostics
        ? { retrieval: ["mock"], concepts: ["ai", "betting"], finalScore: result.score }
        : null,
    }));
  }
  return null;
}

function loadWebJson(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) : structuredClone(fallback);
  } catch {
    return structuredClone(fallback);
  }
}

function saveWebJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function activeTab() {
  return state.tabs.find((tab) => tab.id === state.activeTabId) || state.tabs[0];
}

function saveWorkspaceSoon() {
  clearTimeout(saveWorkspaceSoon.timer);
  saveWorkspaceSoon.timer = setTimeout(() => {
    call("save_workspace", {
      workspace: {
        workspaceName: state.workspaceName,
        tabs: state.tabs,
        activeTabId: state.activeTabId,
        activeActivity: state.activeActivity,
        round: state.round,
        roundSourcePaths: state.roundSourcePaths,
        roundView: state.roundView,
        roundEvidenceFilter: state.roundEvidenceFilter,
        roundAsk: state.roundAsk,
        tools: state.tools,
        layout: state.layout,
      },
    }).catch(console.error);
  }, 150);
}

function applyTheme() {
  document.documentElement.dataset.theme = resolveTheme();
  document.documentElement.dataset.density = state.settings.density;
  document.documentElement.style.setProperty("--scale", state.settings.scale);
}

function resolveTheme() {
  if (state.settings.theme === "system") {
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "natural";
  }
  return state.settings.theme === "naturalWhite" ? "natural" : "dark";
}

function openTab(type, title, tabState = {}) {
  const tab = { id: crypto.randomUUID(), type, title, state: tabState };
  state.tabs.push(tab);
  state.activeTabId = tab.id;
  saveWorkspaceSoon();
  render();
  return tab;
}

function closeTab(id) {
  if (state.tabs.length === 1) return;
  const index = state.tabs.findIndex((tab) => tab.id === id);
  state.tabs = state.tabs.filter((tab) => tab.id !== id);
  if (state.activeTabId === id) {
    state.activeTabId = state.tabs[Math.max(0, index - 1)]?.id || state.tabs[0].id;
  }
  saveWorkspaceSoon();
  render();
}

async function ensureSearchRuntime(shouldRender = false) {
  if (!isTauri()) return null;
  try {
    const runtime = await call("ensure_ollama_runtime");
    state.search.runtime = runtime;
    state.search.logs = runtime.logs || [];
    if (!runtime.ready) {
      state.search.logs = [...state.search.logs, "WARNING: Semantic search is not fully ready. Any fallback will be shown here."];
    }
  } catch (error) {
    state.search.runtime = { ready: false };
    state.search.logs = [`ERROR: Could not inspect Ollama: ${String(error)}`];
  }
  if (shouldRender) render();
  return state.search.runtime;
}

async function runSearch(queryText) {
  state.search.query = queryText;
  state.search.loading = true;
  state.search.error = "";
  state.search.logs = ["Checking local Ollama and search pipeline…"];
  render();

  if (isTauri() && !state.search.runtime?.ready) {
    await ensureSearchRuntime(false);
    render();
  }

  try {
    if (isTauri() && state.round?.id) {
      const response = await call("ask_round", {
        request: {
          roundId: state.round.id,
          query: queryText,
          scope: "ours",
          mode: "smart",
          limit: state.settings.searchResultCount,
          generateAnswer: false,
          includeDiagnostics: true,
        },
      });
      state.search.runtime = response.runtime || null;
      state.search.logs = response.logs || [];
      if (response.runtime && !response.runtime.ready) {
        state.search.logs.push("WARNING: Ollama was not fully ready; review the runtime entries above.");
      }
      state.search.results = sortSearchCards((response.results || []).map((result) => ({
        ...result.card,
        score: result.score,
      })));
    } else {
      state.search.logs = ["Browser preview uses mock search results."];
      state.search.results = sortSearchCards(await call("search_evidence", {
        query: {
          text: queryText,
          limit: state.settings.searchResultCount,
          mode: "hybrid",
          includeDiagnostics: true,
        },
      }));
    }
  } catch (error) {
    state.search.results = [];
    state.search.error = String(error);
    state.search.logs = [...state.search.logs, `ERROR: ${String(error)}`];
  } finally {
    state.search.loading = false;
    render();
  }
}

function sortSearchCards(cards) {
  const score = (card) => {
    const value = Number(card?.score);
    return Number.isFinite(value) ? value : -1;
  };
  return [...cards].sort((left, right) => score(right) - score(left));
}

function formatRetrievalScore(score) {
  const value = Number(score);
  return Number.isFinite(value) ? value.toFixed(3) : "—";
}

function highlightedEvidence(card) {
  return (card?.highlights || [])
    .map((highlight) => typeof highlight === "string" ? highlight : highlight?.text)
    .filter((highlight) => typeof highlight === "string" && highlight.trim());
}

function openEvidenceCard(card) {
  state.focusedCard = card;
  render();
}

function renderEvidenceDrawer(card) {
  const source = card.documentName || card.sourceName || card.section || "Original evidence card";
  const location = [card.startOffset, card.endOffset].every(Number.isFinite)
    ? `Source span ${card.startOffset}–${card.endOffset}`
    : "Original source preserved";
  return `
    <div class="overlay evidence-overlay" data-action="close-evidence">
      <aside class="evidence-drawer" data-modal data-stop-overlay aria-label="Evidence card">
        <header class="evidence-drawer-header">
          <div>
            <p class="eyebrow">Source card</p>
            <h1>${escapeHtml(card.title || card.citation || "Evidence card")}</h1>
          </div>
          <button class="drawer-close" data-action="close-evidence" aria-label="Close evidence card">×</button>
        </header>
        <div class="evidence-drawer-meta">
          <span>${escapeHtml(source)}</span><span>•</span><span>${escapeHtml(location)}</span>
        </div>
        ${card.tag ? `<p class="evidence-drawer-tag">${escapeHtml(card.tag)}</p>` : ""}
        <section class="evidence-drawer-body">
          <h2>Original text</h2>
          <p>${escapeHtml(card.body || card.bodyPreview || "No source text is available for this card.")}</p>
        </section>
        <footer class="evidence-drawer-actions">
          <button class="text-button" data-action="copy-focused-card">Copy card</button>
          ${card.url ? `<button class="text-button strong" data-open-url="${escapeAttr(card.url)}">Open source →</button>` : ""}
        </footer>
      </aside>
    </div>
  `;
}

async function copyCard(card) {
  try {
    await call("copy_evidence", { card });
    flashStatus("Copied card with rich HTML + plain text.");
  } catch (error) {
    flashStatus(`Copy failed: ${error}`);
  }
}

function flashStatus(message) {
  state.statusMessage = message;
  render();
  setTimeout(() => {
    if (state.statusMessage === message) {
      state.statusMessage = "";
      render();
    }
  }, 2500);
}

function executeCommand(id, payload = "") {
  const commandPayload = payload;
  state.commandPaletteOpen = false;
  state.commandText = "";

  if (id === "settings.open") {
    state.settingsOpen = true;
  } else if (id === "browser.open") {
    call("open_external_url", { url: commandPayload || "https://docs.google.com" }).catch(console.error);
  } else if (id === "round.start" || id === "document.import") {
    state.activeActivity = "round";
    state.roundView = "setup";
    ensureRound();
  } else if (id === "tools.cardSeparator") {
    state.activeActivity = "tools";
    state.tools.activeTool = "card-separator";
  } else if (id === "search.evidence") {
    state.activeActivity = "round";
    state.roundView = "evidence";
    runSearch(commandPayload);
  }

  saveWorkspaceSoon();
  render();
}

async function ensureRound() {
  if (state.round) return state.round;
  state.round = isTauri()
    ? await call("create_round_workspace")
    : await mockBackend.createRound();
  saveWorkspaceSoon();
  render();
  return state.round;
}

async function addRoundSource(file) {
  const library = await ensureRound();
  const upload = state.roundUploads.ours || (file ? await uploadFromFile(file) : null);
  const stagedSourcePath = state.roundSourcePaths.ours?.trim();
  const sourcePath = upload?.path || sourcePathFromFile(file) || (!upload?.text && !upload?.bytes ? stagedSourcePath : "");
  const sourceBytes = upload?.bytes || null;
  if (!sourcePath && !sourceBytes?.length) {
    flashStatus("Choose or drop a DOCX file first.");
    return;
  }

  if (isTauri()) {
    const source = await call("import_round_source", {
      request: {
        side: "ours",
        roundId: library.id,
        sourcePath,
        sourceName: upload?.name || file?.name || "",
        sourceBytes,
      },
    });
    state.round = {
      ...library,
      status: "configuring",
      sources: [...library.sources.filter((existing) => existing.side !== "ours"), source],
    };
    flashStatus("Source added to the library.");
  } else {
    state.round = await mockBackend.addRoundSource(library, "ours", file || { name: upload?.name || "evidence-library.docx" });
  }
  state.roundView = "setup";
  state.activeActivity = "round";
  saveWorkspaceSoon();
  render();
}

function sourcePathFromFile(file) {
  return file?.path || file?.webkitRelativePath || "";
}

async function uploadFromFile(file) {
  if (!file) return null;
  const path = sourcePathFromFile(file);
  const name = file.name || "upload.docx";
  if (!path && name.toLowerCase().endsWith(".docx")) {
    return {
      name,
      path: "",
      text: "",
      bytes: Array.from(new Uint8Array(await file.arrayBuffer())),
    };
  }
  const text = path ? "" : await file.text();
  return { name, path, text, bytes: null };
}

function isGrammarUpload(fileOrPath) {
  const name = typeof fileOrPath === "string" ? fileOrPath : fileOrPath?.name || "";
  return name.toLowerCase().endsWith(".sa");
}

async function acceptRoundFiles(_side, files) {
  const item = Array.from(files || []).find((candidate) => {
    const name = typeof candidate === "string" ? candidate : candidate?.name || "";
    return name.toLowerCase().endsWith(".docx");
  });
  if (!item) {
    flashStatus("Choose a DOCX file for the native library.");
    return;
  }

  const sourcePath = typeof item === "string" ? item : "";
  const upload = sourcePath
    ? { name: sourcePath.split(/[\/]/).pop() || "source.docx", path: sourcePath, text: "", bytes: null }
    : await uploadFromFile(item);
  state.roundUploads.ours = upload;
  state.roundSourcePaths.ours = upload.path || upload.name;
  await addRoundSource(typeof item === "string" ? null : item);
}

async function buildRound() {
  const round = await ensureRound();
  if (isTauri()) {
    if (!round.sources.length) {
      flashStatus("Add a DOCX first.");
      return;
    }
    state.round = { ...round, status: "building" };
    saveWorkspaceSoon();
    render();
    try {
      const built = await call("build_round_library", {
        request: { roundId: round.id },
      });
      state.round = {
        ...round,
        status: built.status || "ready",
        sources: round.sources.map((source) => ({
          ...source,
          status: "ready",
          cardCount: built.cardCount ?? source.cardCount,
          parseProgress: 1,
          indexProgress: 1,
          diagnostics: [...(source.diagnostics || []), ...(built.diagnostics || [])],
        })),
      };
      state.roundView = "evidence";
      await refreshRoundEvidence(false);
      flashStatus("Library ready.");
    } catch (error) {
      state.round = { ...round, status: "configuring" };
      flashStatus("Build failed: " + String(error));
    }
    saveWorkspaceSoon();
    render();
    return;
  }
  if (!round.sources.some((source) => source.side === "ours")) {
    flashStatus("Add a source document first.");
    return;
  }
  clearInterval(buildRound.timer);
  state.round = await mockBackend.buildRound(round);
  state.roundBuildTick = 0;
  saveWorkspaceSoon();
  render();

  buildRound.timer = setInterval(async () => {
    state.roundBuildTick += 1;
    state.round = mockBackend.progressRoundBuild(state.round, state.roundBuildTick);
    if (state.round.status === "ready") {
      clearInterval(buildRound.timer);
      state.roundView = "evidence";
      state.roundEvidence = await mockBackend.listEvidence({ scope: "ours", query: state.roundEvidenceFilter });
      flashStatus("Library ready. Search is available.");
    }
    saveWorkspaceSoon();
    render();
  }, 520);
}

async function refreshRoundEvidence(shouldRender = true) {
  try {
    state.roundEvidence = isTauri()
      ? await call("list_round_evidence", {
          query: {
            roundId: state.round?.id || "",
            scope: "ours",
            query: state.roundEvidenceFilter,
            limit: 150,
          },
        })
      : await mockBackend.listEvidence({
          scope: "ours",
          query: state.roundEvidenceFilter,
        });
  } catch (error) {
    state.roundEvidence = [];
    state.statusMessage = `Evidence unavailable: ${String(error)}`;
  }
  if (shouldRender) render();
}

async function runRoundAsk(queryText) {
  state.roundAsk = {
    ...state.roundAsk,
    query: queryText,
    loading: true,
    error: "",
    results: [],
    generated: null,
  };
  render();

  try {
    const response = isTauri()
      ? await call("ask_round", {
          request: {
            roundId: state.round?.id || "",
            query: queryText,
            scope: "ours",
            mode: state.roundAsk.mode,
            limit: state.settings.searchResultCount,
            generateAnswer: true,
            includeDiagnostics: state.settings.developerSearchDiagnostics || state.roundAsk.mode === "advanced",
          },
        })
      : null;
    const results = response?.results || await mockBackend.searchRound({
          query: queryText,
          scope: "ours",
          mode: state.roundAsk.mode,
        });
    const generated = response?.generated || await mockBackend.generateAnswer({
          query: queryText,
          evidenceIds: results.slice(0, 2).map((result) => result.card.id),
          style: "rebuttal",
        });
    state.roundAsk = {
      ...state.roundAsk,
      loading: false,
      results,
      generated,
    };
  } catch (error) {
    state.roundAsk = {
      ...state.roundAsk,
      loading: false,
      error: String(error),
    };
  }
  render();
}

function addToPrepBoard(flow) {
  if (!state.round) return;
  const entry = {
    id: crypto.randomUUID(),
    prompt: flow.prompt || "Prep prompt",
    response: flow.response || "",
    evidenceIds: Array.isArray(flow.evidenceIds) ? flow.evidenceIds : [],
    notes: flow.notes || "",
    savedAt: new Date().toISOString(),
  };
  state.round = {
    ...state.round,
    flows: [...(state.round.flows || []), entry],
  };
  saveWorkspaceSoon();
}

function addAskResultToFlow(index) {
  const result = state.roundAsk.results[index];
  if (!result || !state.round) return;
  addToPrepBoard({
    prompt: state.roundAsk.query || "Prep prompt",
    response: `${result.relationship}: ${result.explanation}`,
    evidenceIds: [result.card.id],
  });
  flashStatus("Added evidence to the Prep Board.");
  render();
}

function addGeneratedToFlow() {
  if (!state.roundAsk.generated || !state.round) return;
  addToPrepBoard({
    prompt: state.roundAsk.query || "Prep prompt",
    response: state.roundAsk.generated.text,
    evidenceIds: state.roundAsk.generated.sources,
  });
  state.roundView = "flow";
  flashStatus("Added draft to the Prep Board.");
  render();
}

async function runCardSeparatorPreview() {
  const tool = state.tools.cardSeparator;
  if (!tool.docxPath.trim()) {
    flashStatus("Drop or choose a DOCX file first.");
    return;
  }
  state.tools.cardSeparator = {
    ...tool,
    running: true,
    ran: false,
    error: "",
    stderr: "",
    rawText: "",
    cardCount: null,
  };
  render();
  try {
    const response = await call("run_card_separator", {
      request: {
        docxPath: tool.docxPath.trim(),
        sourceName: state.cardSeparatorUpload?.name || "",
        docxBytes: state.cardSeparatorUpload?.bytes || null,
      },
    });
    state.tools.cardSeparator = {
      ...state.tools.cardSeparator,
      running: false,
      ran: true,
      rawText: response.output || "",
      stderr: response.stderr || "",
      sourceFile: response.sourceFile || "",
      executablePath: response.executablePath || "",
      cardCount: response.cardCount ?? null,
    };
    flashStatus("Card Separator finished.");
  } catch (error) {
    state.tools.cardSeparator = {
      ...state.tools.cardSeparator,
      running: false,
      ran: false,
      rawText: "",
      stderr: "",
      error: String(error),
      cardCount: null,
    };
    flashStatus("Card Separator failed.");
  }
  saveWorkspaceSoon();
  render();
}

function copySeparatorText() {
  const text = state.tools.cardSeparator.rawText || "";
  navigator.clipboard?.writeText(text);
  flashStatus("Copied separated-card text.");
}

async function acceptCardSeparatorFiles(files) {
  const items = Array.from(files || []);
  const docx = items.find((item) => {
    const name = typeof item === "string" ? item : item?.name || "";
    return name.toLowerCase().endsWith(".docx");
  });
  if (!docx) {
    flashStatus("Drop a DOCX file for Card Separator.");
    return;
  }
  const path = typeof docx === "string" ? docx : sourcePathFromFile(docx) || docx.name || "";
  state.cardSeparatorUpload = typeof docx === "string" || sourcePathFromFile(docx)
    ? null
    : {
        name: docx.name || "card-separator.docx",
        bytes: Array.from(new Uint8Array(await docx.arrayBuffer())),
      };
  state.tools.cardSeparator = {
    ...state.tools.cardSeparator,
    docxPath: path,
    running: false,
    ran: false,
    rawText: "",
    error: "",
    stderr: "",
    cardCount: null,
  };
  state.activeActivity = "tools";
  state.tools.activeTool = "card-separator";
  flashStatus("DOCX staged for Card Separator.");
  saveWorkspaceSoon();
  render();
}

function findEvidenceCard(id) {
  return [...state.search.results, ...state.roundEvidence, ...state.roundAsk.results.map((result) => result.card)].find((card) => card?.id === id);
}

function render() {
  applyTheme();
  if (!app) return;
  app.innerHTML = `
    <main class="app-shell">
      ${renderTopbar()}
      <section class="workspace-grid" style="--sidebar-width: ${state.layout.sidebarWidth}px;">
        ${renderSidebar()}
        <div class="resize-handle sidebar-resize" data-resize-target="sidebar" title="Resize sidebar"></div>
        <section class="editor-area">
          ${renderPanel()}
        </section>
      </section>
      ${renderStatusBar()}
      ${state.focusedCard ? renderEvidenceDrawer(state.focusedCard) : ""}
      ${state.commandPaletteOpen ? renderCommandPalette() : ""}
      ${state.settingsOpen ? renderSettingsDialog() : ""}
    </main>
  `;
}

function renderTopbar() {
  return `
    <header class="topbar">
      <div class="brand" aria-label="seKret aGenda">
        <span class="brand-mark">sa</span>
        <span class="brand-copy"><strong>seKret aGenda</strong><small>debate evidence</small></span>
      </div>
      <nav class="primary-nav" aria-label="Main workspace">
        <button class="${state.activeActivity === "round" ? "active" : ""}" data-activity="round">Round Prep</button>
        <button class="${state.activeActivity === "tools" ? "active" : ""}" data-activity="tools">Tools</button>
      </nav>
      <button class="command-button" data-action="open-command" aria-label="Search commands">
        <span>Search commands or evidence</span><kbd>${shortcutLabel("K")}</kbd>
      </button>
      <button class="topbar-icon" data-action="open-settings" title="Settings" aria-label="Settings">•••</button>
    </header>
  `;
}

function renderActivityBar() {
  return "";
}

function renderSidebar() {
  const isRound = state.activeActivity === "round";
  return `
    <aside class="sidebar">
      <div class="sidebar-heading">
        <p>${escapeHtml(state.workspaceName)}</p>
        <h2>${isRound ? "Round Prep" : "Tools"}</h2>
      </div>
      ${isRound ? renderRoundSidebar() : renderToolsSidebar()}
      <div class="sidebar-spacer"></div>
      <div class="sidebar-footer">
        <span class="status-dot"></span>
        <span>${state.search.error ? "Evidence index needs attention" : "Local evidence ready"}</span>
      </div>
    </aside>
  `;
}

function renderToolsSidebar() {
  const separator = state.tools.activeTool === "card-separator";
  return `
    <nav class="library-nav" aria-label="Tool navigation">
      <button class="${separator ? "active" : ""}" data-tool="card-separator"><span>Card separator</span></button>
      <button data-action="open-data-dir"><span>Workspace data</span></button>
    </nav>
  `;
}

function renderRoundSidebar() {
  return `
    <nav class="round-side-nav" aria-label="Round Prep navigation">
      ${ROUND_VIEWS.map((view) => `
        <button class="${state.roundView === view.id ? "active" : ""}" data-round-view="${view.id}">
          <span>${view.label}</span>
        </button>
      `).join("")}
    </nav>
  `;
}

function renderTabStrip() {
  return `
    <div class="tab-strip">
      <div class="tabs">
        ${state.tabs
          .map(
            (tab) => `
              <button class="tab ${tab.id === state.activeTabId ? "active" : ""}" data-tab="${tab.id}">
                <span class="tab-indicator"></span>
                <span>${escapeHtml(tab.title)}</span>
                ${state.tabs.length > 1 ? `<span class="tab-close" data-close-tab="${tab.id}">×</span>` : ""}
              </button>
            `,
          )
          .join("")}
      </div>
      <button class="new-tab-button" data-action="new-search" aria-label="New search">+</button>
    </div>
  `;
}

function renderPanel() {
  return state.activeActivity === "tools" ? renderToolView() : renderRoundView();
}

function renderToolView(tabState = {}) {
  const tool = tabState.tool || state.tools.activeTool;
  if (tool === "card-separator") return renderCardSeparatorTool();
  return renderPlaceholder("Tool", "Choose a tool from the sidebar.");
}

function renderCardSeparatorTool() {
  const tool = state.tools.cardSeparator;
  const hasInput = Boolean(tool.docxPath.trim());
  const hasOutput = Boolean(tool.rawText);
  const displayName = hasInput ? basename(tool.docxPath) : "";
  return `
    <section class="view tool-view card-separator-view">
      <header class="separator-drop-zone ${hasInput ? "has-file" : ""}" data-drop-card-separator>
        <div>
          <h1>Card separator</h1>
          <p>${hasInput ? escapeHtml(displayName) : "Drop a DOCX file here"}</p>
        </div>
        <div class="separator-input-actions">
          <input value="${escapeAttr(tool.docxPath)}" placeholder="/absolute/path/to/cards.docx" data-card-separator-field="docxPath" />
          <label class="file-button">
            Browse
            <input type="file" accept=".docx" data-card-separator-file />
          </label>
          <button data-action="run-card-separator" ${hasInput ? "" : "disabled"}>${tool.running ? "Separating..." : "Run Preview"}</button>
        </div>
      </header>

      ${
        hasOutput
          ? `<section class="separator-output">
              <div class="separator-output-header">
                <div>
                  <h2>Raw Text Preview</h2>
                </div>
                <div class="button-row">
                  <button data-action="copy-separator-text">Copy Raw Text</button>
                </div>
              </div>
              <pre class="raw-text-preview">${escapeHtml(tool.rawText)}</pre>
            </section>`
          : `<section class="separator-empty-output ${tool.error ? "has-error" : ""}">
              <span aria-hidden="true">✦</span>
              <p>${tool.error ? escapeHtml(tool.error) : hasInput ? "Run preview" : "Preview"}</p>
            </section>`
      }

    </section>
  `;
}

function basename(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || path || "";
}

function renderRoundView() {
  const library = state.round;
  const currentView = ROUND_VIEWS.some((view) => view.id === state.roundView) ? state.roundView : "setup";
  const pageTitle = { setup: "Library", cards: "Cards", evidence: "Search" };
  return `
    <section class="view round-view">
      <header class="round-header round-workspace-header compact-page-header">
        <h1>${pageTitle[currentView] || "Library"}</h1>
        <span class="round-status ${library?.status || "empty"}">${escapeHtml(statusLabel(library?.status || "empty"))}</span>
      </header>
      ${currentView === "setup" ? renderRoundSetup(library) : ""}
      ${currentView === "cards" ? renderRoundCards(library) : ""}
      ${currentView === "evidence" ? renderRoundEvidence() : ""}
    </section>
  `;
}

function renderRoundUnavailable(view) {
  return `
    <section class="round-empty-state">
      <h2>${escapeHtml(view?.label || "Round")}</h2>
      <p>Add a source document to make this workspace searchable.</p>
      <button data-round-view="setup">Go to Library</button>
    </section>
  `;
}

function renderRoundSetup(library) {
  const source = library?.sources.find((item) => item.side === "ours") || library?.sources[0];
  return `
    <section class="round-setup library-setup">
      ${renderLibrarySourcePanel(source, library?.status)}
      ${library?.status === "building" ? renderBuildProgress(library) : ""}
    </section>
  `;
}

function renderLibrarySourcePanel(source, libraryStatus) {
  const sourcePath = state.roundSourcePaths.ours || source?.path || "";
  if (!source) {
    return `
      <article class="library-drop-zone" data-drop-side="ours">
        <span class="library-drop-icon">↓</span>
        <h2>Drop a case</h2>
        <p>DOCX</p>
        <label class="library-browse-button">
          Browse file
          <input type="file" accept=".docx" data-file-side="ours" />
        </label>
        <div class="library-path-row">
          <input value="${escapeAttr(sourcePath)}" placeholder="/path/to/case.docx" data-source-path="ours" />
          <button data-action="import-source" aria-label="Add file path" title="Add file path">+</button>
        </div>
      </article>
    `;
  }

  const status = libraryStatus === "ready" ? "Ready" : libraryStatus === "building" ? "Building" : "Added";
  return `
    <article class="library-card" data-drop-side="ours">
      <div class="library-file-head">
        <span class="library-file-icon">▤</span>
        <div>
          <h2>${escapeHtml(source.filename)}</h2>
          <span>${status}</span>
        </div>
        <label class="library-replace-button" title="Replace source">
          Replace
          <input type="file" accept=".docx" data-file-side="ours" />
        </label>
      </div>
      <div class="library-stats">
        <div><strong>1</strong><span>source</span></div>
        <div><strong>${source.cardCount || "—"}</strong><span>cards</span></div>
        <div><strong>${status === "Ready" ? "✓" : "—"}</strong><span>index</span></div>
      </div>
      <button class="library-build-button" data-action="build-round" ${libraryStatus === "building" ? "disabled" : ""}>
        ${libraryStatus === "ready" ? "Rebuild library" : libraryStatus === "building" ? "Building…" : "Build library"}
      </button>
    </article>
  `;
}

function renderBuildProgress(library) {
  const sources = library.sources.slice(0, 1);
  return `
    <section class="build-progress">
      <h2>Building library</h2>
      <div class="build-columns">
        ${sources.map((source) => `
          <article class="build-card">
            <h3>Evidence source</h3>
            <strong>${escapeHtml(source.filename)}</strong>
            <div class="progress-row"><span>Extract</span><progress value="${source.parseProgress}" max="1"></progress></div>
            <div class="progress-row"><span>Index</span><progress value="${source.indexProgress}" max="1"></progress></div>
            <small>${source.cardCount} cards detected</small>
          </article>
        `).join("")}
      </div>
      <div class="stage-list">
        ${(library.buildStages || []).map((stage) => `
          <div class="stage-row">
            <span>${stage.status === "complete" ? "Done" : stage.status === "running" ? "Running" : "Waiting"}</span>
            <strong>${escapeHtml(stage.label)}</strong>
            <progress value="${stage.progress}" max="1"></progress>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderSearchLog() {
  const logs = state.search.logs || [];
  const runtime = state.search.runtime;
  const label = runtime ? (runtime.ready ? "Local models ready" : "Attention needed") : "Search log";
  if (!logs.length) return "";
  return `
    <details class="search-log" open>
      <summary><span>${escapeHtml(label)}</span><span>${logs.length} events</span></summary>
      <div class="search-log-lines">
        ${logs.map((log) => `<p class="${String(log).startsWith("ERROR:") ? "error" : String(log).startsWith("WARNING:") ? "warning" : ""}">${escapeHtml(log)}</p>`).join("")}
      </div>
    </details>
  `;
}

function renderRoundEvidence() {
  const query = state.search.query || "";
  const resultLabel = state.search.loading ? "Searching…" : `${state.search.results.length} cards`;
  return `
    <section class="round-retrieval compact-workspace-view">
      <form class="search-input" data-form="round-evidence-search">
        <span class="search-icon">⌕</span>
        <input name="query" value="${escapeAttr(query)}" placeholder="Search evidence" autocomplete="off" autofocus />
        <button>${state.search.loading ? "…" : "Search"}</button>
      </form>
      <div class="view-meta"><span>${resultLabel}</span></div>
      ${state.search.error ? `<div class="warning">${escapeHtml(state.search.error)}</div>` : ""}
      ${renderSearchLog()}
      <div class="results-list">
        ${state.search.results.map((card, index) => renderResultCard(card, index)).join("") || (state.search.loading ? "" : `<div class="empty-search"><strong>Search your library</strong></div>`)}
      </div>
    </section>
  `;
}

function renderRoundEvidenceCard(card) {
  return `
    <article class="mini-card" data-open-card-id="${card.id}">
      <div>
        <h3>${escapeHtml(card.citation)}</h3>
        <p>${escapeHtml(card.tag)}</p>
      </div>
      <span>Source card</span>
    </article>
  `;
}

function renderRoundCards(library) {
  const cards = state.roundEvidence;
  const total = library?.sources?.[0]?.cardCount || cards.length;
  return `
    <section class="round-cards compact-workspace-view">
      <div class="cards-toolbar">
        <span>${total} cards</span>
        <button class="text-button" data-action="refresh-library-cards">Refresh</button>
      </div>
      <div class="cards-browser-list">
        ${cards.map((card, index) => `
          <article class="library-card-row" data-open-card-id="${card.id}" tabindex="0">
            <span class="library-card-number">${index + 1}</span>
            <div class="library-card-content">
              <div class="library-card-meta">${escapeHtml(card.section || "Evidence")}</div>
              <h2>${escapeHtml(card.title || card.citation || "Source card")}</h2>
              <p class="library-card-tag">${escapeHtml(card.tag || "Untitled claim")}</p>
              <p class="library-card-preview">${escapeHtml(card.bodyPreview || card.body || "")}</p>
            </div>
            <span class="library-card-open">Open</span>
          </article>
        `).join("") || `<div class="empty-search"><strong>${library?.status === "ready" ? "No cards loaded" : "Build the library first"}</strong></div>`}
      </div>
    </section>
  `;
}

function renderRoundAsk() {
  const resultCount = state.roundAsk.loading ? "Searching…" : `${state.roundAsk.results.length} cards`;
  return `
    <section class="round-ask compact-workspace-view">
      <form class="ask-form" data-form="round-ask">
        <label class="ask-question">
          <span>Prompt</span>
          <textarea name="query" placeholder="What do you need to write?">${escapeHtml(state.roundAsk.query)}</textarea>
        </label>
        <div class="ask-controls-grid compact-ask-controls">
          ${segmented("ask-mode", state.roundAsk.mode, [["smart", "Smart"], ["exact", "Exact"], ["semantic", "Semantic"], ["advanced", "Inspect"]])}
          <button>${state.roundAsk.loading ? "…" : "Draft"}</button>
        </div>
      </form>
      ${state.roundAsk.error ? `<div class="warning">${escapeHtml(state.roundAsk.error)}</div>` : ""}
      <div class="view-meta"><span>${resultCount}</span></div>
      <div class="ask-layout">
        <section class="ask-results">
          ${state.roundAsk.results.map((result, index) => renderAskResult(result, index)).join("") || `<p class="muted">No cards yet.</p>`}
        </section>
        <section class="ai-response">
          ${renderGeneratedResponse(state.roundAsk.generated)}
        </section>
      </div>
    </section>
  `;
}

function renderAskResult(result, index) {
  const score = Number.isFinite(result.score) ? result.score : 0;
  return `
    <article class="ask-result">
      <div class="result-head">
        <h3>${escapeHtml(result.card.citation || result.card.title || "Evidence")}</h3>
        <span class="score">${Math.round(score * 100)}%</span>
      </div>
      <div class="result-meta">
        <span class="relationship">${escapeHtml(result.relationship)}</span>
        <span>Source preserved</span>
      </div>
      <p>${escapeHtml(result.card.tag)}</p>
      <small>${escapeHtml(result.explanation)}</small>
      ${result.card.bodyPreview || result.card.body ? `<p class="ask-preview">${escapeHtml(result.card.bodyPreview || result.card.body).slice(0, 260)}</p>` : ""}
      <div class="result-actions">
        <button data-open-ask-card="${index}">Open source</button>
        <button data-add-ask-flow="${index}">Add to board</button>
      </div>
    </article>
  `;
}

function renderGeneratedResponse(response) {
  if (state.roundAsk.loading) return `<p class="muted">Retrieving evidence and drafting a grounded response...</p>`;
  if (!response) return `<p class="muted">Working drafts always include their source evidence.</p>`;
  const sources = response.sources || [];
  return `
    <p>${escapeHtml(response.text)}</p>
    <div class="source-list">
      <strong>Evidence used</strong>
      ${sources.map((id) => {
        const card = findEvidenceCard(id);
        return `<button data-open-card-id="${id}">${escapeHtml(card?.citation || id)}</button>`;
      }).join("") || `<span class="muted">No sources selected.</span>`}
    </div>
    <div class="button-row">
      <button data-action="copy-generated">Copy</button>
      <button data-action="add-generated-flow">Add to board</button>
      <button data-action="regenerate-answer">Regenerate</button>
    </div>
  `;
}

function renderRoundFlow(library) {
  return `
    <section class="prep-board compact-workspace-view">
      <section class="flow-board">
        ${(library?.flows || []).map((flow) => `
          <article class="flow-card">
            <h2>${escapeHtml(flow.prompt || flow.opponentClaim || "Prep prompt")}</h2>
            <p>${escapeHtml(flow.response)}</p>
            <small>${flow.evidenceIds.length} source${flow.evidenceIds.length === 1 ? "" : "s"}</small>
          </article>
        `).join("") || `<div class="empty-search"><strong>Nothing saved</strong></div>`}
      </section>
    </section>
  `;
}

function renderRoundBrowser() {
  return `
    <section class="round-browser">
      ${renderBrowserView({ url: "https://docs.google.com" })}
    </section>
  `;
}

function renderSearchView(tabState = {}) {
  const query = state.search.query || tabState.query || "";
  const resultLabel = state.search.loading ? "Searching your evidence…" : `${state.search.results.length} matching cards`;
  return `
    <section class="view search-view">
      <header class="search-heading">
        <div>
          <p class="eyebrow">Evidence retrieval</p>
          <h1>Find the evidence behind the argument.</h1>
          <p>Search in plain language. Every result stays linked to its original card.</p>
        </div>
        <div class="search-kicker"><span class="status-dot"></span> Local index ready</div>
      </header>
      <form class="search-input" data-form="search">
        <span class="search-icon">⌕</span>
        <input name="query" value="${escapeAttr(query)}" placeholder="Try “state regulation reduces illegal betting”" autocomplete="off" autofocus />
        <button>Search</button>
      </form>
      <div class="view-meta">
        <span>${resultLabel}</span>
        ${state.settings.developerSearchDiagnostics ? `<span class="diagnostic-pill">Diagnostics on</span>` : ""}
      </div>
      ${state.search.error ? `<div class="warning">${escapeHtml(state.search.error)}</div>` : ""}
      ${renderSearchLog()}
      <div class="results-list">
        ${state.search.results.map((card, index) => renderResultCard(card, index)).join("") || (state.search.loading ? "" : `<div class="empty-search"><strong>Start with a claim, citation, or question.</strong><span>The best cards will appear here with their original source context.</span></div>`)}
      </div>
    </section>
  `;
}

function renderResultCard(card, index) {
  const citation = card.title || card.citation || "Evidence card";
  const section = card.section || "Unfiled evidence";
  const highlights = highlightedEvidence(card);
  // The card content is the exact evidence extracted by the highlight cutter.
  // Title, author, and source metadata remain visible as provenance only.
  const extractedEvidence = highlights.join(" ").replace(/\s+/g, " ").trim();
  return `
    <article class="result-card" data-open-result="${index}" tabindex="0">
      <div class="result-primary">
        <div class="result-overline"><span>${escapeHtml(section)}</span><span>&middot;</span><span>Highlighted evidence</span></div>
        <h3>${escapeHtml(citation)}</h3>
      </div>
      <span class="score" title="Native retrieval score; higher is better">${formatRetrievalScore(card.score)}</span>
      <div class="result-highlight-output">
        ${extractedEvidence ? escapeHtml(extractedEvidence) : `<span class="result-no-highlights">No highlights saved for this card.</span>`}
      </div>
      <footer class="result-actions">
        <span>${escapeHtml(card.author || card.citation || "Original card")}</span>
        <div>
          <button class="text-button" data-copy-result="${index}">Copy</button>
          ${card.url ? `<button class="text-button" data-open-url="${escapeAttr(card.url)}">Source ↗</button>` : ""}
          <button class="text-button strong" data-open-result-button="${index}">Full text &rarr;</button>
        </div>
      </footer>
      ${
        state.settings.developerSearchDiagnostics && card.diagnostics
          ? `<div class="diagnostics">Retrieved via ${card.diagnostics.retrieval.join(", ")} &middot; final score ${Math.round(card.diagnostics.finalScore * 100)}%</div>`
          : ""
      }
    </article>
  `;
}

function renderEvidenceView(card) {
  return `
    <section class="view evidence-view">
      <article class="evidence-header">
        <div>
          <p class="eyebrow">Evidence card</p>
          <h1>${escapeHtml(card.title || card.citation || "Evidence Card")}</h1>
          <p class="evidence-tag">${escapeHtml(card.tag || "")}</p>
          <p class="citation">${escapeHtml(card.citation || "")}</p>
        </div>
        <span class="score large">${card.score ? `${Math.round(card.score * 100)}%` : "--"}</span>
      </article>
      <div class="button-row">
        <button data-copy-active-card>Copy Card</button>
        ${card.url ? `<button data-open-url="${escapeAttr(card.url)}">Open Source</button>` : ""}
      </div>
      <section class="evidence-block">
        <h2>Highlights</h2>
        ${(card.highlights || []).map((highlight) => `<p class="highlight">${escapeHtml(highlight.text || highlight)}</p>`).join("") || `<p class="muted">No highlights captured.</p>`}
      </section>
      <section class="evidence-block">
        <h2>Body</h2>
        <p class="body-text">${escapeHtml(card.body || card.bodyPreview || "")}</p>
      </section>
    </section>
  `;
}

function renderBrowserView(tabState = {}) {
  const url = tabState.url || "https://docs.google.com";
  return `
    <section class="view browser-view">
      <form class="browser-toolbar" data-form="browser">
        <input name="url" value="${escapeAttr(url)}" placeholder="https://docs.google.com" />
        <button>Open Tab</button>
        <button type="button" data-open-url="${escapeAttr(url)}">Open External</button>
      </form>
      <div class="browser-placeholder">
        <h2>Research Browser</h2>
        <p>Tauri uses the platform WebView rather than Qt WebEngine/Chromium. For now, source links and Google Docs use the external-browser escape hatch while we decide the best embedded browsing strategy.</p>
        <button data-open-url="${escapeAttr(url)}">Open ${escapeHtml(url)} externally</button>
      </div>
    </section>
  `;
}

function renderPlaceholder(title, body) {
  return `
    <section class="view placeholder-view">
      <h1>${title}</h1>
      <p>${body}</p>
    </section>
  `;
}

function renderStatusBar() {
  return `
    <footer class="status-bar">
      <span class="${state.search.error ? "status-warning" : "status-ok"}">${state.search.error ? "Database issue" : "Database ready"}</span>
      <span>${state.search.results.length} results</span>
      <span>${state.settings.developerSearchDiagnostics ? "Diagnostics on" : "Diagnostics off"}</span>
      <span class="status-message">${escapeHtml(state.statusMessage || "")}</span>
      <span class="status-path">${escapeHtml(state.paths?.appData || "")}</span>
    </footer>
  `;
}

function renderCommandPalette() {
  const query = state.commandText.toLowerCase();
  const filtered = commands.filter((command) => {
    if (!query) return true;
    return `${command.id} ${command.title} ${command.keywords}`.toLowerCase().includes(query);
  });
  return `
    <div class="overlay" data-action="close-command">
      <section class="command-palette" data-modal data-stop-overlay>
        <input class="command-input" value="${escapeAttr(state.commandText)}" placeholder="Search evidence, run a command, or type a query" autofocus />
        <div class="command-list">
          ${commands
            .map(
              (command) => `
                <button
                  class="command-row"
                  data-command="${command.id}"
                  data-command-search="${escapeAttr(`${command.id} ${command.title} ${command.keywords}`.toLowerCase())}"
                  ${filtered.includes(command) ? "" : "hidden"}
                >
                  <span>${command.title}</span>
                  <small>${command.id}</small>
                </button>
              `,
            )
            .join("")}
        </div>
        <p>No matching command? Press Enter to search evidence.</p>
      </section>
    </div>
  `;
}

function renderSettingsDialog() {
  const categories = ["General", "Appearance", "Search", "Evidence", "Documents", "AI", "Shortcuts", "Storage", "Privacy", "Advanced", "Developer"];
  return `
    <div class="overlay" data-action="close-settings">
      <section class="settings-dialog" data-modal data-stop-overlay>
        <header>
          <h1>Settings</h1>
          <button data-action="close-settings">Close</button>
        </header>
        <div class="settings-grid">
          <nav>
            ${categories.map((category) => `<button class="${state.settingsCategory === category ? "active" : ""}" data-settings-category="${category}">${category}</button>`).join("")}
          </nav>
          <div class="settings-panel">
            ${renderSettingsPanel()}
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderSettingsPanel() {
  if (state.settingsCategory === "Appearance") {
    return `
      <h2>Appearance</h2>
      ${radioSetting("theme", "system", "Follow System")}
      ${radioSetting("theme", "dark", "Dark")}
      ${radioSetting("theme", "naturalWhite", "Natural White")}
      <label class="field">Interface scale <input type="range" min="0.8" max="1.6" step="0.05" value="${state.settings.scale}" data-setting="scale" /></label>
      ${radioSetting("density", "compact", "Compact")}
      ${radioSetting("density", "comfortable", "Comfortable")}
      <button data-action="reset-appearance">Reset Appearance</button>
    `;
  }
  if (state.settingsCategory === "Search") {
    return `
      <h2>Search</h2>
      <label class="field">Results shown <input type="number" min="5" max="100" value="${state.settings.searchResultCount}" data-setting="searchResultCount" /></label>
      <p class="muted">Hybrid retrieval will plug in behind the existing search command.</p>
    `;
  }
  if (state.settingsCategory === "Developer") {
    return `
      <h2>Developer</h2>
      <label class="check"><input type="checkbox" ${state.settings.developerSearchDiagnostics ? "checked" : ""} data-setting="developerSearchDiagnostics" /> Search diagnostics</label>
      <button data-action="open-data-dir">Open Data Directory</button>
    `;
  }
  return `
    <h2>${state.settingsCategory}</h2>
    <p class="muted">This settings category is reserved so configuration has one home as the app grows.</p>
  `;
}

function radioSetting(key, value, label) {
  return `
    <label class="check">
      <input type="radio" name="${key}" value="${value}" ${state.settings[key] === value ? "checked" : ""} data-setting="${key}" />
      ${label}
    </label>
  `;
}

app.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  const closeTabButton = target.closest("[data-close-tab]");
  if (closeTabButton) {
    event.preventDefault();
    event.stopPropagation();
    closeTab(closeTabButton.dataset.closeTab);
    return;
  }

  const activityButton = target.closest("[data-activity]");
  if (activityButton) {
    state.activeActivity = activityButton.dataset.activity;
    saveWorkspaceSoon();
    render();
    return;
  }

  const tabButton = target.closest("[data-tab]");
  if (tabButton) {
    state.activeTabId = tabButton.dataset.tab;
    saveWorkspaceSoon();
    render();
    return;
  }

  const settingsCategoryButton = target.closest("[data-settings-category]");
  if (settingsCategoryButton) {
    state.settingsCategory = settingsCategoryButton.dataset.settingsCategory;
    render();
    return;
  }

  const roundViewButton = target.closest("[data-round-view]");
  if (roundViewButton) {
    state.activeActivity = "round";
    state.roundView = roundViewButton.dataset.roundView;
    saveWorkspaceSoon();
    render();
    if (state.roundView === "cards" && state.round?.status === "ready") {
      refreshRoundEvidence();
    }
    return;
  }

  const commandButton = target.closest("[data-command]");
  if (commandButton) {
    executeCommand(commandButton.dataset.command, state.commandText);
    return;
  }

  const toolButton = target.closest("[data-tool]");
  if (toolButton) {
    state.activeActivity = "tools";
    state.tools.activeTool = toolButton.dataset.tool;
    saveWorkspaceSoon();
    render();
    return;
  }

  const copyResultButton = target.closest("[data-copy-result]");
  if (copyResultButton) {
    event.stopPropagation();
    const card = state.search.results[Number(copyResultButton.dataset.copyResult)];
    if (card) copyCard(card);
    return;
  }

  const openResultButton = target.closest("[data-open-result-button]");
  if (openResultButton) {
    event.stopPropagation();
    const card = state.search.results[Number(openResultButton.dataset.openResultButton)];
    if (card) openEvidenceCard(card);
    return;
  }

  const resultCard = target.closest("[data-open-result]");
  if (resultCard && !target.closest("button")) {
    const card = state.search.results[Number(resultCard.dataset.openResult)];
    if (card) openEvidenceCard(card);
    return;
  }

  const cardIdButton = target.closest("[data-open-card-id]");
  if (cardIdButton) {
    const card = findEvidenceCard(cardIdButton.dataset.openCardId);
    if (card) openEvidenceCard(card);
    return;
  }

  const askCardButton = target.closest("[data-open-ask-card]");
  if (askCardButton) {
    const result = state.roundAsk.results[Number(askCardButton.dataset.openAskCard)];
    if (result?.card) openEvidenceCard(result.card);
    return;
  }

  const askFlowButton = target.closest("[data-add-ask-flow]");
  if (askFlowButton) {
    addAskResultToFlow(Number(askFlowButton.dataset.addAskFlow));
    return;
  }

  const segmentButton = target.closest("[data-segment-name]");
  if (segmentButton) {
    const name = segmentButton.dataset.segmentName;
    const value = segmentButton.dataset.segmentValue;
    if (name === "ask-mode") {
      state.roundAsk.mode = value;
      render();
    }
    return;
  }

  if (target.closest("[data-copy-active-card]")) {
    copyCard(activeTab().state);
    return;
  }

  const openUrlButton = target.closest("[data-open-url]");
  if (openUrlButton) {
    const url = openUrlButton.dataset.openUrl;
    call("open_external_url", { url }).catch(() => window.open(url, "_blank"));
    return;
  }

  const actionElement = target.closest("[data-action]");
  if (!actionElement) return;
  if (actionElement.classList.contains("overlay") && target !== actionElement) return;

  const action = actionElement.dataset.action;
  if (action === "open-command") state.commandPaletteOpen = true;
  else if (action === "open-settings") state.settingsOpen = true;
  else if (action === "close-command") state.commandPaletteOpen = false;
  else if (action === "close-settings") state.settingsOpen = false;
  else if (action === "close-evidence") state.focusedCard = null;
  else if (action === "copy-focused-card" && state.focusedCard) copyCard(state.focusedCard);
  else if (action === "new-search") { state.activeActivity = "round"; state.roundView = "evidence"; }
  else if (action === "open-browser") call("open_external_url", { url: "https://docs.google.com" }).catch(console.error);
  else if (action === "import-source") addRoundSource(null);
  else if (action === "build-round") buildRound();
  else if (action === "refresh-library-cards") refreshRoundEvidence();
  else if (action === "run-card-separator") runCardSeparatorPreview();
  else if (action === "copy-separator-text") copySeparatorText();
  else if (action === "add-generated-flow") addGeneratedToFlow();
  else if (action === "regenerate-answer") runRoundAsk(state.roundAsk.query);
  else if (action === "copy-generated" && state.roundAsk.generated) {
    navigator.clipboard?.writeText(state.roundAsk.generated.text);
    flashStatus("Copied generated response.");
  }
  else if (action === "reset-appearance") {
    state.settings = { ...state.settings, theme: "naturalWhite", density: "comfortable", scale: 1 };
    saveSettings();
  } else if (action === "open-data-dir" && state.paths?.appData) {
    call("reveal_path", { path: state.paths.appData }).catch(console.error);
  }
  render();
});

app.addEventListener("pointerdown", (event) => {
  const handle = event.target instanceof Element ? event.target.closest("[data-resize-target]") : null;
  if (!handle) return;
  event.preventDefault();
  startWorkspaceResize(handle.dataset.resizeTarget, event.clientX);
});

app.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  event.preventDefault();

  if (form.dataset.form === "round-evidence-search" || form.dataset.form === "search") {
    const query = new FormData(form).get("query").toString();
    state.activeActivity = "round";
    state.roundView = "evidence";
    saveWorkspaceSoon();
    runSearch(query);
  } else if (form.dataset.form === "browser") {
    const url = normalizeUrl(new FormData(form).get("url").toString());
    activeTab().state.url = url;
    activeTab().title = "Web: " + url.replace(/^https?:\/\//, "").slice(0, 32);
    saveWorkspaceSoon();
    render();
  } else if (form.dataset.form === "round-ask") {
    const query = new FormData(form).get("query").toString();
    runRoundAsk(query);
  }
});

app.addEventListener("input", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) && !(input instanceof HTMLTextAreaElement)) return;

  if (input.matches("[data-card-separator-field]")) {
    const key = input.dataset.cardSeparatorField;
    state.tools.cardSeparator[key] = input.value;
    state.tools.cardSeparator.ran = false;
    state.tools.cardSeparator.rawText = "";
    state.tools.cardSeparator.error = "";
    state.cardSeparatorUpload = null;
    saveWorkspaceSoon();
    return;
  }

  if (input.classList.contains("command-input")) {
    state.commandText = input.value;
    filterCommandRows();
  }

  if (input.matches("[data-round-evidence-filter]")) {
    state.roundEvidenceFilter = input.value;
    clearTimeout(refreshRoundEvidence.timer);
    refreshRoundEvidence.timer = setTimeout(refreshRoundEvidence, 180);
  }

  if (input.dataset.sourcePath) {
    state.roundSourcePaths[input.dataset.sourcePath] = input.value;
    state.roundUploads[input.dataset.sourcePath] = null;
    saveWorkspaceSoon();
  }

});

app.addEventListener("change", async (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;

  if (input.dataset.fileSide && input.files?.[0]) {
    acceptRoundFiles(input.dataset.fileSide, input.files);
    return;
  }

  if (input.matches("[data-card-separator-file]") && input.files?.[0]) {
    const file = input.files[0];
    state.cardSeparatorUpload = sourcePathFromFile(file)
      ? null
      : {
          name: file.name || "card-separator.docx",
          bytes: Array.from(new Uint8Array(await file.arrayBuffer())),
        };
    state.tools.cardSeparator = {
      ...state.tools.cardSeparator,
      docxPath: sourcePathFromFile(file) || file.name || "",
      running: false,
      ran: false,
      rawText: "",
      error: "",
      stderr: "",
      cardCount: null,
    };
    saveWorkspaceSoon();
    render();
    return;
  }

  if (!input.dataset.setting) return;

  const key = input.dataset.setting;
  if (input.type === "checkbox") state.settings[key] = input.checked;
  else if (input.type === "number" || input.type === "range") state.settings[key] = Number(input.value);
  else state.settings[key] = input.value;
  saveSettings();
  render();
});

app.addEventListener("keydown", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.classList.contains("command-input")) return;

  if (event.key === "Enter") {
    const text = input.value.trim();
    if (text) {
      state.commandPaletteOpen = false;
      state.activeActivity = "round";
      state.roundView = "evidence";
      saveWorkspaceSoon();
      runSearch(text);
    }
  }

  if (event.key === "Escape") {
    state.commandPaletteOpen = false;
    render();
  }
});

app.addEventListener("dragover", (event) => {
  const dropZone = event.target instanceof Element ? event.target.closest("[data-drop-side], [data-drop-card-separator]") : null;
  if (!dropZone) return;
  event.preventDefault();
  dropZone.classList.add("drag-over");
});

app.addEventListener("dragleave", (event) => {
  const dropZone = event.target instanceof Element ? event.target.closest("[data-drop-side], [data-drop-card-separator]") : null;
  dropZone?.classList.remove("drag-over");
});

app.addEventListener("drop", (event) => {
  const dropZone = event.target instanceof Element ? event.target.closest("[data-drop-side], [data-drop-card-separator]") : null;
  if (!dropZone) return;
  event.preventDefault();
  dropZone.classList.remove("drag-over");
  const files = event.dataTransfer?.files;
  if (!files?.length) return;
  if (dropZone.matches("[data-drop-card-separator]")) {
    acceptCardSeparatorFiles(files);
  } else {
    acceptRoundFiles(dropZone.dataset.dropSide, files);
  }
});

async function installNativeDragDrop() {
  if (!isTauri()) return;
  const webview = getCurrentWebview();
  await webview.onDragDropEvent((event) => {
    if (event.payload.type === "over") {
      const side = sideFromDropPosition(event.payload.position);
      const overCardSeparator = Boolean(cardSeparatorDropFromPosition(event.payload.position));
      document.querySelectorAll("[data-drop-side]").forEach((zone) => {
        zone.classList.toggle("drag-over", !overCardSeparator && zone.dataset.dropSide === side);
      });
      document.querySelectorAll("[data-drop-card-separator]").forEach((zone) => {
        zone.classList.toggle("drag-over", overCardSeparator);
      });
      return;
    }
    document.querySelectorAll("[data-drop-side]").forEach((zone) => zone.classList.remove("drag-over"));
    document.querySelectorAll("[data-drop-card-separator]").forEach((zone) => zone.classList.remove("drag-over"));
    if (event.payload.type !== "drop") return;
    if (cardSeparatorDropFromPosition(event.payload.position)) {
      acceptCardSeparatorFiles(event.payload.paths || []);
      return;
    }
    const side = sideFromDropPosition(event.payload.position);
    if (!side) return;
    acceptRoundFiles(side, event.payload.paths || []);
  });
}

function sideFromDropPosition(position) {
  const element = document.elementFromPoint(position?.x || 0, position?.y || 0);
  return element?.closest?.("[data-drop-side]")?.dataset.dropSide || "";
}

function cardSeparatorDropFromPosition(position) {
  const element = document.elementFromPoint(position?.x || 0, position?.y || 0);
  return element?.closest?.("[data-drop-card-separator]") || null;
}

function startWorkspaceResize(target, startX) {
  const initialActivity = state.layout.activityWidth;
  const initialSidebar = state.layout.sidebarWidth;

  function onMove(event) {
    const delta = event.clientX - startX;
    if (target === "activity") {
      state.layout.activityWidth = clamp(initialActivity + delta, 48, 150);
    } else if (target === "sidebar") {
      state.layout.sidebarWidth = clamp(initialSidebar + delta, 180, 420);
    }
    document.querySelector(".workspace-grid")?.style.setProperty("--activity-width", `${state.layout.activityWidth}px`);
    document.querySelector(".workspace-grid")?.style.setProperty("--sidebar-width", `${state.layout.sidebarWidth}px`);
  }

  function onUp() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    document.body.classList.remove("is-resizing");
    saveWorkspaceSoon();
  }

  document.body.classList.add("is-resizing");
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

async function saveSettings() {
  await call("save_settings", { settings: state.settings }).catch(console.error);
}

function normalizeUrl(value) {
  return value.includes("://") ? value : `https://${value}`;
}

function statusLabel(status) {
  return {
    empty: "Empty",
    configuring: "Configuring",
    building: "Building",
    needs_format_config: "Needs Format Config",
    ready: "Ready",
    active: "Active",
    loaded: "File Loaded",
    indexing: "Indexing",
  }[status] || status || "Empty";
}

function segmented(name, activeValue, options) {
  return `
    <div class="segmented">
      ${options.map(([value, label]) => `
        <button type="button" class="${activeValue === value ? "active" : ""}" data-segment-name="${name}" data-segment-value="${value}">
          ${label}
        </button>
      `).join("")}
    </div>
  `;
}

function groupBy(items, getKey) {
  return items.reduce((groups, item) => {
    const key = getKey(item);
    groups[key] ||= [];
    groups[key].push(item);
    return groups;
  }, {});
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function highlightGrammar(value) {
  return escapeHtml(value)
    .replace(/(\[[^\]]+\])/g, '<span class="grammar-field">$1</span>')
    .replace(/(--|\*|\?|\+)/g, '<span class="grammar-token">$1</span>');
}

function fragmentFromHtml(html) {
  return document.createRange().createContextualFragment(html);
}

function shellLikeQuote(value) {
  const text = String(value || "");
  if (!text || !/[\s'"\\]/.test(text)) return text;
  return `'${text.replaceAll("'", "'\\''")}'`;
}

function shortcutLabel(key) {
  return `${navigator.platform.includes("Mac") ? "⌘" : "Ctrl+"}${key}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

window.addEventListener("keydown", (event) => {
  const commandKey = navigator.platform.includes("Mac") ? event.metaKey : event.ctrlKey;
  if (commandKey && event.key.toLowerCase() === "k") {
    event.preventDefault();
    state.commandPaletteOpen = true;
    render();
  }
  if (commandKey && event.key.toLowerCase() === "t") {
    event.preventDefault();
    state.activeActivity = "round";
    state.roundView = "evidence";
    render();
  }
  if (commandKey && event.key.toLowerCase() === "w" && state.focusedCard) {
    event.preventDefault();
    state.focusedCard = null;
    render();
  }
});

const colorSchemeQuery = matchMedia("(prefers-color-scheme: dark)");
if (colorSchemeQuery.addEventListener) {
  colorSchemeQuery.addEventListener("change", () => {
    if (state.settings.theme === "system") render();
  });
} else if (colorSchemeQuery.addListener) {
  colorSchemeQuery.addListener(() => {
    if (state.settings.theme === "system") render();
  });
}

async function bootstrap() {
  const [settings, workspace, paths] = await Promise.all([
    call("load_settings").catch(() => DEFAULT_SETTINGS),
    call("load_workspace").catch(() => null),
    call("platform_paths").catch(() => null),
  ]);

  state.settings = { ...DEFAULT_SETTINGS, ...settings };
  state.paths = paths;
  if (workspace) {
    state.workspaceName = workspace.workspaceName || state.workspaceName;
    state.tabs = Array.isArray(workspace.tabs) && workspace.tabs.length ? workspace.tabs : state.tabs;
    state.activeTabId = workspace.activeTabId || state.tabs[0].id;
    if (!state.tabs.some((tab) => tab.id === state.activeTabId)) {
      state.activeTabId = state.tabs[0].id;
    }
    state.activeActivity = ACTIVITY_IDS.includes(workspace.activeActivity) ? workspace.activeActivity : state.activeActivity;
    state.round = workspace.round || state.round;
    if (state.round?.sources) {
      state.round = { ...state.round, sources: state.round.sources.filter((source) => source.side === "ours").slice(0, 1) };
    }
    state.roundSourcePaths = { ...state.roundSourcePaths, ...(workspace.roundSourcePaths || {}) };
    state.roundView = workspace.roundView || state.roundView;
    state.roundEvidenceFilter = workspace.roundEvidenceFilter || state.roundEvidenceFilter;
    state.roundAsk = { ...state.roundAsk, ...(workspace.roundAsk || {}) };
    state.layout = {
      ...state.layout,
      ...(workspace.layout || {}),
    };
    state.layout.activityWidth = clamp(Number(state.layout.activityWidth) || 72, 56, 150);
    state.layout.sidebarWidth = clamp(Number(state.layout.sidebarWidth) || 260, 200, 420);
    state.tools = {
      ...state.tools,
      ...(workspace.tools || {}),
      cardSeparator: {
        ...state.tools.cardSeparator,
        ...(workspace.tools?.cardSeparator || {}),
        running: false,
        ran: false,
      },
    };
  }
  if (!state.tabs.some((tab) => tab.type === "round")) {
    const roundTab = { id: crypto.randomUUID(), type: "round", title: "Round Setup", state: {} };
    state.tabs.unshift(roundTab);
  }
  await ensureRound();
  if (state.round?.status === "ready") {
    await refreshRoundEvidence(false);
  }
  render();
  // Local model installation and downloads are deliberately deferred until the
  // user runs a semantic search or builds a library. Starting them here makes
  // a fresh desktop install look frozen while Ollama provisions in the background.
  installNativeDragDrop().catch(console.error);
  if (state.roundView === "evidence" && state.search.query) runSearch(state.search.query);
}

window.addEventListener("error", (event) => {
  showStartupError(event.error || event.message);
});

window.addEventListener("unhandledrejection", (event) => {
  showStartupError(event.reason);
});

render();
bootstrap().catch(showStartupError);

function filterCommandRows() {
  const query = state.commandText.trim().toLowerCase();
  document.querySelectorAll("[data-command-search]").forEach((row) => {
    row.hidden = query.length > 0 && !row.dataset.commandSearch.includes(query);
  });
}
