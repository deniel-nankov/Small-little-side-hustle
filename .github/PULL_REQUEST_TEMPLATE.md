## What does this PR do?
(one paragraph summary)

## Type of change
- [ ] New signal
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor
- [ ] Infrastructure

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Signal validation tests pass (if applicable)
- [ ] Manually tested with real FactSet data (if applicable)

## Checklist
- [ ] No hardcoded credentials
- [ ] All new functions have docstrings and type hints
- [ ] No raw DataFrames/dicts crossing module boundaries (Pydantic schemas used)
- [ ] Logging added for significant operations
- [ ] `docs/SIGNAL_REGISTRY.md` updated (if a signal was added/changed)
- [ ] `docs/DATA_CONTRACTS.md` updated (if a schema changed)
- [ ] `make lint` and `make test-unit` pass locally
