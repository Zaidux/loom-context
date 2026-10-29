//! `loom-rs` command line interface.

use std::io::Read;
use std::process::ExitCode;
use std::time::Instant;

use loom_core::{
    count_tokens, decompile, lint, parse, render, row_count, table_sections, RenderOpts,
};

fn read(path: &str) -> Result<String, String> {
    let mut buf = String::new();
    if path == "-" {
        std::io::stdin()
            .read_to_string(&mut buf)
            .map_err(|e| e.to_string())?;
    } else {
        buf = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    }
    Ok(buf)
}

fn usage() -> ! {
    eprintln!(
        "loom-rs 0.1 — fast Loom context language

usage:
  loom-rs parse <file|->
  loom-rs render <file|-> [-b N] [--recap] [--legend] [--chrono]
  loom-rs decompile <file|->
  loom-rs check <file|-> [--strict]
  loom-rs bench <file|-> [--iterations N]"
    );
    std::process::exit(2)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        usage();
    }
    let cmd = args[0].as_str();
    let path = match args.get(1) {
        Some(p) => p.as_str(),
        None => usage(),
    };
    let rest = &args[2..];

    let source = match read(path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error: {}", e);
            return ExitCode::from(2);
        }
    };

    match cmd {
        "parse" => match parse(&source) {
            Ok(doc) => {
                println!(
                    "ok: {} sections, {} rows, {} rules",
                    doc.sections.len(),
                    row_count(&doc),
                    doc.rules.len()
                );
                ExitCode::SUCCESS
            }
            Err(e) => {
                eprintln!("error: {}", e);
                ExitCode::from(2)
            }
        },
        "render" => {
            let mut opts = RenderOpts::default();
            let mut i = 0;
            while i < rest.len() {
                match rest[i].as_str() {
                    "-b" | "--budget" => {
                        i += 1;
                        opts.budget = rest.get(i).and_then(|v| v.parse().ok());
                    }
                    "--recap" => opts.recap = true,
                    "--legend" => opts.legend = true,
                    "--chrono" => opts.salient = false,
                    other => {
                        eprintln!("unknown flag: {}", other);
                        return ExitCode::from(2);
                    }
                }
                i += 1;
            }
            let doc = match parse(&source) {
                Ok(d) => d,
                Err(e) => {
                    eprintln!("error: {}", e);
                    return ExitCode::from(2);
                }
            };
            match render(&doc, &opts) {
                Ok(text) => {
                    print!("{}", text);
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("error: {}", e);
                    ExitCode::from(2)
                }
            }
        }
        "decompile" => match parse(&source) {
            Ok(doc) => {
                print!("{}", decompile(&doc));
                ExitCode::SUCCESS
            }
            Err(e) => {
                eprintln!("error: {}", e);
                ExitCode::from(2)
            }
        },
        "check" => {
            let strict = rest.iter().any(|a| a == "--strict");
            match parse(&source) {
                Ok(doc) => {
                    let problems = lint(&doc);
                    for p in &problems {
                        println!("warn: {}", p);
                    }
                    println!(
                        "{{\"sections\": {}, \"rows\": {}, \"tables\": {}, \"rules\": {}, \"questions\": {}}}",
                        doc.sections.len(),
                        row_count(&doc),
                        table_sections(&doc),
                        doc.rules.len(),
                        doc.questions.len()
                    );
                    if strict && !problems.is_empty() {
                        ExitCode::from(1)
                    } else {
                        ExitCode::SUCCESS
                    }
                }
                Err(e) => {
                    eprintln!("error: {}", e);
                    ExitCode::from(2)
                }
            }
        }
        "bench" => {
            let iterations: usize = rest
                .iter()
                .position(|a| a == "--iterations")
                .and_then(|i| rest.get(i + 1))
                .and_then(|v| v.parse().ok())
                .unwrap_or(1000);
            let doc = match parse(&source) {
                Ok(d) => d,
                Err(e) => {
                    eprintln!("error: {}", e);
                    return ExitCode::from(2);
                }
            };
            let opts = RenderOpts::default();
            // warm up
            for _ in 0..10 {
                let _ = render(&doc, &opts);
            }
            let start = Instant::now();
            for _ in 0..iterations {
                let d = parse(&source).unwrap();
                let _ = render(&d, &opts);
            }
            let elapsed = start.elapsed();
            let per_op = elapsed.as_secs_f64() / iterations as f64;
            println!(
                "iterations={} total={:.3}ms per_op={:.3}us throughput={:.1} ops/s tokens={}",
                iterations,
                elapsed.as_secs_f64() * 1e3,
                per_op * 1e6,
                1.0 / per_op,
                count_tokens(&source)
            );
            ExitCode::SUCCESS
        }
        _ => usage(),
    }
}
