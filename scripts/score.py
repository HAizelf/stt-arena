"""Deterministic scoring: WER (fillers removed), filler recall, latency, cost.

Usage: uv run python scripts/score.py
Adds wer / fillers_hit / fillers_total to each results/<model>.json row and writes
results/_summary.json. Judge verdicts (pass / error_type / reason) come from judge.py.
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from assemble import assemble  # noqa: E402
from common import base_args, load_json, setup, write_json  # noqa: E402

# Hesitation fillers the speaker produced. Backchannels like "mm-hmm" are not counted.
FILLER_RE = re.compile(r"^(u+h*m+|u+h+|e+r+m*|u+r+g+h+|h+m+|a+h+)$")
REPLACE = {"'cause": "because", "cause": "because", "gonna": "going to", "wanna": "want to",
           "gotta": "got to", "kinda": "kind of", "okay": "ok", "alright": "all right",
           "mm-hmm": "mmhmm", "mhm": "mmhmm", "uh-huh": "uhhuh", "ohh": "oh", "ooh": "oh",
           "yep": "yeah", "yup": "yeah"}
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
       "sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n: int) -> list[str]:
    if n < 20:
        return [ONES[n]]
    if n < 100:
        return [TENS[n // 10]] + ([ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [ONES[n // 100], "hundred"] + (number_words(n % 100) if n % 100 else [])
    return number_words(n // 1000) + ["thousand"] + (number_words(n % 1000) if n % 1000 else [])


def ordinal_words(n: int) -> list[str]:
    words = number_words(n)
    last = words[-1]
    special = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
               "nine": "ninth", "twelve": "twelfth"}
    if last in special:
        words[-1] = special[last]
    elif last.endswith("y"):
        words[-1] = last[:-1] + "ieth"
    else:
        words[-1] = last + "th"
    return words


def expand_digits(token: str) -> list[str]:
    """'22' -> twenty two; '7:30' -> seven thirty; '14th' -> fourteenth; long ids -> digit by digit."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", token)
    if m:  # clock time: "3:00" == "three", "7:30" == "seven thirty"
        h, mins = int(m.group(1)), int(m.group(2))
        return number_words(h) + (number_words(mins) if mins else [])
    m = re.fullmatch(r"(\d+)(st|nd|rd|th)", token)
    if m:
        return ordinal_words(int(m.group(1)))
    digits = token.replace(",", "")
    if not digits.isdigit():
        return [token]
    if len(digits) >= 5 or digits.startswith("0"):
        return [ONES[int(d)] for d in digits]
    return number_words(int(digits))


def tokens(text: str) -> list[str]:
    text = text.lower().replace("’", "'").replace("e-mail", "email")
    text = re.sub(r"[\[(][^\])]*[\])]", " ", text)  # [laughs], (sighs)
    text = re.sub(r"(?<![a-z0-9])-|-(?![a-z0-9])", " ", text)  # cut-offs "inside-" / dashes
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", text)  # spelled letters / compounds: z-h-a-n-g, twenty-two
    out = []
    for raw in text.split():
        w = re.sub(r"^[^a-z0-9']+|[^a-z0-9']+$", "", raw)
        w = REPLACE.get(w, w)
        if not w:
            continue
        for part in w.split():
            out.extend(expand_digits(part) if any(ch.isdigit() for ch in part) else [part])
    return out


def fillers(text: str) -> int:
    return sum(bool(FILLER_RE.match(t)) for t in tokens(text))


def content(text: str) -> list[str]:
    return [t for t in tokens(text) if not FILLER_RE.match(t)]


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, round(q * (len(values) - 1)))]


def main() -> None:
    ds = setup(base_args(__doc__).parse_args())
    golden = load_json(ds / "golden.json", {})
    meta = load_json(ds / "results" / "_meta.json", {})
    summary = {}
    for path in sorted((ds / "results").glob("[!_]*.json")):
        key, rows = path.stem, load_json(path, {})
        edits = ref_words = f_hit = f_total = flushes = errors = passes = judged = 0
        lat = []
        for cid, r in rows.items():
            if cid not in golden:
                continue
            if r.get("finals") is not None:  # re-assemble so rule changes apply without a re-run
                r["text"], r["revised_finals"], r["out_of_order"] = assemble(r["finals"])
            gold = golden[cid]["text"]
            ref, hyp = content(gold), content(r.get("text", ""))
            d = edit_distance(ref, hyp)
            r["wer"] = d / max(1, len(ref))
            g_f, c_f = fillers(gold), fillers(r.get("text", ""))
            r["fillers_total"], r["fillers_hit"] = g_f, min(g_f, c_f)
            edits, ref_words = edits + d, ref_words + len(ref)
            f_hit, f_total = f_hit + r["fillers_hit"], f_total + g_f
            if r.get("latency_ms") is not None:
                lat.append(r["latency_ms"])
            flushes += bool(r.get("needed_flush"))
            errors += bool(r.get("error"))
            if r.get("pass") is not None:
                judged += 1
                passes += bool(r["pass"])
        write_json(path, rows)
        m = meta.get(key, {})
        summary[key] = {
            "model": m.get("model", key), "usd_per_min": m.get("usd_per_min"), "multilingual": m.get("multilingual"),
            "clips": len(rows), "wer": edits / max(1, ref_words),
            "filler_recall": f_hit / f_total if f_total else None, "fillers": f"{f_hit}/{f_total}",
            "latency_p50_ms": pct(lat, 0.5), "latency_p95_ms": pct(lat, 0.95),
            "needed_flush": flushes, "errors": errors,
            # no final transcript at all, even after the trailing silence and stream close
            "empty": sum(not r.get("text") and not r.get("error") for r in rows.values()),
            "revised_clips": sum(bool(r.get("revised_finals")) for r in rows.values()),
            "out_of_order_clips": sum(bool(r.get("out_of_order")) for r in rows.values()),
            "pass_rate": passes / judged if judged else None, "judged": judged,
        }
    write_json(ds / "results" / "_summary.json", summary)

    order = sorted(summary.items(), key=lambda kv: (-(kv[1]["pass_rate"] or 0), kv[1]["wer"]))
    print(f"{'model':32} {'pass':>5} {'WER':>6} {'fillers':>8} {'p50':>6} {'p95':>6} {'$/min':>7}")
    for k, s in order:
        p = f"{s['pass_rate'] * 100:.0f}%" if s["pass_rate"] is not None else "-"
        p50 = f"{s['latency_p50_ms']:.0f}" if s["latency_p50_ms"] is not None else "-"
        p95 = f"{s['latency_p95_ms']:.0f}" if s["latency_p95_ms"] is not None else "-"
        print(f"{k:32} {p:>5} {s['wer'] * 100:5.1f}% {s['fillers']:>8} {p50:>6} {p95:>6} {s['usd_per_min'] or 0:>7}")


if __name__ == "__main__":
    main()
