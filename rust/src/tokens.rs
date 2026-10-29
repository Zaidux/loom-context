//! Token accounting. Mirrors `loom/budget.py`'s dependency-free estimator.

/// Rough token estimate: ~3.8 ASCII chars/token, ~1.6 for wide characters.
///
/// The Python implementation prefers tiktoken when installed; this port keeps
/// the estimator only, so it has no network or model-file dependency. Budgets
/// are therefore approximate in Rust and exact in Python.
pub fn estimate_tokens(text: &str) -> usize {
    if text.is_empty() {
        return 0;
    }
    let mut ascii = 0usize;
    let mut wide = 0usize;
    for ch in text.chars() {
        if ch.is_ascii() {
            ascii += 1;
        } else {
            wide += 1;
        }
    }
    let est = (ascii as f64 / 3.8) + (wide as f64 / 1.6);
    est.ceil() as usize
}

pub fn count_tokens(text: &str) -> usize {
    estimate_tokens(text)
}
