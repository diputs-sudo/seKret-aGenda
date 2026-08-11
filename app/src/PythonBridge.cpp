#include "PythonBridge.h"

#include <QProcess>

#include <utility>

PythonBridge::PythonBridge(QString workerPath)
    : m_workerPath(std::move(workerPath))
{
}

QString PythonBridge::workerPath() const
{
    return m_workerPath;
}

QString PythonBridge::healthCheck(QString pythonExecutable) const
{
    QProcess process;
    process.start(pythonExecutable, {m_workerPath, QStringLiteral("--health")});
    if (!process.waitForFinished(3000)) {
        process.kill();
        return QStringLiteral("Python worker did not respond.");
    }

    const QString stderrText = QString::fromUtf8(process.readAllStandardError()).trimmed();
    const QString stdoutText = QString::fromUtf8(process.readAllStandardOutput()).trimmed();
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        return stderrText.isEmpty() ? QStringLiteral("Python worker failed.") : stderrText;
    }
    return stdoutText;
}
