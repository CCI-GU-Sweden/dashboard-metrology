# Dashboard metrology

Planned Django module and scheduled OMERO metrology processor for the [CCI dashboard](https://github.com/CCI-GU-Sweden/Dashboard-django), using [METEOR-core](https://github.com/CCI-GU-Sweden/METEOR-core). The existing METEOR-view Flask application is the reference for processing, scoring and UI behavior.

The separate `metrology_processor` worker and PostgreSQL schema have been exercised against test OMERO. A daily 16:00 Europe/Berlin CronJob is enabled in `core-omero-test`; one saturated test acquisition remains a recorded failure. Crash recovery, future redo UI and production deployment still require further work. The Django module is not implemented. See [Installation.md](Installation.md) for setup, [Proposal.md](Proposal.md) for the design, and [Discovery.md](Discovery.md) for findings.
