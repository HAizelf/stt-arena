"""Shared paths, dataset loading and env handling for every script."""

import argparse
import json
import os
import pathlib

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "datasets" / "callcenter-en"


def base_args(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--dataset", default=os.environ.get("STT_ARENA_DATASET", str(DEFAULT_DATASET)),
                    help="dataset folder (manifest.json, clips/, golden.json)")
    ap.add_argument("--env-file", action="append", default=[],
                    help="extra .env file(s) to load; repeatable. Real env vars always win.")
    return ap


def setup(args: argparse.Namespace) -> pathlib.Path:
    """Load env files and return the dataset folder."""
    load_dotenv(ROOT / ".env")
    for f in args.env_file:
        load_dotenv(f)
    return pathlib.Path(args.dataset).resolve()


def load_json(path: pathlib.Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(path)


def load_models() -> dict:
    return {k: v for k, v in load_json(ROOT / "models.json", {}).items() if not k.startswith("_")}
