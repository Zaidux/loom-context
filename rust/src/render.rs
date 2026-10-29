//! Canonical rendering, budget eviction and head/tail placement.
//! Mirrors `loom/render.py`.

use crate::ast::{Document, Section, Style};
use crate::tokens::count_tokens;

pub const SECTION_ORDER: [&str; 10] = [
    "state", "defs", "evidence", "facts", "refs", "open", "questions", "next", "plan", "notes",
];

pub fn section_priority(name: &str) -> f64 {
    match name {
        "state" => 0.85,
        "defs" => 0.90,
        "evidence" => 0.50,
        "facts" => 0.50,
        "refs" => 0.55,
        "open" => 0.60,
        "questions" => 0.60,
        "next" => 0.70,
        "plan" => 0.70,
        "notes" => 0.10,
        _ => 0.50,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BudgetError {
    pub needed: usize,
    pub budget: usize,
}

impl std::fmt::Display for BudgetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "budget {} is below the mandatory context (goal + done + rules) which needs {} tokens",
            self.budget, self.needed
        )
    }
}

impl std::error::Error for BudgetError {}

fn needs_quote(cell: &str) -> bool {
    cell.contains(',') || cell.contains('"') || cell.trim() != cell
}

fn quote(cell: &str) -> String {
    if !needs_quote(cell) {
        return cell.to_string();
    }
    format!("\"{}\"", cell.replace('"', "\"\""))
}

fn row_priority(section: &Section, row: &crate::ast::Row) -> f64 {
    let mut base = section_priority(&section.name);
    let cols = section.columns.clone().unwrap_or_default();
    if cols.iter().any(|c| c == "trust") {
        if let Ok(v) = row.get(&cols, "trust", "0.5").parse::<f64>() {
            base *= 0.5 + v;
        }
    }
    if cols.iter().any(|c| c == "salience") {
        if let Ok(v) = row.get(&cols, "salience", "0.5").parse::<f64>() {
            base *= 0.5 + v;
        }
    }
    if cols.iter().any(|c| c == "prio") {
        base *= match row.get(&cols, "prio", "2").to_ascii_lowercase().as_str() {
            "high" | "hi" => 1.3,
            "low" | "lo" => 0.6,
            _ => 1.0,
        };
    }
    base
}

fn section_key(section: &Section) -> (usize, String) {
    match SECTION_ORDER.iter().position(|n| *n == section.name) {
        Some(i) => (i, section.name.clone()),
        None => (SECTION_ORDER.len(), section.name.clone()),
    }
}

fn render_section(section: &Section, elided: usize) -> Vec<String> {
    let mut head = format!("#{}", section.name);
    if !section.meta.is_empty() {
        let meta: Vec<String> = section.meta.iter().map(|(k, v)| format!("{}={}", k, v)).collect();
        head.push('[');
        head.push_str(&meta.join(" "));
        head.push(']');
    }
    if section.style == Style::Table {
        if let Some(cols) = &section.columns {
            head.push('{');
            head.push_str(&cols.join(","));
            head.push('}');
        }
    }
    if section.rows.is_empty() && elided > 0 {
        return vec![format!("{} ~elided {}", head, elided)];
    }
    let mut lines = vec![head];
    for row in &section.rows {
        match section.style {
            Style::Kv => {
                let value = row.cells.get(1).cloned().unwrap_or_default();
                lines.push(format!("  {} = {}", row.cells.first().cloned().unwrap_or_default(), value));
            }
            Style::Table => {
                let cells: Vec<String> = row.cells.iter().map(|c| quote(c)).collect();
                lines.push(format!("  {}", cells.join(",")));
            }
            Style::List => {
                lines.push(format!("  - {}", row.cells.first().cloned().unwrap_or_default()));
            }
        }
    }
    if elided > 0 {
        lines.push(format!("  ~elided {}", elided));
    }
    lines
}

pub struct RenderOpts {
    pub budget: Option<usize>,
    pub salient: bool,
    pub recap: bool,
    pub legend: bool,
}

impl Default for RenderOpts {
    fn default() -> Self {
        RenderOpts { budget: None, salient: true, recap: false, legend: false }
    }
}

pub fn render(doc: &Document, opts: &RenderOpts) -> Result<String, BudgetError> {
    // without a budget nothing is mutated, so avoid the clone entirely
    let mut owned: Option<Document> = if opts.budget.is_some() { Some(doc.clone()) } else { None };
    let mut elided: Vec<usize> = vec![0; doc.sections.len()];
    let mut use_recap = opts.recap;

    let render_inner = |d: &Document, elided: &[usize], use_recap: bool| -> String {
        let mut out: Vec<String> = Vec::new();
        if opts.legend {
            out.push(
                ";; loom 1.0 | !goal/!done objective | !must/!never hard rules | ?q unknown | #sections rows"
                    .to_string(),
            );
        }
        out.push(format!("@loom {}", d.version));
        for u in &d.uses {
            out.push(format!("#use {}", u));
        }
        if let Some(goal) = &d.goal {
            out.push(format!("!goal {}", goal));
        }
        if let Some(done) = &d.done {
            out.push(format!("!done {}", done));
        }
        for rule in &d.rules {
            out.push(format!("!{} {}", rule.kind.as_str(), rule.text));
        }

        let mut order: Vec<usize> = (0..d.sections.len()).collect();
        if opts.salient {
            order.sort_by_key(|i| section_key(&d.sections[*i]));
        }
        for i in order {
            out.extend(render_section(&d.sections[i], elided[i]));
        }
        for q in &d.questions {
            out.push(format!("?q {}", q));
        }
        if use_recap && !d.rules.is_empty() {
            let mut recap: String = d
                .rules
                .iter()
                .map(|r| format!("{}: {}", r.kind.as_str(), r.text))
                .collect::<Vec<_>>()
                .join(" | ");
            if recap.len() > 240 {
                recap.truncate(237);
                recap.push_str("...");
            }
            out.push(format!("!rem {}", recap));
        }
        let mut text = out.join("\n");
        text.push('\n');
        text
    };

    let Some(budget) = opts.budget else {
        return Ok(render_inner(doc, &elided, use_recap));
    };
    {
        let d = owned.as_mut().unwrap();
        loop {
            let current = render_inner(d, &elided, use_recap);
            if count_tokens(&current) <= budget {
                break;
            }
            let mut best: Option<(f64, &'static str, usize, usize)> = None;
            for (si, section) in d.sections.iter().enumerate() {
                if section.name == "defs" {
                    continue;
                }
                for (ri, row) in section.rows.iter().enumerate() {
                    let p = row_priority(section, row);
                    if best.map(|b| p < b.0).unwrap_or(true) {
                        best = Some((p, "row", si, ri));
                    }
                }
            }
            if !d.uses.is_empty() {
                if best.map(|b| 0.35 < b.0).unwrap_or(true) {
                    best = Some((0.35, "use", 0, 0));
                }
            }
            if !d.questions.is_empty() {
                if best.map(|b| 0.60 < b.0).unwrap_or(true) {
                    best = Some((0.60, "q", 0, 0));
                }
            }
            match best {
                Some((_, "row", si, ri)) => {
                    d.sections[si].rows.remove(ri);
                    elided[si] += 1;
                }
                Some((_, "use", _, _)) => {
                    d.uses.pop();
                }
                Some((_, _, _, _)) => {
                    d.questions.pop();
                }
                None => break,
            }
        }
        let mut text = render_inner(&d, &elided, use_recap);
        if count_tokens(&text) > budget {
            while !d.uses.is_empty() {
                d.uses.pop();
                text = render_inner(&d, &elided, use_recap);
                if count_tokens(&text) <= budget {
                    break;
                }
            }
        }
        if count_tokens(&text) > budget && use_recap {
            use_recap = false;
            text = render_inner(&d, &elided, use_recap);
        }
        if count_tokens(&text) > budget {
            return Err(BudgetError { needed: count_tokens(&text), budget });
        }
        Ok(text)
    }
}
