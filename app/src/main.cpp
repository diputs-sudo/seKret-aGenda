#include "MainWindow.h"

#include <QApplication>
#include <QByteArray>
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QStringList>

namespace {
QString findDefaultDatabase()
{
    const QByteArray envPath = qgetenv("SEKRET_DB_PATH");
    if (!envPath.isEmpty()) {
        return QString::fromLocal8Bit(envPath);
    }

    QStringList roots;
    roots << QDir::currentPath();

    QDir appDir(QCoreApplication::applicationDirPath());
    for (int i = 0; i < 6; ++i) {
        roots << appDir.absolutePath();
        appDir.cdUp();
    }

    for (const QString& root : roots) {
        const QString candidate = QDir(root).filePath(QStringLiteral("var/sekret-agenda.sqlite3"));
        if (QFileInfo::exists(candidate)) {
            return candidate;
        }
    }

    return QDir::current().filePath(QStringLiteral("var/sekret-agenda.sqlite3"));
}

QString findPythonWorker()
{
    QDir appDir(QCoreApplication::applicationDirPath());
    for (int i = 0; i < 6; ++i) {
        const QString candidate = appDir.filePath(QStringLiteral("python/ai_worker.py"));
        if (QFileInfo::exists(candidate)) {
            return candidate;
        }
        const QString sourceCandidate = appDir.filePath(QStringLiteral("../python/ai_worker.py"));
        if (QFileInfo::exists(sourceCandidate)) {
            return QFileInfo(sourceCandidate).absoluteFilePath();
        }
        appDir.cdUp();
    }
    return QDir::current().filePath(QStringLiteral("app/python/ai_worker.py"));
}
}

int main(int argc, char* argv[])
{
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("Secret Agenda"));
    QApplication::setOrganizationName(QStringLiteral("Secret Agenda"));
    QApplication::setApplicationVersion(QStringLiteral(SECRET_AGENDA_VERSION));

    MainWindow window(findDefaultDatabase(), findPythonWorker());
    window.show();

    return app.exec();
}
