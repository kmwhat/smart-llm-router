# Contributing

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Pull Requests

- Keep changes focused and explain the routing behavior being changed.
- Add tests for quality floors, privacy gates, budget behavior, cooldowns, or fallback changes.
- Use only synthetic public fixtures in tests and examples.
- Never commit API keys, credential catalogs, runtime state, private prompts, or user data.
- Preserve fail-closed behavior when privacy, price, role quality, or evidence is unknown.
- Record provider-specific assumptions with a date and an official source or live probe.

Changes to production role quality bands require task-specific evidence: endpoint
health, a public or authorized private golden set, baseline non-regression, and an
independent review from a different model family or a human maintainer. Promotion
must remain an explicit maintainer action.

Before submitting:

```bash
python -m unittest discover -s tests -v
python -m compileall -q smart_llm_router
git diff --check
```
