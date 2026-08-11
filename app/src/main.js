import { invoke } from "@tauri-apps/api/core";
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
    type: "search",
    title: "Evidence Search",
    state: { query: "" },
  },
];

const commands = [
  { id: "search.evidence", title: "Search evidence", keywords: "backfile query cards" },
  { id: "search.opponent", title: "Search opponent", keywords: "round speech document" },
  { id: "draft.rebuttal", title: "Draft rebuttal", keywords: "ai response argument" },
  { id: "document.import", title: "Import document", keywords: "docx pdf text" },
  { id: "browser.open", title: "Open website", keywords: "web google docs research" },
  { id: "round.start", title: "Start round", keywords: "flow opponent prep" },
  { id: "settings.open", title: "Open settings", keywords: "appearance developer search ai" },
];

const state = {
  settings: { ...DEFAULT_SETTINGS },
  workspaceName: "Default Workspace",
  tabs: [...DEFAULT_TABS],
  activeTabId: DEFAULT_TABS[0].id,
  activeActivity: "search",
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
    const plain = `${card.title || "Evidence Card"}\n${card.tag || ""}\n\n${card.citation || ""}\n\n${card.body || card.bodyPreview || ""}`.trim();
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
    return [
      {
        id: "preview-1",
        title: "Pampus 25",
        author: "Pampus",
        year: 2025,
        section: "AT: State money used for addiction rehab",
        tag: "AI used to grow sportsbook revenue and personalize gambling behavior.",
        citation: "Brian Pampus, GamblingHarm, 2025",
        url: "https://example.com",
        bodyPreview: `Preview result for "${query}". Connect through Tauri to search the local SQLite database.`,
        body: "Artificial intelligence can be used by online sports betting operators to grow revenue by targeting user behavior.",
        highlights: ["AI can personalize promotions.", "Operators optimize for revenue."],
        score: 0.94,
        documentName: "Preview Backfile",
        diagnostics: payload.query?.includeDiagnostics
          ? { retrieval: ["mock"], concepts: ["ai", "betting"], finalScore: 0.94 }
          : null,
      },
    ];
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
    openTab("round", "Round", {});
    openedTab = true;
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
  bindEvents();
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
    ["files", "F", "Files"],
    ["search", "S", "Search"],
    ["round", "R", "Round"],
    ["evidence", "E", "Evidence"],
    ["web", "W", "Web"],
    ["ai", "AI", "AI"],
  ];
  return `
    <nav class="activity-bar">
      ${activities
        .map(
          ([id, label, title]) => `
            <button class="activity-button ${state.activeActivity === id ? "active" : ""}" title="${title}" data-activity="${id}">
              ${label}
            </button>
          `,
        )
        .join("")}
    </nav>
  `;
}

function renderSidebar() {
  const title = {
    files: "Files",
    search: "Search",
    round: "Round",
    evidence: "Evidence",
    web: "Web",
    ai: "AI",
  }[state.activeActivity];
  return `
    <aside class="sidebar">
      <h2>${title}</h2>
      ${state.activeActivity === "search" ? `<button class="wide-button" data-action="new-search">New Evidence Search</button>` : ""}
      ${state.activeActivity === "web" ? `<button class="wide-button" data-action="open-browser">Open Google Docs</button>` : ""}
      ${state.activeActivity === "round" ? `<button class="wide-button" data-command="round.start">Start Round</button>` : ""}
      <p class="sidebar-note">Backfiles, searches, drafts, rounds, and research tabs open inside the same workspace.</p>
      <div class="sidebar-spacer"></div>
      <button class="wide-button secondary" data-action="open-settings">Settings</button>
    </aside>
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
  if (tab.type === "round") return renderPlaceholder("Round", "Opponent arguments, our answers, and grounded rebuttal generation will live here.");
  if (tab.type === "draft") return renderPlaceholder("Draft", "Source-grounded AI output will open here.");
  if (tab.type === "database") return renderPlaceholder("Database", "Backfiles, indexes, and import health will live here.");
  return renderSearchView(tab.state);
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
          <h1>${escapeHtml(card.title || "Evidence Card")}</h1>
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

function bindEvents() {
  document.querySelectorAll("[data-activity]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeActivity = button.dataset.activity;
      saveWorkspaceSoon();
      render();
    });
  });

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTabId = button.dataset.tab;
      saveWorkspaceSoon();
      render();
    });
  });

  document.querySelectorAll("[data-close-tab]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeTab(button.dataset.closeTab);
    });
  });

  document.querySelectorAll("[data-action]").forEach((element) => {
    element.addEventListener("click", (event) => {
      const action = element.dataset.action;
      if (element.dataset.modal && event.target === element) return;
      if (action === "open-command") state.commandPaletteOpen = true;
      if (action === "open-settings") state.settingsOpen = true;
      if (action === "close-command" && event.target === element) state.commandPaletteOpen = false;
      if (action === "close-settings" && (event.target === element || element.tagName === "BUTTON")) state.settingsOpen = false;
      if (action === "new-search") openTab("search", "Evidence Search", {});
      if (action === "open-browser") openTab("browser", "Google Docs", { url: "https://docs.google.com" });
      if (action === "reset-appearance") {
        state.settings = { ...state.settings, theme: "dark", density: "comfortable", scale: 1 };
        saveSettings();
      }
      if (action === "open-data-dir" && state.paths?.appData) {
        call("reveal_path", { path: state.paths.appData }).catch(console.error);
      }
      render();
    });
  });

  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => executeCommand(button.dataset.command, state.commandText));
  });

  document.querySelectorAll("[data-open-result]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      const card = state.search.results[Number(element.dataset.openResult)];
      if (card) openTab("evidence", card.title || "Evidence Card", card);
    });
  });

  document.querySelectorAll("[data-open-result-button]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const card = state.search.results[Number(button.dataset.openResultButton)];
      if (card) openTab("evidence", card.title || "Evidence Card", card);
    });
  });

  document.querySelectorAll("[data-copy-result]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const card = state.search.results[Number(button.dataset.copyResult)];
      if (card) copyCard(card);
    });
  });

  document.querySelector("[data-copy-active-card]")?.addEventListener("click", () => copyCard(activeTab().state));

  document.querySelectorAll("[data-open-url]").forEach((button) => {
    button.addEventListener("click", () => {
      const url = button.dataset.openUrl;
      call("open_external_url", { url }).catch(() => window.open(url, "_blank"));
    });
  });

  document.querySelector('[data-form="search"]')?.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = new FormData(event.currentTarget).get("query").toString();
    activeTab().state.query = query;
    activeTab().title = query ? `Search: ${query}` : "Evidence Search";
    saveWorkspaceSoon();
    runSearch(query);
  });

  document.querySelector('[data-form="browser"]')?.addEventListener("submit", (event) => {
    event.preventDefault();
    const url = normalizeUrl(new FormData(event.currentTarget).get("url").toString());
    activeTab().state.url = url;
    activeTab().title = "Web: " + url.replace(/^https?:\/\//, "").slice(0, 32);
    saveWorkspaceSoon();
    render();
  });

  document.querySelector(".command-input")?.addEventListener("input", (event) => {
    state.commandText = event.target.value;
    filterCommandRows();
  });

  document.querySelector(".command-input")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      const text = event.currentTarget.value.trim();
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

  document.querySelectorAll("[data-settings-category]").forEach((button) => {
    button.addEventListener("click", () => {
      state.settingsCategory = button.dataset.settingsCategory;
      render();
    });
  });

  document.querySelectorAll("[data-setting]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.setting;
      if (input.type === "checkbox") state.settings[key] = input.checked;
      else if (input.type === "number" || input.type === "range") state.settings[key] = Number(input.value);
      else state.settings[key] = input.value;
      saveSettings();
      render();
    });
  });
}

async function saveSettings() {
  await call("save_settings", { settings: state.settings }).catch(console.error);
}

function normalizeUrl(value) {
  return value.includes("://") ? value : `https://${value}`;
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
    state.activeActivity = workspace.activeActivity || state.activeActivity;
  }
  render();
  runSearch(activeTab()?.state?.query || "");
}

bootstrap();

function filterCommandRows() {
  const query = state.commandText.trim().toLowerCase();
  document.querySelectorAll("[data-command-search]").forEach((row) => {
    row.hidden = query.length > 0 && !row.dataset.commandSearch.includes(query);
  });
}
