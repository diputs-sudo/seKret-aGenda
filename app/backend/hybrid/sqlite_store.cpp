#include "sqlite_store.hpp"

#include <sqlite3.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <memory>
#include <sstream>
#include <stdexcept>

namespace sekret::hybrid {
namespace {

struct SqliteDeleter {
    void operator()(sqlite3* db) const {
        if (db != nullptr) {
            sqlite3_close(db);
        }
    }
};

struct StatementDeleter {
    void operator()(sqlite3_stmt* statement) const {
        if (statement != nullptr) {
            sqlite3_finalize(statement);
        }
    }
};

using Database = std::unique_ptr<sqlite3, SqliteDeleter>;
using Statement = std::unique_ptr<sqlite3_stmt, StatementDeleter>;

Database open_database(const std::string& db_path) {
    sqlite3* raw = nullptr;
    if (sqlite3_open_v2(db_path.c_str(), &raw, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        std::string message = raw == nullptr ? "could not open SQLite database" : sqlite3_errmsg(raw);
        if (raw != nullptr) {
            sqlite3_close(raw);
        }
        throw std::runtime_error(message);
    }
    return Database(raw);
}

Statement prepare(sqlite3* db, const std::string& sql) {
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &raw, nullptr) != SQLITE_OK) {
        throw std::runtime_error(sqlite3_errmsg(db));
    }
    return Statement(raw);
}

void bind_text(sqlite3_stmt* statement, int index, const std::string& value) {
    if (sqlite3_bind_text(statement, index, value.c_str(), -1, SQLITE_TRANSIENT) != SQLITE_OK) {
        throw std::runtime_error("failed to bind SQLite text parameter");
    }
}

void bind_int(sqlite3_stmt* statement, int index, int value) {
    if (sqlite3_bind_int(statement, index, value) != SQLITE_OK) {
        throw std::runtime_error("failed to bind SQLite int parameter");
    }
}

std::string column_text(sqlite3_stmt* statement, const char* name) {
    const int count = sqlite3_column_count(statement);
    for (int index = 0; index < count; ++index) {
        if (std::string(sqlite3_column_name(statement, index)) != name) {
            continue;
        }
        const auto* text = sqlite3_column_text(statement, index);
        return text == nullptr ? std::string() : reinterpret_cast<const char*>(text);
    }
    return {};
}

std::optional<std::string> optional_column_text(sqlite3_stmt* statement, const char* name) {
    const auto text = column_text(statement, name);
    if (text.empty()) {
        return std::nullopt;
    }
    return text;
}

std::optional<int> optional_column_int(sqlite3_stmt* statement, const char* name) {
    const int count = sqlite3_column_count(statement);
    for (int index = 0; index < count; ++index) {
        if (std::string(sqlite3_column_name(statement, index)) != name) {
            continue;
        }
        if (sqlite3_column_type(statement, index) == SQLITE_NULL) {
            return std::nullopt;
        }
        return sqlite3_column_int(statement, index);
    }
    return std::nullopt;
}

double column_double(sqlite3_stmt* statement, const char* name) {
    const int count = sqlite3_column_count(statement);
    for (int index = 0; index < count; ++index) {
        if (std::string(sqlite3_column_name(statement, index)) == name) {
            return sqlite3_column_double(statement, index);
        }
    }
    return 0.0;
}

std::string title_for_card(const std::optional<std::string>& author, const std::optional<int>& year, const std::string& citation) {
    if (author.has_value() && !author->empty()) {
        if (year.has_value() && author->find(std::to_string(*year)) == std::string::npos) {
            return *author + " " + std::to_string(*year);
        }
        return *author;
    }
    return citation.substr(0, 80);
}

double score_from_rank(double rank) {
    if (rank == 0.0) {
        return 1.0;
    }
    if (rank < 0.0) {
        const double raw_score = std::abs(rank);
        return std::max(std::round((raw_score / (1.0 + raw_score)) * 1000.0) / 1000.0, 0.001);
    }
    return std::max(std::round((1.0 / (1.0 + rank)) * 1000.0) / 1000.0, 0.001);
}

std::vector<std::string> plain_terms(const std::string& query) {
    std::vector<std::string> tokens;
    std::string current;
    for (char character : query) {
        if (std::isalnum(static_cast<unsigned char>(character)) || character == '\'') {
            current.push_back(character);
            continue;
        }
        if (!current.empty()) {
            tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) {
        tokens.push_back(current);
    }
    return tokens;
}

std::string or_query(const std::string& fts_query) {
    std::istringstream input(fts_query);
    std::ostringstream output;
    std::string token;
    bool first = true;
    while (input >> token) {
        if (token == "AND") {
            continue;
        }
        if (!first) {
            output << " OR ";
        }
        output << token;
        first = false;
    }
    return output.str();
}

bool is_advanced_fts_query(const std::string& query) {
    return query.find('"') != std::string::npos
        || query.find('*') != std::string::npos
        || query.find(" OR ") != std::string::npos
        || query.find(" AND ") != std::string::npos
        || query.find(" NEAR ") != std::string::npos;
}

std::vector<Highlight> load_highlights(sqlite3* db, const std::string& card_id) {
    auto statement = prepare(
        db,
        "SELECT text, coalesce(color, highlight_color, '') AS color "
        "FROM highlights WHERE card_id = ?1 ORDER BY order_index"
    );
    bind_text(statement.get(), 1, card_id);

    std::vector<Highlight> highlights;
    while (sqlite3_step(statement.get()) == SQLITE_ROW) {
        const auto text = column_text(statement.get(), "text");
        if (text.empty()) {
            continue;
        }
        Highlight highlight;
        highlight.text = text;
        highlight.color = optional_column_text(statement.get(), "color");
        highlights.push_back(std::move(highlight));
    }
    return highlights;
}

RetrievedCard card_from_statement(sqlite3* db, sqlite3_stmt* statement, double score) {
    RetrievedCard card;
    card.id = column_text(statement, "id");
    card.card_id = card.id;
    card.document_name = column_text(statement, "document_name");
    card.section = column_text(statement, "section_name");
    card.tag = column_text(statement, "tag");
    card.card_name = column_text(statement, "card_name");
    card.argument_name = column_text(statement, "argument_name");
    card.side = column_text(statement, "side");
    card.source_path = column_text(statement, "source_path");
    card.author = optional_column_text(statement, "author");
    card.year = optional_column_int(statement, "year");
    card.citation = column_text(statement, "citation");
    card.url = optional_column_text(statement, "source_url");
    card.body_preview = column_text(statement, "body_preview");
    card.body = column_text(statement, "body");
    card.title = title_for_card(card.author, card.year, card.citation);
    card.highlights = load_highlights(db, card.id);
    card.score = score;
    card.retrieval_score = score;
    card.reranker_score = score;
    return card;
}

std::vector<RetrievedCard> collect_cards(Database& db, Statement& statement, bool has_rank) {
    std::vector<RetrievedCard> cards;
    while (sqlite3_step(statement.get()) == SQLITE_ROW) {
        const double score = has_rank ? score_from_rank(column_double(statement.get(), "rank")) : 1.0;
        cards.push_back(card_from_statement(db.get(), statement.get(), score));
    }
    return cards;
}

std::string select_cards_sql() {
    return R"SQL(
SELECT
    evidence_cards.id,
    debate_documents.name AS document_name,
    sections.name AS section_name,
    evidence_cards.tag,
    evidence_cards.card_name,
    evidence_cards.argument_name,
    evidence_cards.side,
    evidence_cards.source_path,
    citations.author,
    citations.year,
    citations.raw AS citation,
    citations.source_url,
    substr(evidence_cards.body, 1, 500) AS body_preview,
    evidence_cards.body
FROM evidence_cards
JOIN sections ON sections.id = evidence_cards.section_id
JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
LEFT JOIN citations ON citations.card_id = evidence_cards.id
)SQL";
}

} // namespace

std::string plain_fts_query(const std::string& query) {
    if (is_advanced_fts_query(query)) {
        return query;
    }
    std::ostringstream output;
    bool first = true;
    for (const auto& term : plain_terms(query)) {
        if (term.size() < 2) {
            continue;
        }
        if (!first) {
            output << " AND ";
        }
        output << term << '*';
        first = false;
    }
    return output.str();
}

std::vector<RetrievedCard> search_cards(const std::string& db_path, const std::string& query, std::size_t limit) {
    auto db = open_database(db_path);
    const auto fts_query = plain_fts_query(query);
    if (fts_query.empty()) {
        return {};
    }

    const std::string sql = R"SQL(
SELECT
    evidence_cards_fts.rank AS rank,
    evidence_cards.id,
    debate_documents.name AS document_name,
    sections.name AS section_name,
    evidence_cards.tag,
    evidence_cards.card_name,
    evidence_cards.argument_name,
    evidence_cards.side,
    evidence_cards.source_path,
    citations.author,
    citations.year,
    citations.raw AS citation,
    citations.source_url,
    substr(evidence_cards.body, 1, 500) AS body_preview,
    evidence_cards.body
FROM evidence_cards_fts
JOIN evidence_cards ON evidence_cards.id = evidence_cards_fts.card_id
JOIN sections ON sections.id = evidence_cards.section_id
JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
LEFT JOIN citations ON citations.card_id = evidence_cards.id
WHERE evidence_cards_fts MATCH ?1
ORDER BY evidence_cards_fts.rank
LIMIT ?2
)SQL";

    auto statement = prepare(db.get(), sql);
    bind_text(statement.get(), 1, fts_query);
    bind_int(statement.get(), 2, static_cast<int>(limit));
    auto rows = collect_cards(db, statement, true);
    if (!rows.empty() || is_advanced_fts_query(fts_query)) {
        return rows;
    }

    auto fallback = prepare(db.get(), sql);
    bind_text(fallback.get(), 1, or_query(fts_query));
    bind_int(fallback.get(), 2, static_cast<int>(limit));
    return collect_cards(db, fallback, true);
}

std::vector<RetrievedCard> search_author_citation_cards(const std::string& db_path, const std::string& query, std::size_t limit) {
    auto tokens = plain_terms(query);
    if (tokens.empty()) {
        return {};
    }
    auto db = open_database(db_path);
    std::ostringstream where;
    for (std::size_t index = 0; index < tokens.size(); ++index) {
        if (index != 0) {
            where << " OR ";
        }
        where << "(citations.author LIKE ? OR evidence_cards.card_name LIKE ? OR citations.raw LIKE ?)";
    }
    auto statement = prepare(
        db.get(),
        select_cards_sql() + " WHERE " + where.str()
            + " ORDER BY sections.order_index, evidence_cards.paragraph_start LIMIT ?"
    );
    int bind_index = 1;
    for (const auto& token : tokens) {
        const auto pattern = "%" + token + "%";
        bind_text(statement.get(), bind_index++, pattern);
        bind_text(statement.get(), bind_index++, pattern);
        bind_text(statement.get(), bind_index++, pattern);
    }
    bind_int(statement.get(), bind_index, static_cast<int>(limit));
    return collect_cards(db, statement, false);
}

std::vector<RetrievedCard> lookup_author_cards(const std::string& db_path, const std::string& author, std::size_t limit) {
    auto db = open_database(db_path);
    auto statement = prepare(
        db.get(),
        select_cards_sql()
            + R"SQL(
WHERE citations.author LIKE ?1 OR evidence_cards.card_name LIKE ?2 OR citations.raw LIKE ?3
ORDER BY
    CASE
        WHEN lower(citations.author) = lower(?4) THEN 0
        WHEN lower(evidence_cards.card_name) LIKE lower(?5) THEN 1
        ELSE 2
    END,
    sections.order_index,
    evidence_cards.paragraph_start
LIMIT ?6
)SQL"
    );
    const auto pattern = "%" + author + "%";
    bind_text(statement.get(), 1, pattern);
    bind_text(statement.get(), 2, pattern);
    bind_text(statement.get(), 3, pattern);
    bind_text(statement.get(), 4, author);
    bind_text(statement.get(), 5, author + "%");
    bind_int(statement.get(), 6, static_cast<int>(limit));
    return collect_cards(db, statement, false);
}

std::vector<RetrievedCard> lookup_citation_cards(const std::string& db_path, const std::string& author, int year, std::size_t limit) {
    auto db = open_database(db_path);
    const auto short_year = year % 100 < 10 ? "0" + std::to_string(year % 100) : std::to_string(year % 100);
    auto statement = prepare(
        db.get(),
        select_cards_sql()
            + R"SQL(
WHERE lower(evidence_cards.card_name) IN (?1, ?2, ?3, ?4)
   OR (lower(citations.author) = lower(?5) AND citations.year = ?6)
ORDER BY sections.order_index, evidence_cards.paragraph_start
LIMIT ?7
)SQL"
    );
    bind_text(statement.get(), 1, author + " " + short_year);
    bind_text(statement.get(), 2, author + " " + std::to_string(year));
    bind_text(statement.get(), 3, author + " '" + short_year);
    bind_text(statement.get(), 4, author + " ’" + short_year);
    bind_text(statement.get(), 5, author);
    bind_int(statement.get(), 6, year);
    bind_int(statement.get(), 7, static_cast<int>(limit));
    auto rows = collect_cards(db, statement, false);
    if (!rows.empty()) {
        return rows;
    }

    auto fallback = prepare(
        db.get(),
        select_cards_sql()
            + R"SQL(
WHERE ((citations.author LIKE ?1 OR evidence_cards.card_name LIKE ?2 OR citations.raw LIKE ?3) AND citations.year = ?4)
   OR evidence_cards.card_name LIKE ?5
ORDER BY
    CASE
        WHEN lower(citations.author) = lower(?6) AND citations.year = ?7 THEN 0
        WHEN lower(evidence_cards.card_name) LIKE lower(?8) THEN 1
        ELSE 2
    END,
    sections.order_index,
    evidence_cards.paragraph_start
LIMIT ?9
)SQL"
    );
    const auto author_pattern = "%" + author + "%";
    const auto card_pattern = "%" + author + "%" + short_year + "%";
    bind_text(fallback.get(), 1, author_pattern);
    bind_text(fallback.get(), 2, author_pattern);
    bind_text(fallback.get(), 3, author_pattern);
    bind_int(fallback.get(), 4, year);
    bind_text(fallback.get(), 5, card_pattern);
    bind_text(fallback.get(), 6, author);
    bind_int(fallback.get(), 7, year);
    bind_text(fallback.get(), 8, card_pattern);
    bind_int(fallback.get(), 9, static_cast<int>(limit));
    return collect_cards(db, fallback, false);
}

std::vector<RetrievedCard> lookup_section_cards(const std::string& db_path, const std::string& section, std::size_t limit) {
    auto db = open_database(db_path);
    auto statement = prepare(
        db.get(),
        select_cards_sql()
            + R"SQL(
WHERE sections.name LIKE ?1
ORDER BY CASE WHEN lower(sections.name) = lower(?2) THEN 0 ELSE 1 END, evidence_cards.paragraph_start
LIMIT ?3
)SQL"
    );
    bind_text(statement.get(), 1, "%" + section + "%");
    bind_text(statement.get(), 2, section);
    bind_int(statement.get(), 3, static_cast<int>(limit));
    return collect_cards(db, statement, false);
}

std::map<std::string, RetrievedCard> load_cards_by_ids(const std::string& db_path, const std::vector<std::string>& card_ids) {
    std::map<std::string, RetrievedCard> cards;
    if (card_ids.empty()) {
        return cards;
    }
    auto db = open_database(db_path);
    std::ostringstream placeholders;
    for (std::size_t index = 0; index < card_ids.size(); ++index) {
        if (index != 0) {
            placeholders << ",";
        }
        placeholders << "?";
    }
    auto statement = prepare(
        db.get(),
        select_cards_sql() + " WHERE evidence_cards.id IN (" + placeholders.str() + ")"
    );
    for (std::size_t index = 0; index < card_ids.size(); ++index) {
        bind_text(statement.get(), static_cast<int>(index + 1), card_ids[index]);
    }
    while (sqlite3_step(statement.get()) == SQLITE_ROW) {
        auto card = card_from_statement(db.get(), statement.get(), 0.0);
        cards[card.card_id] = std::move(card);
    }
    return cards;
}

std::vector<Highlight> card_highlights(const std::string& db_path, const std::string& card_id) {
    auto db = open_database(db_path);
    return load_highlights(db.get(), card_id);
}

} // namespace sekret::hybrid
