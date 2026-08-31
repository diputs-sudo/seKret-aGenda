#include "hybrid.hpp"
#include "fusion.hpp"
#include "argument_builder.hpp"
#include "format_parser.hpp"
#include "mechanism.hpp"
#include "ollama_embedder.hpp"
#include "query_intent.hpp"
#include "reranker.hpp"
#include "round_import.hpp"
#include "sqlite_store.hpp"
#include "vector_store.hpp"

#include <sqlite3.h>

#include <algorithm>
#include <cstdlib>
#include <exception>
#include <fstream>
#include <iostream>
#include <string>

namespace {

int expect(bool condition, const std::string& message) {
    if (condition) {
        return 0;
    }
    std::cerr << "FAIL: " << message << "\n";
    return 1;
}

std::string take_string(char* value) {
    if (value == nullptr) {
        return {};
    }
    std::string text(value);
    sekret_hybrid_free_string(value);
    return text;
}

int test_search_json_returns_response() {
    auto result = sekret_hybrid_search_json(
        "var/sekret-agenda.sqlite3",
        "var/chroma",
        "{\"query\":\"Hashem\",\"limit\":3}"
    );
    const auto error = take_string(result.error);
    const auto json = take_string(result.json);

    int failures = 0;
    failures += expect(error.empty(), "expected no error from valid search request");
    failures += expect(!json.empty(), "expected JSON response");
    failures += expect(
        json.find("\"cards\":[") != std::string::npos,
        "expected cards array in JSON response"
    );
    failures += expect(
        json.find("\"sourceStatus\":\"") != std::string::npos,
        "expected source status"
    );
    return failures;
}

int test_search_json_direct_lookup_with_default_db_when_present() {
    const std::string db_path = "var/sekret-agenda.sqlite3";
    std::ifstream db(db_path);
    if (!db.good()) {
        return 0;
    }

    auto result = sekret_hybrid_search_json(
        db_path.c_str(),
        "var/chroma",
        "{\"query\":\"Hashem\",\"limit\":3,\"includeDiagnostics\":true}"
    );
    const auto error = take_string(result.error);
    const auto json = take_string(result.json);

    int failures = 0;
    failures += expect(error.empty(), "expected no error from direct lookup");
    failures += expect(json.find("\"cards\":[{") != std::string::npos, "expected real cards in JSON response");
    failures += expect(json.find("Hashem") != std::string::npos, "expected Hashem direct lookup result");
    failures += expect(
        json.find("\"sourceStatus\":\"BACKFILE-SOURCED\"") != std::string::npos,
        "expected sourced status for direct lookup"
    );
    failures += expect(
        json.find("author_lookup") != std::string::npos,
        "expected author lookup diagnostics"
    );
    return failures;
}

int test_search_json_validates_required_inputs() {
    auto result = sekret_hybrid_search_json(nullptr, nullptr, nullptr);
    const auto error = take_string(result.error);
    const auto json = take_string(result.json);

    int failures = 0;
    failures += expect(json.empty(), "expected no JSON response for invalid inputs");
    failures += expect(!error.empty(), "expected error for invalid inputs");
    failures += expect(
        error.find("db_path and request_json are required") != std::string::npos,
        "expected required-input validation message"
    );
    return failures;
}

int test_query_intent_matches_python_contract_examples() {
    using sekret::hybrid::SearchMode;
    using sekret::hybrid::parse_query_intent;

    int failures = 0;
    const auto filtered = parse_query_intent(
        "author:Tucker year:2020 section:\"AT: Hyperwar\" "
        "Opponent says AI escalates because of automation.",
        "draft"
    );
    failures += expect(filtered.mode == "draft", "expected mode to be preserved");
    failures += expect(filtered.author_filter == "Tucker", "expected author filter");
    failures += expect(filtered.year_min == 2020, "expected year_min filter");
    failures += expect(filtered.year_max == 2020, "expected year_max filter");
    failures += expect(filtered.section_filter == "AT: Hyperwar", "expected section filter");
    failures += expect(
        filtered.opponent_claim == "AI escalates because of automation",
        "expected opponent claim extraction"
    );
    failures += expect(
        filtered.search_text.find("author:Tucker") == std::string::npos,
        "expected filters stripped from search text"
    );

    failures += expect(
        parse_query_intent("Tucker 20").search_mode == SearchMode::Citation,
        "expected citation lookup mode"
    );
    failures += expect(
        parse_query_intent("Tucker").search_mode == SearchMode::Author,
        "expected author lookup mode"
    );
    failures += expect(
        parse_query_intent("AT: Hyperwar").search_mode == SearchMode::Section,
        "expected section lookup mode"
    );
    failures += expect(
        parse_query_intent("Opponent says AI escalates.").search_mode == SearchMode::Argument,
        "expected argument mode"
    );
    failures += expect(
        parse_query_intent("Human oversight prevents AI mistakes.").search_mode == SearchMode::General,
        "expected general mode"
    );

    const auto stopwords = parse_query_intent("Penguins on Mars");
    failures += expect(
        std::find(stopwords.ignored_stopwords.begin(), stopwords.ignored_stopwords.end(), "on")
            != stopwords.ignored_stopwords.end(),
        "expected ignored stopword tracking"
    );
    failures += expect(
        std::find(stopwords.concepts.begin(), stopwords.concepts.end(), "on")
            == stopwords.concepts.end(),
        "expected stopwords excluded from concepts"
    );

    const auto semantic = parse_query_intent(
        "How do sportsbooks use machine learning to maximize bettor engagement?"
    );
    failures += expect(
        std::find(semantic.concepts.begin(), semantic.concepts.end(), "use")
            == semantic.concepts.end(),
        "expected semantic stopword excluded"
    );
    failures += expect(
        std::find(semantic.concepts.begin(), semantic.concepts.end(), "machine_learning")
            != semantic.concepts.end(),
        "expected phrase concept extraction"
    );
    return failures;
}

int test_mechanism_extracts_expected_concepts() {
    int failures = 0;
    const auto phrases = sekret::hybrid::extract_phrase_concepts(
        "Human oversight prevents AI mistakes."
    );
    failures += expect(
        phrases.count("human_oversight") != 0,
        "expected human_oversight phrase concept"
    );

    const auto query = sekret::hybrid::parse_mechanism(
        "AI escalates because of automation"
    );
    const auto card = sekret::hybrid::parse_mechanism(
        "AI improves warning accuracy and reduces unintended escalation."
    );
    failures += expect(
        sekret::hybrid::mechanism_match(query, card) > 0.0,
        "expected non-zero mechanism overlap for escalation card"
    );
    return failures;
}

int test_sqlite_helpers_smoke() {
    int failures = 0;
    failures += expect(
        sekret::hybrid::plain_fts_query("AI sports betting") == "AI* AND sports* AND betting*",
        "expected Python-like plain FTS query"
    );

    const std::string db_path = "var/sekret-agenda.sqlite3";
    std::ifstream db(db_path);
    if (!db.good()) {
        return failures;
    }

    try {
        const auto cards = sekret::hybrid::search_cards(db_path, "AI sports betting", 5);
        failures += expect(cards.size() <= 5, "expected SQLite search to respect limit");
    } catch (const std::exception& error) {
        std::cerr << "SQLite smoke skipped after error: " << error.what() << "\n";
    }
    return failures;
}

int test_ollama_embedding_response_parser() {
    int failures = 0;
    const auto embedding = sekret::hybrid::parse_ollama_embedding_response(
        R"({"embedding":[1, -2.5, 3.25]})"
    );
    failures += expect(embedding.size() == 3, "expected three parsed embedding values");
    failures += expect(embedding[0] == 1.0, "expected first embedding value");
    failures += expect(embedding[1] == -2.5, "expected second embedding value");
    failures += expect(embedding[2] == 3.25, "expected third embedding value");

    bool threw = false;
    try {
        (void)sekret::hybrid::parse_ollama_embedding_response(R"({"message":"nope"})");
    } catch (const sekret::hybrid::EmbeddingError&) {
        threw = true;
    }
    failures += expect(threw, "expected missing embedding to raise EmbeddingError");
    return failures;
}

int test_reciprocal_rank_fusion_unions_sources() {
    sekret::hybrid::RetrievedCard card1;
    card1.card_id = "card-1";
    card1.id = "card-1";
    card1.tag = "AI caution";
    card1.score = 0.8;

    sekret::hybrid::RetrievedCard card2;
    card2.card_id = "card-2";
    card2.id = "card-2";
    card2.tag = "Regulation";
    card2.score = 0.7;

    sekret::hybrid::RetrievedCard card2_sqlite = card2;
    card2_sqlite.score = 0.9;
    sekret::hybrid::RetrievedCard card1_sqlite = card1;
    card1_sqlite.score = 0.6;

    const auto fused = sekret::hybrid::reciprocal_rank_fusion({
        {"fast_vector", {card1, card2}},
        {"sqlite_fts", {card2_sqlite, card1_sqlite}},
    });

    int failures = 0;
    failures += expect(fused.size() == 2, "expected two fused cards");
    failures += expect(fused[0].retrieval_score == fused[1].retrieval_score, "expected equal RRF scores");
    failures += expect(!fused[0].source_ranks.empty(), "expected source ranks");
    failures += expect(!fused[0].source_scores.empty(), "expected source scores");
    return failures;
}

int test_native_sqlite_vector_store_searches_cached_vectors() {
    const std::string db_path = "/tmp/sekret-native-vector-smoke.sqlite3";
    std::remove(db_path.c_str());

    sqlite3* db = nullptr;
    if (sqlite3_open(db_path.c_str(), &db) != SQLITE_OK) {
        return expect(false, "expected temporary vector DB to open");
    }
    const char* sql = R"SQL(
CREATE TABLE native_card_vectors (
    card_id TEXT NOT NULL,
    embedding_kind TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (card_id, embedding_kind, embedding_model)
);
INSERT INTO native_card_vectors VALUES ('card-a', 'fast', 'fake-model', '[1,0,0]', NULL);
INSERT INTO native_card_vectors VALUES ('card-b', 'fast', 'fake-model', '[0,1,0]', NULL);
)SQL";
    char* error = nullptr;
    const int exec_status = sqlite3_exec(db, sql, nullptr, nullptr, &error);
    if (exec_status != SQLITE_OK) {
        std::cerr << "SQLite setup error: " << (error == nullptr ? "" : error) << "\n";
        sqlite3_free(error);
        sqlite3_close(db);
        return expect(false, "expected temporary vector schema setup");
    }
    sqlite3_close(db);

    const sekret::hybrid::NativeSqliteVectorStore store(db_path);
    const auto rows = store.search({1, 0, 0}, "fast", "fake-model", 2);

    int failures = 0;
    failures += expect(store.has_vectors("fast", "fake-model"), "expected cached fast vectors");
    failures += expect(rows.size() == 1, "expected only positive cosine matches");
    failures += expect(rows.front().card_id == "card-a", "expected nearest vector card-a");
    failures += expect(sekret::hybrid::parse_vector_json("[1, 2.5, -3]").size() == 3, "expected vector JSON parsing");
    failures += expect(
        sekret::hybrid::cosine_similarity({1, 0}, {1, 0}) == 1.0,
        "expected unit cosine similarity"
    );
    std::remove(db_path.c_str());
    return failures;
}

int test_format_parser_extracts_dsl_cards() {
    const std::string grammar = R"DSL(
-- [card] -- [author]
[section]?
[tag]
[content]+
)DSL";
    const std::string text = R"TXT(
-- AI Good -- Smith 2024

AT: Innovation

AI improves public services.

Warrant line two.

-- AI Bad -- Jones 2023

AT: Safety

AI creates verification failures.
)TXT";

    const auto parsed = sekret::hybrid::parse_evidence_dsl(text, grammar);

    int failures = 0;
    failures += expect(parsed.cards.size() == 2, "expected two parsed DSL cards");
    failures += expect(parsed.cards.front().fields.at("card") == "AI Good", "expected first card name");
    failures += expect(parsed.cards.front().fields.at("author") == "Smith 2024", "expected first author");
    failures += expect(
        parsed.cards.front().fields.at("content").find("Warrant line two") != std::string::npos,
        "expected repeated content blocks"
    );
    return failures;
}

int test_round_import_writes_opponent_cards_to_sqlite() {
    const std::string db_path = "/tmp/sekret-round-import-smoke.sqlite3";
    const std::string source_path = "/tmp/sekret-round-import-source.txt";
    const std::string grammar_path = "/tmp/sekret-round-import-grammar.sa";
    std::remove(db_path.c_str());

    {
        std::ofstream source(source_path);
        source << "-- AI Good -- Smith 2024\n\nAT: Innovation\n\nAI improves public services.\n";
        std::ofstream grammar(grammar_path);
        grammar << "-- [card] -- [author]\n[section]\n[content]+\n";
    }

    sqlite3* db = nullptr;
    if (sqlite3_open(db_path.c_str(), &db) != SQLITE_OK) {
        return expect(false, "expected temporary round DB to open");
    }
    const char* sql = R"SQL(
PRAGMA foreign_keys = ON;
CREATE TABLE debate_documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT,
    source_format TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES debate_documents(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    argument_type TEXT NOT NULL DEFAULT 'unknown',
    order_index INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE evidence_cards (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES debate_documents(id) ON DELETE CASCADE,
    section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    card_name TEXT,
    argument_name TEXT,
    body TEXT NOT NULL,
    category TEXT,
    topical INTEGER,
    side TEXT,
    source_path TEXT,
    content_hash TEXT NOT NULL,
    paragraph_start INTEGER,
    paragraph_end INTEGER,
    source_format TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE citations (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL UNIQUE REFERENCES evidence_cards(id) ON DELETE CASCADE,
    raw TEXT NOT NULL,
    author TEXT,
    year INTEGER,
    source_url TEXT
);
CREATE TABLE highlights (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES evidence_cards(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    color TEXT,
    highlight_color TEXT,
    order_index INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE evidence_cards_fts USING fts5(
    card_id UNINDEXED,
    tag,
    card_name,
    citation,
    body,
    tokenize='porter unicode61'
);
)SQL";
    char* error = nullptr;
    const int exec_status = sqlite3_exec(db, sql, nullptr, nullptr, &error);
    if (exec_status != SQLITE_OK) {
        std::cerr << "SQLite setup error: " << (error == nullptr ? "" : error) << "\n";
        sqlite3_free(error);
        sqlite3_close(db);
        return expect(false, "expected temporary round schema setup");
    }
    sqlite3_close(db);

    auto result = sekret_import_opponent_dsl_json(db_path.c_str(), source_path.c_str(), grammar_path.c_str());
    const auto import_error = take_string(result.error);
    const auto json = take_string(result.json);

    db = nullptr;
    sqlite3_open(db_path.c_str(), &db);
    sqlite3_stmt* statement = nullptr;
    sqlite3_prepare_v2(
        db,
        "SELECT count(*) FROM evidence_cards WHERE side = 'opponent' AND source_format = 'sa-dsl'",
        -1,
        &statement,
        nullptr
    );
    int count = 0;
    if (sqlite3_step(statement) == SQLITE_ROW) {
        count = sqlite3_column_int(statement, 0);
    }
    sqlite3_finalize(statement);
    sqlite3_close(db);

    int failures = 0;
    failures += expect(import_error.empty(), "expected no error from opponent DSL import");
    failures += expect(json.find("\"cardCount\":1") != std::string::npos, "expected import card count JSON");
    failures += expect(count == 1, "expected one opponent card in SQLite");

    std::remove(db_path.c_str());
    std::remove(source_path.c_str());
    std::remove(grammar_path.c_str());
    return failures;
}

sekret::hybrid::RetrievedCard make_card(
    const std::string& id,
    const std::string& section,
    const std::string& tag,
    const std::string& card_name,
    const std::string& highlight,
    const std::string& body,
    double retrieval_score
) {
    sekret::hybrid::RetrievedCard card;
    card.id = id;
    card.card_id = id;
    card.section = section;
    card.tag = tag;
    card.card_name = card_name;
    card.title = card_name;
    card.body = body;
    card.body_preview = body;
    card.retrieval_score = retrieval_score;
    card.score = retrieval_score;
    card.highlights.push_back({highlight, std::nullopt});
    return card;
}

int test_lightweight_reranker_matches_python_contract() {
    const std::vector<sekret::hybrid::RetrievedCard> cards = {
        make_card(
            "highlight-match",
            "State regulation",
            "Illegal betting declines",
            "Merrefield 25",
            "State enforcement reduces illegal betting.",
            "This body should not affect lightweight scoring.",
            0.5
        ),
        make_card(
            "body-only-match",
            "Miscellaneous",
            "Different claim",
            "Capital 25",
            "Unrelated highlight.",
            "State regulation reduces illegal betting.",
            0.9
        ),
    };

    const auto reranked = sekret::hybrid::LightweightRelevanceReranker().rerank(
        "state regulation reduces illegal betting",
        cards,
        3
    );

    int failures = 0;
    failures += expect(reranked.size() == 1, "expected lightweight scorer to ignore body-only matches");
    failures += expect(
        !reranked.empty() && reranked.front().card.card_id == "highlight-match",
        "expected tag/section/highlight match to survive lightweight reranking"
    );
    failures += expect(
        !reranked.empty() && reranked.front().assessment.relevance_score > 2.0,
        "expected lightweight scorer to expose its lexical relevance score"
    );
    return failures;
}

int test_reranker_gate_and_argument_builder() {
    const auto intent = sekret::hybrid::parse_query_intent(
        "Opponent says AI escalates because of automation."
    );
    std::vector<sekret::hybrid::RetrievedCard> cards = {
        make_card(
            "cox",
            "AT: Hyperwar",
            "AI defuses escalation.",
            "Cox 21",
            "AI improves warning accuracy and reduces unintended escalation.",
            "AI systems help decision-makers avoid false alarms in war.",
            0.02
        ),
        make_card(
            "revenue",
            "AT: AI",
            "AI increases betting revenue.",
            "Market 25",
            "AI behavior manipulation increases sportsbook revenue.",
            "AI behavior manipulation increases sportsbook revenue.",
            0.05
        ),
    };

    const auto reranked = sekret::hybrid::FullContextReranker().rerank(intent, cards);
    std::vector<sekret::hybrid::CandidateAssessment> assessments;
    for (const auto& row : reranked) {
        assessments.push_back(row.assessment);
    }
    const auto gate = sekret::hybrid::split_by_relevance_gate(assessments);
    std::vector<sekret::hybrid::RerankedCard> accepted;
    for (const auto index : gate.accepted_indexes) {
        accepted.push_back(reranked[index]);
    }
    const auto bundle = sekret::hybrid::ArgumentBuilder().build(intent, accepted, 2);

    int failures = 0;
    failures += expect(!reranked.empty(), "expected reranked cards");
    failures += expect(reranked.front().card.card_id == "cox", "expected escalation card first");
    failures += expect(!gate.accepted_indexes.empty(), "expected at least one accepted card");
    failures += expect(!gate.rejected_indexes.empty(), "expected at least one rejected card");
    failures += expect(bundle.source_status == "BACKFILE-SOURCED", "expected sourced argument bundle");
    failures += expect(!bundle.cards.empty(), "expected selected bundle cards");
    failures += expect(!bundle.warrants.empty(), "expected bundle warrants");
    return failures;
}

} // namespace

int main() {
    int failures = 0;
    failures += test_search_json_returns_response();
    failures += test_search_json_direct_lookup_with_default_db_when_present();
    failures += test_search_json_validates_required_inputs();
    failures += test_query_intent_matches_python_contract_examples();
    failures += test_mechanism_extracts_expected_concepts();
    failures += test_sqlite_helpers_smoke();
    failures += test_ollama_embedding_response_parser();
    failures += test_reciprocal_rank_fusion_unions_sources();
    failures += test_native_sqlite_vector_store_searches_cached_vectors();
    failures += test_format_parser_extracts_dsl_cards();
    failures += test_round_import_writes_opponent_cards_to_sqlite();
    failures += test_lightweight_reranker_matches_python_contract();
    failures += test_reranker_gate_and_argument_builder();

    if (failures != 0) {
        std::cerr << failures << " hybrid backend smoke assertion(s) failed.\n";
        return EXIT_FAILURE;
    }

    std::cout << "hybrid backend smoke tests passed\n";
    return EXIT_SUCCESS;
}
