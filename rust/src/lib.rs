//! Loom core: a fast Rust implementation of the context language.
//!
//! ```no_run
//! let doc = loom_core::parse("@loom 1.0\n!goal ship it\n").unwrap();
//! let text = loom_core::render(&doc, &Default::default()).unwrap();
//! ```

pub mod ast;
pub mod decompile;
pub mod ops;
pub mod parser;
pub mod render;
pub mod tokens;

pub use ast::{Document, Row, Rule, RuleKind, Section, Style, VERSION};
pub use decompile::decompile;
pub use ops::{dedupe, lint, row_count, table_sections};
pub use parser::{parse, LoomError};
pub use render::{render, BudgetError, RenderOpts};
pub use tokens::{count_tokens, estimate_tokens};

pub fn parses(source: &str) -> bool {
    parser::parse(source).is_ok()
}
