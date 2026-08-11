#include "EvidenceRepository.h"

#include <QFileInfo>
#include <QRegularExpression>
#include <QSqlError>
#include <QSqlQuery>
#include <QtGlobal>
#include <QVariant>

#include <utility>

namespace {
constexpr auto kSelectCards = R"SQL(
SELECT
    evidence_cards.id,
    debate_documents.name AS document_name,
    sections.name AS section_name,
    evidence_cards.tag,
    evidence_cards.card_name,
    citations.author,
    citations.year,
    citations.raw AS citation,
    substr(evidence_cards.body, 1, 1200) AS body_preview
FROM evidence_cards
JOIN sections ON sections.id = evidence_cards.section_id
JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
LEFT JOIN citations ON citations.card_id = evidence_cards.id
)SQL";

QString normalizeWhitespace(QString value)
{
    value.replace(QRegularExpression("\\s+"), " ");
    return value.trimmed();
}
}

EvidenceRepository::EvidenceRepository(QString dbPath)
    : m_dbPath(std::move(dbPath)),
      m_connectionName(QStringLiteral("secret-agenda-%1").arg(reinterpret_cast<quintptr>(this)))
{
}

EvidenceRepository::~EvidenceRepository()
{
    close();
}

void EvidenceRepository::setDatabasePath(QString dbPath)
{
    if (m_dbPath == dbPath) {
        return;
    }
    close();
    m_dbPath = std::move(dbPath);
}

QString EvidenceRepository::databasePath() const
{
    return m_dbPath;
}

QString EvidenceRepository::lastError() const
{
    return m_lastError;
}

bool EvidenceRepository::open()
{
    if (m_db.isOpen()) {
        return true;
    }

    if (!QFileInfo::exists(m_dbPath)) {
        m_lastError = QStringLiteral("Database not found: %1").arg(m_dbPath);
        return false;
    }

    m_db = QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"), m_connectionName);
    m_db.setDatabaseName(m_dbPath);

    if (!m_db.open()) {
        m_lastError = m_db.lastError().text();
        close();
        return false;
    }

    m_lastError.clear();
    return true;
}

bool EvidenceRepository::isOpen() const
{
    return m_db.isOpen();
}

QVector<EvidenceCard> EvidenceRepository::search(const QString& query, int limit)
{
    if (!open()) {
        return {};
    }

    const QString trimmed = query.trimmed();
    if (trimmed.isEmpty()) {
        return recentCards(limit);
    }

    QVector<EvidenceCard> cards = ftsSearch(trimmed, limit);
    if (!cards.isEmpty()) {
        return cards;
    }
    return likeSearch(trimmed, limit);
}

QVector<EvidenceCard> EvidenceRepository::recentCards(int limit)
{
    QSqlQuery sql(m_db);
    sql.prepare(QString::fromUtf8(kSelectCards) + QStringLiteral(R"SQL(
ORDER BY sections.order_index, evidence_cards.paragraph_start
LIMIT :limit
)SQL"));
    sql.bindValue(QStringLiteral(":limit"), limit);

    QVector<EvidenceCard> cards;
    if (!sql.exec()) {
        m_lastError = sql.lastError().text();
        return cards;
    }

    while (sql.next()) {
        cards.append(cardFromQuery(sql, 0.0));
    }
    m_lastError.clear();
    return cards;
}

QVector<EvidenceCard> EvidenceRepository::ftsSearch(const QString& query, int limit)
{
    const QString ftsQuery = buildFtsQuery(query);
    if (ftsQuery.isEmpty()) {
        return {};
    }

    QSqlQuery sql(m_db);
    sql.prepare(QStringLiteral(R"SQL(
SELECT
    bm25(evidence_cards_fts) AS rank,
    evidence_cards.id,
    debate_documents.name AS document_name,
    sections.name AS section_name,
    evidence_cards.tag,
    evidence_cards.card_name,
    citations.author,
    citations.year,
    citations.raw AS citation,
    substr(evidence_cards.body, 1, 1200) AS body_preview
FROM evidence_cards_fts
JOIN evidence_cards ON evidence_cards.id = evidence_cards_fts.card_id
JOIN sections ON sections.id = evidence_cards.section_id
JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
LEFT JOIN citations ON citations.card_id = evidence_cards.id
WHERE evidence_cards_fts MATCH :query
ORDER BY rank
LIMIT :limit
)SQL"));
    sql.bindValue(QStringLiteral(":query"), ftsQuery);
    sql.bindValue(QStringLiteral(":limit"), limit);

    QVector<EvidenceCard> cards;
    if (!sql.exec()) {
        m_lastError = sql.lastError().text();
        return cards;
    }

    while (sql.next()) {
        const double rank = sql.value(QStringLiteral("rank")).toDouble();
        cards.append(cardFromQuery(sql, 1.0 / (1.0 + qAbs(rank))));
    }
    m_lastError.clear();
    return cards;
}

QVector<EvidenceCard> EvidenceRepository::likeSearch(const QString& query, int limit)
{
    QSqlQuery sql(m_db);
    sql.prepare(QString::fromUtf8(kSelectCards) + QStringLiteral(R"SQL(
WHERE
    evidence_cards.tag LIKE :pattern
    OR evidence_cards.card_name LIKE :pattern
    OR evidence_cards.body LIKE :pattern
    OR citations.raw LIKE :pattern
ORDER BY sections.order_index, evidence_cards.paragraph_start
LIMIT :limit
)SQL"));
    sql.bindValue(QStringLiteral(":pattern"), QStringLiteral("%%1%").arg(query));
    sql.bindValue(QStringLiteral(":limit"), limit);

    QVector<EvidenceCard> cards;
    if (!sql.exec()) {
        m_lastError = sql.lastError().text();
        return cards;
    }

    while (sql.next()) {
        cards.append(cardFromQuery(sql, 0.25));
    }
    m_lastError.clear();
    return cards;
}

QStringList EvidenceRepository::highlightsForCard(const QString& cardId) const
{
    QSqlQuery sql(m_db);
    sql.prepare(QStringLiteral(R"SQL(
SELECT text
FROM highlights
WHERE card_id = :card_id
ORDER BY order_index
LIMIT 6
)SQL"));
    sql.bindValue(QStringLiteral(":card_id"), cardId);

    QStringList highlights;
    if (!sql.exec()) {
        return highlights;
    }

    while (sql.next()) {
        const QString text = normalizeWhitespace(sql.value(0).toString());
        if (!text.isEmpty()) {
            highlights.append(text);
        }
    }
    return highlights;
}

QString EvidenceRepository::buildFtsQuery(const QString& query) const
{
    static const QRegularExpression tokenRe(QStringLiteral("[A-Za-z0-9']+"));

    QStringList tokens;
    auto matches = tokenRe.globalMatch(query);
    while (matches.hasNext()) {
        const QString token = matches.next().captured(0).trimmed();
        if (token.size() >= 2) {
            tokens.append(token + QStringLiteral("*"));
        }
    }
    return tokens.join(QStringLiteral(" OR "));
}

EvidenceCard EvidenceRepository::cardFromQuery(const QSqlQuery& sql, double score) const
{
    EvidenceCard card;
    card.id = sql.value(QStringLiteral("id")).toString();
    card.documentName = sql.value(QStringLiteral("document_name")).toString();
    card.sectionName = sql.value(QStringLiteral("section_name")).toString();
    card.tag = normalizeWhitespace(sql.value(QStringLiteral("tag")).toString());
    card.cardName = normalizeWhitespace(sql.value(QStringLiteral("card_name")).toString());
    card.author = normalizeWhitespace(sql.value(QStringLiteral("author")).toString());
    card.year = sql.value(QStringLiteral("year")).toInt();
    card.citation = normalizeWhitespace(sql.value(QStringLiteral("citation")).toString());
    card.bodyPreview = normalizeWhitespace(sql.value(QStringLiteral("body_preview")).toString());
    card.highlights = highlightsForCard(card.id);
    card.score = score;
    return card;
}

void EvidenceRepository::close()
{
    if (m_db.isValid()) {
        m_db.close();
    }
    m_db = QSqlDatabase();
    QSqlDatabase::removeDatabase(m_connectionName);
}
