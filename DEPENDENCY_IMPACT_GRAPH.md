# Dependency impact graph

Reference read graph: `scripts/powerball_refresh.py` → `core/data_ingestion.py` → `core/storage_manager.py` → canonical SQLite `draws` → `core/enhanced_powerball_query.py` → `core/odds_improvement_generator.py` → `powerball_cli.py`.

Reference write graph: `core/enhanced_powerball_query.py` → `GeneratedPickStorage.__init__` (DDL/migration); `core/odds_improvement_generator.py` → `GeneratedPickStorage.create_batch/save_pick`; `web_app.py` → `save_pick`; CLI `evaluate` → `GeneratedPickStorage.evaluate_against_draws` → ledger SQLite `generated_picks/generation_batches/pick_evaluations`. Consequently the reference app must never be imported or executed in-place for clean-room analysis.

Planned isolated graph: SQLite `draws` (URI mode=ro; SELECT only) → validated row snapshot with UTC cutoff and record hash → sum/PB/white analyzer → in-memory prototype generator with caller-specified bins/slots → in-memory result. No reference write edge, no production adapters, no migration.

Change manifest: new code/tests/docs in `C:/Users/RobMo/PlinkoPBMachine` only. Production path remains unchanged. No external API calls.
