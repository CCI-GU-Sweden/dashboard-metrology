# Proposal: dashboard metrology plugin

Status: design proposal, 18 November 2026. Examples are illustrative and require implementation and testing. No database or OMERO configuration has been changed.

## Goals and existing foundations

Create an installable Django module, an OMERO metrology processor running as a CronJob, and versioned tables in the existing `filestatistics` PostgreSQL database. Reuse [METEOR-core](https://github.com/CCI-GU-Sweden/METEOR-core) for algorithms and METEOR-view for classification, scoring, outputs and UI behavior. Dashboard authentication and permissions remain authoritative.

Existing local METEOR-view data does not need to be retained or migrated. Recalculate the history from the existing images and metadata in OMERO. The dashboard web application only reads and presents results and handles permitted configuration and administrative actions; it must never execute image analysis. Analysis runs exclusively in the separate scheduled processor workload. A manual retry, if offered, only queues work for that processor.

The dashboard's `MODULE_CONTRACT.md` defines trusted in-process modules, opt-in registration, independent endpoint authorization, PostgreSQL 15 support and module-owned setup and deployment. Core settings and an image rebuild are needed; installing this repository alone will not activate a module.

References examined: local METEOR-core commit `eb0627a5760efb5c565913bef2a442532c647b6e` (Python 3.10–3.12); local METEOR-view commit `20a2ad04994f3aa0bd3dac94eed885825bc444f7` plus working-tree changes. Verify the reference version before porting. The dashboard image currently uses Python 3.12. Pin and test compatible METEOR-core, scientific, OMERO client and Ice dependencies in Linux images; no CZI reader is needed to retrieve OMERO pixels.

METEOR-view already uses `getPrimaryPixels().getPlane(z, c, t)` to assemble a `TCZYX` NumPy array. Its classifier selects ring, intensity, PSF/bead, plastic, stairs and star analyses from names; ring images invoke several algorithms. Plastic uniformity combines images from one fileset. The current batch loop selects the first image per unprocessed fileset, ordered by descending fileset ID: that differs from the requested latest ten images. Existing attachment code catches failures and deletes temporary files, so it needs redesign for reliable retries.

## Architecture and packaging

```text
                  OMERO Metrology group
               pixels + metadata | ^ file annotations
                                  v |
 CronJob -> management command -> processor -> METEOR-core
                  |                   |
                  +---- PostgreSQL filestatistics ----+
                                                     |
 ORCID login -> dashboard -> metrology Django app -> pages / APIs
```

Proposed repository layout:

```text
dashboard_metrology/             # Django app and unique Python package
  apps.py dashboard_module.py urls.py views.py models.py
  services/                     # discovery, OMERO, analysis, scoring, persistence
  management/commands/process_metrology.py
  migrations/ templates/dashboard_metrology/ static/dashboard_metrology/
deploy/                          # example setup Job, CronJob and grants
tests/                           # unit, integration, packaging and authorization
```

Package templates, static files and migrations using `pyproject.toml`; preserve attribution and applicable licenses for copied code. Put analysis execution and its scientific dependencies in the separate processor image; dashboard requests must not execute analysis. The processor may use a Django management command in its own workload for database access, but the dashboard web processes never run that command. The core pins a module release or commit in `requirements.txt` (local `modules/` checkouts are ignored and excluded from the image), enables `DASHBOARD_METROLOGY_ENABLED`, registers the app and descriptor, and runs `collectstatic`. The descriptor supplies the URLs; do not include them a second time.

## Processor and OMERO

1. Use a dedicated service user in the Metrology group, authenticating with username/password from an OpenShift Secret. No browser token or interactive login. Verify group policy in test: reading pixels and metadata is read-only, but **creating and linking attachments requires OMERO write permission** on the images. If necessary use a separate authorized writer; root is a fallback only if access cannot otherwise be granted. Restrict Secret access, rotate credentials and never log them. The web container need not receive processor credentials unless a figure proxy requires them.
2. Select the configured group by stable ID, verify the intended group and fail closed on access errors. Query images using deterministic descending OMERO import/creation time and image ID as tie-breaker, via a server-side ordered paginated query and cutoff snapshot. Record acquisition and import timestamps if available; acquisition dates can be missing or inaccurate. Verify the exact query and timestamp field against the deployed OMERO version. Do not silently substitute fileset ID for time.
3. Each daily run attempts up to **ten eligible filesets**, prioritizing newest unprocessed filesets. Persist discovery and processing state; exclude permanent failures until an authorized retry and apply bounded retries/backoff to transient failures. Monitor backlog and use bounded oldest-first catch-up if continuous arrivals starve older filesets.
4. A standard metrology CZI corresponds to one fileset containing one or more images; nonstandard multiple-fileset acquisitions are outside scope. Analyze each fileset with an input manifest and record contributing image IDs. Plastic uniformity may need multiple fileset images; they count as one fileset toward the limit. Unknown classification, missing metadata and unavailable required pixels become explicit failures, not successful empty results.
5. Fetch metadata and planes directly. Validate axes, physical pixel sizes/units, channel/time selection and dimensions against algorithm requirements. Check memory based on actual dtype and dimensions before allocation; stream planes into an array or bounded scratch space, without downloading the original CZI. METEOR-core consumes arrays, so streaming does not eliminate whole-stack memory use. Size CPU, memory, deadlines and scratch from representative images. Use a noninteractive Matplotlib backend.
6. Invoke METEOR-core through a tested adapter and normalize measurements, units, status, provenance and figures. Characterize existing scoring and thresholds, including PSF GIF/OME-TIFF and figure outputs. Store measurements in PostgreSQL and link artifacts as OMERO FileAnnotations using a module namespace, MIME type and stable identity. Track algorithm version, input identity, settings and annotation IDs; never silently overwrite history.

For the initial rebuild, discover the full eligible OMERO history and process it in bounded batches of ten filesets across successive jobs. Measure and report the remaining backlog and estimated completion rate; use oldest-first catch-up or a separately controlled backfill if new arrivals would otherwise starve historical work. Coordinate backfill and the regular CronJob through the same claims and idempotency rules. Reconcile any existing OMERO attachments by stable identity where possible to avoid accumulating duplicates; local Flask results are not a migration source.

### Recovery and idempotency

PostgreSQL and OMERO do not share a transaction. Use durable states such as `pending -> running -> analyzed -> attaching -> complete`, with attempt counters, leases and failure details. In short DB transactions claim a unique logical input/version, write measurements and a durable artifact manifest/outbox. Upload and link outside the transaction, record verified annotation IDs, and mark complete only when all required outputs are confirmed. On restart reconcile against OMERO using a stable run/artifact key before creating again. Handle crashes after upload but before recording IDs, orphaned unlinked annotations, stale leases, deleted images and inaccessible attachments. Persist artifact bytes in durable storage or provide deterministic regeneration and reconciliation. Test every crash window before claiming exactly-once behavior.

Use `concurrencyPolicy: Forbid` plus database claims/locks for manual runs and multiple CronJobs. Enforce uniqueness of run, measurement and artifact identities. Database, authentication and discovery failures should exit nonzero; report partial failures and define exit behavior so retries do not spin. Do not automatically reset data.

Illustrative connection and plane reading (the API and deployed group permissions need integration testing):

```python
import os
from omero.gateway import BlitzGateway

conn = BlitzGateway(os.environ['OMERO_USER'], os.environ['OMERO_PASSWORD'],
                    host=os.environ['OMERO_HOST'], port=int(os.environ.get('OMERO_PORT', '4064')))
try:
    if not conn.connect():
        raise ConnectionError('OMERO authentication failed')
    conn.setGroupForSession(int(os.environ['OMERO_METROLOGY_GROUP_ID']))
    image = conn.getObject('Image', image_id)  # validate image and group
    pixels = image.getPrimaryPixels()
    plane = pixels.getPlane(z, c, t)  # assemble validated TCZYX input as needed
finally:
    conn.close()
```

Add timeouts, validation and robust exception handling; never log credentials or tokens. Use supported OMERO file-annotation and link APIs and verify resulting links with the service identity.

## Database and roles

Use the dashboard's PostgreSQL 15 connection to `filestatistics`, with unique `metrology_*` table names. The versioned SQL baseline is currently the schema authority; future Django models and upgrades must map to it without recreating its tables. A one-shot setup Job uses a provisioned setup identity; web and collector roles do not get DDL. Inspect existing tables/owners and back up before migration. Fail on collisions or incompatible schemas; never drop existing data. Version and document setup and grants. Role creation is a controlled DBA operation, not a web request.

| Entity | Purpose and constraints |
| --- | --- |
| Microscope | Stable identity/name, optional location and external ID; explicit uniqueness policy. |
| Objective lens | Microscope FK, magnification, NA and optional serial; handle nullable NA explicitly, rather than assuming PostgreSQL NULLs are equal. |
| Analysis run and input | Server/group/image/fileset IDs, input manifest, acquisition/import time, category, algorithm/config version, state, attempts and error; unique logical key and indexed selection/state. |
| Measurement | Run, microscope and lens references, metric/category, numeric value, unit, timestamp, status and score; unique per metric/channel or other required dimension. |
| Artifact/outbox | Run, stable artifact key, MIME, checksum, durable location or regeneration data, annotation ID and upload/link state. |
| Threshold and settings | Versioned thresholds/bounds and validated settings, with audit history; include category in natural keys where needed. |
| Score aggregates | Lens/metric, category, objective and microscope scores with period and scoring version; reproducible from measurements and thresholds. |

METEOR-view currently defines `microscopes`, `objective_lenses`, `measurements`, `lens_scores`, `category_scores`, `objective_lens_scores`, `microscope_scores`, `thresholds` and `application_settings`. These are references for the new model and scoring behavior, not tables to import: rebuild historical results from OMERO. Validate timestamps, units, statuses, thresholds and nullable uniqueness against representative acquisitions. Ordinary PostgreSQL unique constraints with nullable columns do not guarantee logical uniqueness. Protect and back up the shared `filestatistics` database and document rollback and forward migrations; no deletion of existing shared database objects is implied.

Give the web identity SELECT and only the additional narrowly scoped writes needed for enabled administrative features; the collector gets necessary SELECT/INSERT/UPDATE and sequence privileges; a controlled setup identity owns migrations. Use explicit grants and review default privileges for future migrations. Provision login secrets separately from role/grant SQL. Test permitted and denied operations with actual deployment identities. Account for Django migration metadata on the shared database.

Illustrative model, omitting other fields and migrations:

```python
class AnalysisRun(models.Model):
    source = models.CharField(max_length=200)  # stable OMERO server identity
    image_id = models.BigIntegerField()
    analysis_version = models.CharField(max_length=100)
    state = models.CharField(max_length=20, default='pending')

    class Meta:
        db_table = 'metrology_analysis_run'
        constraints = [models.UniqueConstraint(
            fields=['source', 'image_id', 'analysis_version'], name='metrology_run_identity')]
```

For multi-image acquisitions the final identity must use a canonical acquisition/manifest and configuration identity instead of blindly relying on this simplified image key.

## Django views and permissions

Port Flask templates and JavaScript to namespaced Django templates extending the dashboard base; translate `url_for`, JSON endpoints and CSRF handling. Use shared dashboard styling and accessible responsive controls.

| Existing Flask feature | Proposed Django destination |
| --- | --- |
| Metrology, microscope/lens/category scores and plots | Landing and drill-down pages with history, status and last successful analysis. |
| Measurements, filters, figure previews and exports | Paginated and filtered measurements, authorized figures and bounded/streamed CSV export. |
| Thresholds and settings | Validated, audited staff/admin configuration with explicit score recomputation. |
| Errors, retry and ignore | Failure details, authorized POST retry/ignore, durable queue and audit trail. |
| Help pages | Adapt explanations, measurement units and thresholds. |
| Flask OMERO login and background thread | Dashboard login and scheduled/controlled worker; no request-scoped OMERO token or in-process job state. |

Initially restrict pages, APIs, exports and figures to operational dashboard users using `operational_access`; require admin authorization for settings and mutations unless a more specific policy is agreed. Every endpoint independently enforces authentication, active/approved role and scope; descriptor visibility alone is insufficient. Use Django CSRF protection and audit mutations. Define microscope/image-level ownership before granting researcher access. Use an authenticated authorized figure proxy or appropriate existing OMERO link, never expose credentials or make attachments public. Define behavior for missing/inaccessible artifacts. Avoid porting the destructive Flask reset endpoint to routine UI.

Illustrative descriptor and core registration:

```python
# dashboard_metrology/dashboard_module.py
from accounts.permissions import operational_access
from dashboard.modules import DashboardModule

def overview_metrics(user):
    return []  # replace with authorized, JSON-serializable metrics

module = DashboardModule(key='metrology', name='Metrology', eyebrow='Microscope health',
                         icon='◈', url_name='metrology_home',
                         urlconf='dashboard_metrology.urls', can_view=operational_access,
                         get_metrics=overview_metrics)

# dashboard/settings.py, after initialization of INSTALLED_APPS and DASHBOARD_MODULES
if os.environ.get('DASHBOARD_METROLOGY_ENABLED', '0') == '1':
    INSTALLED_APPS.append('dashboard_metrology')
    DASHBOARD_MODULES.append('dashboard_metrology.dashboard_module.module')
```

## Deployment example

Build a pinned processor image with the dashboard management-command environment, module, METEOR-core and compatible OMERO/Ice dependencies. This example only shows wiring; provision the image, secrets, database configuration and service account first. Replace placeholders, never commit secret values, and run schema setup before enabling the job.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: dashboard-metrology
spec:
  schedule: '0 16 * * *'
  timeZone: 'Europe/Berlin' # verify support in the target cluster
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 3600
  jobTemplate:
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: 14400
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: processor
              image: 'registry.example/dashboard-metrology@sha256:...'
              command: ['python', 'manage.py', 'process_metrology', '--fileset-limit', '10']
              envFrom:
                - configMapRef: {name: dashboard-metrology-config}
                - secretRef: {name: dashboard-metrology-credentials}
              resources:
                requests: {cpu: '500m', memory: '1Gi'}
                limits: {cpu: '2', memory: '4Gi'}
```

Config includes OMERO host/port/group ID, DB host/name and feature enablement; Secret includes `OMERO_USER`, `OMERO_PASSWORD`, `PGUSER`, `PGPASSWORD` and required Django runtime secrets. Use separate environment and setup/web/collector credentials. Validate schedule, timezone support, limits, network policy, TLS trust, arbitrary non-root UID, scratch space and deadlines on the target OpenShift cluster. Monitor last success, backlog age, failed/retried analyses, partial attachments and job timeouts; document rotation and recovery.

## Delivery and acceptance

The following is the proposed step-by-step implementation and rollout sequence; each stage should pass its checks before the next is deployed.

1. Complete the detailed discovery and acceptance criteria in [Discovery.md](Discovery.md): inventory OMERO acquisitions and metadata, verify permissions and database roles, characterize analysis, and decide backfill and scheduling semantics.
2. Implement package, descriptor, migrations and role/setup documentation; test PostgreSQL 15 empty install, repeated setup, collision/upgrade handling and grants.
3. Characterize classification, metadata/plane adapter and METEOR-core results against METEOR-view, including all analysis types and multi-image filesets. Pin and build processor dependencies.
4. Implement scheduler/claims, reconciliation, retries and attachments; test crash windows, parallel/manual runs, duplicates, authorization failures, oversized images and cleanup with disposable PostgreSQL and an OMERO test group.
5. Port pages, APIs, charts, thresholds, exports, errors and help. Test authorization, CSRF, scoping, no-data/unavailable behavior, score parity and accessibility; exercise enabled/disabled module, overview and packaged static assets with dashboard tests.
6. Build both images and `collectstatic`; run end-to-end on representative test images in the test cluster, confirm results in both systems, observe repeated runs and failures, verify resource use, then document rollout, backups and rollback before production.
7. Run the controlled historical OMERO backfill, monitor progress and fa ilures to completion, reconcile measurements and attachments, then continue the regular scheduled processing. The dashboard only displays status and results throughout.

Open decisions: exact timestamp for newest and backlog handling; OMERO writer/group policy and service account; DB roles and grants; retention, artifact retry storage and operational alert ownership. Test runs are scheduled at 16:00 Europe/Berlin, within the 09:00–17:00 server window; monitor job duration and PSF memory use. Staff can view results and administrators can change measurement status, including REDO, which queues processing. Confirm environment and identities before provisioning credentials or changing the cluster.
