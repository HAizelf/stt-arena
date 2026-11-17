"""Print every STT event (type, time, span, text) for one clip through one model.

Useful when a provider's finals look odd (duplicates, revisions, ordering).
Usage: uv run python scripts/debug_events.py <model_key> <clip_id>
"""

import asyncio
import pathlib
import sys
import time

import aiohttp
from livekit import rtc
from livekit.agents import NOT_GIVEN, inference
from livekit.agents.stt import SpeechEventType

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import base_args, load_models, setup  # noqa: E402
from run_candidates import FRAME_MS, SR, decode_pcm  # noqa: E402


async def main() -> None:
    ap = base_args(__doc__)
    ap.add_argument("model_key")
    ap.add_argument("clip_id")
    args = ap.parse_args()
    ds = setup(args)
    cfg = load_models()[args.model_key]
    pcm = decode_pcm(ds / "clips" / f"{args.clip_id}.mp3")
    async with aiohttp.ClientSession() as session:
        stt = inference.STT(model=cfg["model"], language="en",
                            extra_kwargs=cfg.get("extra_kwargs") or NOT_GIVEN, http_session=session)
        stream = stt.stream()
        t0 = time.monotonic()

        async def read() -> None:
            async for ev in stream:
                if ev.type == SpeechEventType.RECOGNITION_USAGE:
                    continue
                alt = ev.alternatives[0] if ev.alternatives else None
                span = f"[{alt.start_time:.2f}-{alt.end_time:.2f}]" if alt and alt.end_time else ""
                print(f"{time.monotonic() - t0:6.2f}s {ev.type.value:20} {span:14} {(alt.text if alt else '')!r}", flush=True)

        reader = asyncio.create_task(read())
        spf = SR * FRAME_MS // 1000
        frames = [pcm[o * 2:(o + spf) * 2].ljust(spf * 2, b"\0") for o in range(0, len(pcm) // 2, spf)]
        frames += [b"\0" * spf * 2] * int(3000 / FRAME_MS)
        for i, chunk in enumerate(frames, 1):
            stream.push_frame(rtc.AudioFrame(chunk, SR, 1, spf))
            await asyncio.sleep(max(0, t0 + i * FRAME_MS / 1000 - time.monotonic()))
        print(f"{time.monotonic() - t0:6.2f}s -- end_input (speech ended at {len(pcm) / 2 / SR:.2f}s)")
        stream.end_input()
        try:
            await asyncio.wait_for(reader, 8)
        except asyncio.TimeoutError:
            reader.cancel()
        await stream.aclose()


if __name__ == "__main__":
    asyncio.run(main())
