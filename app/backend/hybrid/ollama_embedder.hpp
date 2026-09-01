#pragma once

#include <string>
#include <stdexcept>
#include <vector>

namespace sekret::hybrid {

class EmbeddingError : public std::runtime_error {
public:
    explicit EmbeddingError(const std::string& message);
};

struct OllamaOptions {
    std::string model = "nomic-embed-text";
    std::string base_url = "http://127.0.0.1:11434";
    int timeout_seconds = 120;
};

class OllamaEmbedder {
public:
    explicit OllamaEmbedder(OllamaOptions options = {});

    const std::string& model() const;
    const std::string& base_url() const;

    std::vector<double> embed(const std::string& text) const;

private:
    OllamaOptions options_;
};

struct OllamaGenerationOptions {
    std::string model = "qwen3:4b";
    std::string base_url = "http://127.0.0.1:11434";
    int timeout_seconds = 120;
};

class OllamaGenerator {
public:
    explicit OllamaGenerator(OllamaGenerationOptions options = {});

    const std::string& model() const;
    std::string generate(const std::string& prompt) const;

private:
    OllamaGenerationOptions options_;
};

std::vector<double> parse_ollama_embedding_response(const std::string& json);

} // namespace sekret::hybrid
