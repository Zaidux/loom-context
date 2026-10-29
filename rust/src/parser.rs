//! Line-oriented parser. Mirrors `loom/parser.py`.

use crate::ast::{Document, Row, Rule, RuleKind, Section, Style, VERSION};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoomError {
    pub line: usize,
    pub message: String,
}

impl std::fmt::Display for LoomError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "line {}: {}", self.line, self.message)
    }
}

impl std::error::Error for LoomError {}

fn kv_section(name: &str) -> bool {
    matches!(
        name.to_ascii_lowercase().as_str(),
        "state" | "defs" | "refs" | "def" | "vars" | "env"
    )
}

fn list_section(name: &str) -> bool {
    matches!(
        name.to_ascii_lowercase().as_str(),
        "open" | "next" | "notes" | "plan" | "todo" | "risks"
    )
}

/// Split a comma separated row, honouring double quotes.
pub fn split_cells(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut buf = String::new();
    let mut quoted = false;
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let ch = chars[i];
        if ch == '"' {
            if quoted && i + 1 < chars.len() && chars[i + 1] == '"' {
                buf.push('"');
                i += 2;
                continue;
            }
            quoted = !quoted;
        } else if ch == ',' && !quoted {
            out.push(buf.trim().to_string());
            buf.clear();
        } else {
            buf.push(ch);
        }
        i += 1;
    }
    out.push(buf.trim().to_string());
    out
}

/// Parse `src=tool:bash t=12` style meta.
pub fn parse_meta(text: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for part in split_cells(text) {
        if part.is_empty() {
            continue;
        }
        match part.split_once('=') {
            Some((k, v)) => out.push((k.trim().to_string(), v.trim().trim_matches('"').to_string())),
            None => out.push((part.trim().to_string(), "true".to_string())),
        }
    }
    out
}

fn parse_header(line: &str) -> Option<(String, Vec<(String, String)>, Option<Vec<String>>)> {
    let rest = line.strip_prefix('#')?;
    let name_end = rest
        .char_indices()
        .find(|(_, c)| !(c.is_ascii_alphanumeric() || *c == '_' || *c == '-'))
        .map(|(i, _)| i)
        .unwrap_or(rest.len());
    let name = &rest[..name_end];
    if name.is_empty() {
        return None;
    }
    let mut tail = rest[name_end..].trim();

    let mut meta = Vec::new();
    if let Some(stripped) = tail.strip_prefix('[') {
        let end = stripped.find(']')?;
        meta = parse_meta(&stripped[..end]);
        tail = stripped[end + 1..].trim();
    }
    let mut columns = None;
    if let Some(stripped) = tail.strip_prefix('{') {
        let end = stripped.find('}')?;
        columns = Some(split_cells(&stripped[..end]));
        tail = stripped[end + 1..].trim();
    }
    // `~elided N` may trail a header when every row was evicted; it is
    // renderer metadata, not part of the section declaration.
    if let Some(rest) = tail.strip_prefix("~elided") {
        tail = rest.trim();
        if tail.is_empty() || tail.chars().all(|c| c.is_ascii_digit()) {
            tail = "";
        } else {
            return None;
        }
    }
    if !tail.is_empty() {
        return None;
    }
    Some((name.to_string(), meta, columns))
}

fn strip_ordinal(text: &str) -> &str {
    let digits = text.chars().take_while(|c| c.is_ascii_digit()).count();
    if digits > 0 {
        let rest = &text[digits..];
        if rest.starts_with(". ") || rest.starts_with(") ") {
            return rest[2..].trim_start();
        }
    }
    text
}

pub fn parse(source: &str) -> Result<Document, LoomError> {
    let mut doc = Document::new();
    let mut current: Option<usize> = None;

    for (idx, raw) in source.lines().enumerate() {
        let lineno = idx + 1;
        let line = raw.trim_end();
        let stripped = line.trim();
        if stripped.is_empty() || stripped.starts_with(";;") || stripped.starts_with("//") {
            continue;
        }

        if let Some(rest) = stripped.strip_prefix("@loom") {
            let v = rest.trim();
            doc.version = if v.is_empty() { VERSION.to_string() } else { v.to_string() };
            continue;
        }

        let pragma = stripped.starts_with('!') || stripped.starts_with("?q") || stripped.starts_with("#use");
        if pragma {
            current = None;
        }

        if let Some(rest) = stripped.strip_prefix("!goal") {
            doc.goal = Some(rest.trim().to_string());
            continue;
        }
        if let Some(rest) = stripped.strip_prefix("!done") {
            doc.done = Some(rest.trim().to_string());
            continue;
        }
        if let Some(rest) = stripped.strip_prefix("!must") {
            doc.rules.push(Rule { kind: RuleKind::Must, text: rest.trim().to_string() });
            continue;
        }
        if let Some(rest) = stripped.strip_prefix("!never") {
            doc.rules.push(Rule { kind: RuleKind::Never, text: rest.trim().to_string() });
            continue;
        }
        if let Some(rest) = stripped.strip_prefix("?q") {
            doc.questions.push(rest.trim().to_string());
            continue;
        }
        if let Some(rest) = stripped.strip_prefix("#use") {
            doc.uses.push(rest.trim().to_string());
            continue;
        }

        if !line.starts_with(' ') && !line.starts_with('\t') {
            if let Some((name, meta, columns)) = parse_header(stripped) {
                let style = if columns.is_some() {
                    Style::Table
                } else if kv_section(&name) {
                    Style::Kv
                } else if list_section(&name) {
                    Style::List
                } else {
                    Style::List
                };
                doc.sections.push(Section { name, style, meta, columns, rows: Vec::new() });
                current = Some(doc.sections.len() - 1);
                continue;
            }
        }

        let si = current.ok_or_else(|| LoomError {
            line: lineno,
            message: format!("content outside a section: {}", truncate(stripped, 40)),
        })?;

        // `~elided N` is renderer metadata, not a row.
        if stripped.starts_with("~elided") {
            continue;
        }

        let section = &mut doc.sections[si];

        match section.style {
            Style::Kv => {
                let (k, v) = stripped.split_once('=').ok_or_else(|| LoomError {
                    line: lineno,
                    message: "state rows must be `key = value`".to_string(),
                })?;
                section.rows.push(Row::new(vec![k.trim().to_string(), v.trim().to_string()]));
            }
            Style::Table => {
                let cells = split_cells(stripped);
                let cols = section.columns.as_ref().unwrap();
                if cells.len() != cols.len() {
                    return Err(LoomError {
                        line: lineno,
                        message: format!(
                            "expected {} cells for {{{}}}, got {}",
                            cols.len(),
                            cols.join(","),
                            cells.len()
                        ),
                    });
                }
                section.rows.push(Row::new(cells));
            }
            Style::List => {
                let body = if let Some(rest) = stripped.strip_prefix("- ") {
                    rest
                } else if let Some(rest) = stripped.strip_prefix("* ") {
                    rest
                } else if let Some(rest) = stripped.strip_prefix("+ ") {
                    rest
                } else {
                    strip_ordinal(stripped)
                };
                section.rows.push(Row::new(vec![body.trim().to_string()]));
            }
        }
    }
    Ok(doc)
}

fn truncate(s: &str, n: usize) -> String {
    let mut out: String = s.chars().take(n).collect();
    if s.chars().count() > n {
        out.push_str("...");
    }
    out
}
