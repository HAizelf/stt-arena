"""LLM judge: did each model's transcript keep the meaning of the golden?

  uv run python scripts/judge.py run      one Claude call per clip (needs ANTHROPIC_API_KEY)
  uv run python scripts/judge.py export   write judge/input.json for any other judge (human, other LLM)
  uv run python scripts/judge.py import   merge judge/output.json back into results/

Verdicts land on each results/<model>.json row as pass / error_type / reason.
judge/output.json shape: {clip_id: {model_key: {"pass": bool, "error_type": str, "reason": str}}}
"""

import pathlib
import sys
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import ROOT, base_args, load_json, setup, write_json  # noqa: E402

ErrorType = Literal["none", "negation", "number_or_entity", "content_substitution",
                    "omission", "hallucination", "other"]


def collect(ds: pathlib.Path) -> tuple[list[dict], dict[str, dict]]:
    golden = load_json(ds / "golden.json", {})
    results = {p.stem: load_json(p, {}) for p in sorted((ds / "results").glob("[!_]*.json"))}
    items = []
    for c in load_json(ds / "manifest.json", []):
        cands = {m: r[c["id"]].get("text", "") for m, r in results.items() if c["id"] in r}
        if c["id"] in golden and cands:
            items.append({"clip_id": c["id"], "golden": golden[c["id"]]["text"], "candidates": cands})
    return items, results


def merge(ds: pathlib.Path, results: dict[str, dict], verdicts: dict) -> None:
    merged = missing = 0
    for m, rows in results.items():
        for cid, row in rows.items():
            v = verdicts.get(cid, {}).get(m)
            if not isinstance(v, dict) or not isinstance(v.get("pass"), bool):
                missing += 1
                continue
            row["pass"], row["error_type"], row["reason"] = v["pass"], v.get("error_type", ""), v.get("reason", "")
            merged += 1
        write_json(ds / "results" / f"{m}.json", rows)
    print(f"merged {merged} verdicts, {missing} without one")


def run(ds: pathlib.Path, items: list[dict], model: str, effort: str) -> dict:
    import anthropic
    from pydantic import BaseModel

    class Verdict(BaseModel):
        model: str
        passed: bool
        error_type: ErrorType
        reason: str

    class ClipVerdicts(BaseModel):
        verdicts: list[Verdict]

    client = anthropic.Anthropic(max_retries=4)
    system = (ROOT / "prompts" / "judge.md").read_text()
    out_path = ds / "judge" / "output.json"
    verdicts = load_json(out_path, {})
    for it in items:
        if set(it["candidates"]) <= set(verdicts.get(it["clip_id"], {})):
            continue  # already judged
        cand_lines = "\n".join(f"- {m}: {t!r}" for m, t in it["candidates"].items())
        prompt = f"GOLDEN:\n{it['golden']!r}\n\nCANDIDATES:\n{cand_lines}\n\nReturn one verdict per model key."
        try:
            resp = client.messages.parse(
                model=model, max_tokens=16000, system=system,
                output_config={"effort": effort},
                messages=[{"role": "user", "content": prompt}],
                output_format=ClipVerdicts,
            )
        except anthropic.APIStatusError as e:
            print(f"{it['clip_id']}: API error {e.status_code}, skipped")
            continue
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            print(f"{it['clip_id']}: no verdict ({resp.stop_reason}), skipped")
            continue
        verdicts[it["clip_id"]] = {
            v.model: {"pass": v.passed, "error_type": v.error_type, "reason": v.reason}
            for v in resp.parsed_output.verdicts if v.model in it["candidates"]
        }
        write_json(out_path, verdicts)
        print(f"{it['clip_id']}: {sum(v['pass'] for v in verdicts[it['clip_id']].values())}"
              f"/{len(it['candidates'])} pass", flush=True)
    return verdicts


def main() -> None:
    ap = base_args(__doc__)
    ap.add_argument("mode", choices=["run", "export", "import"])
    ap.add_argument("--model", default="claude-haiku-5-5", help="judge model")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    args = ap.parse_args()
    ds = setup(args)
    items, results = collect(ds)

    if args.mode == "export":
        write_json(ds / "judge" / "input.json", items)
        print(f"{len(items)} clips -> {ds / 'judge' / 'input.json'}")
    elif args.mode == "import":
        merge(ds, results, load_json(ds / "judge" / "output.json", {}))
    else:
        merge(ds, results, run(ds, items, args.model, args.effort))
    print("next: uv run python scripts/score.py")


if __name__ == "__main__":
    main()
