#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#if defined(_WIN32)
#define popen _popen
#define pclose _pclose
#endif

using namespace std;
namespace fs = std::filesystem;

struct Paragraph {
    string text;
    string highlighted_text;
};

struct RawStyle {
    string type;
    bool highlighted = false;
    string parent_id;
};

struct RawCard {
    int card_index = 0;
    string title;
    string citation;
    string full_citation;
    vector<string> body_paragraphs;
    vector<string> highlighted_paragraphs;
};

static const regex CARD_TITLE_RE(R"(^\s*(\d+)\.\s+(.+?)\s*$)");
static const regex DEBATE_TITLE_RE(R"(^\s*\d+\s*[-–—]{1,2}\s*.+\S\s*$)");
static const regex DATE_RE(R"(\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4})\b)");
static const regex URL_RE(R"(\b(?:https?://|www\.|doi:|journals\.|archive\.))", regex::icase);
static const regex SPACE_BEFORE_PUNCTUATION_RE(R"(\s+([,.;:!?%)\]\}]))");
static const regex SPACE_AFTER_OPEN_RE(R"(([(\[\{])\s+)");
static const regex CONTRACTION_APOSTROPHE_RE(R"(\s+(['’])(?=(?:s|t|re|ve|d|ll|m)\b))", regex::icase);
static const regex SHORT_CITATION_BOUNDARY_RE(
    R"(\s+(?:\[|By\b|https?://|www\.|archive\.|doi:|journals\.|[“"]|No Publication\b|Quantum Insider\b|Reuters\b|AP News\b|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}))",
    regex::icase);
static const regex SHORT_CITATION_YEAR_RE(R"(^(.*?(?:[’'‘]\d{2}|\d{2,4})))");

static string run_command(const string &cmd) {
    array<char, 8192> buffer{};
    string result;
    FILE *pipe = popen((cmd + " 2>/dev/null").c_str(), "r");
    if (!pipe) return "";
    while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
        result += buffer.data();
    }
    pclose(pipe);
    return result;
}

static string shell_quote(const fs::path &path) {
    string s = path.string();
    string out = "'";
    for (char ch : s) {
        if (ch == '\'') out += "'\\''";
        else out += ch;
    }
    out += "'";
    return out;
}

static string read_docx_xml(const fs::path &docx, const string &member) {
    return run_command("unzip -p " + shell_quote(docx) + " " + member);
}

static string replace_all(string text, const string &from, const string &to) {
    size_t pos = 0;
    while ((pos = text.find(from, pos)) != string::npos) {
        text.replace(pos, from.size(), to);
        pos += to.size();
    }
    return text;
}

static string trim(const string &s) {
    size_t start = 0;
    while (start < s.size() && isspace(static_cast<unsigned char>(s[start]))) start++;
    size_t end = s.size();
    while (end > start && isspace(static_cast<unsigned char>(s[end - 1]))) end--;
    return s.substr(start, end - start);
}

static string lower_ascii(string s) {
    transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(tolower(c)); });
    return s;
}

static string normalize_spacing(string text) {
    text = replace_all(text, "\xC2\xA0", " ");
    text = regex_replace(text, regex(R"(\s+)"), " ");
    text = trim(text);
    text = regex_replace(text, SPACE_BEFORE_PUNCTUATION_RE, "$1");
    text = regex_replace(text, SPACE_AFTER_OPEN_RE, "$1");
    text = regex_replace(text, CONTRACTION_APOSTROPHE_RE, "$1");
    for (const string &suffix : vector<string>{"s", "t", "re", "ve", "d", "ll", "m"}) {
        text = replace_all(text, " ’" + suffix, "’" + suffix);
        text = replace_all(text, " '" + suffix, "'" + suffix);
    }
    return text;
}

static string xml_attr(const string &tag, const string &attr) {
    regex quoted(attr + "=\"([^\"]*)\"");
    smatch match;
    if (regex_search(tag, match, quoted)) return match[1].str();
    regex single(attr + "='([^']*)'");
    if (regex_search(tag, match, single)) return match[1].str();
    return "";
}

static string decode_xml_entities(string text) {
    text = replace_all(text, "&lt;", "<");
    text = replace_all(text, "&gt;", ">");
    text = replace_all(text, "&quot;", "\"");
    text = replace_all(text, "&apos;", "'");
    text = replace_all(text, "&amp;", "&");

    regex numeric(R"(&#(x?[0-9A-Fa-f]+);)");
    smatch match;
    string out;
    string::const_iterator search_start(text.cbegin());
    while (regex_search(search_start, text.cend(), match, numeric)) {
        out.append(match.prefix().first, match.prefix().second);
        string value = match[1].str();
        long codepoint = 0;
        try {
            if (!value.empty() && value[0] == 'x') codepoint = stol(value.substr(1), nullptr, 16);
            else codepoint = stol(value, nullptr, 10);
        } catch (...) {
            codepoint = 0;
        }
        if (codepoint > 0 && codepoint < 128) out.push_back(static_cast<char>(codepoint));
        search_start = match.suffix().first;
    }
    out.append(search_start, text.cend());
    return out;
}

static vector<string> find_blocks(const string &xml, const string &open_token, const string &close_token) {
    vector<string> blocks;
    size_t pos = 0;
    while (true) {
        size_t start = xml.find(open_token, pos);
        if (start == string::npos) break;
        size_t boundary = start + open_token.size();
        if (boundary < xml.size()) {
            char next = xml[boundary];
            if (!(isspace(static_cast<unsigned char>(next)) || next == '>' || next == '/')) {
                pos = boundary;
                continue;
            }
        }
        size_t open_end = xml.find('>', start);
        if (open_end == string::npos) break;
        size_t end = xml.find(close_token, open_end + 1);
        if (end == string::npos) break;
        blocks.push_back(xml.substr(start, end + close_token.size() - start));
        pos = end + close_token.size();
    }
    return blocks;
}

static string first_tag(const string &xml, const string &tag_name) {
    string needle = "<" + tag_name;
    size_t start = xml.find(needle);
    if (start == string::npos) return "";
    size_t end = xml.find('>', start);
    if (end == string::npos) return "";
    return xml.substr(start, end - start + 1);
}

static string inner_tag_text(const string &xml, const string &tag_name) {
    string needle = "<" + tag_name;
    size_t start = xml.find(needle);
    if (start == string::npos) return "";
    size_t open_end = xml.find('>', start);
    if (open_end == string::npos) return "";
    string close = "</" + tag_name + ">";
    size_t end = xml.find(close, open_end + 1);
    if (end == string::npos) return "";
    return xml.substr(open_end + 1, end - open_end - 1);
}

static bool highlight_in_properties(const string &rpr_xml) {
    if (rpr_xml.empty()) return false;
    string highlight_tag = first_tag(rpr_xml, "w:highlight");
    if (!highlight_tag.empty()) {
        string value = lower_ascii(xml_attr(highlight_tag, "w:val"));
        return !(value.empty() || value == "none" || value == "white");
    }
    string shd_tag = first_tag(rpr_xml, "w:shd");
    if (!shd_tag.empty()) {
        string fill = lower_ascii(xml_attr(shd_tag, "w:fill"));
        return !(fill.empty() || fill == "auto" || fill == "ffffff" || fill == "white");
    }
    return false;
}

static string run_style_id(const string &run_xml) {
    string rpr = inner_tag_text(run_xml, "w:rPr");
    string tag = first_tag(rpr, "w:rStyle");
    return xml_attr(tag, "w:val");
}

static string paragraph_style_id(const string &paragraph_xml) {
    string ppr = inner_tag_text(paragraph_xml, "w:pPr");
    string tag = first_tag(ppr, "w:pStyle");
    return xml_attr(tag, "w:val");
}

static string run_text(const string &run_xml) {
    string out;
    size_t pos = 0;
    while (pos < run_xml.size()) {
        size_t tag_start = run_xml.find('<', pos);
        if (tag_start == string::npos) break;
        if (run_xml.compare(tag_start, 4, "<w:t") == 0) {
            size_t open_end = run_xml.find('>', tag_start);
            if (open_end == string::npos) break;
            size_t close = run_xml.find("</w:t>", open_end + 1);
            if (close == string::npos) break;
            out += decode_xml_entities(run_xml.substr(open_end + 1, close - open_end - 1));
            pos = close + 6;
        } else if (run_xml.compare(tag_start, 6, "<w:tab") == 0) {
            out += " ";
            size_t end = run_xml.find('>', tag_start);
            pos = end == string::npos ? run_xml.size() : end + 1;
        } else if (run_xml.compare(tag_start, 5, "<w:br") == 0 || run_xml.compare(tag_start, 5, "<w:cr") == 0) {
            out += "\n";
            size_t end = run_xml.find('>', tag_start);
            pos = end == string::npos ? run_xml.size() : end + 1;
        } else {
            pos = tag_start + 1;
        }
    }
    return out;
}

static pair<set<string>, set<string>> style_highlights(const fs::path &docx) {
    string xml = read_docx_xml(docx, "word/styles.xml");
    set<string> paragraph_styles;
    set<string> character_styles;
    if (xml.empty()) return {paragraph_styles, character_styles};

    map<string, RawStyle> styles;
    vector<string> style_blocks = find_blocks(xml, "<w:style", "</w:style>");
    for (const string &block : style_blocks) {
        string tag = block.substr(0, block.find('>') + 1);
        string style_id = xml_attr(tag, "w:styleId");
        if (style_id.empty()) continue;
        RawStyle style;
        style.type = xml_attr(tag, "w:type");
        string based_on = first_tag(block, "w:basedOn");
        style.parent_id = xml_attr(based_on, "w:val");
        style.highlighted = highlight_in_properties(inner_tag_text(block, "w:rPr"));
        styles[style_id] = style;
    }

    function<bool(const string &, set<string> &)> inherits_highlight = [&](const string &style_id, set<string> &seen) {
        if (style_id.empty() || !styles.count(style_id) || seen.count(style_id)) return false;
        seen.insert(style_id);
        const RawStyle &style = styles[style_id];
        if (style.highlighted) return true;
        return inherits_highlight(style.parent_id, seen);
    };

    for (const auto &[style_id, style] : styles) {
        set<string> seen;
        if (!inherits_highlight(style_id, seen)) continue;
        if (style.type == "paragraph") paragraph_styles.insert(style_id);
        else if (style.type == "character") character_styles.insert(style_id);
    }
    return {paragraph_styles, character_styles};
}

static vector<Paragraph> parse_paragraphs(const fs::path &docx) {
    string xml = read_docx_xml(docx, "word/document.xml");
    if (xml.empty()) {
        cerr << "Could not read word/document.xml from " << docx << "\n";
        exit(1);
    }
    auto [highlighted_p_styles, highlighted_r_styles] = style_highlights(docx);
    vector<Paragraph> paragraphs;
    vector<string> paragraph_blocks = find_blocks(xml, "<w:p", "</w:p>");

    for (const string &paragraph_xml : paragraph_blocks) {
        string p_style = paragraph_style_id(paragraph_xml);
        bool paragraph_highlighted = highlighted_p_styles.count(p_style) > 0;
        string full;
        vector<string> highlighted_parts;

        for (const string &run_xml : find_blocks(paragraph_xml, "<w:r", "</w:r>")) {
            string text = run_text(run_xml);
            full += text;
            string rpr = inner_tag_text(run_xml, "w:rPr");
            string r_style = run_style_id(run_xml);
            bool run_highlighted = paragraph_highlighted || highlight_in_properties(rpr) || highlighted_r_styles.count(r_style) > 0;
            if (run_highlighted) highlighted_parts.push_back(text);
        }

        string highlighted;
        for (size_t i = 0; i < highlighted_parts.size(); ++i) {
            if (i) highlighted += " ";
            highlighted += highlighted_parts[i];
        }
        paragraphs.push_back({normalize_spacing(full), normalize_spacing(highlighted)});
    }
    return paragraphs;
}

static optional<size_t> next_nonempty_index(const vector<Paragraph> &paragraphs, size_t start) {
    for (size_t i = start; i < paragraphs.size(); ++i) {
        if (!paragraphs[i].text.empty()) return i;
    }
    return nullopt;
}

static int bracket_balance(const string &text) {
    return static_cast<int>(count(text.begin(), text.end(), '[')) - static_cast<int>(count(text.begin(), text.end(), ']'));
}

static bool contains_case_insensitive(const string &text, const string &needle) {
    return lower_ascii(text).find(lower_ascii(needle)) != string::npos;
}

static bool looks_like_citation(string text) {
    text = normalize_spacing(text);
    if (text.size() < 12) return false;
    if (regex_search(text, URL_RE)) return true;
    if (text.find('[') != string::npos && regex_search(text, DATE_RE)) return true;
    if (contains_case_insensitive(text, "accessed") && regex_search(text, DATE_RE)) return true;
    if (text.size() > 80 && regex_search(text, regex(R"(\b(?:\d{2,4}|[’']\d{2})\b)")) &&
        (text.find("//") != string::npos || contains_case_insensitive(text, "google books") ||
         text.find("“") != string::npos || text.find('"') != string::npos)) {
        return true;
    }
    return false;
}

static bool looks_like_citation_continuation(string text, const string &current_citation) {
    text = normalize_spacing(text);
    if (text.empty()) return false;
    if (bracket_balance(current_citation) > 0) return true;
    if (regex_search(text, URL_RE)) return true;
    if (!text.empty() && (text[0] == '.' || text[0] == ',' || text[0] == ')' || text[0] == ']')) return true;
    if (regex_search(text, regex(R"((?:accessed|doa)\s*:?\s*\d)", regex::icase))) return true;
    return false;
}

static bool card_title_match(const string &text, string *title = nullptr) {
    smatch match;
    if (!regex_match(text, match, CARD_TITLE_RE)) return false;
    if (title) *title = match[2].str();
    return true;
}

static bool looks_like_embedded_title(const vector<Paragraph> &paragraphs, size_t index) {
    const Paragraph &paragraph = paragraphs[index];
    const string &text = paragraph.text;
    if (text.empty() || !paragraph.highlighted_text.empty()) return false;
    if (card_title_match(text) || looks_like_citation(text)) return false;
    if (text.size() > 420) return false;

    optional<size_t> citation_index = next_nonempty_index(paragraphs, index + 1);
    if (!citation_index) return false;
    const Paragraph &citation = paragraphs[*citation_index];
    if (regex_match(text, DEBATE_TITLE_RE)) return looks_like_citation(citation.text);
    return (citation.highlighted_text.empty() || regex_search(citation.text, URL_RE)) && looks_like_citation(citation.text);
}

static string start_title_from_text(const string &text) {
    string title;
    if (card_title_match(text, &title)) return title;
    return text;
}

static pair<string, size_t> consume_citation(const vector<Paragraph> &paragraphs, size_t start) {
    optional<size_t> citation_index = next_nonempty_index(paragraphs, start);
    if (!citation_index) return {"", start};

    vector<string> parts{paragraphs[*citation_index].text};
    size_t index = *citation_index + 1;
    while (index < paragraphs.size()) {
        const Paragraph &paragraph = paragraphs[index];
        if (paragraph.text.empty()) {
            index++;
            continue;
        }
        if (!paragraph.highlighted_text.empty() || card_title_match(paragraph.text) || looks_like_embedded_title(paragraphs, index)) break;
        string joined;
        for (size_t i = 0; i < parts.size(); ++i) {
            if (i) joined += " ";
            joined += parts[i];
        }
        if (!looks_like_citation_continuation(paragraph.text, joined)) break;
        parts.push_back(paragraph.text);
        index++;
    }

    string citation;
    for (size_t i = 0; i < parts.size(); ++i) {
        if (i) citation += " ";
        citation += parts[i];
    }
    return {normalize_spacing(citation), index};
}

static string short_citation(string citation) {
    citation = normalize_spacing(citation);
    if (citation.empty()) return "";

    smatch boundary;
    size_t boundary_pos = string::npos;
    if (regex_search(citation, boundary, SHORT_CITATION_BOUNDARY_RE)) {
        boundary_pos = static_cast<size_t>(boundary.position());
    }

    size_t apostrophe_year = string::npos;
    for (const string &mark : vector<string>{u8"‘", u8"’", "'"}) {
        size_t pos = citation.find(mark);
        while (pos != string::npos) {
            size_t digit_pos = pos + mark.size();
            if (digit_pos + 1 < citation.size() &&
                isdigit(static_cast<unsigned char>(citation[digit_pos])) &&
                isdigit(static_cast<unsigned char>(citation[digit_pos + 1]))) {
                apostrophe_year = digit_pos + 2;
                break;
            }
            pos = citation.find(mark, pos + mark.size());
        }
        if (apostrophe_year != string::npos) break;
    }
    for (size_t pos = 0; pos < citation.size(); ++pos) {
        if (apostrophe_year != string::npos) break;
        size_t digit_pos = string::npos;
        unsigned char ch = static_cast<unsigned char>(citation[pos]);
        if (ch == '\'') {
            digit_pos = pos + 1;
        } else if (pos + 2 < citation.size() &&
                   ch == 0xE2 &&
                   static_cast<unsigned char>(citation[pos + 1]) == 0x80 &&
                   (static_cast<unsigned char>(citation[pos + 2]) == 0x98 ||
                    static_cast<unsigned char>(citation[pos + 2]) == 0x99)) {
            digit_pos = pos + 3;
        }
        if (digit_pos != string::npos &&
            digit_pos + 1 < citation.size() &&
            isdigit(static_cast<unsigned char>(citation[digit_pos])) &&
            isdigit(static_cast<unsigned char>(citation[digit_pos + 1]))) {
            apostrophe_year = digit_pos + 2;
            break;
        }
    }
    size_t bracket_pos = citation.find('[');
    if (apostrophe_year != string::npos && (bracket_pos == string::npos || apostrophe_year < bracket_pos)) {
        citation = citation.substr(0, apostrophe_year);
    } else {
        if (boundary_pos != string::npos) {
            citation = citation.substr(0, boundary_pos);
        }

        smatch year;
        if (regex_search(citation, year, SHORT_CITATION_YEAR_RE)) {
            citation = year[1].str();
        }
    }

    citation = trim(citation);
    while (!citation.empty() && string(" ,;:-").find(citation.back()) != string::npos) citation.pop_back();
    if (!citation.empty() && string(".!?").find(citation.back()) == string::npos) citation += ".";
    return citation;
}

static bool is_card_start(const vector<Paragraph> &paragraphs, size_t index) {
    return card_title_match(paragraphs[index].text) || looks_like_embedded_title(paragraphs, index);
}

static vector<RawCard> separate_cards(const fs::path &docx, bool include_empty) {
    vector<Paragraph> paragraphs = parse_paragraphs(docx);
    vector<RawCard> cards;
    RawCard *current = nullptr;
    size_t index = 0;

    while (index < paragraphs.size()) {
        const Paragraph &paragraph = paragraphs[index];
        if (paragraph.text.empty()) {
            index++;
            continue;
        }

        if (is_card_start(paragraphs, index)) {
            auto [full_citation, next_index] = consume_citation(paragraphs, index + 1);
            RawCard card;
            card.card_index = static_cast<int>(cards.size()) + 1;
            card.title = start_title_from_text(paragraph.text);
            card.full_citation = full_citation;
            card.citation = short_citation(full_citation);
            cards.push_back(card);
            current = &cards.back();
            index = next_index;
            continue;
        }

        if (current) {
            current->body_paragraphs.push_back(paragraph.text);
            if (!paragraph.highlighted_text.empty()) current->highlighted_paragraphs.push_back(paragraph.highlighted_text);
        }
        index++;
    }

    if (include_empty) return cards;
    vector<RawCard> filtered;
    for (const RawCard &card : cards) {
        if (!card.body_paragraphs.empty() || !card.highlighted_paragraphs.empty()) filtered.push_back(card);
    }
    return filtered;
}

static string join(const vector<string> &items, const string &separator) {
    string out;
    for (size_t i = 0; i < items.size(); ++i) {
        if (i) out += separator;
        out += items[i];
    }
    return out;
}

static string json_escape(const string &s) {
    string out;
    for (unsigned char ch : s) {
        switch (ch) {
            case '\\': out += "\\\\"; break;
            case '"': out += "\\\""; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (ch < 0x20) {
                    char buf[7];
                    snprintf(buf, sizeof(buf), "\\u%04x", ch);
                    out += buf;
                } else {
                    out.push_back(static_cast<char>(ch));
                }
        }
    }
    return out;
}

static string raw_card_text(const RawCard &card) {
    vector<string> parts{card.title};
    if (!card.citation.empty()) {
        parts.push_back("");
        parts.push_back(card.citation);
    }
    string body = join(card.body_paragraphs, "\n\n");
    if (!body.empty()) {
        parts.push_back("");
        parts.push_back(body);
    }
    return join(parts, "\n");
}

static string highlighted_text(const RawCard &card) {
    return normalize_spacing(join(card.highlighted_paragraphs, " "));
}

static string highlighted_card_text(const RawCard &card, bool preserve_paragraphs, bool full_citations) {
    string highlights = preserve_paragraphs ? join(card.highlighted_paragraphs, "\n\n") : highlighted_text(card);
    if (highlights.empty()) return "";

    vector<string> parts{card.title};
    string citation = full_citations ? card.full_citation : card.citation;
    if (!citation.empty()) {
        parts.push_back("");
        parts.push_back(citation);
    }
    parts.push_back("");
    parts.push_back(highlights);
    return join(parts, "\n");
}

static void write_json_array(ostream &out, const vector<RawCard> &cards) {
    out << "[\n";
    for (size_t i = 0; i < cards.size(); ++i) {
        const RawCard &card = cards[i];
        out << "  {\n";
        out << "    \"card_index\": " << card.card_index << ",\n";
        out << "    \"title\": \"" << json_escape(card.title) << "\",\n";
        out << "    \"citation\": \"" << json_escape(card.citation) << "\",\n";
        out << "    \"full_citation\": \"" << json_escape(card.full_citation) << "\",\n";
        out << "    \"body_paragraphs\": [";
        for (size_t j = 0; j < card.body_paragraphs.size(); ++j) {
            if (j) out << ", ";
            out << "\"" << json_escape(card.body_paragraphs[j]) << "\"";
        }
        out << "],\n";
        out << "    \"highlighted_paragraphs\": [";
        for (size_t j = 0; j < card.highlighted_paragraphs.size(); ++j) {
            if (j) out << ", ";
            out << "\"" << json_escape(card.highlighted_paragraphs[j]) << "\"";
        }
        out << "],\n";
        out << "    \"body_text\": \"" << json_escape(join(card.body_paragraphs, "\n\n")) << "\",\n";
        out << "    \"highlighted_text\": \"" << json_escape(highlighted_text(card)) << "\",\n";
        out << "    \"raw_card\": \"" << json_escape(raw_card_text(card)) << "\"\n";
        out << "  }" << (i + 1 == cards.size() ? "\n" : ",\n");
    }
    out << "]\n";
}

static void write_jsonl(ostream &out, const vector<RawCard> &cards) {
    for (const RawCard &card : cards) {
        out << "{\"card_index\":" << card.card_index
            << ",\"title\":\"" << json_escape(card.title)
            << "\",\"citation\":\"" << json_escape(card.citation)
            << "\",\"full_citation\":\"" << json_escape(card.full_citation)
            << "\",\"body_paragraphs\":[";
        for (size_t j = 0; j < card.body_paragraphs.size(); ++j) {
            if (j) out << ",";
            out << "\"" << json_escape(card.body_paragraphs[j]) << "\"";
        }
        out << "],\"highlighted_paragraphs\":[";
        for (size_t j = 0; j < card.highlighted_paragraphs.size(); ++j) {
            if (j) out << ",";
            out << "\"" << json_escape(card.highlighted_paragraphs[j]) << "\"";
        }
        out << "],\"body_text\":\"" << json_escape(join(card.body_paragraphs, "\n\n"))
            << "\",\"highlighted_text\":\"" << json_escape(highlighted_text(card))
            << "\",\"raw_card\":\"" << json_escape(raw_card_text(card)) << "\"}\n";
    }
}

static void write_text(ostream &out, const vector<RawCard> &cards) {
    for (size_t i = 0; i < cards.size(); ++i) {
        if (i) out << "\n\n--- CARD ---\n\n";
        out << raw_card_text(cards[i]);
    }
    if (!cards.empty()) out << "\n";
}

static void write_highlighted_text(ostream &out, const vector<RawCard> &cards, bool preserve_paragraphs, bool full_citations) {
    bool wrote = false;
    for (const RawCard &card : cards) {
        string block = highlighted_card_text(card, preserve_paragraphs, full_citations);
        if (block.empty()) continue;
        if (wrote) out << "\n\n";
        out << block;
        wrote = true;
    }
    if (wrote) out << "\n";
}

struct Args {
    fs::path docx;
    fs::path output;
    bool json = false;
    bool jsonl = false;
    bool text = false;
    bool preserve_paragraphs = false;
    bool full_citations = false;
    bool include_empty = false;
};

static void usage(const char *program) {
    cerr << "Usage: " << program
         << " cards.docx [--output highlights.txt] [--json] [--jsonl] [--text]"
         << " [--preserve-paragraphs] [--full-citations] [--include-empty]\n";
}

static Args parse_args(int argc, char **argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        string arg = argv[i];
        if (arg == "-o" || arg == "--output") {
            if (i + 1 >= argc) {
                usage(argv[0]);
                exit(2);
            }
            args.output = argv[++i];
        } else if (arg == "--json") {
            args.json = true;
        } else if (arg == "--jsonl") {
            args.jsonl = true;
        } else if (arg == "--text") {
            args.text = true;
        } else if (arg == "--preserve-paragraphs") {
            args.preserve_paragraphs = true;
        } else if (arg == "--full-citations") {
            args.full_citations = true;
        } else if (arg == "--include-empty") {
            args.include_empty = true;
        } else if (arg == "-h" || arg == "--help") {
            usage(argv[0]);
            exit(0);
        } else if (args.docx.empty()) {
            args.docx = arg;
        } else {
            cerr << "Unexpected argument: " << arg << "\n";
            usage(argv[0]);
            exit(2);
        }
    }
    if (args.docx.empty()) {
        usage(argv[0]);
        exit(2);
    }
    return args;
}

int main(int argc, char **argv) {
    Args args = parse_args(argc, argv);
    vector<RawCard> cards = separate_cards(args.docx, args.include_empty);

    unique_ptr<ofstream> file;
    ostream *out = &cout;
    if (!args.output.empty()) {
        file = make_unique<ofstream>(args.output);
        if (!*file) {
            cerr << "Could not write " << args.output << "\n";
            return 1;
        }
        out = file.get();
    }

    if (args.text) write_text(*out, cards);
    else if (args.jsonl) write_jsonl(*out, cards);
    else if (args.json) write_json_array(*out, cards);
    else write_highlighted_text(*out, cards, args.preserve_paragraphs, args.full_citations);
    return 0;
}
