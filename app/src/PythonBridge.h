#pragma once

#include <QString>

class PythonBridge {
public:
    explicit PythonBridge(QString workerPath);

    QString workerPath() const;
    QString healthCheck(QString pythonExecutable = QStringLiteral("python3")) const;

private:
    QString m_workerPath;
};
