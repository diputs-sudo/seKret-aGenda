import { invoke } from "@tauri-apps/api/core";
import { mockBackend } from "./services/mockBackend.js";
import "./styles/app.css";

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
  { id: "settings.open", title: "Open settings", keywords: "appearance developer search ai" },
];

const ROUND_VIEWS = [
  { id: "setup", label: "Setup", requiresReady: false },
  { id: "evidence", label: "Evidence", requiresReady: true },
  { id: "ask", label: "Ask", requiresReady: true },
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
  round: null,
  roundView: "setup",
  roundBuildTick: 0,
  roundEvidence: [],
  roundEvidenceScope: "both",
  roundEvidenceFilter: "",
  roundAsk: {
    query: "",
    mode: "smart",
    scope: "both",
    loading: false,
    results: [],
    generated: null,
    error: "",
  },
};

const app = document.querySelector("#app");
const WEB_STORAGE_KEYS = {
  settings: "secret-agenda.settings",
  workspace: "secret-agenda.workspace",
};

function isTauri() {
  return Boolean(window.__TAURI_INTERNALS__);
}

async function call(command, payload = {}) {
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
        roundView: state.roundView,
        roundEvidenceScope: state.roundEvidenceScope,
        roundEvidenceFilter: state.roundEvidenceFilter,
        roundAsk: state.roundAsk,
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
  state.round = await mockBackend.addRoundSource(round, side, file);
  state.roundView = "setup";
  state.activeActivity = "round";
  saveWorkspaceSoon();
  render();
}

async function buildRound() {
  const round = await ensureRound();
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

async function refreshRoundEvidence() {
  state.roundEvidence = await mockBackend.listEvidence({
    scope: state.roundEvidenceScope,
    query: state.roundEvidenceFilter,
  });
  render();
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
    const results = await mockBackend.searchRound({
      query: queryText,
      scope: state.roundAsk.scope,
      mode: state.roundAsk.mode,
    });
    const generated = await mockBackend.generateAnswer({
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

function findEvidenceCard(id) {
  return [...state.roundEvidence, ...state.roundAsk.results.map((result) => result.card)].find((card) => card?.id === id);
}

function render() {
  applyTheme();
  app.innerHTML = `
    <main class="app-shell">
      ${renderTopbar()}
      <section class="workspace-grid">
        ${renderActivityBar()}
        ${renderSidebar()}
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
  if (tab.type === "draft") return renderPlaceholder("Draft", "Source-grounded AI output will open here.");
  if (tab.type === "database") return renderPlaceholder("Database", "Backfiles, indexes, and import health will live here.");
  return renderSearchView(tab.state);
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
  const canBuild = Boolean(ours && opponent) && round?.status !== "building";
  return `
    <section class="round-setup">
      <div class="source-grid">
        ${renderSourcePanel("ours", "Your Side", ours)}
        ${renderSourcePanel("opponent", "Opponent", opponent)}
      </div>
      <div class="build-actions">
        <button data-action="build-round" ${canBuild ? "" : "disabled"}>Build Round</button>
        <span>${canBuild ? "Ready to process both files." : "Add one source for each side."}</span>
      </div>
      ${round?.status === "building" ? renderBuildProgress(round) : ""}
      ${round?.status === "ready" ? `<div class="ready-banner">Round is ready. Evidence, Ask, and Flow are unlocked.</div>` : ""}
    </section>
  `;
}

function renderSourcePanel(side, title, source) {
  return `
    <article class="source-panel" data-drop-side="${side}">
      <div>
        <h2>${title}</h2>
        <p>${source ? escapeHtml(source.filename) : "Drop DOCX here"}</p>
      </div>
      <div class="source-actions">
        <label class="file-button">
          Browse
          <input type="file" accept=".docx,.pdf,.txt" data-file-side="${side}" />
        </label>
        <button data-action="mock-source" data-source-side="${side}">Use Mock</button>
      </div>
      ${
        source
          ? `<div class="source-meta">
              <span>${escapeHtml(statusLabel(source.status))}</span>
              <span>${source.cardCount ? `${source.cardCount} cards` : "Waiting to build"}</span>
            </div>`
          : `<small>File picker and drag/drop use the same ingestion surface.</small>`
      }
    </article>
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
  return `
    <section class="round-ask">
      <form class="ask-form" data-form="round-ask">
        <textarea name="query" placeholder="opponent says AI increases addiction...">${escapeHtml(state.roundAsk.query)}</textarea>
        <div class="ask-controls">
          ${segmented("ask-mode", state.roundAsk.mode, [["smart", "Smart"], ["exact", "Exact"], ["semantic", "Semantic"], ["advanced", "Advanced"]])}
          ${segmented("ask-scope", state.roundAsk.scope, [["both", "Both"], ["ours", "Our"], ["opponent", "Opp"]])}
          <button>${state.roundAsk.loading ? "Searching..." : "Search"}</button>
        </div>
      </form>
      ${state.roundAsk.error ? `<div class="warning">${escapeHtml(state.roundAsk.error)}</div>` : ""}
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
  return `
    <article class="ask-result">
      <div class="result-head">
        <h3>${escapeHtml(result.card.citation)}</h3>
        <span class="score">${Math.round(result.score * 100)}%</span>
      </div>
      <span class="relationship">${escapeHtml(result.relationship)}</span>
      <p>${escapeHtml(result.card.tag)}</p>
      <small>${escapeHtml(result.explanation)}</small>
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
  return `
    <p>${escapeHtml(response.text)}</p>
    <div class="source-list">
      <strong>Evidence used</strong>
      ${response.sources.map((id) => {
        const card = findEvidenceCard(id);
        return `<button data-open-card-id="${id}">${escapeHtml(card?.citation || id)}</button>`;
      }).join("")}
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
      state.roundAsk.scope = value;
      render();
    }
    return;
  }

  const mockSourceButton = target.closest("[data-source-side]");
  if (mockSourceButton) {
    const side = mockSourceButton.dataset.sourceSide;
    addRoundSource(side, { name: side === "ours" ? "OUR_case.docx" : "OPP_case.docx" });
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
  else if (action === "build-round") buildRound();
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
  if (!(input instanceof HTMLInputElement)) return;

  if (input.classList.contains("command-input")) {
    state.commandText = input.value;
    filterCommandRows();
  }

  if (input.matches("[data-round-evidence-filter]")) {
    state.roundEvidenceFilter = input.value;
    clearTimeout(refreshRoundEvidence.timer);
    refreshRoundEvidence.timer = setTimeout(refreshRoundEvidence, 180);
  }
});

app.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;

  if (input.dataset.fileSide && input.files?.[0]) {
    addRoundSource(input.dataset.fileSide, input.files[0]);
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
  const dropZone = event.target instanceof Element ? event.target.closest("[data-drop-side]") : null;
  if (!dropZone) return;
  event.preventDefault();
  dropZone.classList.add("drag-over");
});

app.addEventListener("dragleave", (event) => {
  const dropZone = event.target instanceof Element ? event.target.closest("[data-drop-side]") : null;
  dropZone?.classList.remove("drag-over");
});

app.addEventListener("drop", (event) => {
  const dropZone = event.target instanceof Element ? event.target.closest("[data-drop-side]") : null;
  if (!dropZone) return;
  event.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = event.dataTransfer?.files?.[0];
  if (file) addRoundSource(dropZone.dataset.dropSide, file);
});

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

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (state.settings.theme === "system") render();
});

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
    state.roundView = workspace.roundView || state.roundView;
    state.roundEvidenceScope = workspace.roundEvidenceScope || state.roundEvidenceScope;
    state.roundEvidenceFilter = workspace.roundEvidenceFilter || state.roundEvidenceFilter;
    state.roundAsk = { ...state.roundAsk, ...(workspace.roundAsk || {}) };
  }
  if (!state.tabs.some((tab) => tab.type === "round")) {
    const roundTab = { id: crypto.randomUUID(), type: "round", title: "Round Setup", state: {} };
    state.tabs.unshift(roundTab);
    state.activeTabId = roundTab.id;
    state.activeActivity = "round";
  }
  await ensureRound();
  if (state.round?.status === "ready") {
    state.roundEvidence = await mockBackend.listEvidence({ scope: state.roundEvidenceScope, query: state.roundEvidenceFilter });
  }
  render();
  if (activeTab()?.type === "search") runSearch(activeTab()?.state?.query || "");
}

bootstrap();

function filterCommandRows() {
  const query = state.commandText.trim().toLowerCase();
  document.querySelectorAll("[data-command-search]").forEach((row) => {
    row.hidden = query.length > 0 && !row.dataset.commandSearch.includes(query);
  });
}
