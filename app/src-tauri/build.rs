fn main() {
    build_hybrid_backend();
    build_card_separator();
    tauri_build::build()
}

fn build_card_separator() {
    let manifest_dir = std::path::PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set by Cargo"),
    );
    let source = manifest_dir.join("../backend/card_separator/card_separator.cpp");
    println!("cargo:rerun-if-changed={}", source.display());
    if !source.exists() {
        panic!("Required card separator source not found: {}", source.display());
    }

    let out_dir = std::path::PathBuf::from(
        std::env::var("OUT_DIR").expect("OUT_DIR is set by Cargo"),
    );
    let executable = out_dir.join(if cfg!(windows) {
        "card_separator.exe"
    } else {
        "card_separator"
    });

    let compiler = std::env::var("CXX").unwrap_or_else(|_| {
        if cfg!(windows) {
            "cl".to_string()
        } else {
            "c++".to_string()
        }
    });

    let status = if cfg!(windows) {
        std::process::Command::new(&compiler)
            .arg("/std:c++17")
            .arg("/EHsc")
            .arg(&source)
            .arg(format!("/Fe:{}", executable.display()))
            .status()
    } else {
        let mut command = std::process::Command::new(&compiler);
        command
            .arg("-std=c++17")
            .arg("-O2")
            .arg(&source)
            .arg("-o")
            .arg(&executable);
        if cfg!(target_os = "macos") {
            command.env("MACOSX_DEPLOYMENT_TARGET", "10.15");
        }
        command.status()
    }
    .unwrap_or_else(|error| panic!("Failed to invoke C++ compiler for card separator: {error}"));

    if !status.success() {
        panic!(
            "Failed to compile authoritative card separator source {}",
            source.display()
        );
    }

    println!("cargo:rustc-env=CARD_SEPARATOR_BIN={}", executable.display());
    println!("cargo:rustc-env=CARD_SEPARATOR_SOURCE={}", source.display());
}

fn build_hybrid_backend() {
    let manifest_dir = std::path::PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set by Cargo"),
    );
    let backend_dir = manifest_dir.join("../backend/hybrid");
    let sources = [
        backend_dir.join("hybrid.cpp"),
        backend_dir.join("relevance.cpp"),
        backend_dir.join("mechanism.cpp"),
        backend_dir.join("query_intent.cpp"),
        backend_dir.join("sqlite_store.cpp"),
        backend_dir.join("ollama_embedder.cpp"),
        backend_dir.join("vector_store.cpp"),
        backend_dir.join("fusion.cpp"),
        backend_dir.join("candidate_assessment.cpp"),
        backend_dir.join("reranker.cpp"),
        backend_dir.join("argument_builder.cpp"),
        backend_dir.join("format_parser.cpp"),
        backend_dir.join("round_import.cpp"),
    ];

    for source in &sources {
        println!("cargo:rerun-if-changed={}", source.display());
    }

    let existing_sources = sources
        .iter()
        .filter(|source| source.exists())
        .collect::<Vec<_>>();
    if existing_sources.is_empty() {
        return;
    }

    let mut build = cc::Build::new();
    build.cpp(true).std("c++17").include(&backend_dir);
    for source in existing_sources {
        build.file(source);
    }
    build.compile("secret_agenda_hybrid");
    println!("cargo:rustc-link-lib=sqlite3");
}
