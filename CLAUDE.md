# GCP / Cloud Run deployment

## Project

- **GCP project ID**: `project-691a3679-1653-40a3-93e` (project number `365888626215`)
- **Region**: `us-central1` for everything
- **Firebase project alias**: same project, used for Hosting (frontend)

## gcloud auth — READ THIS FIRST

`gcloud auth list` on this machine shows multiple credentialed accounts. **Only
`zabadymohamed8@gmail.com` has IAM access to this GCP project.** The other
accounts (e.g. `mohamed.zabady@studentgator.com`, the git commit author
identity) will fail with `PERMISSION_DENIED` on every `gcloud run`/`secrets`/
`storage` command against this project, even though they look like plausible
"the current user" accounts. If any `gcloud` command against
`project-691a3679-1653-40a3-93e` returns a permission error, run:

```
gcloud config set account zabadymohamed8@gmail.com
```

and retry before assuming the resource doesn't exist or access was revoked.

## Cloud Run services (all in `us-central1`)

| Service | Purpose | Image |
|---|---|---|
| `marketing-agent-backend` | The FastAPI app itself | built from this repo's `Dockerfile` |
| `docgen-pdf` | PDF generation MCP server (`generate_pdf_report_tool`) | `ghcr.io/cyanheads/docgen-mcp-server:latest` |
| `presenton` | PPTX generation MCP server (`generate_presentation_tool`) | `ghcr.io/presenton/presenton:latest` |
| `mcp-office-docs` | DOCX generation MCP server (`generate_word_document_tool`) | `georgx22/mcp-office-docs:latest` |

The last three exist only to back the artifact-generation chat tools
(`app/services/artifact_generation.py`, gated by `mcp_artifacts_enabled` in
`app/config.py`, currently defaulted to `True`). They are **not** part of
`docker-compose.yml`'s three sibling services in the same way locally —
locally those run via docker-compose with `UPLOAD_STRATEGY=LOCAL` and a
shared Docker volume; in production they're separate Cloud Run services
with no shared filesystem, so delivery works differently per service (see
below). Get current URLs any time with:

```
gcloud run services list --project=project-691a3679-1653-40a3-93e
```

### Quirks specific to each generation service, learned the hard way

- **`presenton` needs `--no-cpu-throttling`.** Its FastAPI backend does
  real startup work (spaCy/embedding models, template imports) in a
  background subprocess before answering any HTTP request. Cloud Run's
  default "CPU only during request handling" throttling starves that work
  indefinitely — the container never comes up, with **zero log output**
  (not even an error), just a permanent 502 on every `/api/*` route. Fixed
  by always-allocating CPU. If `presenton` ever needs redeploying, keep
  this flag.
- **`presenton`'s API key is per-instance, not portable.** Presenton mints
  API keys via `POST /api/v1/admin/api-keys` after logging in as the
  bootstrap admin (created from `AUTH_USERNAME`/`AUTH_PASSWORD` env vars on
  first boot). A key from one deployment's database is meaningless against
  a fresh one. If `presenton` is ever redeployed from scratch (not just
  updated), you need to re-mint a key:
  ```
  curl -c cookies.txt -X POST https://presenton-365888626215.us-central1.run.app/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"<value of PRESENTON_ADMIN_PASSWORD secret>"}'
  curl -b cookies.txt -X POST https://presenton-365888626215.us-central1.run.app/api/v1/admin/api-keys \
    -H "Content-Type: application/json" \
    -d '{"user_id":"<id from the login response>","label":"marketing-agent-backend","expiry_days":365}'
  ```
  Then store the returned `token` as a new version of the `PRESENTON_API_KEY`
  secret.
- **`presenton`'s MCP calls can take a while.** `start_standard_presentation`
  does real LLM work (outline expansion) before returning a task id — not
  an instant "accepted" response. `app/services/artifact_generation.py`'s
  `_CALL_TIMEOUT_SECONDS` (180s) exists specifically because 60s wasn't
  enough on a cross-Cloud-Run-service hop.
- **`docgen-pdf` (PDF)**: fully stateless, delivers the file as inline
  base64 in the MCP response — no shared storage needed. The base64 lives
  at `structuredContent.document.inlineBase64` (nested one level under
  `"document"` — easy to get wrong; `_extract_docgen_inline_bytes` handles
  this).
- **`mcp-office-docs` (DOCX)**: runs with `UPLOAD_STRATEGY=GCS` (not `LOCAL`
  like docker-compose), uploading to the `marketing-agent-office-docs` GCS
  bucket and reporting a signed download URL in its text response
  (`_extract_bytes_and_filename` downloads it directly). This needs two IAM
  bindings on the shared compute service account
  (`365888626215-compute@developer.gserviceaccount.com`):
  `roles/storage.objectAdmin` on the bucket, and — easy to miss —
  `roles/iam.serviceAccountTokenCreator` **on itself**, required to
  generate signed URLs from Cloud Run without a service account key file.

## Chat file attachments (any type, up to 2 GB)

Users can attach files of any type in chat (`app/routers/attachments.py`,
`app/services/attachment_processing.py`, `app/services/upload_storage.py`).

- **Bytes never pass through the backend in production.** Cloud Run caps
  request bodies at 32 MB, so the browser PUTs the file straight to the
  `marketing-agent-uploads` GCS bucket through a V4 signed URL
  (`UPLOAD_STORAGE=gcs`). Locally (`UPLOAD_STORAGE=local`, the default) it
  PUTs to the backend's own `.../attachments/{id}/content` route instead.
- **The bucket needs a CORS rule** allowing `PUT` + `Content-Type` from the
  Firebase Hosting origin(s). Without it, uploads fail in the browser with a
  CORS error and nothing shows in backend logs. The compute SA needs
  `roles/storage.objectAdmin` on the bucket. Signing reuses the
  `iam.serviceAccountTokenCreator`-on-itself binding described above for
  `mcp-office-docs`.
- **How the agent sees a file** (`ChatAttachment.kind`):
  - `gemini_file`: images, PDF, audio and video are uploaded to the Gemini
    File API and replayed as native media parts. **Gemini files expire after
    48 h.** `ensure_gemini_files` re-uploads from GCS when an older session
    is replayed.
  - `text`: DOCX/XLSX/PPTX and anything that decodes as UTF-8 are extracted
    locally, capped at `max_extracted_chars`.
  - `metadata_only`: everything else. The agent gets the name, type and
    size only.
- **Processing runs as a background task after `/complete` returns.** That's
  why `backend.yml` deploys with `--no-cpu-throttling`: with the default
  throttling, CPU stops between requests and processing (especially a large
  video's Gemini upload) stalls.

## Secret Manager

All secrets live in Secret Manager, project-scoped, referenced by `:latest`:

| Secret | Used by |
|---|---|
| `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `ADMIN_API_KEY`, `DATABASE_URL` | backend, since the first deploy |
| `LANGSMITH_API_KEY` | backend (tracing) |
| `PRESENTON_API_KEY` | backend, to call `presenton`'s MCP endpoint |
| `PRESENTON_ADMIN_PASSWORD` | not read by any app — kept only so a human/Claude can log into `presenton`'s admin UI/API later (see above) |
| `PEXELS_API_KEY` | the `presenton` service itself (image search for slides), not the backend |
| `MCP_OFFICE_DOCS_API_KEY` | backend, to call `mcp-office-docs`'s MCP endpoint (and set as that service's own `API_KEY`) |

The backend's runtime service account (`365888626215-compute@developer.gserviceaccount.com`,
the default compute SA — every Cloud Run service in this project uses it)
needs `roles/secretmanager.secretAccessor` on each secret it reads. New
secret → remember the IAM binding:

```
gcloud secrets add-iam-policy-binding <NAME> \
  --project=project-691a3679-1653-40a3-93e \
  --member="serviceAccount:365888626215-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## How a push to `main` becomes a live deploy

Two independent GitHub Actions workflows, both Workload-Identity-Federated
(no service account key files):

- **`.github/workflows/backend.yml`** — runs `pytest`, then builds+pushes the
  Docker image to Artifact Registry and runs `gcloud run deploy` against
  `marketing-agent-backend`. **Triggers only on push to `main` that touches**
  `app/**`, `alembic/**`, `alembic.ini`, `pyproject.toml`, `uv.lock`,
  `Dockerfile`, or the workflow file itself.
- **`.github/workflows/frontend.yml`** — builds the Vite app and deploys to
  Firebase Hosting. Triggers on push touching `frontend/**`, `firebase.json`,
  `.firebaserc`, or the workflow file itself.

**Gotcha**: `tests/**` is deliberately *not* in `backend.yml`'s path filter.
A commit that only changes a test file (e.g. removing/updating a test to
match a real behavior change) will NOT trigger a redeploy on its own, even
though the test suite gates the deploy step. If you need one, trigger it
manually:

```
gh workflow run backend.yml --ref main
```

(`workflow_dispatch` was added to `backend.yml` specifically for this.)

### Verifying a deploy actually happened

The image tag **is** the git SHA, so this is unambiguous:

```
gh run list --branch main --limit 3                     # did CI run + pass?
gcloud run services describe marketing-agent-backend \
  --project=project-691a3679-1653-40a3-93e --region=us-central1 \
  --format="value(spec.template.spec.containers[0].image,status.latestReadyRevisionName)"
```

Compare the image tag's SHA to `git log -1 --format=%H`. Also worth knowing:
CI ran and "succeeded" only tells you the *last* push's deploy step ran —
check `gh run list --workflow=backend.yml` for the specific commit, since a
test-only commit won't have a corresponding run at all (see gotcha above).

### One-off provisioning commands (new secrets, new Cloud Run services)

These aren't part of any CI workflow — they were run by hand (see git log
for the commits that added each sibling service). If you need to
re-provision or add a new one, `gcloud run deploy <name> --image=... ` needs
an explicit permission rule; see `.claude/settings.local.json` in this repo,
which allow-lists `gcloud run deploy`, `gcloud secrets create`, etc. for this
project.

## Local dev vs. production divergence to keep in mind

- Local: SQLite (`DATABASE_URL=sqlite:///./app.db`) or docker-compose
  Postgres. Production: a real Postgres via the `DATABASE_URL` secret (not
  Cloud SQL — no Cloud SQL instance exists in this project; the Sql Admin
  API isn't even enabled).
- Local: artifact-generation's three sibling services run via
  `docker-compose.yml` with `UPLOAD_STRATEGY=LOCAL` and a shared Docker
  volume (`MCP_SHARED_OUTPUT_DIR`). Production: separate Cloud Run
  services, no shared filesystem — DOCX uses GCS signed URLs instead (see
  above). `app/services/artifact_generation.py`'s `_extract_bytes_and_filename`
  handles both.
