import roundFixture from "../mock/round.json";
import oursEvidenceFixture from "../mock/evidence_ours.json";
import opponentEvidenceFixture from "../mock/evidence_opponent.json";
import searchResultsFixture from "../mock/search_results.json";
import generatedResponseFixture from "../mock/generated_response.json";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const evidence = [...oursEvidenceFixture, ...opponentEvidenceFixture];

function clone(value) {
  return structuredClone(value);
}

function sourceFromFile(side, file) {
  return {
    id: crypto.randomUUID(),
    filename: file?.name || `${side === "ours" ? "OUR" : "OPP"}_case.docx`,
    path: file?.name || "browser-preview.docx",
    side,
    status: "loaded",
    cardCount: 0,
    parseProgress: 0,
    indexProgress: 0,
    error: ""
  };
}

export const mockBackend = {
  async createRound() {
    await sleep(80);
    return {
      ...clone(roundFixture),
      id: crypto.randomUUID(),
      status: "configuring"
    };
  },

  async addRoundSource(round, side, file) {
    await sleep(120);
    return {
      ...round,
      status: "configuring",
      sources: [...round.sources.filter((source) => source.side !== side), sourceFromFile(side, file)]
    };
  },

  async buildRound(round) {
    await sleep(120);
    return {
      ...round,
      status: "building",
      sources: round.sources.map((source) => ({
        ...source,
        status: "indexing",
        cardCount: source.side === "ours" ? 147 : 93,
        parseProgress: 0,
        indexProgress: 0
      })),
      buildStages: round.buildStages.map((stage) => ({ ...stage, status: "pending", progress: 0 }))
    };
  },

  progressRoundBuild(round, tick) {
    const stageIndex = Math.min(round.buildStages.length - 1, Math.floor(tick / 2));
    const stageProgress = tick % 2 === 0 ? 0.54 : 1;
    const buildStages = round.buildStages.map((stage, index) => {
      if (index < stageIndex) return { ...stage, status: "complete", progress: 1 };
      if (index === stageIndex) return { ...stage, status: stageProgress >= 1 ? "complete" : "running", progress: stageProgress };
      return { ...stage, status: "pending", progress: 0 };
    });
    const done = buildStages.every((stage) => stage.status === "complete");

    return {
      ...round,
      status: done ? "ready" : "building",
      sources: round.sources.map((source) => ({
        ...source,
        status: done ? "ready" : "indexing",
        parseProgress: Math.min(1, (tick + 1) / 5),
        indexProgress: Math.min(1, (tick + 1) / 10),
        cardCount: source.cardCount || (source.side === "ours" ? 147 : 93)
      })),
      buildStages
    };
  },

  async listEvidence({ scope = "both", query = "" } = {}) {
    await sleep(120);
    const normalized = query.trim().toLowerCase();
    return evidence.filter((card) => {
      const sideMatch = scope === "both" || card.side === scope;
      const text = `${card.section} ${card.tag} ${card.author} ${card.year} ${card.body}`.toLowerCase();
      return sideMatch && (!normalized || text.includes(normalized));
    });
  },

  async searchRound({ query = "", scope = "both", mode = "smart" } = {}) {
    await sleep(180);
    const scopedEvidence = await this.listEvidence({ scope });
    return searchResultsFixture
      .map((result) => ({
        ...clone(result),
        mode,
        card: scopedEvidence.find((card) => card.id === result.cardId) || evidence.find((card) => card.id === result.cardId)
      }))
      .filter((result) => result.card)
      .map(({ cardId, ...result }) => ({
        ...result,
        explanation: query ? result.explanation : "Mock search result from the round service."
      }));
  },

  async generateAnswer({ evidenceIds = [] } = {}) {
    await sleep(220);
    const response = clone(generatedResponseFixture);
    response.sources = evidenceIds.length ? evidenceIds : response.sources;
    return response;
  },

  async addFlow(round, flow) {
    await sleep(80);
    return {
      ...round,
      flows: [
        ...round.flows,
        {
          id: crypto.randomUUID(),
          opponentClaim: flow.opponentClaim,
          response: flow.response,
          evidenceIds: flow.evidenceIds || [],
          notes: flow.notes || ""
        }
      ]
    };
  }
};
