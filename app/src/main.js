import { invoke } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { mockBackend } from "./services/mockBackend.js";
import "./styles/app.css";

const DEFAULT_OPPONENT_GRAMMAR = `-- [card] -- [author]
[link]
[content]`;

const DEFAULT_SETTINGS = {
  theme: "dark",
  density: "comfortable",
  scale: 1,
  searchResultCount: 20,
  developerSearchDiagnostics: false,
};

const DEFAULT_TABS = [
  {
    id: crypto.randomUUID(),
    type: "round",
    title: "Round Setup",
    state: {},
  },
];

const commands = [
  { id: "search.evidence", title: "Search evidence", keywords: "backfile query cards" },
  { id: "search.opponent", title: "Search opponent", keywords: "round speech document" },
  { id: "draft.rebuttal", title: "Draft rebuttal", keywords: "ai response argument" },
  { id: "document.import", title: "Import document", keywords: "docx pdf text" },
  { id: "browser.open", title: "Open website", keywords: "web google docs research" },
  { id: "round.start", title: "Start round", keywords: "flow opponent prep" },
  { id: "round.ask", title: "Ask round", keywords: "smart search rebuttal evidence" },
  { id: "tools.cardSeparator", title: "Card separator", keywords: "docx split cards highlights citation jsonl" },
  { id: "settings.open", title: "Open settings", keywords: "appearance developer search ai" },
];

const ROUND_VIEWS = [
  { id: "setup", label: "Setup", requiresReady: false },
  { id: "evidence", label: "Evidence", requiresReady: true },
  { id: "ask", label: "Ask", requiresReady: false },
  { id: "flow", label: "Flow", requiresReady: true },
  { id: "browser", label: "Browser", requiresReady: false },
];

const ACTIVITY_IDS = ["tools", "round", "web", "ai"];

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
  },
  paths: null,
  commandPaletteOpen: false,
  commandText: "",
  settingsOpen: false,
  settingsCategory: "Appearance",
  layout: {
    activityWidth: 92,
    sidebarWidth: 280,
  },
  round: null,
  roundSourcePaths: {
    ours: "",
    opponent: "",
    opponentGrammar: "",
  },
  roundUploads: {
    ours: null,
    opponent: null,
    opponentGrammar: null,
  },
  roundGrammarText: DEFAULT_OPPONENT_GRAMMAR,
  roundView: "setup",
  roundBuildTick: 0,
  roundEvidence: [],
  roundEvidenceScope: "both",
  roundEvidenceFilter: "",
  roundAsk: {
    query: "",
    mode: "smart",
    scope: "ours",
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
      activeActivity: "search",
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
      scope: "both",
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
        roundGrammarText: state.roundGrammarText,
        roundView: state.roundView,
        roundEvidenceScope: state.roundEvidenceScope,
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

async function runSearch(queryText) {
  state.search.query = queryText;
  state.search.loading = true;
  state.search.error = "";
  render();

  try {
    state.search.results = await call("search_evidence", {
      query: {
        text: queryText,
        limit: state.settings.searchResultCount,
        mode: "hybrid",
        includeDiagnostics: state.settings.developerSearchDiagnostics,
      },
    });
  } catch (error) {
    state.search.results = [];
    state.search.error = String(error);
  } finally {
    state.search.loading = false;
    render();
  }
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
  let openedTab = false;
  if (id === "settings.open") {
    state.settingsOpen = true;
  } else if (id === "browser.open") {
    openTab("browser", "Research Browser", { url: commandPayload || "https://docs.google.com" });
    openedTab = true;
  } else if (id === "draft.rebuttal") {
    openTab("draft", "Draft Rebuttal", {});
    openedTab = true;
  } else if (id === "round.start") {
    state.activeActivity = "round";
    openTab("round", "Round", {});
    openedTab = true;
    ensureRound();
  } else if (id === "round.ask") {
    state.activeActivity = "round";
    state.roundView = "ask";
    openTab("round", "Round Ask", {});
    openedTab = true;
    ensureRound();
  } else if (id === "document.import") {
    openTab("document", "Import Document", {});
    openedTab = true;
  } else if (id === "tools.cardSeparator") {
    state.activeActivity = "tools";
    state.tools.activeTool = "card-separator";
    openTab("tool", "Card Separator", { tool: "card-separator" });
    openedTab = true;
  } else if (id === "search.evidence" || id === "search.opponent") {
    openTab("search", commandPayload ? `Search: ${commandPayload}` : "Evidence Search", { query: commandPayload });
    openedTab = true;
    runSearch(commandPayload);
  }
  saveWorkspaceSoon();
  if (!openedTab) render();
}

async function ensureRound() {
  if (state.round) return state.round;
  state.round = await mockBackend.createRound();
  saveWorkspaceSoon();
  render();
  return state.round;
}

async function addRoundSource(side, file) {
  const round = await ensureRound();
  if (isTauri()) {
    const upload = state.roundUploads[side] || (file ? await uploadFromFile(file) : null);
    const grammarUpload = state.roundUploads.opponentGrammar;
    const stagedSourcePath = upload?.requiresPath ? "" : state.roundSourcePaths[side]?.trim();
    const sourcePath = upload?.path || sourcePathFromFile(file) || (!upload?.text ? stagedSourcePath : "");
    const sourceText = upload?.text || "";
    if (!sourcePath && !sourceText) {
      flashStatus(upload?.requiresPath ? "For DOCX, drag the file into the app or paste its absolute path." : "Choose or drop a source file first.");
      return;
    }
    const grammarText = state.roundGrammarText.trim();
    if (side === "opponent" && !grammarUpload?.text && !grammarUpload?.path && !state.roundSourcePaths.opponentGrammar.trim() && !grammarText) {
      flashStatus("Add the opponent .sa grammar in the editor or choose a grammar file.");
      return;
    }
    const source = await call("import_round_source", {
      request: {
        side,
        roundId: round.id,
        sourcePath,
        sourceName: upload?.name || file?.name || "",
        sourceText,
        grammarPath: side === "opponent" ? grammarUpload?.path || (!grammarUpload?.text ? state.roundSourcePaths.opponentGrammar.trim() : "") : "",
        grammarName: side === "opponent" ? grammarUpload?.name || "" : "",
        grammarText: side === "opponent" ? grammarUpload?.text || grammarText : "",
      },
    });
    state.round = {
      ...round,
      status: "configuring",
      sources: [...round.sources.filter((existing) => existing.side !== side), source],
    };
    let nextView = "setup";
    if (source.status === "ready") {
      state.round.status = "ready";
      nextView = "evidence";
      await refreshRoundEvidence(false);
    }
    flashStatus(side === "opponent" ? `Imported ${source.cardCount} opponent cards.` : "Source registered.");
    state.roundView = nextView;
  } else {
    state.round = await mockBackend.addRoundSource(round, side, file);
    state.roundView = "setup";
  }
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
  if (!path && file.name?.toLowerCase().endsWith(".docx")) {
    return {
      name: file.name || "upload.docx",
      path: "",
      text: "",
      requiresPath: true,
    };
  }
  const text = path ? "" : await file.text();
  return {
    name: file.name || "upload.txt",
    path,
    text,
  };
}

function isGrammarUpload(fileOrPath) {
  const name = typeof fileOrPath === "string" ? fileOrPath : fileOrPath?.name || "";
  return name.toLowerCase().endsWith(".sa");
}

async function acceptRoundFiles(side, files) {
  const items = Array.from(files || []);
  if (!items.length) return;

  const round = await ensureRound();
  let sourceFile = null;
  let sourcePath = "";
  for (const item of items) {
    if (isGrammarUpload(item)) {
      if (typeof item === "string") {
        state.roundSourcePaths.opponentGrammar = item;
        state.roundUploads.opponentGrammar = { name: item.split(/[\\/]/).pop() || "grammar.sa", path: item, text: "" };
      } else {
        const upload = await uploadFromFile(item);
        state.roundUploads.opponentGrammar = upload;
        state.roundSourcePaths.opponentGrammar = upload.path || upload.name;
        if (upload.text) {
          state.roundGrammarText = upload.text;
        }
      }
    } else {
      sourceFile = typeof item === "string" ? null : item;
      sourcePath = typeof item === "string" ? item : "";
    }
  }

  if (sourcePath) {
    state.roundSourcePaths[side] = sourcePath;
    state.roundUploads[side] = { name: sourcePath.split(/[\\/]/).pop() || "source.txt", path: sourcePath, text: "" };
  } else if (sourceFile) {
    const upload = await uploadFromFile(sourceFile);
    state.roundUploads[side] = upload;
    state.roundSourcePaths[side] = upload.path || (upload.requiresPath ? "" : upload.name);
  }

  if (side === "opponent" && (state.roundUploads.opponent || state.roundSourcePaths.opponent) && (state.roundUploads.opponentGrammar || state.roundSourcePaths.opponentGrammar)) {
    await addRoundSource("opponent", sourceFile);
  } else {
    state.round = {
      ...round,
      sources: [
        ...round.sources.filter((source) => source.side !== side),
        {
          id: `pending-${side}`,
          filename: state.roundUploads[side]?.name || state.roundSourcePaths[side] || "Upload",
          path: state.roundUploads[side]?.path || state.roundSourcePaths[side] || "",
          side,
          status: "loaded",
          cardCount: 0,
          parseProgress: 0,
          indexProgress: 0,
          error: "",
          diagnostics: side === "opponent" ? ["Waiting for source and grammar."] : [],
        },
      ],
    };
    flashStatus(side === "opponent" ? "Opponent upload staged. Add the .sa grammar to import." : "Source staged.");
    saveWorkspaceSoon();
    render();
  }
}

async function buildRound() {
  const round = await ensureRound();
  if (isTauri()) {
    if (!round.sources.length) {
      flashStatus("Add at least one source first.");
      return;
    }
    state.round = {
      ...round,
      status: "ready",
      sources: round.sources.map((source) => ({ ...source, status: source.status === "loaded" ? "ready" : source.status })),
    };
    state.roundView = "evidence";
    await refreshRoundEvidence(false);
    flashStatus("Round ready. Evidence unlocked.");
    saveWorkspaceSoon();
    render();
    return;
  }
  if (!round.sources.some((source) => source.side === "ours") || !round.sources.some((source) => source.side === "opponent")) {
    flashStatus("Add our side and opponent files first.");
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
      state.roundEvidence = await mockBackend.listEvidence({ scope: state.roundEvidenceScope, query: state.roundEvidenceFilter });
      flashStatus("Round ready. Evidence unlocked.");
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
            scope: state.roundEvidenceScope,
            query: state.roundEvidenceFilter,
            limit: 150,
          },
        })
      : await mockBackend.listEvidence({
          scope: state.roundEvidenceScope,
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
            scope: normalizeAskScope(state.roundAsk.scope),
            mode: state.roundAsk.mode,
            limit: state.settings.searchResultCount,
            generateAnswer: true,
            includeDiagnostics: state.settings.developerSearchDiagnostics || state.roundAsk.mode === "advanced",
          },
        })
      : null;
    const results = response?.results || await mockBackend.searchRound({
          query: queryText,
          scope: normalizeAskScope(state.roundAsk.scope),
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

async function addAskResultToFlow(index) {
  const result = state.roundAsk.results[index];
  if (!result || !state.round) return;
  state.round = await mockBackend.addFlow(state.round, {
    opponentClaim: state.roundAsk.query || "Opponent claim",
    response: `${result.relationship}: ${result.explanation}`,
    evidenceIds: [result.card.id],
  });
  flashStatus("Added evidence response to Flow.");
  render();
}

async function addGeneratedToFlow() {
  if (!state.roundAsk.generated || !state.round) return;
  state.round = await mockBackend.addFlow(state.round, {
    opponentClaim: state.roundAsk.query || "Opponent claim",
    response: state.roundAsk.generated.text,
    evidenceIds: state.roundAsk.generated.sources,
  });
  state.roundView = "flow";
  flashStatus("Added generated response to Flow.");
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
  return [...state.roundEvidence, ...state.roundAsk.results.map((result) => result.card)].find((card) => card?.id === id);
}

function render() {
  applyTheme();
  if (!app) return;
  app.innerHTML = `
    <main class="app-shell">
      ${renderTopbar()}
      <section class="workspace-grid" style="--activity-width: ${state.layout.activityWidth}px; --sidebar-width: ${state.layout.sidebarWidth}px;">
        ${renderActivityBar()}
        <div class="resize-handle activity-resize" data-resize-target="activity" title="Resize activity bar"></div>
        ${renderSidebar()}
        <div class="resize-handle sidebar-resize" data-resize-target="sidebar" title="Resize sidebar"></div>
        <section class="editor-area">
          ${renderTabStrip()}
          ${renderPanel()}
        </section>
      </section>
      ${renderStatusBar()}
      ${state.commandPaletteOpen ? renderCommandPalette() : ""}
      ${state.settingsOpen ? renderSettingsDialog() : ""}
    </main>
  `;
}

function renderTopbar() {
  return `
    <header class="topbar">
      <div class="brand">Secret Agenda</div>
      <button class="workspace-button">${escapeHtml(state.workspaceName)} ▾</button>
      <button class="command-button" data-action="open-command">${shortcutLabel("K")}</button>
      <button class="ghost-button" data-action="open-settings">Settings</button>
    </header>
  `;
}

function renderActivityBar() {
  const activities = [
    ["tools", "T", "Tools"],
    ["round", "R", "Round"],
    ["web", "W", "Web"],
    ["ai", "AI", "AI"],
  ];
  return `
    <nav class="activity-bar">
      ${activities
        .map(
          ([id, label, title]) => `
            <button class="activity-button ${state.activeActivity === id ? "active" : ""}" title="${title}" data-activity="${id}">
              <span class="activity-short">${label}</span>
              <span class="activity-label">${title}</span>
            </button>
          `,
        )
        .join("")}
    </nav>
  `;
}

function renderSidebar() {
  const title = {
    tools: "Tools",
    search: "Search",
    round: "Round",
    evidence: "Evidence",
    web: "Web",
    ai: "AI",
  }[state.activeActivity];
  return `
    <aside class="sidebar">
      <h2>${title}</h2>
      ${state.activeActivity === "tools" ? renderToolsSidebar() : ""}
      ${state.activeActivity === "search" ? `<button class="wide-button" data-action="new-search">New Evidence Search</button>` : ""}
      ${state.activeActivity === "web" ? `<button class="wide-button" data-action="open-browser">Open Google Docs</button>` : ""}
      ${state.activeActivity === "round" ? renderRoundSidebar() : ""}
      <p class="sidebar-note">Backfiles, searches, drafts, rounds, and research tabs open inside the same workspace.</p>
      <div class="sidebar-spacer"></div>
      <button class="wide-button secondary" data-action="open-settings">Settings</button>
    </aside>
  `;
}

function renderToolsSidebar() {
  return `
    <button class="wide-button" data-tool="card-separator">Card Separator</button>
    <button class="wide-button" data-action="new-search">Evidence Search</button>
    <button class="wide-button" data-command="document.import">Import Document</button>
    <button class="wide-button" data-command="draft.rebuttal">Draft Rebuttal</button>
  `;
}

function renderRoundSidebar() {
  const round = state.round;
  const ready = round?.status === "ready" || round?.status === "active";
  return `
    <div class="round-sidebar-status">
      <span>Round Status</span>
      <strong>${escapeHtml(statusLabel(round?.status || "empty"))}</strong>
    </div>
    <nav class="round-side-nav">
      ${ROUND_VIEWS.map((view) => {
        const unavailable = view.requiresReady && !ready;
        return `
          <button
            class="${state.roundView === view.id ? "active" : ""}"
            data-round-view="${view.id}"
          >
            <span>${view.label}</span>
            ${unavailable ? `<small>Not ready</small>` : ""}
          </button>
        `;
      }).join("")}
    </nav>
    <button class="wide-button" data-command="round.start">New Round</button>
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
                <span>${escapeHtml(tab.title)}</span>
                ${state.tabs.length > 1 ? `<span class="tab-close" data-close-tab="${tab.id}">×</span>` : ""}
              </button>
            `,
          )
          .join("")}
      </div>
      <button class="new-tab-button" data-action="new-search">+</button>
    </div>
  `;
}

function renderPanel() {
  const tab = activeTab();
  if (!tab) return "";
  if (tab.type === "evidence") return renderEvidenceView(tab.state);
  if (tab.type === "browser") return renderBrowserView(tab.state);
  if (tab.type === "document") return renderPlaceholder("Document Import", "Document import and preview will plug into the document model.");
  if (tab.type === "round") return renderRoundView();
  if (tab.type === "tool") return renderToolView(tab.state);
  if (tab.type === "draft") return renderPlaceholder("Draft", "Source-grounded AI output will open here.");
  if (tab.type === "database") return renderPlaceholder("Database", "Backfiles, indexes, and import health will live here.");
  return renderSearchView(tab.state);
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
          <h1>Card Separator</h1>
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
              <p>${tool.error ? escapeHtml(tool.error) : hasInput ? "Run preview to separate the DOCX into raw card text." : "No preview yet."}</p>
            </section>`
      }

    </section>
  `;
}

function basename(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || path || "";
}

function renderRoundView() {
  const round = state.round;
  const ready = round?.status === "ready" || round?.status === "active";
  const currentView = ROUND_VIEWS.some((view) => view.id === state.roundView) ? state.roundView : "setup";
  const currentMeta = ROUND_VIEWS.find((view) => view.id === currentView);
  const unavailable = currentMeta?.requiresReady && !ready;
  return `
    <section class="view round-view">
      <header class="round-header">
        <div>
          <p>Round Workspace</p>
          <h1>${escapeHtml(round?.name || "New Round")}</h1>
        </div>
        <span class="round-status ${round?.status || "empty"}">${escapeHtml(statusLabel(round?.status || "empty"))}</span>
      </header>
      <nav class="round-nav">
        ${ROUND_VIEWS.map((view) => {
          const pending = view.requiresReady && !ready;
          return `
            <button class="${currentView === view.id ? "active" : ""} ${pending ? "pending" : ""}" data-round-view="${view.id}">
              ${view.label}
            </button>
          `;
        }).join("")}
      </nav>
      ${unavailable ? renderRoundUnavailable(currentMeta) : ""}
      ${!unavailable && currentView === "setup" ? renderRoundSetup(round) : ""}
      ${!unavailable && currentView === "evidence" ? renderRoundEvidence() : ""}
      ${!unavailable && currentView === "ask" ? renderRoundAsk() : ""}
      ${!unavailable && currentView === "flow" ? renderRoundFlow(round) : ""}
      ${!unavailable && currentView === "browser" ? renderRoundBrowser() : ""}
    </section>
  `;
}

function renderRoundUnavailable(view) {
  return `
    <section class="round-empty-state">
      <h2>${escapeHtml(view?.label || "Round")}</h2>
      <p>Add sources and build the round before this workspace has content.</p>
      <button data-round-view="setup">Go to Setup</button>
    </section>
  `;
}

function renderRoundSetup(round) {
  const ours = round?.sources.find((source) => source.side === "ours");
  const opponent = round?.sources.find((source) => source.side === "opponent");
  const canBuild = (isTauri() ? Boolean(ours || opponent) : Boolean(ours && opponent)) && round?.status !== "building";
  return `
    <section class="round-setup">
      <div class="source-grid">
        ${renderSourcePanel("ours", "Your Side", ours)}
        ${renderSourcePanel("opponent", "Opponent", opponent)}
      </div>
      <div class="build-actions">
        <button data-action="build-round" ${canBuild ? "" : "disabled"}>Build Round</button>
        <span>${canBuild ? "Ready to unlock round evidence." : isTauri() ? "Add an opponent DSL source or register your side." : "Add one source for each side."}</span>
      </div>
      ${round?.status === "building" ? renderBuildProgress(round) : ""}
      ${round?.status === "ready" ? `<div class="ready-banner">Round is ready. Evidence, Ask, and Flow are unlocked.</div>` : ""}
    </section>
  `;
}

function renderSourcePanel(side, title, source) {
  const sourcePath = state.roundSourcePaths[side] || source?.path || "";
  const grammarPath = state.roundSourcePaths.opponentGrammar || "";
  return `
    <article class="source-panel" data-drop-side="${side}">
      <div>
        <h2>${title}</h2>
        <p>${source ? escapeHtml(source.filename) : side === "opponent" ? "Drop DOCX and edit the .sa grammar below" : "Drop DOCX/PDF/TXT here"}</p>
      </div>
      <div class="source-paths">
        <input class="path-input" value="${escapeAttr(sourcePath)}" placeholder="/absolute/path/to/${side === "opponent" ? "opponent.docx" : "our-file.docx"}" data-source-path="${side}" />
        ${
          side === "opponent"
            ? `<input class="path-input" value="${escapeAttr(grammarPath)}" placeholder="/absolute/path/to/grammar.sa, optional" data-grammar-path="opponent" />
               ${renderGrammarEditor()}`
            : ""
        }
      </div>
      <div class="source-actions">
        <label class="file-button">
          Browse
          <input type="file" accept="${side === "opponent" ? ".docx,.sa" : ".docx,.pdf,.txt"}" data-file-side="${side}" multiple />
        </label>
        <button data-action="import-source" data-source-side="${side}">${side === "opponent" ? "Import DOCX" : "Register"}</button>
      </div>
      ${
        source
          ? `<div class="source-meta">
              <span>${escapeHtml(statusLabel(source.status))}</span>
              <span>${source.cardCount ? `${source.cardCount} cards` : source.diagnostics?.[0] ? escapeHtml(source.diagnostics[0]) : "Waiting to build"}</span>
            </div>`
          : `<small>${side === "opponent" ? "Opponent import uses DOCX plus the editable SA structure." : "Native import for your side is registered for now."}</small>`
      }
    </article>
  `;
}

function renderGrammarEditor() {
  return `
    <section class="grammar-editor">
      <label>
        <span>SA Grammar</span>
        <textarea spellcheck="false" data-grammar-editor>${escapeHtml(state.roundGrammarText)}</textarea>
      </label>
      <pre aria-hidden="true">${highlightGrammar(state.roundGrammarText)}</pre>
    </section>
  `;
}

function renderBuildProgress(round) {
  const bySide = ["ours", "opponent"].map((side) => round.sources.find((source) => source.side === side)).filter(Boolean);
  return `
    <section class="build-progress">
      <h2>Building Round</h2>
      <div class="build-columns">
        ${bySide.map((source) => `
          <article class="build-card">
            <h3>${source.side === "ours" ? "Your Side" : "Opponent"}</h3>
            <strong>${escapeHtml(source.filename)}</strong>
            <div class="progress-row"><span>Parse</span><progress value="${source.parseProgress}" max="1"></progress></div>
            <div class="progress-row"><span>Index</span><progress value="${source.indexProgress}" max="1"></progress></div>
            <small>${source.cardCount} cards detected</small>
          </article>
        `).join("")}
      </div>
      <div class="stage-list">
        ${round.buildStages.map((stage) => `
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

function renderRoundEvidence() {
  const grouped = groupBy(state.roundEvidence, (card) => card.section || "Evidence");
  return `
    <section class="round-evidence">
      <div class="round-controls">
        ${segmented("round-scope", state.roundEvidenceScope, [["ours", "Our Side"], ["opponent", "Opponent"], ["both", "Both"]])}
        <input class="filter-input" value="${escapeAttr(state.roundEvidenceFilter)}" placeholder="Filter evidence..." data-round-evidence-filter />
      </div>
      <div class="evidence-groups">
        ${Object.entries(grouped).map(([section, cards]) => `
          <section class="evidence-group">
            <h2>${escapeHtml(section)}</h2>
            ${cards.map((card) => renderRoundEvidenceCard(card)).join("")}
          </section>
        `).join("") || `<p class="muted">No evidence matches this filter.</p>`}
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
      <span>${card.side === "ours" ? "Our Side" : "Opponent"}</span>
    </article>
  `;
}

function renderRoundAsk() {
  const backendLabel = isTauri() ? "Desktop backend" : "Mock preview";
  const resultCount = state.roundAsk.loading ? "Searching" : `${state.roundAsk.results.length} result${state.roundAsk.results.length === 1 ? "" : "s"}`;
  return `
    <section class="round-ask">
      <header class="ask-header">
        <div>
          <h2>Ask One Side</h2>
          <p>Choose a side, ask the round question, and Secret Agenda returns evidence from that lane.</p>
        </div>
        <span>${backendLabel}</span>
      </header>
      <form class="ask-form" data-form="round-ask">
        <label class="ask-question">
          <span>Question</span>
          <textarea name="query" placeholder="opponent says AI increases addiction...">${escapeHtml(state.roundAsk.query)}</textarea>
        </label>
        <div class="ask-controls-grid">
          <div class="ask-control">
            <span>Side</span>
            ${segmented("ask-scope", normalizeAskScope(state.roundAsk.scope), [["ours", "Our Side"], ["opponent", "Opponent"]])}
          </div>
          <div class="ask-control">
            <span>Mode</span>
            ${segmented("ask-mode", state.roundAsk.mode, [["smart", "Smart"], ["exact", "Exact"], ["semantic", "Semantic"], ["advanced", "Advanced"]])}
          </div>
          <button>${state.roundAsk.loading ? "Searching..." : "Search"}</button>
        </div>
      </form>
      ${state.roundAsk.error ? `<div class="warning">${escapeHtml(state.roundAsk.error)}</div>` : ""}
      <div class="view-meta">
        <span>${resultCount}</span>
        <span>${normalizeAskScope(state.roundAsk.scope) === "ours" ? "Searching our evidence" : "Searching opponent evidence"}</span>
      </div>
      <div class="ask-layout">
        <section class="ask-results">
          <h2>Best Evidence</h2>
          ${state.roundAsk.results.map((result, index) => renderAskResult(result, index)).join("") || `<p class="muted">Ask a round question to see evidence and a grounded response.</p>`}
        </section>
        <section class="ai-response">
          <h2>AI Response</h2>
          ${renderGeneratedResponse(state.roundAsk.generated)}
        </section>
      </div>
    </section>
  `;
}

function renderAskResult(result, index) {
  const side = result.card.side === "opponent" ? "Opponent" : "Our Side";
  const score = Number.isFinite(result.score) ? result.score : 0;
  return `
    <article class="ask-result">
      <div class="result-head">
        <h3>${escapeHtml(result.card.citation || result.card.title || "Evidence")}</h3>
        <span class="score">${Math.round(score * 100)}%</span>
      </div>
      <div class="result-meta">
        <span class="relationship">${escapeHtml(result.relationship)}</span>
        <span>${side}</span>
      </div>
      <p>${escapeHtml(result.card.tag)}</p>
      <small>${escapeHtml(result.explanation)}</small>
      ${result.card.bodyPreview || result.card.body ? `<p class="ask-preview">${escapeHtml(result.card.bodyPreview || result.card.body).slice(0, 260)}</p>` : ""}
      <div class="result-actions">
        <button data-open-ask-card="${index}">Open</button>
        <button data-add-ask-flow="${index}">Add to Flow</button>
      </div>
    </article>
  `;
}

function renderGeneratedResponse(response) {
  if (state.roundAsk.loading) return `<p class="muted">Retrieving evidence and drafting a grounded response...</p>`;
  if (!response) return `<p class="muted">Generated rebuttals will always include source evidence.</p>`;
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
      <button data-action="add-generated-flow">Add to Flow</button>
      <button data-action="regenerate-answer">Regenerate</button>
    </div>
  `;
}

function renderRoundFlow(round) {
  return `
    <section class="flow-board">
      ${(round?.flows || []).map((flow) => `
        <article class="flow-card">
          <h2>${escapeHtml(flow.opponentClaim)}</h2>
          <p>${escapeHtml(flow.response)}</p>
          <small>${flow.evidenceIds.length} evidence source${flow.evidenceIds.length === 1 ? "" : "s"}</small>
        </article>
      `).join("") || `<p class="muted">Add evidence or a generated response from Ask to start the round flow.</p>`}
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
  return `
    <section class="view search-view">
      <form class="search-input" data-form="search">
        <span>Search</span>
        <input name="query" value="${escapeAttr(query)}" placeholder="AI sports betting addiction" />
        <button>Run</button>
      </form>
      <div class="view-meta">
        <span>${state.search.loading ? "Searching..." : `${state.search.results.length} cards`}</span>
        ${state.settings.developerSearchDiagnostics ? `<span class="diagnostic-pill">Developer diagnostics enabled</span>` : ""}
      </div>
      ${state.search.error ? `<div class="warning">${escapeHtml(state.search.error)}</div>` : ""}
      <div class="results-list">
        ${state.search.results.map((card, index) => renderResultCard(card, index)).join("")}
      </div>
    </section>
  `;
}

function renderResultCard(card, index) {
  return `
    <article class="result-card" data-open-result="${index}">
      <div class="result-head">
        <h3>${escapeHtml(card.title || "Evidence Card")}</h3>
        <span class="score">${card.score ? `${Math.round(card.score * 100)}%` : "--"}</span>
      </div>
      <div class="result-tag">${escapeHtml(card.tag || "")}</div>
      <p>${escapeHtml(card.bodyPreview || "")}</p>
      <div class="result-actions">
        <span>${escapeHtml(card.section || "")}</span>
        <button data-copy-result="${index}">Copy</button>
        <button data-open-result-button="${index}">Open</button>
      </div>
      ${
        state.settings.developerSearchDiagnostics && card.diagnostics
          ? `<div class="diagnostics">Retrieval: ${card.diagnostics.retrieval.join(", ")} · Final ${Math.round(card.diagnostics.finalScore * 100)}%</div>`
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
  const categories = ["General", "Appearance", "Search", "Evidence", "Documents", "Opponent Parsing", "AI", "Browser", "Round", "Shortcuts", "Storage", "Privacy", "Advanced", "Developer"];
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
    state.roundView = roundViewButton.dataset.roundView;
    const ready = state.round?.status === "ready" || state.round?.status === "active";
    if (state.roundView === "evidence" && ready) refreshRoundEvidence();
    else render();
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
    openTab("tool", toolButton.dataset.tool === "card-separator" ? "Card Separator" : "Tool", { tool: toolButton.dataset.tool });
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
    if (card) openTab("evidence", card.title || "Evidence Card", card);
    return;
  }

  const resultCard = target.closest("[data-open-result]");
  if (resultCard && !target.closest("button")) {
    const card = state.search.results[Number(resultCard.dataset.openResult)];
    if (card) openTab("evidence", card.title || "Evidence Card", card);
    return;
  }

  const cardIdButton = target.closest("[data-open-card-id]");
  if (cardIdButton) {
    const card = findEvidenceCard(cardIdButton.dataset.openCardId);
    if (card) openTab("evidence", card.citation || "Evidence Card", card);
    return;
  }

  const askCardButton = target.closest("[data-open-ask-card]");
  if (askCardButton) {
    const result = state.roundAsk.results[Number(askCardButton.dataset.openAskCard)];
    if (result?.card) openTab("evidence", result.card.citation || "Evidence Card", result.card);
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
    if (name === "round-scope") {
      state.roundEvidenceScope = value;
      refreshRoundEvidence();
    } else if (name === "ask-mode") {
      state.roundAsk.mode = value;
      render();
    } else if (name === "ask-scope") {
      state.roundAsk.scope = normalizeAskScope(value);
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
  else if (action === "new-search") openTab("search", "Evidence Search", {});
  else if (action === "open-browser") openTab("browser", "Google Docs", { url: "https://docs.google.com" });
  else if (action === "import-source") addRoundSource(actionElement.dataset.sourceSide, null);
  else if (action === "build-round") buildRound();
  else if (action === "run-card-separator") runCardSeparatorPreview();
  else if (action === "copy-separator-text") copySeparatorText();
  else if (action === "add-generated-flow") addGeneratedToFlow();
  else if (action === "regenerate-answer") runRoundAsk(state.roundAsk.query);
  else if (action === "copy-generated" && state.roundAsk.generated) {
    navigator.clipboard?.writeText(state.roundAsk.generated.text);
    flashStatus("Copied generated response.");
  }
  else if (action === "reset-appearance") {
    state.settings = { ...state.settings, theme: "dark", density: "comfortable", scale: 1 };
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

  if (form.dataset.form === "search") {
    const query = new FormData(form).get("query").toString();
    activeTab().state.query = query;
    activeTab().title = query ? `Search: ${query}` : "Evidence Search";
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

  if (input.matches("[data-grammar-editor]")) {
    state.roundGrammarText = input.value;
    input.closest(".grammar-editor")?.querySelector("pre")?.replaceChildren(fragmentFromHtml(highlightGrammar(input.value)));
    saveWorkspaceSoon();
    return;
  }

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
    saveWorkspaceSoon();
  }

  if (input.dataset.grammarPath === "opponent") {
    state.roundSourcePaths.opponentGrammar = input.value;
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
      openTab("search", `Search: ${text}`, { query: text });
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

function normalizeAskScope(scope) {
  return scope === "opponent" ? "opponent" : "ours";
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
    openTab("search", "Evidence Search", {});
  }
  if (commandKey && event.key.toLowerCase() === "w") {
    event.preventDefault();
    closeTab(state.activeTabId);
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
    state.roundSourcePaths = { ...state.roundSourcePaths, ...(workspace.roundSourcePaths || {}) };
    state.roundGrammarText = workspace.roundGrammarText || state.roundGrammarText;
    state.roundView = workspace.roundView || state.roundView;
    state.roundEvidenceScope = workspace.roundEvidenceScope || state.roundEvidenceScope;
    state.roundEvidenceFilter = workspace.roundEvidenceFilter || state.roundEvidenceFilter;
    state.roundAsk = { ...state.roundAsk, ...(workspace.roundAsk || {}) };
    state.roundAsk.scope = normalizeAskScope(state.roundAsk.scope);
    state.layout = {
      ...state.layout,
      ...(workspace.layout || {}),
    };
    state.layout.activityWidth = clamp(Number(state.layout.activityWidth) || 92, 48, 150);
    state.layout.sidebarWidth = clamp(Number(state.layout.sidebarWidth) || 280, 180, 420);
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
    state.activeTabId = roundTab.id;
    state.activeActivity = "round";
  }
  await ensureRound();
  if (state.round?.status === "ready") {
    await refreshRoundEvidence(false);
  }
  render();
  installNativeDragDrop().catch(console.error);
  if (activeTab()?.type === "search") runSearch(activeTab()?.state?.query || "");
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
