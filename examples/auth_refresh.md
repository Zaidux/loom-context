# Task brief: fix the auth refresh bug

## Objective

Fix the failing refresh test in the authentication service without changing
any public API surface.

## Definition of done

The full auth test suite passes and no public function signature changes.

## Constraints

- You must preserve backwards compatibility for all public endpoints.
- You must never edit `src/auth/public.py`.
- Do not upgrade the token library in this change.
- Keep the diff under 150 lines.

## Current state

- repo: acme/api at branch main
- failing test: test_auth_refresh
- attempts so far: 2
- owner: platform-team

## Evidence

- test_run.ts:41 says expected status 200 but got 401 (confidence 0.95)
- config.py:88 sets refresh_ttl to 900 seconds (confidence 0.90)
- the staging clock was measured 42 seconds ahead of the auth server (confidence 0.80)
- test_run.ts:41 says expected status 200 but got 401 (confidence 0.95)

## Open questions

- Does production use NTP?
- Is refresh_ttl overridable from the environment?

## Plan

- Check whether clock skew is handled in token validation.
- Add a regression test for a 42 second skew.
- Re-run the auth suite.
