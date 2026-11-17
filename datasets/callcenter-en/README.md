# callcenter-en: example dataset

28 short **customer turns** from role-played English customer-service calls: 14 accents × 2 clips, 7–14 s each, across 16 service domains (banking, telecom, travel, delivery, insurance and more). The clips are deliberately hard for speech-to-text. They contain:

- spelled-out names ("Z H A N G", "M-A-R-C")
- long digit strings (account and phone numbers)
- dates and times ("the fourteenth of December at seven thirty")
- negations ("do not call me between three and four")
- plenty of fillers ("uh", "um"), false starts and repairs

## Source and license

Derived from **[AppTek Call-Center Dialogues](https://huggingface.co/datasets/apptek-com/apptek_callcenter_dialogues)** by AppTek, licensed **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)**. The calls are role-played, not real customer calls.

Everything in this folder (audio clips, transcripts, model outputs, verdicts) is a derivative work and is shared under the same **CC BY-SA 4.0** license. The repository's MIT license does not apply to this folder.

The source dataset is intended for evaluation, not model training. Please keep it that way.

### Changes made

- Selected customer segments using the dataset's `diarization` timings (`scripts/prepare_apptek.py`, seed 7).
- Cut each segment from the **customer's own channel** (no agent crosstalk), then converted it to 16 kHz mono MP3.
- Converted AppTek's transcript conventions to plain verbatim text: `(uh)` → `uh`, cut-off `wor~` → `wor-`.

## Files

| File | What it holds |
|---|---|
| `manifest.json` | One row per clip: id, accent, domain, gender, the dataset's original transcript (`reference`) and source timing |
| `clips/` | The audio clips |
| `golden.json` | The ground truth used for scoring. Seeded from AppTek's manual verbatim transcript and marked verified. `draft` holds the ElevenLabs Scribe draft for comparison |
| `golden_raw/` | Raw Scribe responses (word timings and confidence, used by the dashboard) |
| `results/` | One file per STT model, plus `_summary.json` |
| `judge/` | The LLM judge's verdicts |

Rebuild it from scratch with `uv run python scripts/prepare_apptek.py`.
