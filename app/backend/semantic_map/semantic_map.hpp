#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace sekret::semantic_map {

struct ArgumentChunk {
    std::string argument_id;
    int document_id = 0;
    std::string document_name;
    std::string original_text;
    std::string semantic_summary;
    std::vector<float> embedding;
    std::size_t start_offset = 0;
    std::size_t end_offset = 0;
    std::vector<std::string> citations;
    std::vector<std::string> topics;
    double confidence = 0.0;
    std::string model;
};

enum class Relationship {
    SameArgument,
    Supports,
    Attacks,
    RespondsTo,
    PartialOverlap,
    Related,
    Unrelated,
};

struct ArgumentCluster {
    std::string cluster_id;
    std::string label;
    std::vector<std::string> argument_ids;
};

struct ArgumentEdge {
    std::string from_argument_id;
    std::string to_argument_id;
    Relationship relationship = Relationship::Unrelated;
    std::string direction;
    double similarity = 0.0;
    double confidence = 0.0;
    std::string model;
};

struct SemanticMap {
    std::vector<ArgumentChunk> arguments;
    std::vector<ArgumentCluster> clusters;
    std::vector<ArgumentEdge> edges;
};

struct PrototypeOptions {
    std::size_t embedding_dimensions = 256;
    std::size_t top_k = 5;
    double cluster_similarity = 0.58;
    double novelty_similarity = 0.48;
    std::string model = "feature-hash-baseline";
};

std::vector<ArgumentChunk> chunk_document(
    int document_id,
    const std::string& document_name,
    const std::string& text,
    const PrototypeOptions& options = {}
);

SemanticMap build_map(
    std::vector<ArgumentChunk> arguments,
    const PrototypeOptions& options = {}
);

double cosine_similarity(const std::vector<float>& left, const std::vector<float>& right);

std::string relationship_name(Relationship relationship);
std::string map_to_json(const SemanticMap& map);
std::string map_to_text(const SemanticMap& map);

} // namespace sekret::semantic_map
