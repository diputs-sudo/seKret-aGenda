#include "argument_builder.hpp"

#include "relevance.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <sstream>

namespace sekret::hybrid {
namespace {

double card_score(const RerankedCard& card) {
    if (card.assessment.relevance_score != 0.0) {
        return card.assessment.relevance_score;
    }
    if (card.card.reranker_score != 0.0) {
        return card.card.reranker_score;
    }
    return card.card.retrieval_score;
}

std::set<std::string> card_terms(const RerankedCard& card) {
    std::ostringstream text;
    text << card.card.section << ' ' << card.card.tag << ' ' << highlight_text(card.card)
         << ' ' << (card.card.body.empty() ? card.card.body_preview : card.card.body);
    auto mechanism = parse_mechanism(text.str());
    auto values = terms(text.str());
    values.insert(mechanism.object_groups.begin(), mechanism.object_groups.end());
    values.insert(mechanism.phrase_concepts.begin(), mechanism.phrase_concepts.end());
    return values;
}

std::set<std::string> phrase_terms(const RerankedCard& card) {
    std::set<std::string> phrases;
    for (const auto& term : card_terms(card)) {
        if (term.find('_') != std::string::npos) {
            phrases.insert(term);
        }
    }
    return phrases;
}

double similarity(const RerankedCard& left, const RerankedCard& right) {
    const auto left_terms = card_terms(left);
    const auto right_terms = card_terms(right);
    if (left_terms.empty() || right_terms.empty()) {
        return 0.0;
    }
    std::size_t overlap = 0;
    for (const auto& term : left_terms) {
        if (right_terms.count(term) != 0) {
            ++overlap;
        }
    }
    std::set<std::string> union_terms = left_terms;
    union_terms.insert(right_terms.begin(), right_terms.end());
    const double lexical = static_cast<double>(overlap) / static_cast<double>(union_terms.size());
    const bool same_author = left.card.author == right.card.author && left.card.author.has_value();
    const bool same_document = !left.card.document_name.empty() && left.card.document_name == right.card.document_name;
    const bool same_section = !left.card.section.empty() && left.card.section == right.card.section;
    const auto left_phrases = phrase_terms(left);
    const auto right_phrases = phrase_terms(right);
    bool shared_phrase = false;
    for (const auto& phrase : left_phrases) {
        if (right_phrases.count(phrase) != 0) {
            shared_phrase = true;
            break;
        }
    }
    return std::min(
        1.0,
        lexical
            + (same_author ? 0.15 : 0.0)
            + (same_document ? 0.1 : 0.0)
            + (same_section && shared_phrase ? 0.18 : 0.0)
    );
}

double cluster_similarity(const RerankedCard& card, const std::vector<RerankedCard>& group) {
    double best = 0.0;
    for (const auto& other : group) {
        best = std::max(best, similarity(card, other));
    }
    return best;
}

std::string cluster_thesis(const std::vector<RerankedCard>& cards) {
    for (const auto& card : cards) {
        if (!card.card.tag.empty()) {
            return card.card.tag;
        }
    }
    return "Retrieved evidence supports a related response.";
}

std::vector<std::string> supporting_claims(const std::vector<RerankedCard>& cards) {
    std::vector<std::string> claims;
    for (const auto& card : cards) {
        if (card.card.tag.empty()) {
            continue;
        }
        if (std::find(claims.begin(), claims.end(), card.card.tag) == claims.end()) {
            claims.push_back(card.card.tag);
        }
    }
    return claims;
}

std::set<std::string> card_like_terms(const std::string& text) {
    auto mechanism = parse_mechanism(text);
    auto values = terms(text);
    values.insert(mechanism.object_groups.begin(), mechanism.object_groups.end());
    values.insert(mechanism.phrase_concepts.begin(), mechanism.phrase_concepts.end());
    for (const auto& generic : mechanism.generic_terms) {
        values.erase(generic);
    }
    return values;
}

double query_cluster_bonus(const std::vector<RerankedCard>& cards, const QueryIntent* intent) {
    if (intent == nullptr) {
        return 0.0;
    }
    const auto query_terms = card_like_terms(retrieval_text(*intent));
    if (query_terms.empty()) {
        return 0.0;
    }
    std::set<std::string> cluster_terms;
    for (const auto& card : cards) {
        auto values = card_terms(card);
        cluster_terms.insert(values.begin(), values.end());
    }
    std::size_t overlap = 0;
    for (const auto& term : query_terms) {
        if (cluster_terms.count(term) != 0) {
            ++overlap;
        }
    }
    return std::min(0.22, (static_cast<double>(overlap) / static_cast<double>(query_terms.size())) * 0.22);
}

double cluster_confidence(const std::vector<RerankedCard>& cards, const QueryIntent* intent) {
    if (cards.empty()) {
        return 0.0;
    }
    std::vector<double> scores;
    for (const auto& card : cards) {
        scores.push_back(card_score(card));
    }
    std::sort(scores.begin(), scores.end(), std::greater<>());
    scores.resize(std::min<std::size_t>(scores.size(), 3));
    double sum = 0.0;
    for (double score : scores) {
        sum += score;
    }
    const double average = sum / static_cast<double>(scores.size());
    const double size_bonus = std::min(0.12, 0.035 * static_cast<double>(cards.size() > 0 ? cards.size() - 1 : 0));
    std::set<std::string> authors;
    std::set<std::string> documents;
    for (const auto& card : cards) {
        authors.insert(card.card.author.value_or(card.card.card_name));
        documents.insert(card.card.document_name);
    }
    const double diversity_bonus = std::min(
        0.08,
        0.02 * static_cast<double>(authors.size() > 0 ? authors.size() - 1 : 0)
            + 0.02 * static_cast<double>(documents.size() > 0 ? documents.size() - 1 : 0)
    );
    return std::round(std::min(1.0, average + size_bonus + diversity_bonus + query_cluster_bonus(cards, intent)) * 1000.0) / 1000.0;
}

double mmr_score(
    const RerankedCard& card,
    const std::vector<RerankedCard>& selected,
    double lambda_relevance,
    const std::map<std::string, double>& cluster_score_by_card
) {
    const auto id = card.card.card_id.empty() ? card.card.id : card.card.card_id;
    const double relevance = card_score(card) * 0.6 + cluster_score_by_card.at(id) * 0.4;
    double redundancy = 0.0;
    for (const auto& other : selected) {
        redundancy = std::max(redundancy, similarity(card, other));
    }
    return lambda_relevance * relevance - (1.0 - lambda_relevance) * redundancy;
}

std::vector<std::string> warrants(const std::vector<RerankedCard>& cards) {
    std::vector<std::string> result;
    for (const auto& card : cards) {
        std::string text;
        if (!card.card.highlights.empty()) {
            text = card.card.highlights.front().text;
        }
        if (text.empty()) {
            text = card.card.tag;
        }
        if (!text.empty() && std::find(result.begin(), result.end(), text) == result.end()) {
            result.push_back(text);
        }
    }
    return result;
}

std::string main_claim(const QueryIntent& intent, const ArgumentCluster* cluster, const std::vector<std::string>& warrants) {
    if (cluster != nullptr) {
        return cluster->thesis;
    }
    if (intent.opponent_claim.has_value()) {
        return "No backfile evidence passed the gate for: " + *intent.opponent_claim;
    }
    if (!warrants.empty()) {
        return warrants.front();
    }
    return "No backfile evidence passed the gate.";
}

} // namespace

ArgumentBundle ArgumentBuilder::build(
    const QueryIntent& intent,
    const std::vector<RerankedCard>& cards,
    std::size_t limit
) const {
    auto clusters = cluster_arguments(cards, &intent);
    auto selected = select_diverse_cards(clusters, limit);
    auto bundle_warrants = warrants(selected);
    const auto* main_cluster = clusters.empty() ? nullptr : &clusters.front();

    ArgumentBundle bundle;
    bundle.query = intent.raw_query;
    bundle.opponent_claim = intent.opponent_claim;
    bundle.main_claim = main_claim(intent, main_cluster, bundle_warrants);
    bundle.warrants = std::move(bundle_warrants);
    bundle.cards = std::move(selected);
    bundle.clusters = std::move(clusters);
    bundle.source_status = bundle.cards.empty() ? "ANALYSIS ONLY" : "BACKFILE-SOURCED";
    if (bundle.cards.empty()) {
        bundle.uncertainty = "No retrieved cards passed the relevance gate.";
    }
    return bundle;
}

std::vector<ArgumentCluster> cluster_arguments(
    const std::vector<RerankedCard>& cards,
    const QueryIntent* intent
) {
    std::vector<std::vector<RerankedCard>> groups;
    for (const auto& card : cards) {
        bool placed = false;
        for (auto& group : groups) {
            if (cluster_similarity(card, group) >= 0.22) {
                group.push_back(card);
                placed = true;
                break;
            }
        }
        if (!placed) {
            groups.push_back({card});
        }
    }

    std::vector<ArgumentCluster> clusters;
    for (std::size_t index = 0; index < groups.size(); ++index) {
        auto group = groups[index];
        std::sort(group.begin(), group.end(), [](const RerankedCard& left, const RerankedCard& right) {
            return card_score(left) > card_score(right);
        });
        ArgumentCluster cluster;
        cluster.id = "cluster-" + std::to_string(index + 1);
        cluster.section = group.empty() ? std::string() : group.front().card.section;
        cluster.thesis = cluster_thesis(group);
        cluster.supporting_claims = supporting_claims(group);
        cluster.confidence = cluster_confidence(group, intent);
        cluster.cards = std::move(group);
        clusters.push_back(std::move(cluster));
    }
    std::sort(clusters.begin(), clusters.end(), [](const ArgumentCluster& left, const ArgumentCluster& right) {
        return left.confidence > right.confidence;
    });
    return clusters;
}

std::vector<RerankedCard> select_diverse_cards(
    const std::vector<ArgumentCluster>& clusters,
    std::size_t limit,
    double lambda_relevance
) {
    std::map<std::string, double> cluster_score_by_card;
    std::vector<RerankedCard> candidates;
    for (const auto& cluster : clusters) {
        for (const auto& card : cluster.cards) {
            const auto id = card.card.card_id.empty() ? card.card.id : card.card.card_id;
            cluster_score_by_card[id] = cluster.confidence;
            candidates.push_back(card);
        }
    }

    std::vector<RerankedCard> selected;
    while (!candidates.empty() && selected.size() < limit) {
        auto best = std::max_element(candidates.begin(), candidates.end(), [&](const RerankedCard& left, const RerankedCard& right) {
            return mmr_score(left, selected, lambda_relevance, cluster_score_by_card)
                < mmr_score(right, selected, lambda_relevance, cluster_score_by_card);
        });
        selected.push_back(*best);
        const auto selected_id = best->card.card_id.empty() ? best->card.id : best->card.card_id;
        candidates.erase(
            std::remove_if(candidates.begin(), candidates.end(), [&](const RerankedCard& card) {
                const auto id = card.card.card_id.empty() ? card.card.id : card.card.card_id;
                return id == selected_id;
            }),
            candidates.end()
        );
    }
    return selected;
}

} // namespace sekret::hybrid
