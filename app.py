"""Public CAD-search demo for Yuhi Patent.

Accepts a STEP/STL upload, runs the real yuhi-cad analysis engine (the same
deterministic geometry/assembly parser the desktop app uses) as an isolated,
time-boxed subprocess, then searches the real JPO gazette corpus using terms
derived from the extracted part names.

Honesty notes shown to the user, and true here:
- No AI is configured, so there is no semantic/Japanese-labeling step (the
  desktop app's "AIが設定されていない" degraded path). Search quality depends
  on the uploaded file's own part names via a small EN->JA glossary.
- Match badges are a simple substring heuristic over title/abstract, not the
  desktop app's full claim-level comparison.
- Uploaded files are processed in a temp directory and deleted immediately
  after analysis; nothing is stored.
"""

import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import zlib
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from glossary import to_search_terms

ROOT = Path(__file__).parent
DB_PATH = ROOT / "patents.db"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ANALYZE_TIMEOUT_SECONDS = 45
ALLOWED_EXTENSIONS = {".step", ".stp", ".stl"}

app = FastAPI(title="Yuhi Patent CAD Search Demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yuhi-ai-labs.vercel.app"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


def get_db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def run_cad_analysis(input_path: Path, out_dir: Path, job_id: str) -> dict:
    """Run yuhi-cad as a subprocess so a bad file can't take the server down."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "yuhi_cad.cli",
            "analyze",
            "--input",
            str(input_path),
            "--output",
            str(out_dir),
            "--job-id",
            job_id,
            "--no-render",
        ],
        capture_output=True,
        text=True,
        timeout=ANALYZE_TIMEOUT_SECONDS,
    )
    result_file = out_dir / f"cad-analysis-{job_id}.json"
    if result_file.exists():
        return json.loads(result_file.read_text(encoding="utf-8"))
    # analyze() failed before writing a file: surface the worker's structured error.
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "error" in payload:
            raise HTTPException(422, payload["error"].get("message_ja", "解析に失敗しました。"))
    raise HTTPException(422, "CADファイルを解析できませんでした。ファイルが壊れているか、対応していない形式の可能性があります。")


def score_component(term: str, title: str, abstract: str) -> str:
    haystack = f"{title} {abstract}"
    if term and term in haystack:
        return "hit"
    # partial: any 2+ char slice of the term shows up (very rough, intentionally simple)
    if len(term) >= 2:
        for i in range(len(term) - 1):
            if term[i : i + 2] in haystack:
                return "partial"
    return "miss"


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "STEP (.step/.stp) または STL (.stl) のみ対応しています。")

    body = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "ファイルサイズは20MBまでです。")
    if len(body) == 0:
        raise HTTPException(400, "空のファイルです。")

    job_id = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=f"yuhi-cad-{job_id}-") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / f"upload{suffix}"
        input_path.write_bytes(body)
        try:
            analysis = await asyncio.to_thread(run_cad_analysis, input_path, tmp_dir, job_id)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "解析がタイムアウトしました。ファイルサイズ・複雑さを確認してください。")
        finally:
            # Belt and suspenders: TemporaryDirectory already removes this,
            # but the uploaded bytes never touch persistent storage regardless.
            shutil.rmtree(tmp_dir, ignore_errors=True)

    components = analysis.get("components", [])
    component_names = [c.get("normalized_name") or c.get("original_name") or "" for c in components]
    component_names = [n for n in component_names if n]

    search_terms: list[str] = []
    term_by_component: dict[str, list[str]] = {}
    for name in component_names:
        terms = to_search_terms(name)
        term_by_component[name] = terms
        for t in terms:
            if t not in search_terms:
                search_terms.append(t)

    results = []
    if search_terms:
        con = get_db()
        try:
            like_clauses = " OR ".join(["title LIKE ? OR abstract LIKE ?"] * len(search_terms))
            params: list[str] = []
            for t in search_terms:
                like = f"%{t}%"
                params.extend([like, like])
            rows = con.execute(
                f"SELECT publication_number, title, abstract FROM documents WHERE {like_clauses} LIMIT 12",
                params,
            ).fetchall()
            for row in rows:
                badges = {}
                for name, terms in term_by_component.items():
                    best = "miss"
                    for t in terms:
                        s = score_component(t, row["title"], row["abstract"])
                        if s == "hit":
                            best = "hit"
                            break
                        if s == "partial":
                            best = "partial"
                    badges[name] = best
                results.append(
                    {
                        "publication_number": row["publication_number"],
                        "title": row["title"],
                        "abstract": row["abstract"][:220],
                        "badges": badges,
                    }
                )
        finally:
            con.close()

    return JSONResponse(
        {
            "job_id": job_id,
            "source": analysis.get("source"),
            "model": analysis.get("model"),
            "components": component_names,
            "search_terms": search_terms,
            "results": results,
        }
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "db": DB_PATH.exists()}


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
