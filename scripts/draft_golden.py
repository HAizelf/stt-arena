"""Draft verbatim golden transcripts with ElevenLabs Scribe (batch speech-to-text).

Usage: uv run python scripts/draft_golden.py [--language en]
Needs ELEVENLABS_API_KEY. Keeps fillers, false starts and stutters (no_verbatim=false).
Re-runs only send clips without a saved draft; your edits in golden.json are never overwritten.
"""

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import base_args, load_json, setup, write_json  # noqa: E402

URL = "https://api.elevenlabs.io/v1/speech-to-text"


def multipart(fields: dict, file_path: pathlib.Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
                 f"Content-Type: audio/mpeg\r\n\r\n".encode() + file_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    ap = base_args(__doc__)
    ap.add_argument("--language", default="en")
    ap.add_argument("--model", default="scribe_v2")
    args = ap.parse_args()
    ds = setup(args)

    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is not set (.env or --env-file)")

    fields = {"model_id": args.model, "language_code": args.language, "no_verbatim": "false",
              "tag_audio_events": "true", "timestamps_granularity": "word", "temperature": "0"}
    raw_dir = ds / "golden_raw"
    raw_dir.mkdir(exist_ok=True)
    golden = load_json(ds / "golden.json", {})
    done = failed = 0
    for c in load_json(ds / "manifest.json", []):
        raw_path = raw_dir / f"{c['id']}.json"
        if not raw_path.exists():
            body, ctype = multipart(fields, ds / "clips" / f"{c['id']}.mp3")
            req = urllib.request.Request(URL, data=body, headers={"xi-api-key": key, "Content-Type": ctype})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw_path.write_text(r.read().decode())
            except urllib.error.HTTPError as e:
                failed += 1
                print("FAILED", c["id"], e.code, e.read().decode()[:200])
                continue
        draft = json.loads(raw_path.read_text())["text"].strip()
        row = golden.setdefault(c["id"], {"text": draft, "verified": False})
        row["draft"] = draft
        done += 1
    write_json(ds / "golden.json", golden)
    print(f"drafted {done}, failed {failed}")


if __name__ == "__main__":
    main()
