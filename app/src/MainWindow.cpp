#include "MainWindow.h"

#include <QAction>
#include <QApplication>
#include <QAbstractItemView>
#include <QFileDialog>
#include <QFont>
#include <QHeaderView>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenuBar>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSplitter>
#include <QStatusBar>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QVBoxLayout>
#include <QWidget>

#include <utility>

MainWindow::MainWindow(QString dbPath, QString pythonWorkerPath, QWidget* parent)
    : QMainWindow(parent),
      m_repository(std::move(dbPath)),
      m_python(std::move(pythonWorkerPath))
{
    buildUi();
    createMenus();
    applyStyle();
    refreshStatus();
    runSearch();
}

void MainWindow::buildUi()
{
    setWindowTitle(QStringLiteral("Secret Agenda"));
    resize(1180, 760);

    auto* central = new QWidget(this);
    auto* root = new QVBoxLayout(central);
    root->setContentsMargins(18, 16, 18, 18);
    root->setSpacing(12);

    auto* title = new QLabel(QStringLiteral("Secret Agenda"), central);
    title->setObjectName(QStringLiteral("AppTitle"));
    root->addWidget(title);

    m_dbStatus = new QLabel(central);
    m_dbStatus->setObjectName(QStringLiteral("DbStatus"));
    root->addWidget(m_dbStatus);

    auto* searchRow = new QWidget(central);
    auto* searchLayout = new QHBoxLayout(searchRow);
    searchLayout->setContentsMargins(0, 0, 0, 0);
    searchLayout->setSpacing(8);

    m_searchInput = new QLineEdit(searchRow);
    m_searchInput->setPlaceholderText(QStringLiteral("Search evidence, citations, sections, or warrants"));
    m_searchInput->setClearButtonEnabled(true);
    m_searchButton = new QPushButton(QStringLiteral("Search"), searchRow);
    m_searchButton->setDefault(true);
    searchLayout->addWidget(m_searchInput, 1);
    searchLayout->addWidget(m_searchButton);
    root->addWidget(searchRow);

    auto* splitter = new QSplitter(central);

    m_modeList = new QListWidget(splitter);
    m_modeList->setObjectName(QStringLiteral("ModeList"));
    m_modeList->addItems({
        QStringLiteral("Search"),
        QStringLiteral("Explain"),
        QStringLiteral("Draft Rebuttal"),
        QStringLiteral("Summary"),
        QStringLiteral("Final Focus")
    });
    m_modeList->setCurrentRow(0);
    m_modeList->setFixedWidth(180);

    m_resultsTable = new QTableWidget(splitter);
    m_resultsTable->setColumnCount(4);
    m_resultsTable->setHorizontalHeaderLabels({
        QStringLiteral("Score"),
        QStringLiteral("Card"),
        QStringLiteral("Section"),
        QStringLiteral("Tag")
    });
    m_resultsTable->horizontalHeader()->setStretchLastSection(true);
    m_resultsTable->horizontalHeader()->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    m_resultsTable->horizontalHeader()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    m_resultsTable->horizontalHeader()->setSectionResizeMode(2, QHeaderView::ResizeToContents);
    m_resultsTable->verticalHeader()->setVisible(false);
    m_resultsTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_resultsTable->setSelectionMode(QAbstractItemView::SingleSelection);
    m_resultsTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_resultsTable->setAlternatingRowColors(true);

    m_details = new QPlainTextEdit(splitter);
    m_details->setReadOnly(true);
    m_details->setLineWrapMode(QPlainTextEdit::WidgetWidth);
    m_details->setPlaceholderText(QStringLiteral("Select a card to inspect citation, highlights, and body preview."));

    splitter->setStretchFactor(0, 0);
    splitter->setStretchFactor(1, 3);
    splitter->setStretchFactor(2, 2);
    root->addWidget(splitter, 1);

    setCentralWidget(central);

    connect(m_searchButton, &QPushButton::clicked, this, &MainWindow::runSearch);
    connect(m_searchInput, &QLineEdit::returnPressed, this, &MainWindow::runSearch);
    connect(m_resultsTable, &QTableWidget::cellClicked, this, &MainWindow::showSelectedCard);
}

void MainWindow::createMenus()
{
    auto* fileMenu = menuBar()->addMenu(QStringLiteral("&File"));
    auto* openDb = fileMenu->addAction(QStringLiteral("Open SQLite Database..."));
    auto* quit = fileMenu->addAction(QStringLiteral("Quit"));

    auto* toolsMenu = menuBar()->addMenu(QStringLiteral("&Tools"));
    auto* pythonHealth = toolsMenu->addAction(QStringLiteral("Python Worker Health"));

    connect(openDb, &QAction::triggered, this, &MainWindow::openDatabase);
    connect(quit, &QAction::triggered, qApp, &QApplication::quit);
    connect(pythonHealth, &QAction::triggered, this, &MainWindow::showPythonHealth);
}

void MainWindow::applyStyle()
{
    qApp->setStyleSheet(QStringLiteral(R"QSS(
QMainWindow {
    background: #f6f4ef;
}
QLabel#AppTitle {
    color: #1f2933;
    font-size: 28px;
    font-weight: 700;
}
QLabel#DbStatus {
    color: #59636e;
    font-size: 12px;
}
QLineEdit {
    background: #ffffff;
    border: 1px solid #c7ccd1;
    border-radius: 6px;
    padding: 9px 10px;
    selection-background-color: #2f6f73;
}
QPushButton {
    background: #2f6f73;
    color: #ffffff;
    border: 0;
    border-radius: 6px;
    padding: 9px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background: #245a5d;
}
QListWidget#ModeList {
    background: #ebe7df;
    border: 1px solid #d4cec2;
    border-radius: 6px;
    padding: 6px;
}
QListWidget#ModeList::item {
    border-radius: 4px;
    padding: 9px;
}
QListWidget#ModeList::item:selected {
    background: #2f6f73;
    color: white;
}
QTableWidget, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #d4cec2;
    border-radius: 6px;
    color: #1f2933;
}
QHeaderView::section {
    background: #ebe7df;
    border: 0;
    border-right: 1px solid #d4cec2;
    padding: 7px;
    font-weight: 700;
}
QTableWidget::item {
    padding: 6px;
}
)QSS"));
}

void MainWindow::refreshStatus()
{
    const QString state = m_repository.open()
        ? QStringLiteral("Connected")
        : QStringLiteral("Not connected");
    m_dbStatus->setText(QStringLiteral("%1: %2").arg(state, m_repository.databasePath()));

    if (!m_repository.lastError().isEmpty()) {
        statusBar()->showMessage(m_repository.lastError(), 7000);
    }
}

void MainWindow::runSearch()
{
    refreshStatus();
    const QVector<EvidenceCard> cards = m_repository.search(m_searchInput->text(), 40);
    setCards(cards);

    if (cards.isEmpty() && !m_repository.lastError().isEmpty()) {
        m_details->setPlainText(m_repository.lastError());
    } else if (cards.isEmpty()) {
        m_details->setPlainText(QStringLiteral("No matching cards."));
    }
}

void MainWindow::openDatabase()
{
    const QString path = QFileDialog::getOpenFileName(
        this,
        QStringLiteral("Open Secret Agenda SQLite Database"),
        m_repository.databasePath(),
        QStringLiteral("SQLite databases (*.sqlite *.sqlite3 *.db);;All files (*)")
    );
    if (path.isEmpty()) {
        return;
    }

    m_repository.setDatabasePath(path);
    refreshStatus();
    runSearch();
}

void MainWindow::setCards(QVector<EvidenceCard> cards)
{
    m_cards = std::move(cards);
    m_resultsTable->setRowCount(m_cards.size());

    for (int row = 0; row < m_cards.size(); ++row) {
        const EvidenceCard& card = m_cards.at(row);
        const QString source = !card.cardName.isEmpty()
            ? card.cardName
            : (!card.author.isEmpty() ? card.author : QStringLiteral("Unknown"));
        m_resultsTable->setItem(row, 0, new QTableWidgetItem(card.score > 0.0 ? QString::number(card.score, 'f', 3) : QString()));
        m_resultsTable->setItem(row, 1, new QTableWidgetItem(source));
        m_resultsTable->setItem(row, 2, new QTableWidgetItem(card.sectionName));
        m_resultsTable->setItem(row, 3, new QTableWidgetItem(card.tag));
    }

    if (!m_cards.isEmpty()) {
        m_resultsTable->selectRow(0);
        renderDetails(m_cards.first());
    }
}

void MainWindow::showSelectedCard(int row, int)
{
    if (row < 0 || row >= m_cards.size()) {
        return;
    }
    renderDetails(m_cards.at(row));
}

void MainWindow::renderDetails(const EvidenceCard& card)
{
    QStringList lines;
    lines << QStringLiteral("Card")
          << QStringLiteral("----")
          << (!card.cardName.isEmpty() ? card.cardName : card.author)
          << QString()
          << QStringLiteral("Section")
          << QStringLiteral("-------")
          << card.sectionName
          << QString()
          << QStringLiteral("Tag")
          << QStringLiteral("---")
          << card.tag
          << QString()
          << QStringLiteral("Citation")
          << QStringLiteral("--------")
          << card.citation
          << QString()
          << QStringLiteral("Highlights")
          << QStringLiteral("----------");

    if (card.highlights.isEmpty()) {
        lines << QStringLiteral("No highlights captured.");
    } else {
        for (const QString& highlight : card.highlights) {
            lines << QStringLiteral("- %1").arg(highlight);
        }
    }

    lines << QString()
          << QStringLiteral("Body Preview")
          << QStringLiteral("------------")
          << card.bodyPreview;

    m_details->setPlainText(lines.join(QLatin1Char('\n')));
}

void MainWindow::showPythonHealth()
{
    QMessageBox::information(
        this,
        QStringLiteral("Python Worker"),
        m_python.healthCheck()
    );
}
