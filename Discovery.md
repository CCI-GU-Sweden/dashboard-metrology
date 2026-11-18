# Milestone 1: discovery and implementation decisions

## Scope and completion criteria

1. Inventory the test OMERO Metrology group: group ID and permissions, image and fileset counts, import-date range, available metadata, classification distribution, multi-image acquisitions, dimensions and pixel types. Inspect representative examples for each analysis type without copying sensitive image data into the repository.
2. Validate a dedicated service identity can authenticate without a browser token, read group images and pixels, and create/link and retrieve a test attachment. Record the precise group policy and minimum permissions. Use test-owned data and clean up only artifacts created for this check.
3. Characterize METEOR-view classification, metadata requirements, image grouping, measurements, thresholds and scoring against representative OMERO images. Record missing metadata, unsupported cases and output types; define reproducible test fixtures.
4. Verify the test `filestatistics` database, existing table names, schema ownership, roles and grants; propose migration and runtime identities without changing unrelated objects.
5. Specify deterministic ordering, eligibility, the ten-image limit, multi-image accounting, retry behavior and a bounded full-history backfill. Define acceptance checks for completeness and reconciliation.
6. Decide dashboard visibility and administrative permissions, deployment schedule, resource sizing and operational ownership. Record unresolved decisions explicitly; do not claim that inspection establishes policy.

Deliverable: update this document with evidence, reproducible safe commands, decisions, remaining unknowns and a concrete milestone 2 plan. Do not include credentials or sensitive metadata. Completion requires representative tests of both pixel access and attachment permissions, not merely cluster connectivity.

## Findings so far

- User uploaded representative images (about 600 MB) to test OMERO. Standard metrology CZI acquisitions map to one fileset with one or more images; nonstandard multiple-fileset acquisitions are outside scope.
- The daily limit is ten filesets, scheduled at 16:00 Europe/Berlin in test, where servers operate 09:00–17:00. Verify timezone support and completion before shutdown; monitor RAM, especially for PSF analysis.
- Staff can view results; administrators can change measurement status, including REDO. REDO queues work for the processor and does not run analysis in the dashboard.
- Fetch pixel size, channel count and, where needed, time dimension from OMERO metadata; verify units and values against representative acquisitions.
- Inspection confirmed no `metrology_*` tables before installation. SQL baseline 1 and the NOLOGIN `metrology_processor` privilege role were subsequently installed in `filestatistics-pg15` / `omerofilestats`; selected grants and nullable uniqueness passed a rolled-back check. Dedicated login `metrology_worker` and Secret `dashboard-metrology-db` were created; TCP login and schema-version SELECT passed.
- Test OMERO group Metrology has ID 103. Non-LDAP account `metrology_service` (ID 102) and Secret `dashboard-metrology-omero` were created in `core-omero-test`. Gateway login using the Secret succeeds; its sole listed group is Metrology. It sees 19 images and 11 filesets and reads a sample 600×600 plane. The account created and linked `dashboard_metrology_test_567.csv` (annotation ID 1098) to image 567 and read back its contents successfully. The test attachment remains on the image. Initial login failed because Windows line endings added a carriage return during provisioning; the account password was corrected to match the Secret.
- Metrology tables belong in `filestatistics-pg15` (`omerofilestats`), not the OMERO server's separate PostgreSQL database.
- Scope authorized by the user: `core-omero-test` namespace only. Local METEOR-view data is not being migrated; OMERO is the source for rebuilding history. Analysis belongs in a separate processor workload.
- Read-only workload inspection found one ready replica each for `omero-server`, `filestatistics-pg15` and `dashboard-django`. A Secret named `omero-server-root-password` exists; its contents and suitability for a processor have not been inspected. A dedicated least-privilege account remains the goal.
- A read-only query inside `filestatistics-pg15` identified database `omerofilestats` on PostgreSQL 15.18. This does not establish application grants or confirm the intended metrology schema.
- Representative analysis, end-to-end processor permissions and backfill policy remain to be checked. Cluster changes so far include the OMERO account, its Secret and test attachment, plus the initial database schema, roles and database credential Secret.

## Processor test, 18 November 2026

- Schema upgrades 2 (per-image analysis override) and 3 (durable artifact bytes) were applied to test PostgreSQL. A one-fileset worker job processed fileset 511, wrote one measurement and linked two result artifacts. Database role and completed-fileset deduplication were checked.
- The 10-fileset batch started fileset 510 and was OOM-killed at the 8 GiB limit while running METEOR-core ring-spread analysis. Its run remains `running` because the process was killed; the worker's retry path will pick it up, but should not be scheduled repeatedly until memory behavior is addressed. Metrics showed approximately 3.0 GiB, then 3.7 GiB and 5.5 GiB before termination.
- METEOR-core `RSF_analysis` parallelizes ring crops and accumulates upsampled ring volumes before averaging; this is a likely source of the memory growth, not a proven root cause. Profiling and an upstream bounded-memory implementation or validated resource-sizing change are needed. The latest local worker edits, including batched pixel reads, have not yet been rebuilt and end-to-end tested. Do not enable the daily CronJob on this basis.

## Retest with METEOR-core 3de0672

- Test image `sha256:1310c583ef0766de887fe8cf7c6b96cf819cfc301980a9485a6b0b87a76de2d2` uses the newer bounded-memory METEOR-core and current worker. The job created from the test CronJob processed ten eligible filesets in about 11 minutes: six succeeded and four were recorded as failures. Memory samples for the formerly failing ring analysis were below 1 GiB; a later ring acquisition sampled around 1.4 GiB.
- Two multi-image Plastic filesets and a PSF fileset required explicit overrides; retries completed all three. The intensity fileset 509 failed three times because the image contains saturated pixels and is marked permanent failure. No successful results were fabricated for it. Ten of eleven test filesets now have completed results; 38 measurements and 30 linked artifact records were present across them. Five artifacts for fileset 510 were independently fetched and checksum-verified against PostgreSQL.
- A subsequent job attempted zero filesets and succeeded, verifying the completed-run skip behavior. The older OOM-interrupted run for 510 was marked superseded. The CronJob is enabled for 16:00 Europe/Berlin, concurrency Forbid, with the image digest above. This is test-environment validation, not proof of crash recovery or a production resource guarantee. The UI for setting overrides and redo remains to be implemented; test overrides were added directly to the test database.
