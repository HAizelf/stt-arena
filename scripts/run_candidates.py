"""Stream every clip through each candidate STT model at real-time pace (LiveKit Inference).

Usage: uv run python scripts/run_candidates.py [model_key ...] [--clips N]
Writes <dataset>/results/<model_key>.json: {clip_id: {text, finals, latency_ms, needed_flush, ...}}.
Resumes: clips already in a results file are skipped (delete the file to re-run a model).
"""

import asyncio
import pathlib
import subprocess
import sys
import time

import aiohttp
from livekit import rtc
from livekit.agents import NOT_GIVEN, inference
from livekit.agents.stt import SpeechEventType

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from assemble import assemble  # noqa: E402
from common import base_args, load_json, load_models, setup, write_json  # noqa: E402

SR, FRAME_MS = 16000, 20
# Silence streamed after each clip. Longer than any provider's default end-of-turn
# timeout (Cartesia ink-2: 5.6 s), so turn-aware models finalise instead of being cut off.
TAIL_SILENCE_S = 6.0
CLOSE_TIMEOUT_S = 8.0


def decode_pcm(path: pathlib.Path) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True, check=True,
    ).stdout


async def _pace(start: float, n_frames: int) -> None:
    await asyncio.sleep(max(0.0, start + n_frames * FRAME_MS / 1000 - time.monotonic()))


async def run_clip(stt: inference.STT, pcm: bytes, tail_s: float = TAIL_SILENCE_S) -> dict:
    stream = stt.stream()
    finals: list[dict] = []

    async def read() -> None:
        async for ev in stream:
            if ev.type == SpeechEventType.FINAL_TRANSCRIPT and ev.alternatives:
                alt = ev.alternatives[0]
                if alt.text.strip():
                    finals.append({"text": alt.text.strip(), "start": alt.start_time or 0.0,
                                   "end": alt.end_time or 0.0, "t": time.monotonic()})

    reader = asyncio.create_task(read())
    spf = SR * FRAME_MS // 1000
    start, n = time.monotonic(), 0
    for off in range(0, len(pcm) // 2, spf):
        stream.push_frame(rtc.AudioFrame(pcm[off * 2:(off + spf) * 2].ljust(spf * 2, b"\0"), SR, 1, spf))
        n += 1
        await _pace(start, n)
    speech_end = time.monotonic()

    silence = b"\0" * spf * 2
    for _ in range(int(tail_s * 1000 / FRAME_MS)):
        stream.push_frame(rtc.AudioFrame(silence, SR, 1, spf))
        n += 1
        await _pace(start, n)
    tail_end = time.monotonic()

    stream.end_input()
    try:
        await asyncio.wait_for(reader, CLOSE_TIMEOUT_S)
    except asyncio.TimeoutError:
        reader.cancel()
    await stream.aclose()

    last = finals[-1]["t"] if finals else None
    text, revised, out_of_order = assemble(finals)
    return {
        "text": text,
        "finals": [{k: f[k] for k in ("text", "start", "end")} for f in finals],
        "revised_finals": revised,
        "out_of_order": out_of_order,
        # end of speech -> last final; 0 when every final arrived before speech ended
        "latency_ms": None if last is None else max(0.0, (last - speech_end) * 1000),
        # finals only came after end_input(): live, the turn would wait on the provider
        "needed_flush": last is not None and last > tail_end,
        "error": None,
    }


async def run_model(key: str, cfg: dict, clips: list[dict], pcm: dict, ds: pathlib.Path,
                    session: aiohttp.ClientSession, language: str, tail_s: float) -> None:
    out_path = ds / "results" / f"{key}.json"
    results = load_json(out_path, {})
    stt = inference.STT(model=cfg["model"], language=language,
                        extra_kwargs=cfg.get("extra_kwargs") or NOT_GIVEN, http_session=session)
    for c in clips:
        if c["id"] in results and not results[c["id"]].get("error"):
            continue
        try:
            results[c["id"]] = await run_clip(stt, pcm[c["id"]], tail_s)
        except Exception as e:  # one bad clip/provider must not stop the run
            results[c["id"]] = {"text": "", "finals": [], "revised_finals": 0, "out_of_order": False,
                                "latency_ms": None, "needed_flush": False,
                                "error": f"{type(e).__name__}: {e}"[:300]}
        write_json(out_path, results)
    errors = sum(bool(r.get("error")) for r in results.values())
    empty = sum(not r.get("text") and not r.get("error") for r in results.values())
    print(f"{key:32} done {len(results)} clips, errors {errors}, empty {empty}", flush=True)


async def main() -> None:
    ap = base_args(__doc__)
    ap.add_argument("models", nargs="*", help="model keys from models.json (default: all)")
    ap.add_argument("--clips", type=int, default=None, help="only the first N clips (smoke test)")
    ap.add_argument("--language", default="en")
    ap.add_argument("--tail", type=float, default=TAIL_SILENCE_S, help="seconds of silence after each clip")
    args = ap.parse_args()
    ds = setup(args)

    models = load_models()
    keys = args.models or list(models)
    unknown = [k for k in keys if k not in models]
    if unknown:
        raise SystemExit(f"unknown model keys: {unknown}")

    clips = load_json(ds / "manifest.json", [])[: args.clips]
    pcm = {c["id"]: decode_pcm(ds / "clips" / f"{c['id']}.mp3") for c in clips}
    write_json(ds / "results" / "_meta.json",
               {k: {"model": v["model"], "extra_kwargs": v.get("extra_kwargs", {}),
                    "usd_per_min": v.get("usd_per_min"), "multilingual": v.get("multilingual")}
                for k, v in models.items()})
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(run_model(k, models[k], clips, pcm, ds, session, args.language, args.tail)
                               for k in keys))


if __name__ == "__main__":
    asyncio.run(main())
