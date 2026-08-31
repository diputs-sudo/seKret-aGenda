#include "semantic_map.hpp"

#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace {

std::string read_file(const std::string& path) {
    if (path == "-") {
        std::ostringstream contents;
        contents << std::cin.rdbuf();
        return contents.str();
    }
    std::ifstream input(path);
    if (!input) throw std::runtime_error("could not open " + path);
    std::ostringstream contents;
    contents << input.rdbuf();
    return contents.str();
}

std::vector<std::vector<float>> read_embeddings(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("could not open embedding file " + path);
    std::vector<std::vector<float>> result;
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream values(line);
        std::vector<float> vector;
        float value = 0.0F;
        while (values >> value) vector.push_back(value);
        if (!vector.empty()) result.push_back(std::move(vector));
    }
    return result;
}

} // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: semantic_map <text-file|-> [--json] [--embeddings-file path]\n";
        return 2;
    }
    try {
        const auto text = read_file(argv[1]);
        sekret::semantic_map::PrototypeOptions options;
        bool json = false;
        std::string embedding_file;
        for (int index = 2; index < argc; ++index) {
            const std::string argument = argv[index];
            if (argument == "--json") {
                json = true;
            } else if (argument == "--embeddings-file" && index + 1 < argc) {
                embedding_file = argv[++index];
            } else {
                throw std::runtime_error("unknown argument: " + argument);
            }
        }
        auto chunks = sekret::semantic_map::chunk_document(1, argv[1], text, options);
        if (!embedding_file.empty()) {
            const auto embeddings = read_embeddings(embedding_file);
            if (embeddings.size() != chunks.size()) {
                throw std::runtime_error("embedding count mismatch: expected " + std::to_string(chunks.size()) + ", received " + std::to_string(embeddings.size()));
            }
            for (std::size_t index = 0; index < chunks.size(); ++index) {
                chunks[index].embedding = embeddings[index];
                chunks[index].model = "external-embedding";
            }
        }
        const auto map = sekret::semantic_map::build_map(std::move(chunks), options);
        if (json) {
            std::cout << sekret::semantic_map::map_to_json(map) << "\n";
        } else {
            std::cout << sekret::semantic_map::map_to_text(map);
        }
    } catch (const std::exception& error) {
        std::cerr << "semantic_map: " << error.what() << "\n";
        return 1;
    }
    return 0;
}
