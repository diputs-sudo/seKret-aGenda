#pragma once

#include "hybrid.hpp"

extern "C" SekretHybridJsonResult sekret_import_opponent_dsl_json(
    const char* db_path,
    const char* source_path,
    const char* grammar_path
);
