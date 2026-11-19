# Dashboard metrology

Planned Django module and scheduled OMERO metrology processor for the [CCI dashboard](https://github.com/CCI-GU-Sweden/Dashboard-django), using [METEOR-core](https://github.com/CCI-GU-Sweden/METEOR-core). The existing METEOR-view Flask application is the reference for processing, scoring and UI behavior.

The `dashboard_metrology` Django module provides a staff-only, read-only microscope and measurement viewer, interactive measurement history, and an unresolved-fileset review page. The history uses the most recent 5,000 dated measurements for the selected microscope/lens, separates different units, and labels import-time fallback. Scores are displayed when present; scoring and administrative REDO are not yet implemented. The separate processor and PostgreSQL schema have been exercised against test OMERO. A daily 16:00 Europe/Berlin CronJob is enabled in `core-omero-test`; one saturated test acquisition remains a recorded failure. Crash recovery and production deployment still require further work. See [Installation.md](Installation.md) for setup, [Proposal.md](Proposal.md) for the design, and [Discovery.md](Discovery.md) for findings.

Run `python scripts/update_test_meteor_core.py` to build the current METEOR-core `main` and update the test CronJob to its immutable image digest without contacting OMERO. Updates are on demand, not automatic.
