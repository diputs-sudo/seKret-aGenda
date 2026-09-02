#include "hybrid.hpp"
#include "native_pipeline.hpp"
#include "query_intent.hpp"
#include "reranker.hpp"

#include <chrono>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <optional>
#include <string>

namespace {

struct Arguments {
    std::string command;
    std::string query_or_docx;
    std::string db = "var/sekret-agenda.sqlite3";
    std::string schema = "backend/models/sqlite_schema.sql";
    std::string kind = "all";
    std::size_t limit = 10;
    std::size_t top = 3;
    std::size_t max_chars = 6000;
    bool reset = false;
    bool rerank = false;
    bool debug = false;
    bool concept_debug = false;
    bool timings = false;
    bool full_context_rerank = false;
    bool model_rerank = false;
    std::size_t model_rerank_debug_trials = 0;
};

[[noreturn]] void usage(const std::string& error = {}) {
    if (!error.empty()) {
        std::cerr << "native pipeline error: " << error << "\n\n";
    }
    std::cerr << R"(Native seKret-aGenda retrieval pipeline

Usage:
  scripts/native_pipeline.sh import-docx <case.docx> --db <database.sqlite3>
  scripts/native_pipeline.sh build-vector --db <database.sqlite3> [--kind fast|deep|all] [--reset]
  scripts/native_pipeline.sh query <query> --db <database.sqlite3> [--limit N] [--top N] [--full-context] [--model-rerank] [--verify-model-rerank N] [--debug] [--timings]
  scripts/native_pipeline.sh query-vector <query> --db <database.sqlite3> [--limit N] [--rerank] [--top N] [--timings]
  scripts/native_pipeline.sh analyze <query> --db <database.sqlite3> [--limit N] [--top N] [--debug] [--concept-debug] [--timings]

`query-hybrid` remains a compatibility alias for the lightweight `query` command.

The native pipeline stores exact-cosine vectors in SQLite. It intentionally
does not read Chroma's Python-managed on-disk format.
)";
    std::exit(error.empty() ? 0 : 2);
}

std::size_t parse_size(const std::string& flag, const std::string& value) {
    try {
        const auto parsed = std::stoull(value);
        if (parsed == 0) {
            throw std::invalid_argument("zero");
        }
        return static_cast<std::size_t>(parsed);
    } catch (const std::exception&) {
        usage(flag + " requires a positive integer");
    }
}

Arguments parse_arguments(int argc, char** argv) {
    if (argc < 2) {
        usage();
    }
    Arguments result;
    result.command = argv[1];
    if (result.command != "import-docx" && result.command != "build-vector"
        && result.command != "query-vector" && result.command != "query"
        && result.command != "analyze" && result.command != "query-hybrid") {
        usage("unknown command: " + result.command);
    }
    int index = 2;
    if (result.command != "build-vector") {
        if (index >= argc || argv[index][0] == '-') {
            usage(result.command + " requires a DOCX path or query");
        }
        result.query_or_docx = argv[index++];
    }
    while (index < argc) {
        const std::string flag = argv[index++];
        const auto require_value = [&](std::string& destination) {
            if (index >= argc) {
                usage(flag + " requires a value");
            }
            destination = argv[index++];
        };
        if (flag == "--db") {
            require_value(result.db);
        } else if (flag == "--schema") {
            require_value(result.schema);
        } else if (flag == "--kind") {
            require_value(result.kind);
        } else if (flag == "--limit") {
            std::string value;
            require_value(value);
            result.limit = parse_size(flag, value);
        } else if (flag == "--top") {
            std::string value;
            require_value(value);
            result.top = parse_size(flag, value);
        } else if (flag == "--max-chars") {
            std::string value;
            require_value(value);
            result.max_chars = parse_size(flag, value);
        } else if (flag == "--reset") {
            result.reset = true;
        } else if (flag == "--full-context") {
            result.full_context_rerank = true;
        } else if (flag == "--model-rerank") {
            result.model_rerank = true;
        } else if (flag == "--verify-model-rerank") {
            std::string value;
            require_value(value);
            result.model_rerank_debug_trials = parse_size(flag, value);
            result.model_rerank = true;
            result.debug = true;
        } else if (flag == "--rerank") {
            result.rerank = true;
        } else if (flag == "--debug") {
            result.debug = true;
        } else if (flag == "--concept-debug") {
            result.concept_debug = true;
        } else if (flag == "--timings") {
            result.timings = true;
        } else if (flag == "--chroma") {
            std::string ignored;
            require_value(ignored);
            std::cerr << "Note: --chroma is ignored by the native SQLite vector pipeline.\n";
        } else {
            usage("unknown option: " + flag);
        }
    }
    return result;
}

void print_timing_header() {
    std::cout << "\nStage timings (ms)\n" << std::string(45, '-') << "\n";
}

void print_timing(const std::string& stage, double milliseconds) {
    std::cout << std::left << std::setw(32) << stage
              << std::right << std::fixed << std::setprecision(1)
              << milliseconds << "\n";
}

void print_vector_timings(const sekret::hybrid::NativeVectorQueryStats& stats, double rerank_ms) {
    print_timing_header();
    print_timing("vector availability", stats.vector_availability_ms);
    print_timing("query embedding", stats.embedding_ms);
    print_timing("native vector search", stats.vector_search_ms);
    print_timing("SQLite hydration", stats.hydration_ms);
    if (rerank_ms >= 0.0) {
        print_timing("lightweight rerank", rerank_ms);
    }
}

void print_response_timings(const sekret::hybrid::HybridSearchResponse& response) {
    print_timing_header();
    for (const auto& [stage, milliseconds] : response.timings) {
        print_timing(stage, milliseconds);
    }
}

void print_vector_results(const Arguments& arguments) {
    sekret::hybrid::NativeVectorQueryStats stats;
    const auto rows = sekret::hybrid::query_native_vectors(
        arguments.db,
        arguments.query_or_docx,
        arguments.limit,
        &stats
    );
    std::cout << "Vector results\n" << std::string(45, '-') << "\n";
    for (const auto& row : rows) {
        const auto source = row.card_name.empty() ? row.author.value_or("Unknown") : row.card_name;
        std::cout << row.score << "  " << source << "  " << row.section << "  |  " << row.tag << "\n";
    }
    if (!arguments.rerank) {
        if (arguments.debug || arguments.timings) {
            print_vector_timings(stats, -1.0);
        }
        return;
    }
    const auto rerank_started = std::chrono::steady_clock::now();
    const auto reranked = sekret::hybrid::LightweightRelevanceReranker().rerank(
        arguments.query_or_docx,
        rows,
        arguments.top
    );
    const auto rerank_elapsed = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - rerank_started
    ).count();
    std::cout << "\nReranked vector results\n" << std::string(45, '-') << "\n";
    if (reranked.empty()) {
        std::cout << "No cards passed the lightweight relevance gate.\n";
    }
    for (const auto& row : reranked) {
        const auto source = row.card.card_name.empty()
            ? row.card.author.value_or("Unknown")
            : row.card.card_name;
        std::cout << row.card.score << " rel=" << row.assessment.relevance_score << "  "
                  << source << "  " << row.card.section << "  |  " << row.card.tag << "\n";
    }
    if (arguments.debug || arguments.timings) {
        print_vector_timings(stats, rerank_elapsed);
    }
}

void print_hybrid_results(const Arguments& arguments) {
    const bool analysis_mode = arguments.command == "analyze";
    sekret::hybrid::HybridEngine engine({arguments.db, {}});
    sekret::hybrid::HybridSearchRequest request;
    request.query = arguments.query_or_docx;
    request.full_context_rerank = arguments.full_context_rerank;
    request.model_rerank = arguments.model_rerank;
    request.model_rerank_debug_trials = arguments.model_rerank_debug_trials;
    request.limit = arguments.command == "query-hybrid" ? arguments.limit : arguments.top;
    request.vector_limit = arguments.limit;
    request.lexical_limit = arguments.limit;
    request.citation_limit = arguments.limit;
    request.analysis_mode = analysis_mode;
    request.include_diagnostics = arguments.debug || arguments.concept_debug;
    const auto response = engine.search(request);
    if (arguments.debug) {
        const auto intent = sekret::hybrid::parse_query_intent(arguments.query_or_docx);
        std::cout << "Query intent\n" << std::string(45, '-') << "\n";
        std::cout << "Execution: " << (analysis_mode ? "full analysis" : "lightweight production query") << "\n";
        std::cout << "Mode: " << sekret::hybrid::search_mode_name(intent.search_mode) << "\n";
        std::cout << "Search text: " << intent.search_text << "\n";
        std::cout << "Retrieval text: " << sekret::hybrid::retrieval_text(intent) << "\n";
        std::cout << "Opponent claim: " << intent.opponent_claim.value_or("") << "\n";
        const auto& concepts = arguments.concept_debug ? intent.concepts : intent.phrase_concepts;
        if (!response.logs.empty()) {
            std::cout << "Pipeline log\n" << std::string(45, '-') << "\n";
            for (const auto& line : response.logs) {
                std::cout << line << "\n";
            }
            std::cout << "\n";
        }
        std::cout << (arguments.concept_debug ? "Expanded concepts: " : "Concepts: ");
        for (std::size_t index = 0; index < concepts.size(); ++index) {
            if (index != 0) {
                std::cout << ", ";
            }
            std::cout << concepts[index];
        }
        std::cout << "\n\n";
    }
    std::cout << (analysis_mode ? "Analysis results\n" : "Query results\n")
              << std::string(45, '-') << "\n";
    if (response.cards.empty()) {
        std::cout << "No evidence matched.\n";
    }
    for (const auto& card : response.cards) {
        std::cout << card.score << "  " << card.title << "  " << card.section << "  |  " << card.tag << "\n";
        if (card.diagnostics.has_value()) {
            std::cout << "Sources: ";
            for (std::size_t index = 0; index < card.diagnostics->retrieval_sources.size(); ++index) {
                if (index != 0) {
                    std::cout << ", ";
                }
                std::cout << card.diagnostics->retrieval_sources[index];
            }
            std::cout << "\n";
            std::cout << "Retrieval=" << card.diagnostics->retrieval_score
                      << " rerank=" << card.diagnostics->reranker_score << "\n";
        }
    }
    if (arguments.debug || arguments.timings) {
        print_response_timings(response);
    }
}
} // namespace

int main(int argc, char** argv) {
    try {
        const auto arguments = parse_arguments(argc, argv);
        if (arguments.command == "import-docx") {
            const auto stats = sekret::hybrid::import_docx_to_sqlite(
                arguments.query_or_docx,
                arguments.db,
                arguments.schema
            );
            std::cout << "Built " << arguments.db << "\n";
            std::cout << "Document: " << stats.document_name << "\n";
            std::cout << "Sections: " << stats.sections << "\n";
            std::cout << "Cards: " << stats.cards << "\n";
            std::cout << "Citations: " << stats.citations << "\n";
            std::cout << "Highlights: " << stats.highlights << "\n";
        } else if (arguments.command == "build-vector") {
            const auto stats = sekret::hybrid::build_native_vector_cache(
                arguments.db,
                arguments.kind,
                arguments.reset,
                arguments.max_chars
            );
            if (arguments.kind == "fast" || arguments.kind == "all") {
                std::cout << "Cached " << stats.fast << " fast native vectors.\n";
            }
            if (arguments.kind == "deep" || arguments.kind == "all") {
                std::cout << "Cached " << stats.deep << " deep native vectors.\n";
            }
        } else if (arguments.command == "query-vector") {
            print_vector_results(arguments);
        } else {
            print_hybrid_results(arguments);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "native pipeline failed: " << error.what() << "\n";
        return 1;
    }
}
