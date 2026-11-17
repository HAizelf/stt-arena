"""Turn a provider's stream of FINAL transcripts into one clip transcript.

Providers differ. Some re-send a turn (formatted, then unformatted, or merged with
the next turn); some send continuations that all start at 0; some send no
timestamps. So a final counts as a revision only when its words match the
trailing finals it would replace. Order stays as delivered: that is what a live
voice agent sees.
"""

import difflib
import re

SIMILAR = 0.9
MAX_REVISED_RUN = 3


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def assemble(finals: list[dict]) -> tuple[str, int, bool]:
    """Returns (text, revised_count, out_of_order)."""
    kept: list[dict] = []
    revised = 0
    for f in finals:
        new = _words(f["text"])
        for n in range(min(MAX_REVISED_RUN, len(kept)), 0, -1):
            old = [w for k in kept[-n:] for w in _words(k["text"])]
            if new and difflib.SequenceMatcher(None, old, new).ratio() >= SIMILAR:
                del kept[-n:]
                revised += n
                break
        kept.append(f)

    # Only providers with absolute timestamps (every start > 0 after the first) can be out of order.
    starts = [k.get("start", 0) for k in kept]
    absolute = len(kept) > 1 and all(s > 0.05 for s in starts[1:])
    out_of_order = absolute and any(b < a for a, b in zip(starts, starts[1:]))
    return " ".join(k["text"] for k in kept), revised, out_of_order
