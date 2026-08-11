#pragma once

#include "EvidenceCard.h"
#include "EvidenceRepository.h"
#include "PythonBridge.h"

#include <QMainWindow>
#include <QVector>

class QLabel;
class QLineEdit;
class QListWidget;
class QPlainTextEdit;
class QPushButton;
class QTableWidget;

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(QString dbPath, QString pythonWorkerPath, QWidget* parent = nullptr);

private slots:
    void runSearch();
    void openDatabase();
    void showSelectedCard(int row, int column);
    void showPythonHealth();

private:
    void buildUi();
    void createMenus();
    void applyStyle();
    void refreshStatus();
    void setCards(QVector<EvidenceCard> cards);
    void renderDetails(const EvidenceCard& card);

    EvidenceRepository m_repository;
    PythonBridge m_python;
    QVector<EvidenceCard> m_cards;

    QLabel* m_dbStatus = nullptr;
    QLineEdit* m_searchInput = nullptr;
    QPushButton* m_searchButton = nullptr;
    QListWidget* m_modeList = nullptr;
    QTableWidget* m_resultsTable = nullptr;
    QPlainTextEdit* m_details = nullptr;
};
