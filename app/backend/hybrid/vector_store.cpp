#include "vector_store.hpp"

#include <sqlite3.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <utility>

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

std::string column_text(sqlite3_stmt* statement, int index) {
    const auto* text = sqlite3_column_text(statement, index);
    return text == nullptr ? std::string() : reinterpret_cast<const char*>(text);
}

bool table_exists(sqlite3* db, const std::string& table_name) {
    auto statement = prepare(
        db,
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1 LIMIT 1"
    );
    bind_text(statement.get(), 1, table_name);
    return sqlite3_step(statement.get()) == SQLITE_ROW;
}

struct ScoredVector {
    std::string card_id;
    double score = 0.0;
};

} // namespace

NativeSqliteVectorStore::NativeSqliteVectorStore(std::string db_path)
    : db_path_(std::move(db_path)) {}

bool NativeSqliteVectorStore::has_vectors(
    const std::string& embedding_kind,
    const std::string& embedding_model
) const {
    auto db = open_database(db_path_);
    if (!table_exists(db.get(), kNativeVectorTable)) {
        return false;
    }
    auto statement = prepare(
        db.get(),
        "SELECT 1 FROM native_card_vectors "
        "WHERE embedding_kind = ?1 AND embedding_model = ?2 LIMIT 1"
    );
    bind_text(statement.get(), 1, embedding_kind);
    bind_text(statement.get(), 2, embedding_model);
    return sqlite3_step(statement.get()) == SQLITE_ROW;
}

std::vector<RetrievedCard> NativeSqliteVectorStore::search(
    const std::vector<double>& query_embedding,
    const std::string& embedding_kind,
    const std::string& embedding_model,
    std::size_t limit
) const {
    if (query_embedding.empty()) {
        return {};
    }

    auto db = open_database(db_path_);
    if (!table_exists(db.get(), kNativeVectorTable)) {
        return {};
    }
    auto statement = prepare(
        db.get(),
        "SELECT card_id, vector_json FROM native_card_vectors "
        "WHERE embedding_kind = ?1 AND embedding_model = ?2"
    );
    bind_text(statement.get(), 1, embedding_kind);
    bind_text(statement.get(), 2, embedding_model);

    std::vector<ScoredVector> scored;
    while (sqlite3_step(statement.get()) == SQLITE_ROW) {
        const auto card_id = column_text(statement.get(), 0);
        const auto vector = parse_vector_json(column_text(statement.get(), 1));
        const auto score = cosine_similarity(query_embedding, vector);
        if (!card_id.empty() && score > 0.0) {
            scored.push_back({card_id, score});
        }
    }

    std::sort(scored.begin(), scored.end(), [](const auto& left, const auto& right) {
        return left.score > right.score;
    });
    if (scored.size() > limit) {
        scored.resize(limit);
    }

    std::vector<RetrievedCard> rows;
    rows.reserve(scored.size());
    for (const auto& item : scored) {
        RetrievedCard card;
        card.id = item.card_id;
        card.card_id = item.card_id;
        card.score = std::round(item.score * 1000.0) / 1000.0;
        card.retrieval_score = card.score;
        rows.push_back(std::move(card));
    }
    return rows;
}

std::vector<double> parse_vector_json(const std::string& json) {
    std::vector<double> values;
    std::size_t index = 0;
    while (index < json.size() && json[index] != '[') {
        ++index;
    }
    if (index == json.size()) {
        return values;
    }
    ++index;
    while (index < json.size()) {
        while (index < json.size() && std::isspace(static_cast<unsigned char>(json[index]))) {
            ++index;
        }
        if (index < json.size() && json[index] == ']') {
            return values;
        }
        char* end = nullptr;
        const double value = std::strtod(json.c_str() + index, &end);
        if (end == json.c_str() + index) {
            return {};
        }
        values.push_back(value);
        index = static_cast<std::size_t>(end - json.c_str());
        while (index < json.size() && std::isspace(static_cast<unsigned char>(json[index]))) {
            ++index;
        }
        if (index < json.size() && json[index] == ',') {
            ++index;
            continue;
        }
        if (index < json.size() && json[index] == ']') {
            return values;
        }
        return {};
    }
    return {};
}

double cosine_similarity(const std::vector<double>& left, const std::vector<double>& right) {
    if (left.empty() || left.size() != right.size()) {
        return 0.0;
    }
    double dot = 0.0;
    double left_norm = 0.0;
    double right_norm = 0.0;
    for (std::size_t index = 0; index < left.size(); ++index) {
        dot += left[index] * right[index];
        left_norm += left[index] * left[index];
        right_norm += right[index] * right[index];
    }
    if (left_norm == 0.0 || right_norm == 0.0) {
        return 0.0;
    }
    return std::max(0.0, dot / (std::sqrt(left_norm) * std::sqrt(right_norm)));
}

} // namespace sekret::hybrid
