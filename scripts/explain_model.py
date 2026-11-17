"""Explain one model's misses: judge FAILs plus a WER breakdown (substitutions / deletions / insertions).

Usage: uv run python scripts/explain_model.py deepgram-nova-3
"""

import collections
import difflib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import base_args, load_json, setup  # noqa: E402
from score import content  # noqa: E402


def main() -> None:
    ap = base_args(__doc__)
    ap.add_argument("model")
    args = ap.parse_args()
    ds = setup(args)
    rows = load_json(ds / "results" / f"{args.model}.json", {})
    golden = load_json(ds / "golden.json", {})
    order = {c["id"]: i + 1 for i, c in enumerate(load_json(ds / "manifest.json", []))}

    fails = [(cid, r) for cid, r in rows.items() if r.get("pass") is False]
    print(f"== Judge FAILs ({len(fails)}/{len(rows)})")
    for cid, r in sorted(fails, key=lambda kv: order.get(kv[0], 0)):
        print(f"{order.get(cid, 0):02d} {cid} [{r.get('error_type')}] {r.get('reason')}")

    subs, dels, ins = collections.Counter(), collections.Counter(), collections.Counter()
    worst = []
    for cid, r in rows.items():
        ref, hyp = content(golden.get(cid, {}).get("text", "")), content(r.get("text", ""))
        for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_opcodes():
            if op == "replace":
                subs[f"{' '.join(ref[a1:a2])} → {' '.join(hyp[b1:b2])}"] += 1
            elif op == "delete":
                dels[" ".join(ref[a1:a2])] += 1
            elif op == "insert":
                ins[" ".join(hyp[b1:b2])] += 1
        worst.append((r.get("wer", 0), cid))
    print(f"\n== WER spans: {sum(subs.values())} substituted, {sum(dels.values())} deleted, {sum(ins.values())} inserted")
    print("Worst clips:", ", ".join(f"{cid} {w * 100:.0f}%" for w, cid in sorted(worst, reverse=True)[:5]))
    print("\nSubstitutions:", "; ".join(k for k, _ in subs.most_common(20)))
    print("\nDeleted:", "; ".join(k for k, _ in dels.most_common(20)))
    print("\nInserted:", "; ".join(k for k, _ in ins.most_common(15)))


if __name__ == "__main__":
    main()
