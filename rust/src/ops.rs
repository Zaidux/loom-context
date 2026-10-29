//! Deduplication and linting. Mirrors `loom/ops.py`.

use crate::ast::{Document, Style};
use std::collections::{HashMap, HashSet};

fn norm(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_ascii_lowercase()
}

/// Collapse duplicate rows, ignoring the `id` column. Returns rows removed.
pub fn dedupe(doc: &mut Document) -> usize {
    let mut removed = 0;
    for section in &mut doc.sections {
        let skip: HashSet<usize> = section
            .columns
            .as_ref()
            .map(|cols| {
                cols.iter()
                    .enumerate()
                    .filter(|(_, c)| matches!(c.to_ascii_lowercase().as_str(), "id" | "row" | "no"))
                    .map(|(i, _)| i)
                    .collect()
            })
            .unwrap_or_default();
        let mut seen: HashMap<String, usize> = HashMap::new();
        let mut keep: Vec<crate::ast::Row> = Vec::new();
        for row in section.rows.drain(..) {
            let body: Vec<&String> = row
                .cells
                .iter()
                .enumerate()
                .filter(|(i, _)| !skip.contains(i))
                .map(|(_, c)| c)
                .collect();
            let key = norm(&body.iter().map(|s| s.as_str()).collect::<Vec<_>>().join("|"));
            if key.is_empty() {
                continue;
            }
            match seen.get(&key) {
                Some(&idx) => {
                    removed += 1;
                    if row.cells.len() > keep[idx].cells.len() {
                        keep[idx] = row;
                    }
                }
                None => {
                    seen.insert(key, keep.len());
                    keep.push(row);
                }
            }
        }
        section.rows = keep;
    }
    removed
}

/// Non-fatal warnings.
pub fn lint(doc: &Document) -> Vec<String> {
    let mut problems = Vec::new();
    if doc.goal.is_none() {
        problems.push("no !goal: the model has no objective to anchor on".to_string());
    }
    if doc.done.is_none() {
        problems.push("no !done: success is undefined, so the agent may stop early".to_string());
    }
    for section in &doc.sections {
        if section.rows.is_empty() {
            problems.push(format!("#{} is empty", section.name));
        }
        for row in &section.rows {
            let len: usize = row.cells.iter().map(|c| c.chars().count()).sum::<usize>()
                + row.cells.len().saturating_sub(1);
            if len > 400 {
                problems.push(format!(
                    "#{} has a {}-char row; split it or move it to #refs",
                    section.name, len
                ));
            }
        }
    }
    let musts: HashSet<String> = doc
        .rules
        .iter()
        .filter(|r| r.kind == crate::ast::RuleKind::Must)
        .map(|r| norm(&r.text))
        .collect();
    let nevers: HashSet<String> = doc
        .rules
        .iter()
        .filter(|r| r.kind == crate::ast::RuleKind::Never)
        .map(|r| norm(&r.text))
        .collect();
    let mut clashes: Vec<&String> = musts.intersection(&nevers).collect();
    clashes.sort();
    for clash in clashes {
        problems.push(format!("contradiction: {:?} is both !must and !never", clash));
    }
    if doc.questions.len() > 8 {
        problems.push("more than 8 open questions: resolve some before spending context".to_string());
    }
    problems
}

/// Count rows across all sections.
pub fn row_count(doc: &Document) -> usize {
    doc.sections.iter().map(|s| s.rows.len()).sum()
}

/// Count table sections (used by the CLI summary).
pub fn table_sections(doc: &Document) -> usize {
    doc.sections.iter().filter(|s| s.style == Style::Table).count()
}
