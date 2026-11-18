# PlinkoBPMachine

Clean-room rebuild of the Powerball draw engine around the Master Plinko theory, plus the `genome_lab/` cold-start MVP laboratory.

- Mission and gates: `Instruction.md`
- Governing policy: `Clean_Room_Policy.md`
- Authoritative work ledger: `Master_Build_Journal.md`
- Genome MVP spec (pass-3 handoff): `Genome/`

## Testing

The project is uv-managed with a locked dev group (pytest 8.3.2, ruff 0.16.0, black 26.5.1) and has no `[build-system]`, so the in-repo packages (`plinko`, `genome_lab`) are never installed into the environment.

Run the suite from the repository root with:

```
uv run python -m pytest
```

`python -m pytest` puts the repository root on `sys.path`, which is what makes the in-repo packages importable. Bare `uv run pytest` fails at collection with `ModuleNotFoundError` because the packages are not on the path — use the `python -m` form for every test run (`uv run python -m pytest -q` for quiet output).

## Quality gate

All code work must pass the declared gate before completion, run against the changed paths and then the full suite:

```
uv run ruff check <changed paths>
uv run black --check <changed paths>
uv run python -m pytest
```

Line length is 100 (black, per `pyproject.toml`).
