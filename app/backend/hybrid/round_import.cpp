#include "round_import.hpp"

#include "format_parser.hpp"

#include <sqlite3.h>

#include <chrono>
#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>

namespace sekret::hybrid {
namespace {

std::string read_text_file(const char* path) {
    if (path == nullptr || std::string(path).empty()) {
        throw std::invalid_argument("source_path and grammar_path are required");
    }
    std::ifstream input(path);
    if (!input.good()) {
        throw std::runtime_error("Could not read file: " + std::string(path));
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}

char* copy_c_string(const std::string& value) {
    const auto byte_count = value.size() + 1;
    auto* buffer = static_cast<char*>(std::malloc(byte_count));
    if (buffer == nullptr) {
        return nullptr;
    }
    std::memcpy(buffer, value.c_str(), byte_count);
    return buffer;
}

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (const unsigned char ch : value) {
        switch (ch) {
        case '"':
            out << "\\\"";
            break;
        case '\\':
            out << "\\\\";
            break;
        case '\b':
            out << "\\b";
            break;
        case '\f':
            out << "\\f";
            break;
        case '\n':
            out << "\\n";
            break;
        case '\r':
            out << "\\r";
            break;
        case '\t':
            out << "\\t";
            break;
        default:
            if (ch < 0x20) {
                out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch);
            } else {
                out << ch;
            }
        }
    }
    return out.str();
}

std::string now_iso() {
    const auto now = std::chrono::system_clock::now();
    const auto time = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &time);
#else
    gmtime_r(&time, &utc);
#endif
    std::ostringstream out;
    out << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
    return out.str();
}

std::string stable_hex_hash(const std::string& value) {
    const auto hash = std::hash<std::string>{}(value);
    std::ostringstream out;
    out << std::hex << hash;
    return out.str();
}

std::string field_or(const ParsedDslCard& card, const std::string& key, const std::string& fallback = "") {
    const auto it = card.fields.find(key);
    if (it == card.fields.end() || it->second.empty()) {
        return fallback;
    }
    return it->second;
}

int year_from(const std::string& text) {
    for (std::size_t index = 0; index + 3 < text.size(); ++index) {
        const auto chunk = text.substr(index, 4);
        if (std::all_of(chunk.begin(), chunk.end(), [](unsigned char ch) { return std::isdigit(ch); })) {
            const int year = std::stoi(chunk);
            if (year >= 1600 && year <= 2200) {
                return year;
            }
        }
    }
    return 0;
}

std::string basename_for(const std::string& path) {
    const auto slash = path.find_last_of("/\\");
    const auto name = slash == std::string::npos ? path : path.substr(slash + 1);
    return name.empty() ? path : name;
}

void exec(sqlite3* db, const char* sql) {
    char* error = nullptr;
    const int status = sqlite3_exec(db, sql, nullptr, nullptr, &error);
    if (status != SQLITE_OK) {
        std::string message = error == nullptr ? "SQLite exec failed" : error;
        sqlite3_free(error);
        throw std::runtime_error(message);
    }
}

class Statement {
public:
    Statement(sqlite3* db, const char* sql) : statement_(nullptr) {
        if (sqlite3_prepare_v2(db, sql, -1, &statement_, nullptr) != SQLITE_OK) {
            throw std::runtime_error(sqlite3_errmsg(db));
        }
    }

    ~Statement() {
        sqlite3_finalize(statement_);
    }

    sqlite3_stmt* get() {
        return statement_;
    }

    void reset() {
        sqlite3_reset(statement_);
        sqlite3_clear_bindings(statement_);
    }

private:
    sqlite3_stmt* statement_;
};

void bind_text(sqlite3_stmt* statement, int index, const std::string& value) {
    sqlite3_bind_text(statement, index, value.c_str(), -1, SQLITE_TRANSIENT);
}

void bind_optional_int(sqlite3_stmt* statement, int index, int value) {
    if (value == 0) {
        sqlite3_bind_null(statement, index);
    } else {
        sqlite3_bind_int(statement, index, value);
    }
}

void step_done(sqlite3* db, sqlite3_stmt* statement) {
    if (sqlite3_step(statement) != SQLITE_DONE) {
        throw std::runtime_error(sqlite3_errmsg(db));
    }
}

std::string import_opponent_dsl(const std::string& db_path, const std::string& source_path, const std::string& grammar_path) {
    const auto source_text = read_text_file(source_path.c_str());
    const auto grammar_text = read_text_file(grammar_path.c_str());
    const auto parsed = parse_evidence_dsl(source_text, grammar_text);
    if (parsed.cards.empty()) {
        throw std::runtime_error("DSL import found no cards.");
    }

    sqlite3* db = nullptr;
    if (sqlite3_open(db_path.c_str(), &db) != SQLITE_OK) {
        const std::string message = db == nullptr ? "Could not open database" : sqlite3_errmsg(db);
        if (db != nullptr) {
            sqlite3_close(db);
        }
        throw std::runtime_error(message);
    }

    const auto document_id = "doc-dsl-" + stable_hex_hash(source_path + source_text);
    const auto document_name = basename_for(source_path);
    const auto now = now_iso();

    try {
        exec(db, "PRAGMA foreign_keys = ON");
        exec(db, "BEGIN IMMEDIATE");

        Statement delete_document(db, "DELETE FROM debate_documents WHERE id = ?");
        bind_text(delete_document.get(), 1, document_id);
        step_done(db, delete_document.get());

        Statement insert_document(
            db,
            "INSERT INTO debate_documents (id, name, source_path, source_format, metadata_json, created_at) "
            "VALUES (?, ?, ?, 'sa-dsl', ?, ?)"
        );
        bind_text(insert_document.get(), 1, document_id);
        bind_text(insert_document.get(), 2, document_name);
        bind_text(insert_document.get(), 3, source_path);
        bind_text(insert_document.get(), 4, "{\"importer\":\"native-cpp\",\"side\":\"opponent\"}");
        bind_text(insert_document.get(), 5, now);
        step_done(db, insert_document.get());

        Statement insert_section(
            db,
            "INSERT INTO sections (id, document_id, parent_id, name, argument_type, order_index, metadata_json) "
            "VALUES (?, ?, NULL, ?, 'unknown', ?, '{}')"
        );
        Statement insert_card(
            db,
            "INSERT INTO evidence_cards ("
            "id, document_id, section_id, tag, card_name, argument_name, body, category, topical, side, "
            "source_path, content_hash, paragraph_start, paragraph_end, source_format, metadata_json, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opponent', ?, ?, ?, ?, 'sa-dsl', ?, ?)"
        );
        Statement insert_citation(
            db,
            "INSERT INTO citations (id, card_id, raw, author, year, source_url) VALUES (?, ?, ?, ?, ?, ?)"
        );
        Statement insert_highlight(
            db,
            "INSERT INTO highlights (id, card_id, text, color, highlight_color, order_index) VALUES (?, ?, ?, ?, ?, 0)"
        );
        Statement insert_fts(
            db,
            "INSERT INTO evidence_cards_fts (card_id, tag, card_name, citation, body) VALUES (?, ?, ?, ?, ?)"
        );

        std::map<std::string, std::string> section_ids;
        int section_order = 0;
        int card_order = 0;
        for (const auto& card : parsed.cards) {
            const auto section_name = field_or(card, "section", "Opponent");
            auto section_id_it = section_ids.find(section_name);
            if (section_id_it == section_ids.end()) {
                const auto section_id = document_id + "-section-" + stable_hex_hash(section_name);
                insert_section.reset();
                bind_text(insert_section.get(), 1, section_id);
                bind_text(insert_section.get(), 2, document_id);
                bind_text(insert_section.get(), 3, section_name);
                sqlite3_bind_int(insert_section.get(), 4, section_order++);
                step_done(db, insert_section.get());
                section_id_it = section_ids.emplace(section_name, section_id).first;
            }

            const auto citation = field_or(card, "citation", field_or(card, "card", field_or(card, "author", "Opponent")));
            const auto author = field_or(card, "author");
            const auto body = field_or(card, "content", field_or(card, "body"));
            const auto tag = field_or(card, "tag", field_or(card, "claim", field_or(card, "card", "Opponent evidence")));
            const auto card_name = field_or(card, "card", citation);
            const auto link = field_or(card, "link", field_or(card, "url"));
            const auto highlight = field_or(card, "highlight", body.substr(0, std::min<std::size_t>(body.size(), 320)));
            const int year = year_from(field_or(card, "year", citation + " " + author));
            const auto card_id = document_id + "-card-" + stable_hex_hash(card_name + body + std::to_string(card_order));
            const auto content_hash = stable_hex_hash(tag + "\n" + citation + "\n" + body);

            insert_card.reset();
            bind_text(insert_card.get(), 1, card_id);
            bind_text(insert_card.get(), 2, document_id);
            bind_text(insert_card.get(), 3, section_id_it->second);
            bind_text(insert_card.get(), 4, tag);
            bind_text(insert_card.get(), 5, card_name);
            bind_text(insert_card.get(), 6, field_or(card, "argument"));
            bind_text(insert_card.get(), 7, body);
            bind_text(insert_card.get(), 8, source_path);
            bind_text(insert_card.get(), 9, content_hash);
            sqlite3_bind_int(insert_card.get(), 10, static_cast<int>(card.block_start));
            sqlite3_bind_int(insert_card.get(), 11, static_cast<int>(card.block_end));
            bind_text(insert_card.get(), 12, "{\"parser\":\"native-dsl\"}");
            bind_text(insert_card.get(), 13, now);
            step_done(db, insert_card.get());

            insert_citation.reset();
            bind_text(insert_citation.get(), 1, card_id + "-citation");
            bind_text(insert_citation.get(), 2, card_id);
            bind_text(insert_citation.get(), 3, citation);
            bind_text(insert_citation.get(), 4, author);
            bind_optional_int(insert_citation.get(), 5, year);
            bind_text(insert_citation.get(), 6, link);
            step_done(db, insert_citation.get());

            if (!highlight.empty()) {
                insert_highlight.reset();
                bind_text(insert_highlight.get(), 1, card_id + "-highlight");
                bind_text(insert_highlight.get(), 2, card_id);
                bind_text(insert_highlight.get(), 3, highlight);
                bind_text(insert_highlight.get(), 4, "yellow");
                bind_text(insert_highlight.get(), 5, "yellow");
                step_done(db, insert_highlight.get());
            }

            insert_fts.reset();
            bind_text(insert_fts.get(), 1, card_id);
            bind_text(insert_fts.get(), 2, tag);
            bind_text(insert_fts.get(), 3, card_name);
            bind_text(insert_fts.get(), 4, citation);
            bind_text(insert_fts.get(), 5, body);
            step_done(db, insert_fts.get());
            ++card_order;
        }

        exec(db, "COMMIT");
    } catch (...) {
        sqlite3_exec(db, "ROLLBACK", nullptr, nullptr, nullptr);
        sqlite3_close(db);
        throw;
    }
    sqlite3_close(db);

    std::ostringstream diagnostics;
    diagnostics << "[";
    for (std::size_t index = 0; index < parsed.diagnostics.size(); ++index) {
        if (index != 0) {
            diagnostics << ",";
        }
        diagnostics << "\"" << json_escape(parsed.diagnostics[index]) << "\"";
    }
    diagnostics << "]";

    std::ostringstream json;
    json << "{"
         << "\"id\":\"" << json_escape(document_id) << "\","
         << "\"filename\":\"" << json_escape(document_name) << "\","
         << "\"path\":\"" << json_escape(source_path) << "\","
         << "\"side\":\"opponent\","
         << "\"status\":\"ready\","
         << "\"cardCount\":" << parsed.cards.size() << ","
         << "\"parseProgress\":1,"
         << "\"indexProgress\":1,"
         << "\"error\":\"\","
         << "\"diagnostics\":" << diagnostics.str()
         << "}";
    return json.str();
}

} // namespace
} // namespace sekret::hybrid

extern "C" SekretHybridJsonResult sekret_import_opponent_dsl_json(
    const char* db_path,
    const char* source_path,
    const char* grammar_path
) {
    if (db_path == nullptr || source_path == nullptr || grammar_path == nullptr) {
        return {nullptr, sekret::hybrid::copy_c_string("db_path, source_path, and grammar_path are required")};
    }
    try {
        const auto json = sekret::hybrid::import_opponent_dsl(db_path, source_path, grammar_path);
        return {sekret::hybrid::copy_c_string(json), nullptr};
    } catch (const std::exception& error) {
        return {nullptr, sekret::hybrid::copy_c_string(error.what())};
    }
}
