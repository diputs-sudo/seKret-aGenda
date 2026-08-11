#include "relevance.hpp"

#include <cctype>
#include <sstream>
#include <vector>

namespace sekret::hybrid {
namespace {

bool is_term_character(char character) {
    return std::isalnum(static_cast<unsigned char>(character)) || character == '-';
}

std::string lower_copy(const std::string& text) {
    std::string lowered;
    lowered.reserve(text.size());
    for (const unsigned char character : text) {
        lowered.push_back(static_cast<char>(std::tolower(character)));
    }
    return lowered;
}

std::vector<std::string> tokenize_terms(const std::string& text) {
    std::vector<std::string> tokens;
    std::string current;
    for (char character : text) {
        if (is_term_character(character)) {
            current.push_back(character);
            continue;
        }
        if (!current.empty()) {
            tokens.push_back(lower_copy(current));
            current.clear();
        }
    }
    if (!current.empty()) {
        tokens.push_back(lower_copy(current));
    }
    return tokens;
}

} // namespace

const std::set<std::string>& stopwords() {
    static const std::set<std::string> words = {
        "a", "an", "and", "are", "because", "by", "for", "from", "how",
        "in", "is", "it", "of", "on", "or", "says", "that", "the",
        "this", "to", "with", "what", "why",
    };
    return words;
}

const std::set<std::string>& semantic_stopwords() {
    static const std::set<std::string> words = {
        "able", "become", "becomes", "became", "do", "does", "did", "doing",
        "get", "gets", "got", "give", "gives", "given", "make", "makes",
        "made", "provide", "provides", "provided", "show", "shows",
        "showing", "use", "uses", "used", "using",
    };
    return words;
}

std::set<std::string> terms(const std::string& text) {
    std::set<std::string> result;
    for (const auto& token : tokenize_terms(text)) {
        if (stopwords().count(token) != 0 || semantic_stopwords().count(token) != 0) {
            continue;
        }
        result.insert(token);
    }
    return result;
}

std::string highlight_text(const EvidenceCard& card) {
    std::ostringstream output;
    for (const auto& highlight : card.highlights) {
        if (highlight.text.empty()) {
            continue;
        }
        if (output.tellp() > 0) {
            output << ' ';
        }
        output << highlight.text;
    }
    return output.str();
}

} // namespace sekret::hybrid
