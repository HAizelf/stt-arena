"""Local dashboard: review/edit goldens and compare models.

Usage: uv run python scripts/serve.py [--port 8765]   then open http://127.0.0.1:8765
Serves web/index.html, the dataset's clips, and a small JSON API. Golden edits are
written to <dataset>/golden.json.
"""

import json
import pathlib
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import ROOT, base_args, load_json, setup, write_json  # noqa: E402

LOCK = threading.Lock()
DS: pathlib.Path


def rows() -> dict:
    golden = load_json(DS / "golden.json", {})
    summary = load_json(DS / "results" / "_summary.json", {})
    results = {p.stem: load_json(p, {}) for p in sorted((DS / "results").glob("[!_]*.json"))}
    order = sorted(results, key=lambda m: (-(summary.get(m, {}).get("pass_rate") or 0),
                                           summary.get(m, {}).get("wer", 9)))
    out = []
    for c in load_json(DS / "manifest.json", []):
        raw = load_json(DS / "golden_raw" / f"{c['id']}.json", {})
        words = [{k: w.get(k) for k in ("text", "type", "logprob", "start", "end")}
                 for w in raw.get("words", []) if w.get("type") != "spacing"]
        g = golden.get(c["id"], {})
        out.append({**c, "golden": g.get("text"), "draft": g.get("draft"), "verified": g.get("verified", False),
                    "golden_source": g.get("source"), "words": words,
                    "candidates": {m: results[m].get(c["id"]) for m in order}})
    return {"dataset": DS.name, "rows": out, "models": order, "summary": summary}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "web"), **kw)

    def log_message(self, *a):
        pass

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/rows":
            return self._json(200, rows())
        if self.path.startswith("/clips/"):
            return self._clip()
        return super().do_GET()

    def _clip(self) -> None:
        """Serve an mp3 with Range support: browsers need it to seek (and Safari to play)."""
        path = (DS / self.path.lstrip("/").split("?")[0]).resolve()
        if path.parent != (DS / "clips").resolve() or not path.is_file():
            return self._json(404, {"error": "not found"})
        data, size = path.read_bytes(), path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                start = int(a) if a else max(0, size - int(b))
                end = min(int(b), size - 1) if a and b else size - 1
            except ValueError:
                start, end = 0, size - 1
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        chunk = data[start:end + 1]
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def do_POST(self):
        if self.path != "/api/golden":
            return self._json(404, {"error": "not found"})
        try:
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            clip_id = str(data["id"])
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"error": "bad request"})
        with LOCK:
            golden = load_json(DS / "golden.json", {})
            row = golden.setdefault(clip_id, {})
            if "text" in data:
                row["text"] = str(data["text"])
            if "verified" in data:
                row["verified"] = bool(data["verified"])
            write_json(DS / "golden.json", golden)
        return self._json(200, {"ok": True, "row": row})


def main() -> None:
    global DS
    ap = base_args(__doc__)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    DS = setup(args)
    print(f"Dashboard for {DS.name}: http://127.0.0.1:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
