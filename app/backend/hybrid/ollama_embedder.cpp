#include "ollama_embedder.hpp"

#include <arpa/inet.h>
#include <netdb.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace sekret::hybrid {
namespace {

struct ParsedUrl {
    std::string host;
    std::string port;
    std::string prefix_path;
};

std::string trim_trailing_slash(std::string value) {
    while (value.size() > 1 && value.back() == '/') {
        value.pop_back();
    }
    return value;
}

std::string env_or_default(const char* name, std::string fallback) {
    const char* value = std::getenv(name);
    if (value == nullptr || std::string(value).empty()) {
        return fallback;
    }
    return value;
}

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
                    output << "\\u00";
                    constexpr char hex[] = "0123456789abcdef";
                    output << hex[(character >> 4) & 0x0f] << hex[character & 0x0f];
                } else {
                    output << character;
                }
        }
    }
    return output.str();
}

ParsedUrl parse_http_url(std::string url) {
    url = trim_trailing_slash(url);
    constexpr const char* scheme = "http://";
    if (url.rfind(scheme, 0) != 0) {
        throw EmbeddingError("Only http:// Ollama base URLs are supported by the native client.");
    }

    auto remainder = url.substr(std::strlen(scheme));
    auto slash = remainder.find('/');
    auto authority = slash == std::string::npos ? remainder : remainder.substr(0, slash);
    auto path = slash == std::string::npos ? std::string() : remainder.substr(slash);
    auto colon = authority.rfind(':');

    ParsedUrl parsed;
    parsed.host = colon == std::string::npos ? authority : authority.substr(0, colon);
    parsed.port = colon == std::string::npos ? "80" : authority.substr(colon + 1);
    parsed.prefix_path = path;
    if (parsed.host.empty() || parsed.port.empty()) {
        throw EmbeddingError("Invalid Ollama base URL.");
    }
    return parsed;
}

std::string ollama_options_json() {
    std::ostringstream output;
    bool has_option = false;
    auto append_int_option = [&](const char* name, const char* env_name) {
        const char* value = std::getenv(env_name);
        if (value == nullptr || std::string(value).empty()) {
            return;
        }
        char* end = nullptr;
        const long parsed = std::strtol(value, &end, 10);
        if (end == value || *end != '\0') {
            return;
        }
        if (!has_option) {
            output << ",\"options\":{";
            has_option = true;
        } else {
            output << ",";
        }
        output << "\"" << name << "\":" << parsed;
    };

    append_int_option("num_gpu", "SEKRET_OLLAMA_NUM_GPU");
    if (std::getenv("SEKRET_OLLAMA_NUM_GPU") == nullptr) {
        append_int_option("num_gpu", "OLLAMA_NUM_GPU");
    }
    append_int_option("main_gpu", "SEKRET_OLLAMA_MAIN_GPU");
    if (has_option) {
        output << "}";
    }
    return output.str();
}

std::string embedding_request_json(const std::string& model, const std::string& prompt) {
    std::ostringstream output;
    output << "{\"model\":\"" << json_escape(model) << "\",";
    output << "\"prompt\":\"" << json_escape(prompt) << "\"";
    output << ollama_options_json();
    output << "}";
    return output.str();
}

int connect_socket(const ParsedUrl& url, int timeout_seconds) {
    addrinfo hints{};
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_family = AF_UNSPEC;

    addrinfo* raw_results = nullptr;
    const int status = getaddrinfo(url.host.c_str(), url.port.c_str(), &hints, &raw_results);
    if (status != 0) {
        throw EmbeddingError(std::string("Could not resolve Ollama host: ") + gai_strerror(status));
    }
    std::unique_ptr<addrinfo, decltype(&freeaddrinfo)> results(raw_results, freeaddrinfo);

    for (auto* address = results.get(); address != nullptr; address = address->ai_next) {
        const int fd = socket(address->ai_family, address->ai_socktype, address->ai_protocol);
        if (fd < 0) {
            continue;
        }

        timeval timeout{};
        timeout.tv_sec = timeout_seconds;
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));

        if (connect(fd, address->ai_addr, address->ai_addrlen) == 0) {
            return fd;
        }
        close(fd);
    }
    throw EmbeddingError("Could not reach Ollama. Is Ollama running?");
}

void send_all(int fd, const std::string& data) {
    const char* cursor = data.data();
    std::size_t remaining = data.size();
    while (remaining > 0) {
        const ssize_t sent = send(fd, cursor, remaining, 0);
        if (sent <= 0) {
            throw EmbeddingError("Failed to send request to Ollama.");
        }
        cursor += sent;
        remaining -= static_cast<std::size_t>(sent);
    }
}

std::string recv_all(int fd) {
    std::string response;
    char buffer[8192];
    while (true) {
        const ssize_t count = recv(fd, buffer, sizeof(buffer), 0);
        if (count == 0) {
            break;
        }
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw EmbeddingError("Failed while reading Ollama response.");
        }
        response.append(buffer, static_cast<std::size_t>(count));
    }
    return response;
}

std::string post_json(const ParsedUrl& url, const std::string& path, const std::string& body, int timeout_seconds) {
    const int fd = connect_socket(url, timeout_seconds);
    std::unique_ptr<int, void (*)(int*)> guard(new int(fd), [](int* value) {
        if (value != nullptr) {
            close(*value);
            delete value;
        }
    });

    const std::string request_path = url.prefix_path + path;
    std::ostringstream request;
    request << "POST " << request_path << " HTTP/1.1\r\n";
    request << "Host: " << url.host << ":" << url.port << "\r\n";
    request << "Content-Type: application/json\r\n";
    request << "Content-Length: " << body.size() << "\r\n";
    request << "Connection: close\r\n\r\n";
    request << body;

    send_all(fd, request.str());
    auto response = recv_all(fd);
    auto header_end = response.find("\r\n\r\n");
    if (header_end == std::string::npos) {
        throw EmbeddingError("Ollama returned an invalid HTTP response.");
    }

    auto status_line_end = response.find("\r\n");
    auto status_line = response.substr(0, status_line_end);
    if (status_line.find(" 200 ") == std::string::npos) {
        const auto response_body = response.substr(header_end + 4);
        throw EmbeddingError(
            "Ollama embedding request failed: " + status_line
                + (response_body.empty() ? std::string() : ": " + response_body)
        );
    }
    return response.substr(header_end + 4);
}

std::size_t skip_ws(const std::string& text, std::size_t index) {
    while (index < text.size() && std::isspace(static_cast<unsigned char>(text[index]))) {
        ++index;
    }
    return index;
}

} // namespace

EmbeddingError::EmbeddingError(const std::string& message) : std::runtime_error(message) {}

OllamaEmbedder::OllamaEmbedder(OllamaOptions options) : options_(std::move(options)) {
    options_.model = env_or_default("SEKRET_EMBED_MODEL", options_.model);
    options_.base_url = trim_trailing_slash(env_or_default("OLLAMA_BASE_URL", options_.base_url));
}

const std::string& OllamaEmbedder::model() const {
    return options_.model;
}

const std::string& OllamaEmbedder::base_url() const {
    return options_.base_url;
}

std::vector<double> OllamaEmbedder::embed(const std::string& text) const {
    const auto url = parse_http_url(options_.base_url);
    const auto body = embedding_request_json(options_.model, text);
    return parse_ollama_embedding_response(
        post_json(url, "/api/embeddings", body, options_.timeout_seconds)
    );
}

std::vector<double> parse_ollama_embedding_response(const std::string& json) {
    const auto key = json.find("\"embedding\"");
    if (key == std::string::npos) {
        throw EmbeddingError("Ollama response did not include an embedding.");
    }
    const auto array_begin = json.find('[', key);
    if (array_begin == std::string::npos) {
        throw EmbeddingError("Ollama embedding JSON was invalid.");
    }

    std::vector<double> embedding;
    std::size_t index = array_begin + 1;
    while (index < json.size()) {
        index = skip_ws(json, index);
        if (index < json.size() && json[index] == ']') {
            return embedding;
        }

        char* end = nullptr;
        const double value = std::strtod(json.c_str() + index, &end);
        if (end == json.c_str() + index) {
            throw EmbeddingError("Ollama embedding array contained a non-number.");
        }
        embedding.push_back(value);
        index = static_cast<std::size_t>(end - json.c_str());
        index = skip_ws(json, index);

        if (index < json.size() && json[index] == ',') {
            ++index;
            continue;
        }
        if (index < json.size() && json[index] == ']') {
            return embedding;
        }
        throw EmbeddingError("Ollama embedding array was malformed.");
    }
    throw EmbeddingError("Ollama embedding JSON was incomplete.");
}

} // namespace sekret::hybrid
