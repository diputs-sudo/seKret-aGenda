fn main() {
    build_hybrid_backend();
    tauri_build::build()
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
        backend_dir.join("fusion.cpp"),
        backend_dir.join("candidate_assessment.cpp"),
        backend_dir.join("reranker.cpp"),
        backend_dir.join("argument_builder.cpp"),
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
