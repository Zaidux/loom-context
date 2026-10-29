//! Integration tests. They share fixtures with the Python test suite, so a
//! behaviour change in either implementation breaks a test in both.

use loom_core::{dedupe, decompile, lint, parse, render, RenderOpts};

const AUTH: &str = include_str!("../../examples/auth_refresh.loom");

#[test]
fn roundtrip_is_idempotent() {
    let doc = parse(AUTH).expect("parse");
    let first = render(&doc, &RenderOpts::default()).expect("render");
    let second = render(&parse(&first).expect("reparse"), &RenderOpts::default()).expect("rerender");
    assert_eq!(first, second);
}

#[test]
fn decompile_keeps_every_fact() {
    let text = decompile(&parse(AUTH).unwrap());
    for needle in ["test_auth_refresh", "900s", "+42s", "src/auth/public.py", "NTP"] {
        assert!(text.contains(needle), "missing {needle}");
    }
    assert!(text.contains("Objective:"));
    assert!(text.contains("Hard constraints:"));
}

#[test]
fn table_cell_count_is_validated() {
    let err = parse("#evidence{id,src}\n  only-one\n").unwrap_err();
    assert_eq!(err.line, 2);
}

#[test]
fn budget_never_drops_a_rule() {
    let doc = parse(AUTH).unwrap();
    let out = render(&doc, &RenderOpts { budget: Some(130), recap: true, ..Default::default() })
        .expect("should fit");
    assert!(out.contains("!never edit src/auth/public.py"));
    assert!(out.contains("!goal"));
    assert!(out.contains("~elided") || out.contains("?q"));
}

#[test]
fn infeasible_budget_errors_instead_of_truncating() {
    let doc = parse(AUTH).unwrap();
    let err = render(&doc, &RenderOpts { budget: Some(10), ..Default::default() }).unwrap_err();
    assert!(err.needed > err.budget);
}

#[test]
fn budgeted_render_parses_back() {
    let doc = parse(AUTH).unwrap();
    let full = render(&doc, &RenderOpts::default()).unwrap();
    let budget = loom_core::count_tokens(&full) / 2;
    let out = render(
        &doc,
        &RenderOpts { budget: Some(budget), recap: true, ..Default::default() },
    )
    .unwrap();
    let again = parse(&out).expect("budgeted render must re-parse");
    assert_eq!(again.goal, doc.goal);
    assert_eq!(again.rules, doc.rules);
}

#[test]
fn dedupe_collapses_identical_rows() {
    let src = "#evidence{id,text}\n  e1,same thing\n  e2,same thing\n";
    let mut doc = parse(src).unwrap();
    assert_eq!(dedupe(&mut doc), 1);
    assert_eq!(doc.section("evidence").unwrap().rows.len(), 1);
}

#[test]
fn lint_flags_contradiction() {
    let doc = parse("!must ship\n!never ship\n#state\n  a = 1\n").unwrap();
    let problems = lint(&doc);
    assert!(problems.iter().any(|p| p.contains("contradiction")));
    assert!(problems.iter().any(|p| p.contains("no !goal")));
}

#[test]
fn unicode_and_quotes_survive_rendering() {
    let src = "#evidence{id,text}\n  e1,\"héllo, \\\"world\\\"\"\n";
    let doc = parse(src).expect("unicode row");
    let out = render(&doc, &RenderOpts::default()).unwrap();
    assert!(out.contains("héllo"));
    let again = parse(&out).unwrap();
    assert_eq!(again.section("evidence").unwrap().rows.len(), 1);
}
