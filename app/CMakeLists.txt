cmake_minimum_required(VERSION 3.21)

project(SecretAgendaApp
    VERSION 0.1.0
    DESCRIPTION "Native desktop shell for seKret aGenda"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 REQUIRED COMPONENTS Widgets Sql)
qt_standard_project_setup()

add_executable(SecretAgenda
    MACOSX_BUNDLE
    WIN32
    src/main.cpp
    src/MainWindow.cpp
    src/MainWindow.h
    src/EvidenceRepository.cpp
    src/EvidenceRepository.h
    src/EvidenceCard.h
    src/PythonBridge.cpp
    src/PythonBridge.h
)

target_link_libraries(SecretAgenda
    PRIVATE
        Qt6::Widgets
        Qt6::Sql
)

target_compile_definitions(SecretAgenda
    PRIVATE
        SECRET_AGENDA_VERSION="${PROJECT_VERSION}"
)

set_target_properties(SecretAgenda PROPERTIES
    OUTPUT_NAME "Secret Agenda"
    MACOSX_BUNDLE_GUI_IDENTIFIER "dev.secretagenda.desktop"
    MACOSX_BUNDLE_BUNDLE_NAME "Secret Agenda"
    MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"
    MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"
)

install(TARGETS SecretAgenda
    BUNDLE DESTINATION .
    RUNTIME DESTINATION .
)
