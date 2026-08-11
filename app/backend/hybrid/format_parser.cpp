#include "format_parser.hpp"

#include <algorithm>
#include <cctype>
#include <regex>
#include <sstream>

namespace sekret::hybrid {
namespace {

struct GrammarLine {
    std::string raw;
    std::vector<std::string> fields;
    bool optional = false;
    bool repeated = false;
};

std::string trim(const std::string& text) {
    auto begin = text.begin();
    while (begin != text.end() && std::isspace(static_cast<unsigned char>(*begin))) {
        ++begin;
    }
    auto end = text.end();
    while (end != begin && std::isspace(static_cast<unsigned char>(*(end - 1)))) {
        --end;
    }
    return std::string(begin, end);
}

std::vector<std::string> blocks_from_text(const std::string& text) {
    std::vector<std::string> blocks;
    std::istringstream input(text);
    std::ostringstream current;
    std::string line;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            const auto block = trim(current.str());
            if (!block.empty()) {
                blocks.push_back(block);
            }
            current.str("");
            current.clear();
            continue;
        }
        if (current.tellp() > 0) {
            current << "\n";
        }
        current << line;
    }
    const auto block = trim(current.str());
    if (!block.empty()) {
        blocks.push_back(block);
    }
    return blocks;
}

std::vector<std::string> fields_for_line(const std::string& line) {
    static const std::regex field_re(R"(\[([A-Za-z_][A-Za-z0-9_-]*)(?::[A-Za-z][A-Za-z0-9_-]*)?\])");
    std::vector<std::string> fields;
    for (std::sregex_iterator it(line.begin(), line.end(), field_re), end; it != end; ++it) {
        fields.push_back((*it)[1].str());
    }
    return fields;
}

std::vector<GrammarLine> parse_grammar_lines(const std::string& grammar_source) {
    std::vector<GrammarLine> lines;
    std::istringstream input(grammar_source);
    std::string line;
    bool in_defaults = false;
    while (std::getline(input, line)) {
        auto value = trim(line);
        if (value.empty() || value.rfind("#", 0) == 0 || value.rfind("//", 0) == 0) {
            continue;
        }
        if (value.rfind("@defaults", 0) == 0) {
            in_defaults = true;
            continue;
        }
        if (in_defaults) {
            if (value == "}") {
                in_defaults = false;
            }
            continue;
        }
        if (value.rfind("@", 0) == 0) {
            continue;
        }
        GrammarLine parsed;
        parsed.raw = value;
        parsed.fields = fields_for_line(value);
        if (!value.empty()) {
            const char quantifier = value.back();
            parsed.optional = quantifier == '?' || quantifier == '*';
            parsed.repeated = quantifier == '*' || quantifier == '+';
        }
        if (!parsed.fields.empty()) {
            lines.push_back(parsed);
        }
    }
    return lines;
}

std::map<std::string, std::string> parse_defaults(const std::string& grammar_source) {
    std::map<std::string, std::string> defaults;
    std::istringstream input(grammar_source);
    std::string line;
    bool in_defaults = false;
    while (std::getline(input, line)) {
        auto value = trim(line);
        if (value.rfind("@defaults", 0) == 0) {
            in_defaults = true;
            continue;
        }
        if (!in_defaults) {
            continue;
        }
        if (value == "}") {
            break;
        }
        const auto colon = value.find(':');
        if (colon == std::string::npos) {
            continue;
        }
        defaults[trim(value.substr(0, colon))] = trim(value.substr(colon + 1));
    }
    return defaults;
}

bool line_has_field(const GrammarLine& line, const std::string& field) {
    return std::find(line.fields.begin(), line.fields.end(), field) != line.fields.end();
}

std::regex line_regex(const GrammarLine& line) {
    std::string pattern = "^";
    std::size_t cursor = 0;
    static const std::regex field_re(R"(\[([A-Za-z_][A-Za-z0-9_-]*)(?::[A-Za-z][A-Za-z0-9_-]*)?\][?*+]?)");
    for (std::sregex_iterator it(line.raw.begin(), line.raw.end(), field_re), end; it != end; ++it) {
        const auto match = *it;
        auto literal = line.raw.substr(cursor, static_cast<std::size_t>(match.position()) - cursor);
        literal = std::regex_replace(literal, std::regex(R"([.^$|()\\{}*+?\[\]])"), R"(\$&)");
        pattern += literal;
        pattern += "(.+?)";
        cursor = static_cast<std::size_t>(match.position() + match.length());
    }
    auto tail = line.raw.substr(cursor);
    while (!tail.empty() && (tail.back() == '?' || tail.back() == '*' || tail.back() == '+')) {
        tail.pop_back();
    }
    tail = std::regex_replace(tail, std::regex(R"([.^$|()\\{}*+?\[\]])"), R"(\$&)");
    pattern += tail;
    pattern += "$";
    return std::regex(pattern, std::regex::icase);
}

bool match_line_fields(const GrammarLine& grammar, const std::string& block, std::map<std::string, std::string>& fields) {
    std::smatch match;
    const auto regex = line_regex(grammar);
    if (!std::regex_match(block, match, regex)) {
        if (grammar.fields.size() == 1) {
            fields[grammar.fields.front()] = block;
            return true;
        }
        return false;
    }
    for (std::size_t index = 0; index < grammar.fields.size(); ++index) {
        if (index + 1 < match.size()) {
            fields[grammar.fields[index]] = trim(match[index + 1].str());
        }
    }
    return true;
}

} // namespace

DslParseResult parse_evidence_dsl(const std::string& text, const std::string& grammar_source) {
    DslParseResult result;
    result.defaults = parse_defaults(grammar_source);
    const auto grammar = parse_grammar_lines(grammar_source);
    const auto blocks = blocks_from_text(text);
    auto boundary_it = std::find_if(grammar.begin(), grammar.end(), [](const auto& line) {
        return line_has_field(line, "card");
    });
    if (boundary_it == grammar.end()) {
        result.diagnostics.push_back("Grammar must include a [card] boundary.");
        return result;
    }

    for (std::size_t index = 0; index < blocks.size();) {
        std::map<std::string, std::string> fields = result.defaults;
        if (!match_line_fields(*boundary_it, blocks[index], fields)) {
            ++index;
            continue;
        }

        ParsedDslCard card;
        card.block_start = index;
        card.fields = fields;
        ++index;

        for (const auto& line : grammar) {
            if (&line == &(*boundary_it)) {
                continue;
            }
            if (line_has_field(line, "content") && line.repeated) {
                std::ostringstream content;
                while (index < blocks.size()) {
                    std::map<std::string, std::string> probe;
                    if (match_line_fields(*boundary_it, blocks[index], probe)) {
                        break;
                    }
                    if (content.tellp() > 0) {
                        content << "\n\n";
                    }
                    content << blocks[index];
                    ++index;
                }
                card.fields["content"] = content.str();
                continue;
            }
            if (index >= blocks.size()) {
                if (!line.optional) {
                    result.diagnostics.push_back("Missing required DSL line near card " + card.fields["card"]);
                }
                continue;
            }
            std::map<std::string, std::string> parsed;
            if (match_line_fields(line, blocks[index], parsed)) {
                for (const auto& [key, value] : parsed) {
                    card.fields[key] = value;
                }
                ++index;
            } else if (!line.optional) {
                result.diagnostics.push_back("Could not match DSL line near card " + card.fields["card"]);
            }
        }
        card.block_end = index == 0 ? 0 : index - 1;
        result.cards.push_back(std::move(card));
    }
    return result;
}

} // namespace sekret::hybrid
