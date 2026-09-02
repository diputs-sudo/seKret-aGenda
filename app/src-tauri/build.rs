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
        panic!(
            "Required card separator source not found: {}",
            source.display()
        );
    }

    let out_dir =
        std::path::PathBuf::from(std::env::var("OUT_DIR").expect("OUT_DIR is set by Cargo"));
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

    println!(
        "cargo:rustc-env=CARD_SEPARATOR_BIN={}",
        executable.display()
    );
    println!("cargo:rustc-env=CARD_SEPARATOR_SOURCE={}", source.display());
}

fn build_hybrid_backend() {
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let manifest_dir = std::path::PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set by Cargo"),
    );
    let backend_dir = manifest_dir.join("../backend/hybrid");
    let sources = [
        backend_dir.join("hybrid.cpp"),
        backend_dir.join("native_pipeline.cpp"),
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
    ];

    for source in &sources {
        println!("cargo:rerun-if-changed={}", source.display());
    }
    println!(
        "cargo:rerun-if-changed={}",
        manifest_dir
            .join("../../backend/models/sqlite_schema.sql")
            .display()
    );

    let existing_sources = sources
        .iter()
        .filter(|source| source.exists())
        .collect::<Vec<_>>();
    if existing_sources.is_empty() {
        return;
    }

    let mut build = cc::Build::new();
    build
        .cpp(true)
        .std("c++17")
        .flag_if_supported("/EHsc")
        .include(&backend_dir);

    if target_os == "windows" {
        // vcpkg supplies the headers and link metadata for the native Windows
        // build. These dependencies are compiled into the app; end users do
        // not need vcpkg or any external runtime.
        for package in ["minizip", "libxml2", "sqlite3"] {
            let mut config = vcpkg::Config::new();
            config.emit_includes(false);
            let library = config.find_package(package).unwrap_or_else(|error| {
                panic!(
                    "Windows native build requires vcpkg package `{package}`. Run `vcpkg install minizip libxml2 sqlite3`: {error}"
                )
            });
            for include_path in library.include_paths {
                // The portable importer uses the classic minizip and libxml2
                // include forms (<unzip.h> and <libxml/parser.h>). vcpkg keeps
                // their headers in package-specific subdirectories.
                if package == "minizip" {
                    build.include(include_path.join("minizip"));
                } else if package == "libxml2" {
                    build.include(include_path.join("libxml2"));
                }
                build.include(include_path);
            }
        }
    } else {
        let cflags = std::process::Command::new("pkg-config")
            .args(["--cflags", "minizip", "libxml-2.0"])
            .output()
            .expect("pkg-config is required to build the native DOCX importer");
        if !cflags.status.success() {
            panic!("pkg-config could not locate minizip and libxml-2.0");
        }
        for flag in String::from_utf8_lossy(&cflags.stdout).split_whitespace() {
            if let Some(path) = flag.strip_prefix("-I") {
                let include_path = std::path::PathBuf::from(path);
                // Homebrew minizip stores unzip.h in an extra minizip directory.
                let minizip_headers = include_path.join("minizip");
                if minizip_headers.join("unzip.h").exists() {
                    build.include(&minizip_headers);
                }
                build.include(&include_path);
            } else {
                build.flag(flag);
            }
        }
    }
    for source in existing_sources {
        build.file(source);
    }
    build.compile("secret_agenda_hybrid");

    if target_os == "windows" {
        // Winsock backs the native HTTP client used for Ollama embeddings and
        // reranking. vcpkg emits linkage for the other three libraries.
        println!("cargo:rustc-link-lib=ws2_32");
    } else {
        let libs = std::process::Command::new("pkg-config")
            .args(["--libs", "minizip", "libxml-2.0"])
            .output()
            .expect("pkg-config is required to link the native DOCX importer");
        if !libs.status.success() {
            panic!("pkg-config could not resolve native DOCX importer libraries");
        }
        for flag in String::from_utf8_lossy(&libs.stdout).split_whitespace() {
            if let Some(path) = flag.strip_prefix("-L") {
                println!("cargo:rustc-link-search=native={path}");
            } else if let Some(name) = flag.strip_prefix("-l") {
                println!("cargo:rustc-link-lib={name}");
            }
        }
        println!("cargo:rustc-link-lib=sqlite3");
    }
}
