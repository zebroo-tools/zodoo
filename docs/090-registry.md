# Using the Docker Registry

zodoo can push and pull all Docker images (including base images like postgres, redis, etc.) to/from a private Docker registry. This speeds up deployments on production systems — no local builds needed.

## Push (build server / developer machine)

### 1. Configure the registry URL

```bash
odoo setting HUB_URL=registry.zebroo.de:443/myprojectname
odoo setting DOCKER_IMAGE_TAG=latest
```

### 2. Login

```bash
odoo docker-registry login
```

There are no shared default credentials for registry.zebroo.de — every user has
their own account. You only need one to **push**; see
[Pulling needs no account](#pulling-needs-no-account) below.

`odoo build` asks for an account at the point where it would upload something,
and stores user and password in `~/.odoo/settings`. A freshly requested account
can read but not write yet — ask an admin for push rights at
https://registry.zebroo.de/admin.

Note that `docker login` cannot tell you whether your credentials are correct:
registry.zebroo.de answers the version endpoint without a challenge (that is
what makes anonymous pulling possible), so the client reports success for any
password. zodoo checks the credentials itself against an endpoint that is still
protected and says so when they are rejected.

### When a push ends in 401

The same anonymous `/v2/` bites harder on the way out. The classic docker
client probes `/v2/` at the start of a push session, gets `200`, concludes no
authentication is needed — and then sends the **entire session without
credentials**. Everything appears to upload, and the final manifest PUT fails
with `401`. Only clients using the containerd image store are unaffected,
which is what made this so confusing: it worked on one machine and on no other.

`registry-push.zebroo.de` points at the same server but demands
authentication everywhere, so a push works with any client:

```bash
docker login registry-push.zebroo.de
```

Verified on 06.09.2026: both names resolve to 46.254.140.82; `/v2/` answers
`200` on `registry.zebroo.de` and `401` on `registry-push.zebroo.de`. Pull
over the anonymous name, push over the other one — it is the same stock, which
is what the CI does (`ZODOO_REGISTRY_PUSH_URL`, see
`.github/workflows/prebuild-images.yml`).

zodoo does this on its own: as long as `ZODOO_REGISTRY_URL` is the default
`registry.zebroo.de`, `odoo build` pulls from there and pushes to
`registry-push.zebroo.de` — with the same account, nothing to set up. To push
somewhere else, set the push address explicitly; pulls are not affected:

```bash
odoo setting ZODOO_REGISTRY_PUSH_URL=registry-push.example.com
```

For any other `ZODOO_REGISTRY_URL` without a push address, zodoo pushes to the
pull address as before.

### 3. Build images

```bash
odoo build
```

### 4. Push

```bash
odoo regpush
```

All images (Odoo, postgres, proxy, etc.) are pushed. Image tags include a SHA-based identifier.

---

> This project registry (`HUB_URL` / `REGISTRY=1`, push and pull below) is
> for deploying a specific project's images to production or a customer
> system — a manual, per-project setup. It's separate from the anonymous
> build-cache registry described in
> [Pulling needs no account](#pulling-needs-no-account), which just speeds up
> local builds and needs no configuration.

## Pull (production / target system)

### 1. Configure the same registry URL and enable registry mode

```bash
odoo setting HUB_URL=registry.zebroo.de:443/myprojectname
odoo setting REGISTRY=1
odoo setting DOCKER_IMAGE_TAG=latest
```

`REGISTRY=1` rewrites all image references to point to `HUB_URL` and disables local builds.

### 2. Login

```bash
odoo docker-registry login
```

### 3. Pull

```bash
odoo regpull
```

### 4. Start

```bash
odoo up -d
```

---

## Pulling needs no account

Separate from the project images above, zodoo keeps a **build cache** in the
same registry, and reading from it costs nothing to set up.

`registry.zebroo.de` serves the prebuilt CPython image (`zodoo/python`)
anonymously. That is the one that matters on a fresh machine: without it, the
build compiles CPython locally, which takes about a quarter of an hour. The
registry URL already has a default, so this works with no configuration at all
— there is no question to answer and nothing to log in to.

Everything else stays behind the login: the per-service cache images
(`zodoo-*`), every project namespace, and `/v2/_catalog` — the repository
listing names customers, so it is not public.

| Setting                    | Description                                                                                        |
| -------------------------- | -------------------------------------------------------------------------------------------------- |
| `ZODOO_REGISTRY_URL`       | Default `registry.zebroo.de`                                                                       |
| `ZODOO_REGISTRY_PUSH_URL`  | Push target; empty = `registry-push.zebroo.de` for the default registry, else `ZODOO_REGISTRY_URL` |
| `ZODOO_REGISTRY_USERNAME`  | Only needed for pushing                                                                            |
| `ZODOO_REGISTRY_PASSWORD`  | Only needed for pushing                                                                            |
| `ZODOO_REGISTRY_SUGGESTED` | `0` opts out completely — no pulls, no account, no questions                                       |

Do not confuse this with the `REGISTRY=1` setting above: that one rewrites all
image references to `HUB_URL` and blocks local builds, which is meant for
production systems and would break a development machine.

### Background uploads (job queue)

`odoo build` does not push the cache images itself. It writes one job per
upload to `~/.odoo/run/<project>/jobqueue/` and starts a detached
`odoo run-crontab`, which runs with the same project name and `-xs`/`-xd`
files as the build. Its output lands in `jobqueue/log/worker_<time>.log`.

| File                         | Meaning                  |
| ---------------------------- | ------------------------ |
| `<id>.json`                  | waiting                  |
| `<id>.json.processing.<pid>` | a worker is uploading it |
| `<id>.json.failed.<n>`       | failed `n` times         |

A failed upload is retried by the next `odoo run-crontab` (started by the next
build, or by hand): at most `ZODOO_JOBQUEUE_MAX_ATTEMPTS` times in total, not
before `ZODOO_JOBQUEUE_RETRY_DELAY_MINUTES` have passed, and only while the job
is younger than `ZODOO_JOBQUEUE_RETRY_MAX_AGE_HOURS`. Older failed jobs stay as
they are; look at the worker log, then delete them.

### How the cache images get there: prebuild with CVE scan

The CI workflow `Prebuild generic images`
(`.github/workflows/prebuild-images.yml`) builds the project-independent
`zodoo-*` images (postgres, proxy, cronjobs, …) and uploads them. Before
anything is uploaded, every image is scanned for known vulnerabilities with
[Trivy](https://trivy.dev):

1. `odoo build --no-zodoo-push <services>` builds the images. Without the flag
   `odoo build` would queue the upload itself, before any scan.
2. `.github/scripts/trivy-scan-images.sh` scans exactly the local images that
   `odoo zodoo-push` uploads (`<project>-<service>`, the same rule as
   `_local_image_name()` in `lib_zodoo_registry.py`; the project name comes
   from `odoo setup status`). If either changes, adapt the script too — a
   mismatch fails the job, it never scans the wrong image. The log shows the
   image ID of every scanned image; right before the push the script checks
   that the IDs are still the same.
3. `odoo zodoo-push <services>` uploads them.

Trivy is a pinned release binary, checked against its SHA-256 before use
(`TRIVY_VERSION` / `TRIVY_SHA256` in the workflow). There is deliberately no
override through repository variables: a new version means a PR that changes
both values together.

**Report.** The job summary shows a table per Odoo version: per image the
number of CRITICAL, HIGH and MEDIUM findings, the fixable ones in brackets.
The full reports (JSON and a readable table per image) are attached to the run
as the artifact `trivy-reports` (kept 14 days). The repository is public, so
any GitHub user can download the artifact. The JSON reports therefore leave
out the image config (environment variables, build history). The CVE list
itself stays in: the images are pulled anonymously, so anyone can scan them
anyway.

**Findings do not fail the job.** The scan reports, it does not block; a
threshold is a separate decision.

**A failing scan does (fail-closed).** If the vulnerability database cannot be
downloaded, Trivy exits with an error, an image is missing or changed after the
scan, the job fails and `odoo zodoo-push` does not run — nothing is uploaded.

**Manual test run.** Start the workflow by hand (Actions → Prebuild generic
images → Run workflow, or `gh workflow run prebuild-images.yml --ref <branch>`)
with these inputs:

| Input                | Default       | Effect                                                            |
| -------------------- | ------------- | ----------------------------------------------------------------- |
| `versions`           | `19.0,20.0`   | Odoo versions to build                                            |
| `services`           | empty (= all) | Space-separated subset, e.g. `postgres` (only `a-z`, `0-9`, `_`)  |
| `push`               | on            | Off: build and scan only, `zodoo-push` is skipped                 |
| `force_scan_failure` | off           | Makes the scan fail on purpose, to check that nothing is uploaded |

Push and scheduled runs always use the defaults, so they always upload.

Only the CI prebuild is scanned. Images that `odoo build` uploads from a
developer or customer machine go to the registry without this scan.

---

## Self-signed certificates

If your registry uses a self-signed TLS certificate:

```bash
odoo docker-registry self-sign-hub-certificate
```

---

## Settings reference

| Setting            | Description                                                            |
| ------------------ | ---------------------------------------------------------------------- |
| `HUB_URL`          | Registry URL: `user:password@host:port/path` or `host:port/path`       |
| `REGISTRY`         | `1` = force pull from registry, block local builds (use on production) |
| `DOCKER_IMAGE_TAG` | Tag for images (e.g. `latest`, `v1.2.3`, `main`)                       |
