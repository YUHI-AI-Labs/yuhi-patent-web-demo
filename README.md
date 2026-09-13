# Yuhi Patent — CAD Search Demo (public)

Upload a STEP/STL file, get an actual `yuhi-cad` analysis (the same
deterministic geometry engine the desktop app uses), and search the real
JPO gazette corpus using terms derived from the extracted part names.

This is **not** the full product. No AI is configured here, so there is no
Japanese semantic-labeling step — search quality depends on the uploaded
file's own part names plus a small built-in English→Japanese glossary
(`glossary.py`). Match badges are a simple substring heuristic, not the
desktop app's claim-level comparison. See the in-app note for the full
disclosure shown to visitors.

Uploaded files are processed in a temp directory and deleted immediately
after analysis (`shutil.rmtree` + the `TemporaryDirectory` context both
clean up); nothing is persisted.

## Why this needs real hosting (not Streamlit / not Vercel)

- `cadquery-ocp` bundles OpenCascade — a large native geometry kernel, well
  past Vercel's serverless function size limit and not something Streamlit
  Community Cloud is built to run.
- Analysis of a real file can take several seconds to tens of seconds, past
  typical serverless execution-time limits.
- It needs a normal long-running container with real memory (OpenCascade +
  a loaded SQLite corpus comfortably wants ~1GB RAM).

## Local run

Requires Python 3.11+ (cadquery-ocp does not have wheels for older or newer
versions on every platform — check current availability before deviating).

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install ./cad-worker
# patents.db is already committed in this repo (~80MB, real JPO corpus)
.venv/bin/uvicorn app:app --reload --port 8080
```

Then open http://localhost:8080.

## Deploying

### Option A: Render.com (recommended — no local Docker needed)

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. On [render.com](https://render.com), New → Web Service → connect this repo
   (`YUHI-AI-Labs/yuhi-patent-web-demo`).
3. Render will pick up `render.yaml` (Docker runtime, root `Dockerfile`).
4. Pick an instance size with **at least 1GB RAM** — OpenCascade + a loaded
   corpus will not fit comfortably in Render's smallest free tier. This is a
   paid instance (a few dollars a month), not free.

### Option B: Fly.io

Needs `flyctl auth login` (interactive browser login) once, then, from this
repo's root:

```bash
flyctl launch --config fly.toml --no-deploy
flyctl deploy --config fly.toml
```

`fly.toml` scales to zero machines when idle (`min_machines_running = 0`),
so idle cost is close to nothing, but a cold start after idling will be slow
(container boot + loading OpenCascade).

## Security notes for whoever deploys this

- Upload size capped at 20MB, extension allowlist (`.step`/`.stp`/`.stl`),
  analysis subprocess timeout at 45s — all in `app.py`. Tune before wide
  traffic.
- No rate limiting is implemented yet. Add one (e.g. at a reverse proxy, or
  `slowapi`) before linking this from anywhere with meaningful traffic.
- CORS is locked to `https://yuhi-ai-labs.vercel.app` in `app.py`.
