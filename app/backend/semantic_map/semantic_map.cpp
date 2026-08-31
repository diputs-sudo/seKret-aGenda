#include "semantic_map.hpp"

#include <algorithm>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <iomanip>
#include <numeric>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

namespace sekret::semantic_map {
namespace {

std::string lower(std::string value) {
    for (char& character : value) {
        character = static_cast<char>(std::tolower(static_cast<unsigned char>(character)));
    }
    return value;
}

std::string trim(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

std::vector<std::string> words(const std::string& text) {
    static const std::unordered_set<std::string> stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "because", "by", "for",
        "from", "has", "in", "is", "it", "of", "on", "or", "that", "the",
        "their", "this", "to", "was", "with", "will", "would", "can", "could",
    };
    std::vector<std::string> result;
    std::string current;
    for (char character : lower(text)) {
        if (std::isalnum(static_cast<unsigned char>(character))) {
            current.push_back(character);
        } else if (!current.empty()) {
            if (current.size() > 2 && !stopwords.count(current)) result.push_back(current);
            current.clear();
        }
    }
    if (current.size() > 2 && !stopwords.count(current)) result.push_back(current);
    return result;
}

std::uint64_t hash_word(const std::string& word) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (unsigned char character : word) {
        hash ^= character;
        hash *= 1099511628211ULL;
    }
    return hash;
}

std::vector<float> embed_feature_hash(const std::string& text, std::size_t dimensions) {
    std::vector<float> result(dimensions, 0.0F);
    for (const auto& word : words(text)) {
        const auto index = hash_word(word) % dimensions;
        result[index] += 1.0F;
    }
    const float norm = std::sqrt(std::inner_product(result.begin(), result.end(), result.begin(), 0.0F));
    if (norm > 0.0F) {
        for (float& value : result) value /= norm;
    }
    return result;
}

std::string make_preview(const std::string& text) {
    auto cleaned = trim(text);
    std::replace(cleaned.begin(), cleaned.end(), '\n', ' ');
    if (cleaned.size() <= 180) return cleaned;
    const auto boundary = cleaned.find_last_of(" .,:;", 180);
    return cleaned.substr(0, boundary == std::string::npos ? 180 : boundary) + "...";
}

std::vector<std::string> extract_citations(const std::string& text) {
    std::vector<std::string> citations;
    const std::regex pattern(R"(([A-Z][A-Za-z-]+(?:\s+et al\.)?\s+[‘']?\d{2,4}))");
    for (std::sregex_iterator it(text.begin(), text.end(), pattern), end; it != end; ++it) {
        citations.push_back((*it)[1].str());
    }
    return citations;
}

std::vector<std::string> extract_topics(const std::string& text) {
    std::unordered_map<std::string, int> counts;
    for (const auto& word : words(text)) ++counts[word];
    std::vector<std::pair<std::string, int>> ranked(counts.begin(), counts.end());
    std::sort(ranked.begin(), ranked.end(), [](const auto& left, const auto& right) {
        return left.second > right.second;
    });
    std::vector<std::string> topics;
    for (std::size_t index = 0; index < ranked.size() && index < 6; ++index) {
        topics.push_back(ranked[index].first);
    }
    return topics;
}

bool contains_any(const std::string& text, const std::vector<std::string>& needles) {
    const auto lowered = lower(text);
    return std::any_of(needles.begin(), needles.end(), [&](const auto& needle) {
        return lowered.find(needle) != std::string::npos;
    });
}

Relationship classify_relationship_heuristic(const ArgumentChunk& left, const ArgumentChunk& right, double similarity) {
    const auto combined = lower(left.original_text + " " + right.original_text);
    if (contains_any(combined, {"however", "but ", "instead", "fails", "undermines", "worse", "not ", "cannot"})) {
        return Relationship::Attacks;
    }
    if (contains_any(combined, {"supports", "confirms", "therefore", "shows", "reduces", "improves", "prevents"})) {
        return Relationship::Supports;
    }
    if (contains_any(left.original_text, {"respond", "answer", "reply"}) ||
        contains_any(right.original_text, {"respond", "answer", "reply"})) {
        return Relationship::RespondsTo;
    }
    if (similarity >= 0.62) return Relationship::PartialOverlap;
    if (similarity >= 0.42) return Relationship::Related;
    return Relationship::Unrelated;
}

std::string json_escape(const std::string& value) {
    std::ostringstream output;
    for (unsigned char character : value) {
        switch (character) {
            case '"': output << "\\\""; break;
            case '\\': output << "\\\\"; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default: output << character; break;
        }
    }
    return output.str();
}

} // namespace

double cosine_similarity(const std::vector<float>& left, const std::vector<float>& right) {
    if (left.empty() || left.size() != right.size()) return 0.0;
    double dot = 0.0;
    double left_norm = 0.0;
    double right_norm = 0.0;
    for (std::size_t index = 0; index < left.size(); ++index) {
        dot += left[index] * right[index];
        left_norm += left[index] * left[index];
        right_norm += right[index] * right[index];
    }
    if (left_norm == 0.0 || right_norm == 0.0) return 0.0;
    return dot / std::sqrt(left_norm * right_norm);
}

std::vector<ArgumentChunk> chunk_document(int document_id, const std::string& document_name, const std::string& text, const PrototypeOptions& options) {
    std::vector<ArgumentChunk> chunks;
    std::size_t paragraph_start = 0;
    while (paragraph_start < text.size()) {
        const auto separator = text.find("\n\n", paragraph_start);
        const auto paragraph_end = separator == std::string::npos ? text.size() : separator;
        const auto paragraph = trim(text.substr(paragraph_start, paragraph_end - paragraph_start));
        if (!paragraph.empty()) {
            ArgumentChunk chunk;
            chunk.argument_id = "arg-" + std::to_string(document_id) + "-" + std::to_string(chunks.size() + 1);
            chunk.document_id = document_id;
            chunk.document_name = document_name;
            chunk.original_text = paragraph;
            chunk.semantic_summary = make_preview(paragraph);
            chunk.embedding = embed_feature_hash(chunk.semantic_summary, options.embedding_dimensions);
            chunk.start_offset = paragraph_start + text.substr(paragraph_start, paragraph_end - paragraph_start).find(paragraph);
            chunk.end_offset = chunk.start_offset + paragraph.size();
            chunk.citations = extract_citations(paragraph);
            chunk.topics = extract_topics(paragraph);
            chunk.confidence = 0.0;
            chunk.model = options.model;
            chunks.push_back(std::move(chunk));
        }
        if (separator == std::string::npos) break;
        paragraph_start = separator + 2;
    }
    return chunks;
}

SemanticMap build_map(std::vector<ArgumentChunk> arguments, const PrototypeOptions& options) {
    SemanticMap map;
    map.arguments = std::move(arguments);
    for (auto& argument : map.arguments) {
        if (argument.embedding.empty()) argument.embedding = embed_feature_hash(argument.semantic_summary, options.embedding_dimensions);
    }

    for (std::size_t index = 0; index < map.arguments.size(); ++index) {
        const auto& argument = map.arguments[index];
        std::string best_cluster;
        double best_similarity = 0.0;
        for (const auto& cluster : map.clusters) {
            for (const auto& member_id : cluster.argument_ids) {
                const auto member = std::find_if(map.arguments.begin(), map.arguments.end(), [&](const auto& candidate) {
                    return candidate.argument_id == member_id;
                });
                if (member == map.arguments.end()) continue;
                const auto similarity = cosine_similarity(argument.embedding, member->embedding);
                if (similarity > best_similarity) {
                    best_similarity = similarity;
                    best_cluster = cluster.cluster_id;
                }
            }
        }
        if (best_similarity >= options.cluster_similarity) {
            auto cluster = std::find_if(map.clusters.begin(), map.clusters.end(), [&](const auto& candidate) {
                return candidate.cluster_id == best_cluster;
            });
            cluster->argument_ids.push_back(argument.argument_id);
        } else {
            map.clusters.push_back({"cluster-" + std::to_string(map.clusters.size() + 1), make_preview(argument.semantic_summary), {argument.argument_id}});
        }

        std::vector<std::pair<double, std::size_t>> candidates;
        for (std::size_t prior = 0; prior < index; ++prior) {
            candidates.emplace_back(cosine_similarity(argument.embedding, map.arguments[prior].embedding), prior);
        }
        std::sort(candidates.rbegin(), candidates.rend());
        const auto candidate_count = std::min(options.top_k, candidates.size());
        for (std::size_t candidate_index = 0; candidate_index < candidate_count; ++candidate_index) {
            const auto [similarity, prior] = candidates[candidate_index];
            if (similarity < options.novelty_similarity) continue;
            const auto relationship = classify_relationship_heuristic(map.arguments[prior], argument, similarity);
            if (relationship == Relationship::Unrelated) continue;
            map.edges.push_back({map.arguments[prior].argument_id, argument.argument_id, relationship, "prior_to_new", similarity, 0.0, "heuristic-baseline"});
        }
    }
    return map;
}

std::string relationship_name(Relationship relationship) {
    switch (relationship) {
        case Relationship::SameArgument: return "SAME_ARGUMENT";
        case Relationship::Supports: return "SUPPORTS";
        case Relationship::Attacks: return "ATTACKS";
        case Relationship::RespondsTo: return "RESPONDS_TO";
        case Relationship::PartialOverlap: return "PARTIAL_OVERLAP";
        case Relationship::Related: return "RELATED";
        case Relationship::Unrelated: return "UNRELATED";
    }
    return "UNRELATED";
}

std::string map_to_json(const SemanticMap& map) {
    std::ostringstream output;
    output << "{\"arguments\":[";
    for (std::size_t index = 0; index < map.arguments.size(); ++index) {
        if (index) output << ",";
        const auto& argument = map.arguments[index];
        output << "{\"argumentId\":\"" << json_escape(argument.argument_id) << "\",\"documentId\":" << argument.document_id
               << ",\"documentName\":\"" << json_escape(argument.document_name) << "\",\"originalText\":\"" << json_escape(argument.original_text)
               << "\",\"semanticSummary\":\"" << json_escape(argument.semantic_summary) << "\",\"startOffset\":" << argument.start_offset
               << ",\"endOffset\":" << argument.end_offset << ",\"citations\":[";
        for (std::size_t item = 0; item < argument.citations.size(); ++item) { if (item) output << ","; output << "\"" << json_escape(argument.citations[item]) << "\""; }
        output << "],\"topics\":[";
        for (std::size_t item = 0; item < argument.topics.size(); ++item) { if (item) output << ","; output << "\"" << json_escape(argument.topics[item]) << "\""; }
        output << "],\"confidence\":" << argument.confidence << ",\"model\":\"" << json_escape(argument.model) << "\"}";
    }
    output << "],\"clusters\":[";
    for (std::size_t index = 0; index < map.clusters.size(); ++index) {
        if (index) output << ",";
        const auto& cluster = map.clusters[index];
        output << "{\"clusterId\":\"" << cluster.cluster_id << "\",\"label\":\"" << json_escape(cluster.label) << "\",\"argumentIds\":[";
        for (std::size_t item = 0; item < cluster.argument_ids.size(); ++item) { if (item) output << ","; output << "\"" << cluster.argument_ids[item] << "\""; }
        output << "]}";
    }
    output << "],\"edges\":[";
    for (std::size_t index = 0; index < map.edges.size(); ++index) {
        if (index) output << ",";
        const auto& edge = map.edges[index];
        output << "{\"from\":\"" << edge.from_argument_id << "\",\"to\":\"" << edge.to_argument_id << "\",\"relationship\":\"" << relationship_name(edge.relationship)
               << "\",\"direction\":\"" << edge.direction << "\",\"similarity\":" << edge.similarity << ",\"confidence\":" << edge.confidence << ",\"model\":\"" << edge.model << "\"}";
    }
    output << "]}";
    return output.str();
}

std::string map_to_text(const SemanticMap& map) {
    std::ostringstream output;
    output << "ARGUMENTS\n";
    for (const auto& argument : map.arguments) {
        output << "- " << argument.argument_id << " [" << argument.document_name << "] " << argument.semantic_summary << "\n";
        output << "  source: " << argument.start_offset << "-" << argument.end_offset << "\n";
    }
    output << "\nCLUSTERS\n";
    for (const auto& cluster : map.clusters) output << "- " << cluster.cluster_id << ": " << cluster.label << " (" << cluster.argument_ids.size() << " arguments)\n";
    output << "\nRELATIONSHIPS\n";
    for (const auto& edge : map.edges) output << "- " << edge.from_argument_id << " --" << relationship_name(edge.relationship) << "--> " << edge.to_argument_id << " (" << std::fixed << std::setprecision(2) << edge.similarity << ")\n";
    return output.str();
}

} // namespace sekret::semantic_map
