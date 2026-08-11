#pragma once

#include <QString>
#include <QStringList>

struct EvidenceCard {
    QString id;
    QString documentName;
    QString sectionName;
    QString tag;
    QString cardName;
    QString author;
    QString citation;
    QString bodyPreview;
    QStringList highlights;
    int year = 0;
    double score = 0.0;
};
