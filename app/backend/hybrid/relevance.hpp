#pragma once

#include "hybrid.hpp"

#include <set>
#include <string>

namespace sekret::hybrid {

const std::set<std::string>& stopwords();
const std::set<std::string>& semantic_stopwords();

std::set<std::string> terms(const std::string& text);
std::string highlight_text(const EvidenceCard& card);

} // namespace sekret::hybrid
