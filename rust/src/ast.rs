//! Core data model. Mirrors `loom/ast.py`.

pub const VERSION: &str = "1.0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Style {
    Kv,
    List,
    Table,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuleKind {
    Must,
    Never,
}

impl RuleKind {
    pub fn as_str(self) -> &'static str {
        match self {
            RuleKind::Must => "must",
            RuleKind::Never => "never",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Rule {
    pub kind: RuleKind,
    pub text: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Row {
    pub cells: Vec<String>,
}

impl Row {
    pub fn new(cells: Vec<String>) -> Self {
        Row { cells }
    }

    pub fn get(&self, columns: &[String], name: &str, default: &str) -> String {
        match columns.iter().position(|c| c == name) {
            Some(i) => self.cells.get(i).cloned().unwrap_or_else(|| default.to_string()),
            None => default.to_string(),
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Section {
    pub name: String,
    pub style: Style,
    pub meta: Vec<(String, String)>,
    pub columns: Option<Vec<String>>,
    pub rows: Vec<Row>,
}

impl Default for Style {
    fn default() -> Self {
        Style::List
    }
}

impl Section {
    pub fn new(name: &str, style: Style) -> Self {
        Section {
            name: name.to_string(),
            style,
            ..Default::default()
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Document {
    pub version: String,
    pub goal: Option<String>,
    pub done: Option<String>,
    pub rules: Vec<Rule>,
    pub uses: Vec<String>,
    pub questions: Vec<String>,
    pub sections: Vec<Section>,
}

impl Document {
    pub fn new() -> Self {
        Document {
            version: VERSION.to_string(),
            ..Default::default()
        }
    }

    pub fn section(&self, name: &str) -> Option<&Section> {
        self.sections.iter().find(|s| s.name == name)
    }

    pub fn section_mut(&mut self, name: &str) -> Option<&mut Section> {
        self.sections.iter_mut().find(|s| s.name == name)
    }

    pub fn ensure(&mut self, name: &str, style: Style) -> &mut Section {
        if let Some(pos) = self.sections.iter().position(|s| s.name == name) {
            return &mut self.sections[pos];
        }
        self.sections.push(Section::new(name, style));
        self.sections.last_mut().unwrap()
    }
}
