#include "hybrid.hpp"

#include <cstdlib>
#include <cstring>
#include <exception>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

namespace sekret::hybrid {
namespace {

std::string json_escape(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
        switch (character) {
            case '"':
                output << "\\\"";
                break;
            case '\\':
                output << "\\\\";
                break;
            case '\b':
                output << "\\b";
                break;
            case '\f':
                output << "\\f";
                break;
            case '\n':
                output << "\\n";
                break;
            case '\r':
                output << "\\r";
                break;
            case '\t':
                output << "\\t";
                break;
            default:
                if (character < 0x20) {
                    output << "\\u";
                    output << "00";
                    constexpr char hex[] = "0123456789abcdef";
                    output << hex[(character >> 4) & 0x0f];
                    output << hex[character & 0x0f];
                } else {
                    output << character;
                }
                break;
        }
    }
    return output.str();
}

char* copy_c_string(const std::string& value) {
    const auto byte_count = value.size() + 1;
    auto* buffer = static_cast<char*>(std::malloc(byte_count));
    if (buffer == nullptr) {
        return nullptr;
    }
    std::memcpy(buffer, value.c_str(), byte_count);
    return buffer;
}

std::string response_to_json(const HybridSearchResponse& response) {
    std::ostringstream output;
    output << "{";
    output << "\"cards\":[],";
    output << "\"sourceStatus\":\"" << json_escape(response.source_status) << "\",";
    output << "\"mainClaim\":\"" << json_escape(response.main_claim) << "\",";
    output << "\"uncertainty\":";
    if (response.uncertainty.has_value()) {
        output << "\"" << json_escape(*response.uncertainty) << "\"";
    } else {
        output << "null";
    }
    output << "}";
    return output.str();
}

} // namespace

class HybridEngine::Impl {
public:
    explicit Impl(HybridEngineOptions options) : options_(std::move(options)) {
        if (options_.db_path.empty()) {
            throw std::invalid_argument("HybridEngine requires a SQLite database path.");
        }
    }

    HybridSearchResponse search(const HybridSearchRequest& request) const {
        HybridSearchResponse response;
        response.source_status = "ANALYSIS ONLY";
        response.main_claim = "C++ hybrid backend is compiled but retrieval is not implemented yet.";
        response.uncertainty =
            request.query.empty()
                ? "No query was provided."
                : "The C++ hybrid translation is being added one module at a time.";
        return response;
    }

private:
    HybridEngineOptions options_;
};

HybridEngine::HybridEngine(HybridEngineOptions options)
    : impl_(std::make_unique<Impl>(std::move(options))) {}

HybridEngine::~HybridEngine() = default;

HybridEngine::HybridEngine(HybridEngine&&) noexcept = default;

HybridEngine& HybridEngine::operator=(HybridEngine&&) noexcept = default;

HybridSearchResponse HybridEngine::search(const HybridSearchRequest& request) const {
    return impl_->search(request);
}

} // namespace sekret::hybrid

extern "C" {

SekretHybridJsonResult sekret_hybrid_search_json(
    const char* db_path,
    const char* chroma_path,
    const char* request_json
) {
    try {
        if (db_path == nullptr || request_json == nullptr) {
            throw std::invalid_argument("db_path and request_json are required.");
        }

        sekret::hybrid::HybridEngine engine({
            std::string(db_path),
            chroma_path == nullptr ? std::string() : std::string(chroma_path),
        });
        sekret::hybrid::HybridSearchRequest request;
        request.query = request_json;

        const auto response = engine.search(request);
        return {
            sekret::hybrid::copy_c_string(sekret::hybrid::response_to_json(response)),
            nullptr,
        };
    } catch (const std::exception& error) {
        return {nullptr, sekret::hybrid::copy_c_string(error.what())};
    } catch (...) {
        return {
            nullptr,
            sekret::hybrid::copy_c_string("Unknown C++ hybrid backend error."),
        };
    }
}

void sekret_hybrid_free_string(char* value) {
    std::free(value);
}

} // extern "C"
