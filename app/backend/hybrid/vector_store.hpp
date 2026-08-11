#pragma once

#include "ollama_embedder.hpp"
#include "sqlite_store.hpp"

#include <memory>
#include <string>
#include <vector>

namespace sekret::hybrid {

constexpr const char* kFastVectorKind = "fast";
constexpr const char* kDeepVectorKind = "deep";
constexpr const char* kNativeVectorTable = "native_card_vectors";

class VectorStore {
public:
    virtual ~VectorStore() = default;

    virtual bool has_vectors(const std::string& embedding_kind, const std::string& embedding_model) const = 0;
    virtual std::vector<RetrievedCard> search(
        const std::vector<double>& query_embedding,
        const std::string& embedding_kind,
        const std::string& embedding_model,
        std::size_t limit
    ) const = 0;
};

class NativeSqliteVectorStore final : public VectorStore {
public:
    explicit NativeSqliteVectorStore(std::string db_path);

    bool has_vectors(const std::string& embedding_kind, const std::string& embedding_model) const override;
    std::vector<RetrievedCard> search(
        const std::vector<double>& query_embedding,
        const std::string& embedding_kind,
        const std::string& embedding_model,
        std::size_t limit
    ) const override;

private:
    std::string db_path_;
};

std::vector<double> parse_vector_json(const std::string& json);
double cosine_similarity(const std::vector<double>& left, const std::vector<double>& right);

} // namespace sekret::hybrid
