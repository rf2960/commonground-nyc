# Contributing

## Suggested ownership

- Ruochen: `app.py`, session/tool loop, `commonground/fairness.py`, final integration.
- Andrew: location resolution, candidate areas, transit matrix, fastest scoring.
- Yulia: cafe search, cafe scoring, result cards, and final UI polish.

## Branch workflow

1. Pull `main` and create a focused branch such as `andrew/transit-tools`.
2. Keep shared tool shapes aligned with `docs/TOOL_CONTRACTS.md`.
3. Add tests and run `uv run pytest`.
4. Open a pull request; another teammate reviews before merge.
5. Rebase or merge the latest `main` before final integration.

Avoid having several people rewrite `app.py` or `tools.py` at once. Implement domain
logic in separate modules, then make one small integration change to the registry.

