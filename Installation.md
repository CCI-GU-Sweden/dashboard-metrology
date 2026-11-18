# Installation and setup

This is a step-by-step installation guide for the metrology module. **Current status:** SQL versions 1–3 are installed in `core-omero-test`; a full batch was run with the newer METEOR-core, and a daily test CronJob is enabled. One saturated acquisition failed. The Django package, dashboard registration and UI are not implemented. Do not deploy this guide unchanged to production.

## 1. Prerequisites and target

1. Select the intended environment and verify its namespace, PostgreSQL host, database and OMERO server. The current test target is namespace `core-omero-test`, deployment `filestatistics-pg15`, database `omerofilestats` (PostgreSQL 15), OMERO service `omero:4064`, group `Metrology` (ID 103). These identifiers are environment-specific.
2. Obtain a database setup identity with the ability to create roles and tables and grant privileges, and the existing dashboard database role name. Baseline SQL currently assumes the role `filestats_dashboard`; adapt and review it for other environments. Backup the shared database and review existing objects and roles before applying changes. The script stops on collisions rather than adopting or altering unknown objects.
3. Prepare an OMERO service user with password login and access to the Metrology group. Confirm it can read representative pixels and create and link file annotations on other users' images. In test, `metrology_service` and Secret `dashboard-metrology-omero` already exist; image 567 has a verified test CSV attachment. Restrict Secret access and rotate credentials under local policy.
4. Agree schedule and timezone, resource limits, backlog policy and monitoring. In test the proposed schedule is 16:00 Europe/Berlin daily, within the 09:00–17:00 server window. Measure peak PSF memory and job duration before setting production limits.

## 2. Install database baseline

1. Review [sql/001_initial.sql](sql/001_initial.sql). It creates `metrology_*` tables, indexes, schema version 1 and the restricted `metrology_processor` **NOLOGIN** privilege role in a single transaction. It grants dashboard SELECT, measurement-status UPDATE and action INSERT; it does not itself enforce user-level authorization. The future Django views must enforce staff/admin access and audit changes. No data from the local Flask database is imported.
2. For the test environment only, from the repository root run:

   ```powershell
   python scripts/apply_test_schema.py
   python scripts/verify_test_schema.py
   ```

   The first command has already been run on the current test database. **Do not rerun it on an installed database**: it deliberately fails on existing objects and rolls back. The verification command checks selected privileges and nullable lens uniqueness within a rolled-back transaction. For another environment, have the database operator apply the reviewed SQL with `psql -v ON_ERROR_STOP=1` as the setup identity and run the verification with the appropriate role names.
3. Apply `sql/002_analysis_override.sql` then `sql/003_artifact_payload.sql` once, using the same controlled setup identity. Check `SELECT max(version) FROM public.metrology_schema_version;` returns `3`, and inspect grants and table ownership with the target identities. These upgrades have already been applied in test. A future revision must have an ordered upgrade script; `001_initial.sql` is a baseline, not a general-purpose migration or collision-reconciliation tool. SQL is currently the schema authority; future Django models must map this baseline and its upgrade process rather than independently recreating it.
4. Provision a **separate login identity** for the processor using the database operator's approved credential workflow. Grant it membership in `metrology_processor`, configure its password as a Kubernetes Secret, and verify it inherits the required privileges and cannot modify unrelated tables or perform DDL. `metrology_processor` itself cannot log in. In test, login `metrology_worker` and Secret `dashboard-metrology-db` have been created; TCP login and schema-version SELECT succeeded. Avoid embedding credentials in SQL, shell history, manifests or this repository. The application connection must have only the privileges needed for its dashboard/management-command dependencies in addition to module tables; decide and test those grants when the command is implemented.

## 3. Install and register the Django module — pending implementation

1. Build and publish a versioned package containing the app, templates, static assets and compatible SQL upgrades. Pin that release/commit in the dashboard core's requirements. For local development only, the dashboard contract supports `pip install -e ./modules/dashboard-metrology --no-deps` once the package exists. Local `modules/` checkouts are ignored by the core and are not copied into its image.
2. In dashboard settings add the opt-in `DASHBOARD_METROLOGY_ENABLED` switch, app and module descriptor as shown in [Proposal.md](Proposal.md). The descriptor registers URLs. Implement endpoint-level role checks: staff may view; admins may request status changes and REDO. REDO must enqueue processor work, never run image analysis in the web process.
3. Rebuild the dashboard image, run `collectstatic`, and deploy through the normal dashboard rollout. Configure the existing dashboard database credentials. Verify disabled and enabled behavior, pages, APIs, audit records and denial for unauthorized users.

## 4. Install and run the processor — test validation in progress

1. Build `Dockerfile.processor` and pin the resulting image digest. It runs `python -m metrology_processor.worker`, separately from the dashboard, using the OMERO client/Ice runtime and the pinned METEOR-core commit. The example base image is specific to the test registry; configure an appropriate equivalent elsewhere. `MPLBACKEND=Agg` and writable OMERO temporary directories are set in the image. Test memory and scratch limits with representative images; scientific transitive dependencies still require a reproducible lock and compatibility validation.
2. Supply the OMERO Secret and the separate processor database login Secret to the job, with host, port, database, group and image configuration supplied separately. Do not mount these credentials into the dashboard web container unless a specifically authorized feature requires them.
3. Run an explicit one-off test job against test OMERO, then deploy [deploy/cronjob.example.yaml](deploy/cronjob.example.yaml) with a verified image digest for up to ten eligible **filesets** daily. The current test deployment is recorded in [deploy/cronjob.test.yaml](deploy/cronjob.test.yaml). It uses `timeZone: Europe/Berlin`, `concurrencyPolicy: Forbid` and an 8 GiB limit; verify cluster support, size and completion before test servers stop. The worker defaults to 10 filesets, loads input calibration in micrometres from OMERO key-value annotations, and reads `METROLOGY_OMERO_PORT` (default 4064) rather than OpenShift's injected `OMERO_PORT`. Verify rows and OMERO attachments, repeat the job and verify no duplicates.
4. Run the controlled backfill of existing OMERO history, monitor backlog, failures, memory and attachments, and reconcile the results. Local METEOR-view data is not migrated. Set up alerts for failures, stale runs and storage or memory exhaustion.

## 5. Upgrade, recovery and verification

Review backups and schema ownership before each ordered upgrade; apply the upgrade once as the setup identity, update grants for new objects, deploy compatible images, and test login, permissions, pages, processing and attachment reconciliation. Rollback must follow the specific release's documented procedure; disabling the module must not delete data. Cross-system writes need recovery because PostgreSQL and OMERO do not share transactions. Reconcile pending runs and artifacts after interrupted jobs. Never log passwords or tokens.
