#include "semantic_map.hpp"

#include <iostream>
#include <string>

namespace {

int expect(bool condition, const std::string& message) {
    if (condition) return 0;
    std::cerr << "FAIL: " << message << "\n";
    return 1;
}

} // namespace

int main() {
    using namespace sekret::semantic_map;
    const std::string first =
        "Since legalization of sports betting, illegal markets have dropped by a third. Cohen '25 explains that illegal sportsbook share fell from 36 percent to 24 percent.";
    const std::string second =
        "State regulation reduces illegal sports betting markets. The market share of illegal sportsbooks fell from 36 percent to 24 percent, according to Cohen '25.";
    const std::string third =
        "Federal sports-betting regulation violates federalism and state sovereignty. States should retain authority to experiment with consumer protection.";
    const auto first_chunks = chunk_document(1, "messy-one.txt", first + "\n\n" + third);
    const auto second_chunks = chunk_document(2, "messy-two.txt", second);
    std::vector<ArgumentChunk> all = first_chunks;
    all.insert(all.end(), second_chunks.begin(), second_chunks.end());
    const auto map = build_map(std::move(all));

    int failures = 0;
    failures += expect(map.arguments.size() == 3, "paragraphs should become provenance-preserving chunks");
    failures += expect(map.arguments[0].start_offset == 0, "first chunk should start at source offset zero");
    failures += expect(map.arguments[0].end_offset > map.arguments[0].start_offset, "chunk should preserve source span");
    failures += expect(!map.arguments[0].citations.empty(), "citation should be extracted without requiring formatting");
    failures += expect(map.clusters.size() == 2, "similar market arguments should cluster while federalism remains novel");
    failures += expect(!map.edges.empty(), "nearest-neighbor candidate retrieval should produce a relationship");
    failures += expect(map_to_json(map).find("originalText") != std::string::npos, "JSON must retain original source text");
    failures += expect(map_to_json(map).find("startOffset") != std::string::npos, "JSON must retain provenance offsets");
    return failures;
}
