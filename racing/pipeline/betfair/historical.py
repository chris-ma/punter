"""
Betfair Historical Data ingestion.

Betfair provides free daily bz2-compressed market files at:
  https://historicdata.betfair.com/

Each file contains a sequence of newline-delimited JSON objects representing
streaming market updates (RunnerChange, MarketChange, etc.) in the same
format as the Betfair Streaming API. betfairlightweight's `streaming` module
parses these directly.

AU thoroughbred WIN markets have a marketType of "WIN" and an eventType of
"Horse Racing". We filter to those and reconstruct each runner's final
Starting Price (BSP) and a coarse end-of-market snapshot for training.

Usage (CLI):
    python -m racing.pipeline.betfair.historical \
        --path data/2024-01-01.bz2 \
        --output data/parsed/

The output is a Parquet file per day with one row per runner per race.
"""

import bz2
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

AU_TIMEZONE_BY_STATE = {
    "NSW": "Australia/Sydney",
    "VIC": "Australia/Melbourne",
    "QLD": "Australia/Brisbane",
    "WA": "Australia/Perth",
    "SA": "Australia/Adelaide",
    "TAS": "Australia/Hobart",
    "ACT": "Australia/Sydney",
    "NT": "Australia/Darwin",
}


@dataclass
class RaceRow:
    market_id: str
    race_date: str
    event_name: str
    country: str
    track: str
    selection_id: int
    runner_name: str
    bsp: float | None
    win_back_close: float | None  # final back price before close
    win_lay_close: float | None
    total_matched: float
    status: str  # WINNER | LOSER | REMOVED


def _extract_state_from_venue(venue: str) -> str:
    """
    Betfair venue strings are typically "Track Name (STATE)" or just "Track Name".
    Returns a best-effort state code.
    """
    if "(" in venue and ")" in venue:
        code = venue.split("(")[-1].rstrip(")")
        return code.strip().upper()
    return "UNK"


def parse_bz2_file(path: Path) -> list[RaceRow]:
    """
    Parse a single Betfair historical bz2 file into a flat list of RaceRows.

    betfairlightweight can parse the streaming format directly, but to avoid
    dependency complexity we parse the JSON manually here — the format is
    stable and well-documented.
    """
    rows: list[RaceRow] = []
    market_defs: dict[str, dict] = {}       # market_id → latest MarketDefinition
    runner_bsp: dict[str, dict[int, float]] = {}        # market_id → {sel_id → bsp}
    runner_back: dict[str, dict[int, float]] = {}
    runner_lay: dict[str, dict[int, float]] = {}
    runner_vol: dict[str, dict[int, float]] = {}

    opener = bz2.open if path.suffix == ".bz2" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            op = msg.get("op", "")
            market_id = msg.get("id", "")

            # Market change message — contains MarketDefinition and/or RunnerChanges
            if op == "mcm":
                for mc in msg.get("mc", []):
                    mid = mc.get("id", "")
                    if not mid:
                        continue

                    if "marketDefinition" in mc:
                        market_defs[mid] = mc["marketDefinition"]

                    # Runner changes: price updates
                    for rc in mc.get("rc", []):
                        sid = rc.get("id")
                        if sid is None:
                            continue

                        # BSP near-price
                        if "spb" in rc:
                            runner_bsp.setdefault(mid, {})[sid] = rc["spb"]

                        # Best available back/lay
                        if "batb" in rc and rc["batb"]:
                            best = rc["batb"][0]  # [level, price, size]
                            runner_back.setdefault(mid, {})[sid] = best[1]
                        if "batl" in rc and rc["batl"]:
                            best = rc["batl"][0]
                            runner_lay.setdefault(mid, {})[sid] = best[1]

                        if "trd" in rc:
                            for trd in rc["trd"]:
                                runner_vol.setdefault(mid, {})[sid] = (
                                    runner_vol.get(mid, {}).get(sid, 0) + trd[1]
                                )

    # Build output rows from accumulated state
    for mid, defn in market_defs.items():
        market_type = defn.get("marketType", "")
        event_type = defn.get("eventTypeId", "")
        country = defn.get("countryCode", "")

        # AU thoroughbred WIN markets only
        if market_type != "WIN" or event_type != "7" or country != "AU":
            continue

        venue = defn.get("venue", "")
        event_name = defn.get("eventName", "")
        market_time = defn.get("marketTime", "")

        try:
            race_dt = datetime.fromisoformat(market_time.replace("Z", "+00:00"))
            race_date = race_dt.astimezone(timezone.utc).date().isoformat()
        except (ValueError, AttributeError):
            race_date = ""

        for runner in defn.get("runners", []):
            sid = runner.get("id")
            name = runner.get("name", "")
            status = runner.get("status", "")

            bsp_val = runner.get("bsp") or runner_bsp.get(mid, {}).get(sid)

            rows.append(
                RaceRow(
                    market_id=mid,
                    race_date=race_date,
                    event_name=event_name,
                    country=country,
                    track=venue,
                    selection_id=sid,
                    runner_name=name,
                    bsp=float(bsp_val) if bsp_val else None,
                    win_back_close=runner_back.get(mid, {}).get(sid),
                    win_lay_close=runner_lay.get(mid, {}).get(sid),
                    total_matched=runner_vol.get(mid, {}).get(sid, 0.0),
                    status=status,
                )
            )

    log.info("Parsed %d runner rows from %s", len(rows), path.name)
    return rows


def parse_directory(data_dir: Path, output_dir: Path) -> None:
    """Parse all .bz2 files in data_dir, write one Parquet per file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(data_dir.glob("*.bz2"))
    log.info("Found %d bz2 files in %s", len(files), data_dir)

    for f in files:
        out_path = output_dir / f.with_suffix(".parquet").name
        if out_path.exists():
            log.debug("Skipping %s (already parsed)", f.name)
            continue

        rows = parse_bz2_file(f)
        if not rows:
            log.warning("No AU WIN market rows in %s", f.name)
            continue

        df = pd.DataFrame([asdict(r) for r in rows])
        df.to_parquet(out_path, index=False)
        log.info("Wrote %s (%d rows)", out_path.name, len(df))


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Parse Betfair historical bz2 files")
    parser.add_argument("--path", type=Path, help="Single bz2 file to parse")
    parser.add_argument("--dir", type=Path, help="Directory of bz2 files")
    parser.add_argument("--output", type=Path, default=Path("data/parsed"))
    args = parser.parse_args()

    if args.path:
        rows = parse_bz2_file(args.path)
        df = pd.DataFrame([asdict(r) for r in rows])
        out = args.output / args.path.with_suffix(".parquet").name
        args.output.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
        print(f"Wrote {out} ({len(df)} rows)")
    elif args.dir:
        parse_directory(args.dir, args.output)
    else:
        parser.error("Provide --path or --dir")
