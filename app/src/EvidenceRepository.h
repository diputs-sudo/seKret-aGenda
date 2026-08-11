#pragma once

#include "EvidenceCard.h"

#include <QSqlDatabase>
#include <QString>
#include <QVector>

class EvidenceRepository {
public:
    explicit EvidenceRepository(QString dbPath);
    ~EvidenceRepository();

    EvidenceRepository(const EvidenceRepository&) = delete;
    EvidenceRepository& operator=(const EvidenceRepository&) = delete;

    void setDatabasePath(QString dbPath);
    QString databasePath() const;
    QString lastError() const;
    bool open();
    bool isOpen() const;

    QVector<EvidenceCard> search(const QString& query, int limit = 25);

private:
    QVector<EvidenceCard> recentCards(int limit);
    QVector<EvidenceCard> ftsSearch(const QString& query, int limit);
    QVector<EvidenceCard> likeSearch(const QString& query, int limit);
    QStringList highlightsForCard(const QString& cardId) const;
    QString buildFtsQuery(const QString& query) const;
    EvidenceCard cardFromQuery(const QSqlQuery& sql, double score) const;
    void close();

    QString m_dbPath;
    QString m_connectionName;
    QString m_lastError;
    QSqlDatabase m_db;
};
