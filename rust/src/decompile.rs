//! Loom -> English. Mirrors `loom/decompile.py`.

use crate::ast::{Document, RuleKind, Style};

fn label(name: &str) -> String {
    let lower = name.to_ascii_lowercase();
    let known = match lower.as_str() {
        "state" => Some("Current state"),
        "defs" => Some("Definitions"),
        "evidence" => Some("Evidence"),
        "facts" => Some("Facts"),
        "refs" => Some("References"),
        "open" | "questions" => Some("Open questions"),
        "next" => Some("Next actions"),
        "plan" => Some("Plan"),
        "notes" => Some("Notes"),
        "risks" => Some("Risks"),
        "calls" => Some("Tool calls"),
        "tasks" => Some("Tasks"),
        "incidents" => Some("Incidents"),
        _ => None,
    };
    match known {
        Some(l) => l.to_string(),
        None => {
            let mut chars = lower.replace(['-', '_'], " ").chars().collect::<Vec<_>>();
            if let Some(first) = chars.first_mut() {
                *first = first.to_ascii_uppercase();
            }
            chars.into_iter().collect()
        }
    }
}

fn decompile_row(columns: &[String], row: &crate::ast::Row) -> String {
    let mut parts: Vec<String> = Vec::new();
    for (i, col) in columns.iter().enumerate() {
        let value = row.cells.get(i).cloned().unwrap_or_default();
        if value.is_empty() {
            continue;
        }
        match col.as_str() {
            "text" | "desc" | "description" | "summary" | "value" => parts.insert(0, value),
            "trust" | "confidence" => parts.push(format!("confidence {}", value)),
            "salience" | "prio" | "priority" => parts.push(format!("priority {}", value)),
            "id" => {}
            _ => parts.push(format!("{}: {}", col, value)),
        }
    }
    format!("{}.", parts.join("; "))
}

pub fn decompile(doc: &Document) -> String {
    let mut out: Vec<String> = Vec::new();
    if let Some(goal) = &doc.goal {
        out.push(format!("Objective: {}", goal));
    }
    if let Some(done) = &doc.done {
        out.push(format!("Definition of done: {}", done));
    }
    if !doc.rules.is_empty() {
        out.push("Hard constraints:".to_string());
        for rule in &doc.rules {
            let verb = if rule.kind == RuleKind::Must {
                "You must"
            } else {
                "You must never"
            };
            out.push(format!("- {} {}", verb, rule.text));
        }
    }
    if !doc.uses.is_empty() {
        out.push(format!("Available capabilities: {}.", doc.uses.join(", ")));
    }
    for section in &doc.sections {
        if section.rows.is_empty() {
            continue;
        }
        let mut head = label(&section.name);
        if !section.meta.is_empty() {
            let meta: Vec<String> = section.meta.iter().map(|(k, v)| format!("{}={}", k, v)).collect();
            head.push_str(&format!(" ({})", meta.join(", ")));
        }
        out.push(format!("{}:", head));
        for row in &section.rows {
            match section.style {
                Style::Kv => {
                    let key = row.cells.first().cloned().unwrap_or_default();
                    let value = row.cells.get(1).cloned().unwrap_or_default();
                    out.push(format!("- {} is {}.", key, value));
                }
                Style::Table => {
                    let cols = section.columns.clone().unwrap_or_default();
                    out.push(format!("- {}", decompile_row(&cols, row)));
                }
                Style::List => {
                    out.push(format!("- {}", row.cells.first().cloned().unwrap_or_default()));
                }
            }
        }
    }
    if !doc.questions.is_empty() {
        out.push("Unknowns to resolve before acting:".to_string());
        for q in &doc.questions {
            out.push(format!("- {}", q));
        }
    }
    let mut text = out.join("\n");
    text.push('\n');
    text
}
