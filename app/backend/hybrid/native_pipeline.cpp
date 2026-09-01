#include "native_pipeline.hpp"

#include "ollama_embedder.hpp"
#include "vector_store.hpp"

#include <unzip.h>
#include <libxml/parser.h>
#include <libxml/tree.h>
#include <sqlite3.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <memory>
#include <optional>
#include <random>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace sekret::hybrid {
namespace {

constexpr const char* kWordNamespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
constexpr const char* kParserVersion = "docx-v2-native";

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

struct XmlDeleter {
    void operator()(xmlDoc* document) const {
        if (document != nullptr) {
            xmlFreeDoc(document);
        }
    }
};

using Database = std::unique_ptr<sqlite3, SqliteDeleter>;
using Statement = std::unique_ptr<sqlite3_stmt, StatementDeleter>;
using XmlDocument = std::unique_ptr<xmlDoc, XmlDeleter>;

struct Run {
    std::string text;
    std::optional<std::string> highlight;
    std::optional<std::string> style;
    std::optional<double> font_size;
    bool bold = false;
    bool underline = false;
};

struct Paragraph {
    int index = 0;
    std::optional<std::string> style;
    std::string text;
    std::vector<Run> runs;
};

struct HighlightStyles {
    std::set<std::string> paragraph_styles;
    std::set<std::string> character_styles;
};

struct CitationFields {
    std::string raw;
    std::optional<std::string> author;
    std::optional<int> year;
    std::optional<std::string> url;
};

struct NativeHighlight {
    std::string text;
    std::optional<std::string> color;
    int paragraph_index = 0;
    std::optional<int> run_index;
    std::optional<int> start_char;
    std::optional<int> end_char;
    std::optional<std::string> style;
    std::optional<double> font_size;
    bool bold = false;
    bool underline = false;
};

struct NativeCard {
    std::string id;
    std::string document_id;
    std::string section_id;
    std::string section_name;
    std::string tag;
    CitationFields citation;
    std::string card_name;
    std::string body;
    int paragraph_start = 0;
    int paragraph_end = 0;
    std::vector<NativeHighlight> highlights;
};

struct NativeSection {
    std::string id;
    std::string name;
    std::string argument_type;
    int order_index = 0;
    std::vector<NativeCard> cards;
};

struct NativeDocument {
    std::string id;
    std::string name;
    std::string source_path;
    std::vector<NativeSection> sections;
};

struct EmbeddingRecord {
    std::string card_id;
    std::string text;
};

Database open_database(const std::string& path) {
    sqlite3* raw = nullptr;
    if (sqlite3_open(path.c_str(), &raw) != SQLITE_OK) {
        const std::string message = raw == nullptr ? "could not open SQLite database" : sqlite3_errmsg(raw);
        if (raw != nullptr) {
            sqlite3_close(raw);
        }
        throw std::runtime_error(message);
    }
    return Database(raw);
}

void exec(sqlite3* db, const std::string& sql) {
    char* error = nullptr;
    if (sqlite3_exec(db, sql.c_str(), nullptr, nullptr, &error) != SQLITE_OK) {
        const std::string message = error == nullptr ? sqlite3_errmsg(db) : error;
        sqlite3_free(error);
        throw std::runtime_error(message);
    }
}

Statement prepare(sqlite3* db, const std::string& sql) {
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &raw, nullptr) != SQLITE_OK) {
        throw std::runtime_error(sqlite3_errmsg(db));
    }
    return Statement(raw);
}

void bind_text(sqlite3_stmt* statement, int index, const std::string& text) {
    if (sqlite3_bind_text(statement, index, text.c_str(), -1, SQLITE_TRANSIENT) != SQLITE_OK) {
        throw std::runtime_error("failed to bind SQLite text parameter");
    }
}

void bind_optional_text(sqlite3_stmt* statement, int index, const std::optional<std::string>& text) {
    if (!text.has_value()) {
        if (sqlite3_bind_null(statement, index) != SQLITE_OK) {
            throw std::runtime_error("failed to bind SQLite NULL parameter");
        }
    } else {
        bind_text(statement, index, *text);
    }
}

void bind_optional_int(sqlite3_stmt* statement, int index, const std::optional<int>& value) {
    if (!value.has_value()) {
        if (sqlite3_bind_null(statement, index) != SQLITE_OK) {
            throw std::runtime_error("failed to bind SQLite NULL parameter");
        }
    } else if (sqlite3_bind_int(statement, index, *value) != SQLITE_OK) {
        throw std::runtime_error("failed to bind SQLite integer parameter");
    }
}

void bind_optional_double(sqlite3_stmt* statement, int index, const std::optional<double>& value) {
    if (!value.has_value()) {
        if (sqlite3_bind_null(statement, index) != SQLITE_OK) {
            throw std::runtime_error("failed to bind SQLite NULL parameter");
        }
    } else if (sqlite3_bind_double(statement, index, *value) != SQLITE_OK) {
        throw std::runtime_error("failed to bind SQLite real parameter");
    }
}

void step_done(sqlite3* db, sqlite3_stmt* statement) {
    if (sqlite3_step(statement) != SQLITE_DONE) {
        throw std::runtime_error(sqlite3_errmsg(db));
    }
}

void reset_statement(Statement& statement) {
    sqlite3_reset(statement.get());
    sqlite3_clear_bindings(statement.get());
}

std::string column_text(sqlite3_stmt* statement, int index) {
    const auto* value = sqlite3_column_text(statement, index);
    return value == nullptr ? std::string() : reinterpret_cast<const char*>(value);
}

std::string trim(std::string value) {
    auto begin = value.begin();
    while (begin != value.end() && std::isspace(static_cast<unsigned char>(*begin))) {
        ++begin;
    }
    auto end = value.end();
    while (end != begin && std::isspace(static_cast<unsigned char>(*(end - 1)))) {
        --end;
    }
    return {begin, end};
}

std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return value;
}

std::string normalize_unicode_whitespace(const std::string& text) {
    std::string normalized;
    normalized.reserve(text.size());
    for (std::size_t index = 0; index < text.size();) {
        const auto character = static_cast<unsigned char>(text[index]);
        const bool no_break_space = character == 0xc2U && index + 1 < text.size()
            && static_cast<unsigned char>(text[index + 1]) == 0xa0U;
        const bool unicode_space = character == 0xe2U && index + 2 < text.size()
            && static_cast<unsigned char>(text[index + 1]) == 0x80U && (
                (static_cast<unsigned char>(text[index + 2]) >= 0x80U
                    && static_cast<unsigned char>(text[index + 2]) <= 0x8aU)
                || static_cast<unsigned char>(text[index + 2]) == 0xafU);
        const bool ideographic_space = character == 0xe3U && index + 2 < text.size()
            && static_cast<unsigned char>(text[index + 1]) == 0x80U
            && static_cast<unsigned char>(text[index + 2]) == 0x80U;
        if (no_break_space) {
            normalized.push_back(' ');
            index += 2;
        } else if (unicode_space || ideographic_space) {
            normalized.push_back(' ');
            index += 3;
        } else {
            normalized.push_back(text[index++]);
        }
    }
    return normalized;
}

std::size_t utf8_codepoint_count(const std::string& text) {
    std::size_t count = 0;
    for (const unsigned char character : text) {
        if ((character & 0xc0U) != 0x80U) {
            ++count;
        }
    }
    return count;
}

std::string normalize_spacing(std::string text) {
    text = normalize_unicode_whitespace(text);
    text = std::regex_replace(text, std::regex(R"(\s+)"), " ");
    text = std::regex_replace(text, std::regex(R"(\s+([,.;:!?%)\]\}]))"), "$1");
    text = std::regex_replace(text, std::regex(R"(([\(\[\{])\s+)"), "$1");
    return trim(text);
}

std::string iso_now() {
    const auto now = std::chrono::system_clock::now();
    const auto time = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &time);
#else
    gmtime_r(&time, &utc);
#endif
    std::ostringstream output;
    output << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
    return output.str();
}

std::string random_id() {
    std::array<unsigned char, 16> bytes{};
    std::random_device device;
    for (auto& byte : bytes) {
        byte = static_cast<unsigned char>(device());
    }
    bytes[6] = static_cast<unsigned char>((bytes[6] & 0x0fU) | 0x40U);
    bytes[8] = static_cast<unsigned char>((bytes[8] & 0x3fU) | 0x80U);
    std::ostringstream output;
    for (std::size_t index = 0; index < bytes.size(); ++index) {
        if (index == 4 || index == 6 || index == 8 || index == 10) {
            output << '-';
        }
        output << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(bytes[index]);
    }
    return output.str();
}

std::string stable_hash(const std::string& text) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (const unsigned char character : text) {
        hash ^= character;
        hash *= 1099511628211ULL;
    }
    std::ostringstream output;
    output << std::hex << hash;
    return output.str();
}

std::string basename_without_extension(const std::string& path) {
    auto name = std::filesystem::path(path).filename().string();
    const auto dot = name.find_last_of('.');
    return dot == std::string::npos ? name : name.substr(0, dot);
}

std::string read_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input.good()) {
        throw std::runtime_error("Could not read file: " + path);
    }
    std::ostringstream output;
    output << input.rdbuf();
    return output.str();
}

std::string read_docx_part(const std::string& docx_path, const char* part_name, bool required) {
    unzFile archive = unzOpen64(docx_path.c_str());
    if (archive == nullptr) {
        throw std::runtime_error("Could not open DOCX archive: " + docx_path);
    }
    if (unzLocateFile(archive, part_name, 0) != UNZ_OK) {
        unzClose(archive);
        if (!required) {
            return {};
        }
        throw std::runtime_error(std::string("DOCX is missing ") + part_name);
    }
    if (unzOpenCurrentFile(archive) != UNZ_OK) {
        unzClose(archive);
        throw std::runtime_error(std::string("Could not read DOCX part ") + part_name);
    }
    std::string result;
    std::array<char, 8192> buffer{};
    while (true) {
        const int count = unzReadCurrentFile(archive, buffer.data(), static_cast<unsigned int>(buffer.size()));
        if (count < 0) {
            unzCloseCurrentFile(archive);
            unzClose(archive);
            throw std::runtime_error(std::string("Could not read DOCX part ") + part_name);
        }
        if (count == 0) {
            break;
        }
        result.append(buffer.data(), static_cast<std::size_t>(count));
    }
    unzCloseCurrentFile(archive);
    unzClose(archive);
    return result;
}

XmlDocument parse_xml(const std::string& xml, const std::string& name) {
    if (xml.empty()) {
        return XmlDocument(nullptr);
    }
    auto* document = xmlReadMemory(
        xml.data(),
        static_cast<int>(xml.size()),
        name.c_str(),
        nullptr,
        XML_PARSE_NONET | XML_PARSE_NOERROR | XML_PARSE_NOWARNING
    );
    if (document == nullptr) {
        throw std::runtime_error("Could not parse XML part: " + name);
    }
    return XmlDocument(document);
}

bool node_is(const xmlNode* node, const char* name) {
    return node != nullptr
        && node->type == XML_ELEMENT_NODE
        && xmlStrEqual(node->name, BAD_CAST name) != 0;
}

xmlNode* first_child(xmlNode* node, const char* name) {
    if (node == nullptr) {
        return nullptr;
    }
    for (auto* child = node->children; child != nullptr; child = child->next) {
        if (node_is(child, name)) {
            return child;
        }
    }
    return nullptr;
}

std::optional<std::string> attribute(xmlNode* node, const char* name) {
    if (node == nullptr) {
        return std::nullopt;
    }
    xmlChar* value = xmlGetNsProp(node, BAD_CAST name, BAD_CAST kWordNamespace);
    if (value == nullptr) {
        value = xmlGetProp(node, BAD_CAST name);
    }
    if (value == nullptr) {
        return std::nullopt;
    }
    std::string result(reinterpret_cast<const char*>(value));
    xmlFree(value);
    return result;
}

std::string node_text(xmlNode* node) {
    if (node == nullptr) {
        return {};
    }
    xmlChar* value = xmlNodeGetContent(node);
    if (value == nullptr) {
        return {};
    }
    std::string result(reinterpret_cast<const char*>(value));
    xmlFree(value);
    return result;
}

std::optional<std::string> highlight_value(xmlNode* properties) {
    if (properties == nullptr) {
        return std::nullopt;
    }
    if (auto* highlight = first_child(properties, "highlight"); highlight != nullptr) {
        const auto value = lower_copy(attribute(highlight, "val").value_or(""));
        if (!value.empty() && value != "none" && value != "white") {
            return value;
        }
    }
    if (auto* shading = first_child(properties, "shd"); shading != nullptr) {
        const auto value = lower_copy(attribute(shading, "fill").value_or(""));
        if (!value.empty() && value != "auto" && value != "ffffff" && value != "white") {
            return value;
        }
    }
    return std::nullopt;
}

std::optional<double> font_size(xmlNode* properties) {
    const auto value = attribute(first_child(properties, "sz"), "val");
    if (!value.has_value()) {
        return std::nullopt;
    }
    try {
        return static_cast<double>(std::stoi(*value)) / 2.0;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

HighlightStyles read_highlight_styles(const std::string& styles_xml) {
    HighlightStyles result;
    if (styles_xml.empty()) {
        return result;
    }
    const auto document = parse_xml(styles_xml, "word/styles.xml");
    struct Definition {
        std::string type;
        std::string parent;
        bool has_highlight = false;
    };
    std::map<std::string, Definition> definitions;
    auto* root = xmlDocGetRootElement(document.get());
    for (auto* style = root == nullptr ? nullptr : root->children; style != nullptr; style = style->next) {
        if (!node_is(style, "style")) {
            continue;
        }
        const auto id = attribute(style, "styleId");
        if (!id.has_value() || id->empty()) {
            continue;
        }
        Definition definition;
        definition.type = attribute(style, "type").value_or("");
        definition.has_highlight = highlight_value(first_child(style, "rPr")).has_value();
        if (auto* based_on = first_child(style, "basedOn"); based_on != nullptr) {
            definition.parent = attribute(based_on, "val").value_or("");
        }
        definitions[*id] = std::move(definition);
    }
    std::map<std::string, bool> memo;
    std::set<std::string> visiting;
    const auto inherits = [&](const auto& self, const std::string& id) -> bool {
        if (const auto cached = memo.find(id); cached != memo.end()) {
            return cached->second;
        }
        if (visiting.count(id) != 0 || definitions.count(id) == 0) {
            return false;
        }
        visiting.insert(id);
        const auto& definition = definitions.at(id);
        const bool result_value = definition.has_highlight
            || (!definition.parent.empty() && self(self, definition.parent));
        visiting.erase(id);
        memo[id] = result_value;
        return result_value;
    };
    for (const auto& [id, definition] : definitions) {
        if (!inherits(inherits, id)) {
            continue;
        }
        if (definition.type == "paragraph") {
            result.paragraph_styles.insert(id);
        } else if (definition.type == "character") {
            result.character_styles.insert(id);
        }
    }
    return result;
}

std::string run_text(xmlNode* run) {
    std::string result;
    for (auto* child = run == nullptr ? nullptr : run->children; child != nullptr; child = child->next) {
        if (node_is(child, "t")) {
            result += node_text(child);
        } else if (node_is(child, "tab")) {
            result += " ";
        } else if (node_is(child, "br") || node_is(child, "cr")) {
            result += "\n";
        }
    }
    return result;
}

std::vector<Paragraph> read_paragraphs(const std::string& docx_path) {
    const auto document_xml = read_docx_part(docx_path, "word/document.xml", true);
    const auto styles_xml = read_docx_part(docx_path, "word/styles.xml", false);
    const auto styles = read_highlight_styles(styles_xml);
    const auto document = parse_xml(document_xml, "word/document.xml");
    auto* body = first_child(xmlDocGetRootElement(document.get()), "body");
    if (body == nullptr) {
        throw std::runtime_error("DOCX document.xml has no body");
    }
    std::vector<Paragraph> paragraphs;
    int paragraph_index = 0;
    for (auto* node = body->children; node != nullptr; node = node->next) {
        if (!node_is(node, "p")) {
            continue;
        }
        Paragraph paragraph;
        paragraph.index = paragraph_index++;
        auto* paragraph_properties = first_child(node, "pPr");
        if (auto* paragraph_style = first_child(paragraph_properties, "pStyle"); paragraph_style != nullptr) {
            paragraph.style = attribute(paragraph_style, "val");
        }
        const bool paragraph_highlight = paragraph.style.has_value()
            && styles.paragraph_styles.count(*paragraph.style) != 0;
        for (auto* child = node->children; child != nullptr; child = child->next) {
            if (!node_is(child, "r")) {
                continue;
            }
            Run run;
            run.text = run_text(child);
            if (run.text.empty()) {
                continue;
            }
            auto* properties = first_child(child, "rPr");
            if (auto* run_style = first_child(properties, "rStyle"); run_style != nullptr) {
                run.style = attribute(run_style, "val");
            }
            run.highlight = highlight_value(properties);
            if (!run.highlight.has_value() && paragraph_highlight) {
                run.highlight = "style";
            }
            if (!run.highlight.has_value() && run.style.has_value()
                && styles.character_styles.count(*run.style) != 0) {
                run.highlight = "style";
            }
            run.font_size = font_size(properties);
            run.bold = first_child(properties, "b") != nullptr;
            run.underline = first_child(properties, "u") != nullptr;
            paragraph.runs.push_back(std::move(run));
        }
        std::ostringstream text;
        for (const auto& run : paragraph.runs) {
            text << run.text;
        }
        paragraph.text = normalize_spacing(text.str());
        if (!paragraph.text.empty()) {
            paragraphs.push_back(std::move(paragraph));
        }
    }
    return paragraphs;
}
bool is_section_heading(const Paragraph& paragraph) {
    return paragraph.style.has_value() && (*paragraph.style == "Heading2" || *paragraph.style == "Heading3");
}

bool is_card_heading(const Paragraph& paragraph) {
    return paragraph.style.has_value() && *paragraph.style == "Heading4";
}

std::string argument_type(const std::string& text) {
    const auto normalized = lower_copy(trim(text));
    if (normalized.rfind("at:", 0) == 0) {
        return "answer_to";
    }
    if (normalized.rfind("ov", 0) == 0 || normalized.find("overview") != std::string::npos) {
        return "overview";
    }
    return normalized.empty() ? "unknown" : "argument";
}

std::optional<std::string> first_url(const std::string& text) {
    static const std::regex pattern(R"(https?://[^\s)\]]+)", std::regex::icase);
    std::smatch match;
    if (std::regex_search(text, match, pattern)) {
        return match[0].str();
    }
    return std::nullopt;
}

std::optional<std::string> first_author(const std::string& text) {
    auto candidate = trim(text);
    const auto delimiter = candidate.find_first_of(",[(");
    if (delimiter != std::string::npos) {
        candidate = trim(candidate.substr(0, delimiter));
    }
    candidate = std::regex_replace(candidate, std::regex(R"(\s+[-–—].*$)"), "");
    candidate = std::regex_replace(candidate, std::regex(R"(\s+[‘'’]?\d{2,4}\b.*$)"), "");
    candidate = trim(candidate);
    if (candidate.empty()) {
        return std::nullopt;
    }
    const auto split = candidate.find_last_of(" \t\r\n");
    return split == std::string::npos ? candidate : candidate.substr(split + 1);
}

std::optional<int> first_year(const std::string& text) {
    std::smatch match;
    if (std::regex_search(text, match, std::regex(R"(\b(19\d{2}|20\d{2})\b)"))) {
        return std::stoi(match[1].str());
    }
    if (std::regex_search(text, match, std::regex(R"((?:[‘']|\b)(\d{2})(?:\b|[.,\]]))"))) {
        const int year = std::stoi(match[1].str());
        return year < 70 ? 2000 + year : 1900 + year;
    }
    return std::nullopt;
}

CitationFields parse_citation(const std::string& text) {
    CitationFields result;
    result.raw = text;
    result.url = first_url(text);
    result.author = first_author(text);
    result.year = first_year(text);
    return result;
}

std::string card_name(const CitationFields& citation) {
    if (citation.author.has_value() && citation.year.has_value()) {
        std::ostringstream output;
        output << *citation.author << ' ' << std::setw(2) << std::setfill('0') << (*citation.year % 100);
        return output.str();
    }
    return citation.author.value_or("");
}

void append_highlight(
    std::vector<NativeHighlight>& highlights,
    std::vector<std::string>& text_parts,
    const std::optional<std::string>& color,
    int paragraph_index,
    const std::optional<int>& run_index,
    const std::optional<int>& start_char,
    int end_char,
    const std::optional<std::string>& style,
    const std::optional<double>& font_size_value,
    bool bold,
    bool underline
) {
    std::ostringstream raw_text;
    for (const auto& part : text_parts) {
        raw_text << part;
    }
    const auto text = normalize_spacing(raw_text.str());
    if (!text.empty()) {
        highlights.push_back({
            text,
            color,
            paragraph_index,
            run_index,
            start_char,
            end_char,
            style,
            font_size_value,
            bold,
            underline,
        });
    }
}

std::vector<NativeHighlight> extract_highlights(const std::vector<Paragraph>& paragraphs) {
    std::vector<NativeHighlight> highlights;
    for (const auto& paragraph : paragraphs) {
        int offset = 0;
        std::vector<std::string> active_text;
        std::optional<std::string> active_color;
        std::optional<int> active_start;
        std::optional<int> active_run_index;
        std::optional<std::string> active_style;
        std::optional<double> active_font_size;
        bool active_bold = false;
        bool active_underline = false;
        for (std::size_t index = 0; index < paragraph.runs.size(); ++index) {
            const auto& run = paragraph.runs[index];
            const int start = offset;
            offset += static_cast<int>(utf8_codepoint_count(run.text));
            if (run.highlight.has_value()) {
                if (active_color == run.highlight) {
                    active_text.push_back(run.text);
                } else {
                    append_highlight(highlights, active_text, active_color, paragraph.index, active_run_index,
                        active_start, start, active_style, active_font_size, active_bold, active_underline);
                    active_text = {run.text};
                    active_color = run.highlight;
                    active_start = start;
                    active_run_index = static_cast<int>(index);
                    active_style = run.style;
                    active_font_size = run.font_size;
                    active_bold = run.bold;
                    active_underline = run.underline;
                }
            } else {
                append_highlight(highlights, active_text, active_color, paragraph.index, active_run_index,
                    active_start, start, active_style, active_font_size, active_bold, active_underline);
                active_text.clear();
                active_color.reset();
                active_start.reset();
                active_run_index.reset();
                active_style.reset();
                active_font_size.reset();
                active_bold = false;
                active_underline = false;
            }
        }
        append_highlight(highlights, active_text, active_color, paragraph.index, active_run_index,
            active_start, offset, active_style, active_font_size, active_bold, active_underline);
    }
    return highlights;
}

NativeDocument parse_docx(const std::string& docx_path) {
    const auto paragraphs = read_paragraphs(docx_path);
    NativeDocument document;
    document.id = random_id();
    document.name = basename_without_extension(docx_path);
    document.source_path = docx_path;

    NativeSection* current_section = nullptr;
    int section_order = 0;
    std::size_t index = 0;
    while (index < paragraphs.size()) {
        const auto& paragraph = paragraphs[index];
        if (is_section_heading(paragraph)) {
            NativeSection section;
            section.id = random_id();
            section.name = paragraph.text;
            section.argument_type = argument_type(paragraph.text);
            section.order_index = section_order++;
            document.sections.push_back(std::move(section));
            current_section = &document.sections.back();
            ++index;
            continue;
        }
        if (!is_card_heading(paragraph)) {
            ++index;
            continue;
        }
        if (current_section == nullptr) {
            NativeSection section;
            section.id = random_id();
            section.name = "Uncategorized";
            section.argument_type = "unknown";
            section.order_index = section_order++;
            document.sections.push_back(std::move(section));
            current_section = &document.sections.back();
        }
        const auto citation_index = index + 1;
        if (citation_index >= paragraphs.size() || is_section_heading(paragraphs[citation_index])
            || is_card_heading(paragraphs[citation_index])) {
            index = citation_index;
            continue;
        }
        const auto body_start = citation_index + 1;
        auto body_end = body_start;
        while (body_end < paragraphs.size() && !is_section_heading(paragraphs[body_end])
            && !is_card_heading(paragraphs[body_end])) {
            ++body_end;
        }
        std::vector<Paragraph> body_paragraphs;
        std::ostringstream body;
        for (auto body_index = body_start; body_index < body_end; ++body_index) {
            if (!body_paragraphs.empty()) {
                body << "\n\n";
            }
            body << paragraphs[body_index].text;
            body_paragraphs.push_back(paragraphs[body_index]);
        }
        const auto body_text = trim(body.str());
        if (!body_text.empty()) {
            NativeCard card;
            card.id = random_id();
            card.document_id = document.id;
            card.section_id = current_section->id;
            card.section_name = current_section->name;
            card.tag = paragraph.text;
            card.citation = parse_citation(paragraphs[citation_index].text);
            card.card_name = card_name(card.citation);
            card.body = body_text;
            card.paragraph_start = paragraph.index;
            card.paragraph_end = body_paragraphs.empty() ? paragraph.index : body_paragraphs.back().index;
            card.highlights = extract_highlights(body_paragraphs);
            current_section->cards.push_back(std::move(card));
        }
        index = body_end;
    }
    return document;
}

void ensure_native_vector_schema(sqlite3* db) {
    exec(db, R"SQL(
CREATE TABLE IF NOT EXISTS native_card_vectors (
    card_id TEXT NOT NULL,
    embedding_kind TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (card_id, embedding_kind, embedding_model),
    FOREIGN KEY (card_id) REFERENCES evidence_cards(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_native_card_vectors_kind_model
    ON native_card_vectors(embedding_kind, embedding_model);
)SQL");
}

std::string clip_embedding_text(const std::string& text, std::size_t max_chars) {
    if (max_chars == 0 || text.size() <= max_chars) {
        return text;
    }
    auto clipped = trim(text.substr(0, max_chars));
    const auto paragraph = clipped.rfind("\n\n");
    if (paragraph != std::string::npos && paragraph >= max_chars / 2) {
        return trim(clipped.substr(0, paragraph));
    }
    std::size_t sentence = std::string::npos;
    for (const auto* marker : {". ", "? ", "! "}) {
        const auto found = clipped.rfind(marker);
        if (found != std::string::npos) {
            sentence = sentence == std::string::npos ? found : std::max(sentence, found);
        }
    }
    if (sentence != std::string::npos && sentence >= max_chars / 2) {
        return trim(clipped.substr(0, sentence + 1));
    }
    return clipped;
}

std::string vector_json(const std::vector<double>& vector) {
    std::ostringstream output;
    output << '[' << std::setprecision(17);
    for (std::size_t index = 0; index < vector.size(); ++index) {
        if (index != 0) {
            output << ',';
        }
        output << vector[index];
    }
    output << ']';
    return output.str();
}

std::string highlights_for_card(sqlite3* db, const std::string& card_id) {
    auto statement = prepare(db, "SELECT text FROM highlights WHERE card_id = ?1 ORDER BY order_index");
    bind_text(statement.get(), 1, card_id);
    std::ostringstream output;
    while (sqlite3_step(statement.get()) == SQLITE_ROW) {
        const auto text = column_text(statement.get(), 0);
        if (text.empty()) {
            continue;
        }
        if (output.tellp() > 0) {
            output << '\n';
        }
        output << text;
    }
    return output.str();
}

std::vector<EmbeddingRecord> embedding_records(sqlite3* db, const std::string& kind) {
    auto statement = prepare(
        db,
        "SELECT evidence_cards.id, sections.name, evidence_cards.tag, "
        "coalesce(citations.raw, ''), evidence_cards.body "
        "FROM evidence_cards "
        "JOIN sections ON sections.id = evidence_cards.section_id "
        "LEFT JOIN citations ON citations.card_id = evidence_cards.id "
        "ORDER BY sections.order_index, evidence_cards.paragraph_start"
    );
    std::vector<EmbeddingRecord> records;
    while (sqlite3_step(statement.get()) == SQLITE_ROW) {
        const auto card_id = column_text(statement.get(), 0);
        const auto section = column_text(statement.get(), 1);
        const auto tag = column_text(statement.get(), 2);
        const auto citation = column_text(statement.get(), 3);
        const auto body = column_text(statement.get(), 4);
        const auto highlights = highlights_for_card(db, card_id);
        std::vector<std::string> parts = {section, tag};
        if (kind == kDeepVectorKind) {
            parts.push_back(citation);
        }
        parts.push_back(highlights);
        if (kind == kDeepVectorKind) {
            parts.push_back(body);
        }
        std::ostringstream text;
        for (const auto& part : parts) {
            if (part.empty()) {
                continue;
            }
            if (text.tellp() > 0) {
                text << "\n\n";
            }
            text << part;
        }
        records.push_back({card_id, text.str()});
    }
    return records;
}
std::string json_escape(const std::string& text) {
    std::ostringstream output;
    for (const unsigned char character : text) {
        switch (character) {
            case '"':
                output << "\\\"";
                break;
            case '\\':
                output << "\\\\";
                break;
            case '\n':
                output << "\\n";
                break;
            case '\r':
                output << "\\r";
                break;
            case '\t':
                output << "\\t";
                break;
            default:
                if (character < 0x20) {
                    output << "\\u00";
                    constexpr char hex[] = "0123456789abcdef";
                    output << hex[(character >> 4) & 0x0f] << hex[character & 0x0f];
                } else {
                    output << character;
                }
        }
    }
    return output.str();
}

void insert_document(sqlite3* db, const NativeDocument& document) {
    auto insert_document_stmt = prepare(
        db,
        "INSERT INTO debate_documents (id, name, source_path, source_format, metadata_json, created_at) "
        "VALUES (?, ?, ?, 'docx', ?, ?)"
    );
    bind_text(insert_document_stmt.get(), 1, document.id);
    bind_text(insert_document_stmt.get(), 2, document.name);
    bind_text(insert_document_stmt.get(), 3, document.source_path);
    bind_text(insert_document_stmt.get(), 4, std::string("{\"parser_version\":\"") + kParserVersion + "\"}");
    bind_text(insert_document_stmt.get(), 5, iso_now());
    step_done(db, insert_document_stmt.get());

    auto insert_section_stmt = prepare(
        db,
        "INSERT INTO sections (id, document_id, parent_id, name, argument_type, order_index, metadata_json) "
        "VALUES (?, ?, NULL, ?, ?, ?, '{}')"
    );
    auto insert_card_stmt = prepare(
        db,
        "INSERT INTO evidence_cards (id, document_id, section_id, tag, card_name, argument_name, body, "
        "category, topical, side, source_path, content_hash, paragraph_start, paragraph_end, source_format, "
        "metadata_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'ours', ?, ?, ?, ?, 'docx', ?, ?)"
    );
    auto insert_citation_stmt = prepare(
        db,
        "INSERT INTO citations (id, card_id, raw, author, year, source_url) VALUES (?, ?, ?, ?, ?, ?)"
    );
    auto insert_highlight_stmt = prepare(
        db,
        "INSERT INTO highlights (id, card_id, text, color, highlight_color, paragraph_index, run_index, "
        "start_char, end_char, style, font_size, bold, underline, order_index) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    );
    auto insert_fts_stmt = prepare(
        db,
        "INSERT INTO evidence_cards_fts (card_id, tag, card_name, citation, body) VALUES (?, ?, ?, ?, ?)"
    );

    for (const auto& section : document.sections) {
        reset_statement(insert_section_stmt);
        bind_text(insert_section_stmt.get(), 1, section.id);
        bind_text(insert_section_stmt.get(), 2, document.id);
        bind_text(insert_section_stmt.get(), 3, section.name);
        bind_text(insert_section_stmt.get(), 4, section.argument_type);
        sqlite3_bind_int(insert_section_stmt.get(), 5, section.order_index);
        step_done(db, insert_section_stmt.get());

        for (const auto& card : section.cards) {
            reset_statement(insert_card_stmt);
            bind_text(insert_card_stmt.get(), 1, card.id);
            bind_text(insert_card_stmt.get(), 2, card.document_id);
            bind_text(insert_card_stmt.get(), 3, card.section_id);
            bind_text(insert_card_stmt.get(), 4, card.tag);
            bind_optional_text(
                insert_card_stmt.get(),
                5,
                card.card_name.empty() ? std::optional<std::string>() : std::optional<std::string>(card.card_name)
            );
            bind_text(insert_card_stmt.get(), 6, card.section_name);
            bind_text(insert_card_stmt.get(), 7, card.body);
            bind_text(insert_card_stmt.get(), 8, document.source_path);
            bind_text(
                insert_card_stmt.get(),
                9,
                stable_hash(
                    card.document_id + "\n" + card.section_id + "\n" + card.tag + "\n"
                    + card.citation.raw + "\n" + card.body
                )
            );
            sqlite3_bind_int(insert_card_stmt.get(), 10, card.paragraph_start);
            sqlite3_bind_int(insert_card_stmt.get(), 11, card.paragraph_end);
            bind_text(
                insert_card_stmt.get(),
                12,
                std::string("{\"section_name\":\"") + json_escape(card.section_name)
                    + "\",\"parser_version\":\"" + kParserVersion + "\"}"
            );
            bind_text(insert_card_stmt.get(), 13, iso_now());
            step_done(db, insert_card_stmt.get());

            reset_statement(insert_citation_stmt);
            bind_text(insert_citation_stmt.get(), 1, random_id());
            bind_text(insert_citation_stmt.get(), 2, card.id);
            bind_text(insert_citation_stmt.get(), 3, card.citation.raw);
            bind_optional_text(insert_citation_stmt.get(), 4, card.citation.author);
            bind_optional_int(insert_citation_stmt.get(), 5, card.citation.year);
            bind_optional_text(insert_citation_stmt.get(), 6, card.citation.url);
            step_done(db, insert_citation_stmt.get());

            for (std::size_t highlight_index = 0; highlight_index < card.highlights.size(); ++highlight_index) {
                const auto& highlight = card.highlights[highlight_index];
                reset_statement(insert_highlight_stmt);
                bind_text(insert_highlight_stmt.get(), 1, random_id());
                bind_text(insert_highlight_stmt.get(), 2, card.id);
                bind_text(insert_highlight_stmt.get(), 3, highlight.text);
                bind_optional_text(insert_highlight_stmt.get(), 4, highlight.color);
                bind_optional_text(insert_highlight_stmt.get(), 5, highlight.color);
                sqlite3_bind_int(insert_highlight_stmt.get(), 6, highlight.paragraph_index);
                bind_optional_int(insert_highlight_stmt.get(), 7, highlight.run_index);
                bind_optional_int(insert_highlight_stmt.get(), 8, highlight.start_char);
                bind_optional_int(insert_highlight_stmt.get(), 9, highlight.end_char);
                bind_optional_text(insert_highlight_stmt.get(), 10, highlight.style);
                bind_optional_double(insert_highlight_stmt.get(), 11, highlight.font_size);
                sqlite3_bind_int(insert_highlight_stmt.get(), 12, highlight.bold ? 1 : 0);
                sqlite3_bind_int(insert_highlight_stmt.get(), 13, highlight.underline ? 1 : 0);
                sqlite3_bind_int(insert_highlight_stmt.get(), 14, static_cast<int>(highlight_index));
                step_done(db, insert_highlight_stmt.get());
            }

            reset_statement(insert_fts_stmt);
            bind_text(insert_fts_stmt.get(), 1, card.id);
            bind_text(insert_fts_stmt.get(), 2, card.tag);
            bind_text(insert_fts_stmt.get(), 3, card.card_name);
            bind_text(insert_fts_stmt.get(), 4, card.citation.raw);
            bind_text(insert_fts_stmt.get(), 5, card.body);
            step_done(db, insert_fts_stmt.get());
        }
    }
}

std::size_t count_rows(sqlite3* db, const char* table) {
    const auto statement = prepare(db, std::string("SELECT count(*) FROM ") + table);
    if (sqlite3_step(statement.get()) != SQLITE_ROW) {
        throw std::runtime_error(sqlite3_errmsg(db));
    }
    return static_cast<std::size_t>(sqlite3_column_int64(statement.get(), 0));
}

} // namespace

NativeDocumentStats import_docx_to_sqlite_with_schema_text(
    const std::string& docx_path,
    const std::string& db_path,
    const std::string& schema_sql
) {
    const auto document = parse_docx(docx_path);
    const std::filesystem::path target(db_path);
    if (target.has_parent_path()) {
        std::filesystem::create_directories(target.parent_path());
    }
    std::error_code remove_error;
    std::filesystem::remove(target, remove_error);
    if (remove_error) {
        throw std::runtime_error(
            "Could not replace SQLite database: " + db_path + ": " + remove_error.message()
        );
    }

    const auto db = open_database(db_path);
    exec(db.get(), "PRAGMA foreign_keys = ON");
    exec(db.get(), schema_sql);
    exec(db.get(), "BEGIN IMMEDIATE");
    try {
        insert_document(db.get(), document);
        exec(db.get(), "COMMIT");
    } catch (...) {
        sqlite3_exec(db.get(), "ROLLBACK", nullptr, nullptr, nullptr);
        throw;
    }

    return {
        document.name,
        count_rows(db.get(), "sections"),
        count_rows(db.get(), "evidence_cards"),
        count_rows(db.get(), "citations"),
        count_rows(db.get(), "highlights"),
    };
}

NativeDocumentStats import_docx_to_sqlite(
    const std::string& docx_path,
    const std::string& db_path,
    const std::string& schema_path
) {
    return import_docx_to_sqlite_with_schema_text(docx_path, db_path, read_file(schema_path));
}

NativeVectorBuildStats build_native_vector_cache(
    const std::string& db_path,
    const std::string& kind,
    bool reset,
    std::size_t max_chars
) {
    if (kind != "fast" && kind != "deep" && kind != "all") {
        throw std::invalid_argument("--kind must be fast, deep, or all");
    }
    const auto db = open_database(db_path);
    exec(db.get(), "PRAGMA foreign_keys = ON");
    ensure_native_vector_schema(db.get());
    const OllamaEmbedder embedder;
    const std::vector<std::string> kinds = kind == "all"
        ? std::vector<std::string>{kFastVectorKind, kDeepVectorKind}
        : std::vector<std::string>{kind};
    NativeVectorBuildStats stats;

    for (const auto& selected_kind : kinds) {
        if (reset) {
            auto remove_existing = prepare(
                db.get(),
                "DELETE FROM native_card_vectors WHERE embedding_kind = ?1 AND embedding_model = ?2"
            );
            bind_text(remove_existing.get(), 1, selected_kind);
            bind_text(remove_existing.get(), 2, embedder.model());
            step_done(db.get(), remove_existing.get());
        }
        const auto records = embedding_records(db.get(), selected_kind);
        auto upsert = prepare(
            db.get(),
            "INSERT INTO native_card_vectors (card_id, embedding_kind, embedding_model, vector_json, updated_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(card_id, embedding_kind, embedding_model) DO UPDATE SET "
            "vector_json = excluded.vector_json, updated_at = excluded.updated_at"
        );
        exec(db.get(), "BEGIN IMMEDIATE");
        try {
            for (const auto& record : records) {
                const auto embedding = embedder.embed(clip_embedding_text(record.text, max_chars));
                reset_statement(upsert);
                bind_text(upsert.get(), 1, record.card_id);
                bind_text(upsert.get(), 2, selected_kind);
                bind_text(upsert.get(), 3, embedder.model());
                bind_text(upsert.get(), 4, vector_json(embedding));
                step_done(db.get(), upsert.get());
            }
            exec(db.get(), "COMMIT");
        } catch (...) {
            sqlite3_exec(db.get(), "ROLLBACK", nullptr, nullptr, nullptr);
            throw;
        }
        if (selected_kind == kFastVectorKind) {
            stats.fast = records.size();
        } else {
            stats.deep = records.size();
        }
    }
    return stats;
}

std::vector<RetrievedCard> query_native_vectors(
    const std::string& db_path,
    const std::string& query,
    std::size_t limit,
    NativeVectorQueryStats* stats
) {
    const auto elapsed_ms = [](const auto& started) {
        const auto elapsed = std::chrono::steady_clock::now() - started;
        return std::chrono::duration<double, std::milli>(elapsed).count();
    };
    const OllamaEmbedder embedder;
    const NativeSqliteVectorStore store(db_path);
    const auto availability_started = std::chrono::steady_clock::now();
    if (!store.has_vectors(kFastVectorKind, embedder.model())) {
        throw std::runtime_error(
            "No native fast vectors found for model " + embedder.model()
            + ". Run scripts/native_pipeline.sh build-vector first."
        );
    }
    if (stats != nullptr) {
        stats->vector_availability_ms = elapsed_ms(availability_started);
    }
    const auto embedding_started = std::chrono::steady_clock::now();
    const auto embedding = embedder.embed(query);
    if (stats != nullptr) {
        stats->embedding_ms = elapsed_ms(embedding_started);
    }
    const auto search_started = std::chrono::steady_clock::now();
    const auto matches = store.search(embedding, kFastVectorKind, embedder.model(), limit);
    if (stats != nullptr) {
        stats->vector_search_ms = elapsed_ms(search_started);
    }
    std::vector<std::string> ids;
    ids.reserve(matches.size());
    for (const auto& match : matches) {
        ids.push_back(match.card_id);
    }
    const auto hydration_started = std::chrono::steady_clock::now();
    const auto cards_by_id = load_cards_by_ids(db_path, ids);
    std::vector<RetrievedCard> results;
    results.reserve(matches.size());
    for (const auto& match : matches) {
        const auto found = cards_by_id.find(match.card_id);
        if (found == cards_by_id.end()) {
            continue;
        }
        auto card = found->second;
        card.score = match.score;
        card.retrieval_score = match.retrieval_score;
        results.push_back(std::move(card));
    }
    if (stats != nullptr) {
        stats->hydration_ms = elapsed_ms(hydration_started);
    }
    return results;
}

} // namespace sekret::hybrid

namespace {

std::string native_pipeline_json_escape(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
        switch (character) {
            case '"': output << static_cast<char>(92) << '"'; break;
            case '\\': output << static_cast<char>(92) << static_cast<char>(92); break;
            case '\n': output << static_cast<char>(92) << 'n'; break;
            case '\r': output << static_cast<char>(92) << 'r'; break;
            case '\t': output << static_cast<char>(92) << 't'; break;
            default:
                if (character < 0x20) {
                    constexpr char hex[] = "0123456789abcdef";
                    output << static_cast<char>(92) << "u00" << hex[(character >> 4) & 0x0f] << hex[character & 0x0f];
                } else {
                    output << character;
                }
        }
    }
    return output.str();
}

char* native_pipeline_copy_string(const std::string& value) {
    auto* result = static_cast<char*>(std::malloc(value.size() + 1));
    if (result == nullptr) {
        return nullptr;
    }
    std::memcpy(result, value.c_str(), value.size() + 1);
    return result;
}

SekretNativePipelineJsonResult native_pipeline_error(const std::string& message) {
    return {nullptr, native_pipeline_copy_string(message)};
}

} // namespace

extern "C" {

SekretNativePipelineJsonResult sekret_native_import_docx_json(
    const char* docx_path,
    const char* db_path,
    const char* schema_sql
) {
    try {
        if (docx_path == nullptr || db_path == nullptr || schema_sql == nullptr) {
            throw std::invalid_argument("docx_path, db_path, and schema_sql are required.");
        }
        const auto stats = sekret::hybrid::import_docx_to_sqlite_with_schema_text(
            docx_path, db_path, schema_sql
        );
        std::ostringstream json;
        json << "{\"documentName\":\"" << native_pipeline_json_escape(stats.document_name)
             << "\",\"sections\":" << stats.sections
             << ",\"cards\":" << stats.cards
             << ",\"citations\":" << stats.citations
             << ",\"highlights\":" << stats.highlights << "}";
        return {native_pipeline_copy_string(json.str()), nullptr};
    } catch (const std::exception& error) {
        return native_pipeline_error(error.what());
    } catch (...) {
        return native_pipeline_error("Unknown native import error.");
    }
}

SekretNativePipelineJsonResult sekret_native_build_vectors_json(
    const char* db_path,
    const char* kind,
    int reset
) {
    try {
        if (db_path == nullptr) {
            throw std::invalid_argument("db_path is required.");
        }
        const auto stats = sekret::hybrid::build_native_vector_cache(
            db_path, kind == nullptr ? "all" : kind, reset != 0, 6000
        );
        std::ostringstream json;
        json << "{\"fast\":" << stats.fast << ",\"deep\":" << stats.deep << "}";
        return {native_pipeline_copy_string(json.str()), nullptr};
    } catch (const std::exception& error) {
        return native_pipeline_error(error.what());
    } catch (...) {
        return native_pipeline_error("Unknown native vector build error.");
    }
}

} // extern "C"
