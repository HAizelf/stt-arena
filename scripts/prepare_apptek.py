"""Build the example dataset from AppTek Call-Center Dialogues (CC BY-SA 4.0).

Picks short CUSTOMER turns (customer channel only, no agent crosstalk), spread
across accents and domains, cuts them to mp3 and writes:

  datasets/callcenter-en/manifest.json   one row per clip (+ the dataset's own transcript)
  datasets/callcenter-en/golden.json     golden seeded from the dataset's verbatim transcript

Usage: uv run python scripts/prepare_apptek.py [--per-accent 2] [--seed 7]
Downloads go to .cache/apptek (gitignored). Needs ffmpeg.
"""

import argparse
import json
import pathlib
import random
import re
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets" / "callcenter-en"
CACHE = ROOT / ".cache" / "apptek"
HF = "https://huggingface.co/datasets/apptek-com/apptek_callcenter_dialogues/resolve/main"
ACCENTS = [
    "en-AU", "en-CA", "en-CN", "en-GB", "en-GB_SCT", "en-GB_WLS", "en-IE", "en-IN",
    "en-MX", "en-SG", "en-US_Aave", "en-US_General", "en-US_Southern", "en-ZA",
]
MIN_S, MAX_S, MIN_WORDS = 7.0, 14.0, 10
INTERESTING = re.compile(r"\((u+h+|u+m+|e+r+m*|h+m+)[,.]?\)|\b(not|never|no|don't|can't|didn't|won't|isn't|wasn't)\b|"
                         r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|hundred|thousand)\b",
                         re.I)


def fetch(url: str, dest: pathlib.Path) -> pathlib.Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dest)
    return dest


def to_golden(text: str) -> str:
    """AppTek conventions -> plain verbatim: '(uh)' -> 'uh', 'wor~' -> 'wor-'."""
    text = text.replace("´", "'").replace("’", "'")
    text = re.sub(r"\(([^)]*)\)", r"\1", text)
    text = re.sub(r"(\w)~", r"\1-", text).replace("~", "")
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-accent", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    picked, used_domains = [], set()
    for accent in ACCENTS:
        dia = fetch(f"{HF}/diarization/{accent}/metadata.jsonl", CACHE / "meta" / f"dia_{accent}.jsonl")
        chans = fetch(f"{HF}/test/{accent}/metadata.jsonl", CACHE / "meta" / f"test_{accent}.jsonl")
        # customer channel file per (call, speaker)
        channel_of = {}
        for line in chans.read_text().splitlines():
            r = json.loads(line)
            call = re.sub(r"_channel\d+\.wav$", "", pathlib.Path(r["file_name"]).name)
            channel_of[(call, r["speaker_id"])] = r["file_name"]

        candidates = []
        for line in dia.read_text().splitlines():
            call_row = json.loads(line)
            call = pathlib.Path(call_row["file_name"]).stem
            for i, s in enumerate(call_row["segments"]):
                dur = s["end"] - s["start"]
                if s["role"] != "customer" or not MIN_S <= dur <= MAX_S:
                    continue
                if len(s["text"].split()) < MIN_WORDS or (call, s["speaker_id"]) not in channel_of:
                    continue
                candidates.append({
                    "call": call, "seg": i, "accent": accent, "domain": call_row["domain"],
                    "gender": s.get("gender"), "start": s["start"], "end": s["end"], "text": s["text"],
                    "channel_file": channel_of[(call, s["speaker_id"])],
                    "score": len(INTERESTING.findall(s["text"])),
                })
        rng.shuffle(candidates)
        # prefer turns with fillers/negations/numbers, then unseen domains
        candidates.sort(key=lambda c: (-min(c["score"], 3), c["domain"] in used_domains))
        chosen_calls = set()
        for c in candidates:
            if len([p for p in picked if p["accent"] == accent]) >= args.per_accent:
                break
            if c["call"] in chosen_calls:
                continue
            chosen_calls.add(c["call"])
            used_domains.add(c["domain"])
            picked.append(c)

    clips_dir = OUT / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest, golden = [], {}
    for n, c in enumerate(picked, 1):
        clip_id = f"{c['accent'].lower().replace('-', '_')}_{n:02d}"
        wav = fetch(f"{HF}/test/{c['accent']}/{c['channel_file']}",
                    CACHE / "audio" / c["accent"] / pathlib.Path(c["channel_file"]).name)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{c['start']:.2f}", "-to", f"{c['end']:.2f}",
             "-i", str(wav), "-ac", "1", "-ar", "16000", "-b:a", "48k", str(clips_dir / f"{clip_id}.mp3")],
            check=True,
        )
        manifest.append({
            "id": clip_id, "accent": c["accent"], "domain": c["domain"], "gender": c["gender"],
            "reference": c["text"],
            "source": {"dataset": "apptek-com/apptek_callcenter_dialogues", "file": c["channel_file"],
                       "accent": c["accent"], "start": c["start"], "end": c["end"]},
        })
        golden[clip_id] = {"text": to_golden(c["text"]), "verified": False, "source": "dataset"}
        print(f"{clip_id:18} {c['domain']:16} {c['end'] - c['start']:5.1f}s  {c['text'][:70]}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    golden_path = OUT / "golden.json"
    if golden_path.exists():  # never clobber human edits
        old = json.loads(golden_path.read_text())
        golden = {k: old.get(k, v) for k, v in golden.items()}
    golden_path.write_text(json.dumps(golden, indent=1, ensure_ascii=False))
    print(f"\n{len(manifest)} clips -> {OUT}")


if __name__ == "__main__":
    main()
