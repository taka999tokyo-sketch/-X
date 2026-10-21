"""ARK-only, paper-only A--J daily execution ledger.

This module deliberately has no broker, HTTP, n8n, Drive, or FAL adapter.
It accepts immutable CSV snapshots supplied by an adapter, fixes selections before
15:00 JST, records 15:30 entries, and scores the next trading day.  Every write is
append-only JSON with a SHA-256 chain, so a late snapshot cannot silently become an
ARK result.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
TEAMS = tuple("ABCDEFGHIJ")
BUY, SELL = "BUY", "SELL"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def parse_jst(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(JST)


def require_window(value: datetime, start: time, end: time, label: str) -> None:
    if not start <= value.timetz().replace(tzinfo=None) <= end:
        raise ValueError(f"{label} must be between {start} and {end} JST")


@dataclass(frozen=True)
class Candidate:
    code: str
    name: str
    price: float
    turnover_yen: float
    borrow_ok: bool
    restricted: bool
    halted: bool
    delisting_watch: bool
    sector: str
    theme: str
    momentum_5d: float
    reversal_1d: float
    zero_line_distance: float
    volume_ratio: float


@dataclass(frozen=True)
class Pick:
    team: str
    side: str
    rank: int
    code: str
    name: str
    score: float
    snapshot_sha256: str


def load_candidates(path: Path) -> tuple[list[Candidate], str]:
    raw = path.read_bytes()
    rows = list(csv.DictReader(raw.decode().splitlines()))
    required = set(Candidate.__dataclass_fields__)
    if not rows or not required.issubset(rows[0]):
        raise ValueError("snapshot CSV has missing required columns")
    truth = {"1", "true", "yes", "y"}
    candidates = []
    for row in rows:
        candidates.append(Candidate(
            code=row["code"].zfill(4), name=row["name"], price=float(row["price"]),
            turnover_yen=float(row["turnover_yen"]), borrow_ok=row["borrow_ok"].lower() in truth,
            restricted=row["restricted"].lower() in truth, halted=row["halted"].lower() in truth,
            delisting_watch=row["delisting_watch"].lower() in truth, sector=row["sector"], theme=row["theme"],
            momentum_5d=float(row["momentum_5d"]), reversal_1d=float(row["reversal_1d"]),
            zero_line_distance=float(row["zero_line_distance"]), volume_ratio=float(row["volume_ratio"]),
        ))
    if len({c.code for c in candidates}) != len(candidates):
        raise ValueError("snapshot has duplicate codes")
    return candidates, sha256_bytes(raw)


def eligible(c: Candidate, side: str) -> bool:
    if c.price < 500 or c.turnover_yen < 5_000_000_000 or c.halted or c.delisting_watch:
        return False
    return side != SELL or (c.borrow_ok and not c.restricted)


def team_score(c: Candidate, team: str, side: str) -> float:
    """Ten deterministic, inspectable variations; no model call or future data."""
    weights = {
        "A": (1.0, 0.2, -0.4, 0.2), "B": (0.8, 0.6, -0.2, 0.1),
        "C": (0.5, 1.0, -0.3, 0.3), "D": (1.2, -0.2, -0.7, 0.1),
        "E": (0.3, 1.2, -0.2, 0.2), "F": (0.7, 0.5, -0.8, 0.4),
        "G": (1.1, 0.1, -0.5, 0.5), "H": (0.4, 0.9, -0.6, 0.1),
        "I": (0.9, 0.3, -0.1, 0.6), "J": (0.6, 0.7, -0.9, 0.2),
    }[team]
    sign = 1 if side == BUY else -1
    m, r, z, v = weights
    return sign * (m*c.momentum_5d + r*c.reversal_1d + z*c.zero_line_distance + v*c.volume_ratio)


def choose(candidates: Iterable[Candidate], team: str, side: str, snapshot_sha256: str) -> list[Pick]:
    pool = [c for c in candidates if eligible(c, side)]
    ranked = sorted(pool, key=lambda c: (-team_score(c, team, side), c.code))
    chosen: list[Candidate] = []
    sector_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    for c in ranked:
        if sector_counts.get(c.sector, 0) >= 3 or theme_counts.get(c.theme, 0) >= 2:
            continue
        chosen.append(c); sector_counts[c.sector] = sector_counts.get(c.sector, 0)+1; theme_counts[c.theme] = theme_counts.get(c.theme, 0)+1
        if len(chosen) == 5:
            break
    if len(chosen) != 5:
        raise ValueError(f"{team}/{side}: insufficient eligible diversified candidates ({len(chosen)}/5)")
    return [Pick(team, side, i+1, c.code, c.name, round(team_score(c, team, side), 8), snapshot_sha256) for i, c in enumerate(chosen)]


class Ledger:
    def __init__(self, root: Path):
        self.root = root; self.root.mkdir(parents=True, exist_ok=True)
        self.path = root / "arkx_aj_ledger.jsonl"

    def events(self) -> list[dict]:
        if not self.path.exists(): return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def append(self, event: dict) -> dict:
        prior = self.events()
        event = dict(event)
        event["previous_event_sha256"] = prior[-1]["event_sha256"] if prior else None
        event["event_sha256"] = sha256_bytes(canonical_json({k:v for k,v in event.items() if k != "event_sha256"}))
        with self.path.open("a", encoding="utf-8") as out: out.write(json.dumps(event, ensure_ascii=False, sort_keys=True)+"\n")
        return event

    def verify(self) -> None:
        previous = None
        for event in self.events():
            if event["previous_event_sha256"] != previous: raise ValueError("ledger chain is broken")
            expected = sha256_bytes(canonical_json({k:v for k,v in event.items() if k != "event_sha256"}))
            if event["event_sha256"] != expected: raise ValueError("ledger event hash is broken")
            previous = expected


def freeze(ledger: Ledger, trading_date: str, snapshot: Path, captured_at: str, fixed_at: str) -> dict:
    captured, fixed = parse_jst(captured_at), parse_jst(fixed_at)
    if captured.date().isoformat() != trading_date or fixed.date().isoformat() != trading_date: raise ValueError("wrong trading date")
    require_window(captured, time(14, 30), time(15, 0), "snapshot capture")
    require_window(fixed, time(14, 30), time(15, 0), "candidate freeze")
    if fixed < captured: raise ValueError("cannot freeze before capture")
    if any(e.get("kind")=="freeze" and e.get("trading_date")==trading_date for e in ledger.events()): raise ValueError("already frozen")
    candidates, digest = load_candidates(snapshot)
    picks = [asdict(p) for t in TEAMS for side in (BUY, SELL) for p in choose(candidates, t, side, digest)]
    return ledger.append({"kind":"freeze", "trading_date":trading_date, "captured_at":captured.isoformat(), "fixed_at":fixed.isoformat(), "snapshot_sha256":digest, "picks":picks, "status":"PAPER_ONLY"})


def record_entries(ledger: Ledger, trading_date: str, entries: Path, recorded_at: str) -> dict:
    moment = parse_jst(recorded_at); require_window(moment, time(15, 30), time(15, 35), "entry record")
    freeze_event = next((e for e in ledger.events() if e.get("kind")=="freeze" and e.get("trading_date")==trading_date), None)
    if not freeze_event: raise ValueError("no frozen ARK picks")
    raw = entries.read_bytes(); rows = list(csv.DictReader(raw.decode().splitlines()))
    expected = {(p["team"], p["side"], p["code"]) for p in freeze_event["picks"]}
    actual = {(r["team"], r["side"], r["code"].zfill(4)) for r in rows}
    if expected != actual or any(float(r["entry_price"]) <= 0 for r in rows): raise ValueError("entries must exactly match frozen ARK picks")
    return ledger.append({"kind":"entries", "trading_date":trading_date, "recorded_at":moment.isoformat(), "source_sha256":sha256_bytes(raw), "rows":rows, "status":"PAPER_ONLY"})


def score(ledger: Ledger, entry_date: str, exit_date: str, exits: Path, scored_at: str) -> dict:
    moment = parse_jst(scored_at); require_window(moment, time(15, 30), time(16, 30), "score")
    entry_event = next((e for e in ledger.events() if e.get("kind")=="entries" and e.get("trading_date")==entry_date), None)
    if not entry_event: raise ValueError("no ARK entry record")
    raw = exits.read_bytes(); rows = list(csv.DictReader(raw.decode().splitlines()))
    by_key = {(r["team"], r["side"], r["code"].zfill(4)): r for r in rows}
    result = []
    for entry in entry_event["rows"]:
        key = (entry["team"], entry["side"], entry["code"].zfill(4)); exit_row = by_key.get(key)
        if not exit_row: raise ValueError(f"missing exit: {key}")
        # All fees are explicit inputs; absence is not treated as zero.
        required_fee = ("brokerage_yen", "borrow_fee_yen", "reverse_interest_yen", "other_fee_yen")
        if any(name not in exit_row or exit_row[name] == "" for name in required_fee): raise ValueError("fee inputs are required")
        entry_price, exit_price = float(entry["entry_price"]), float(exit_row["exit_price"])
        gross = (exit_price-entry_price)/entry_price if entry["side"] == BUY else (entry_price-exit_price)/entry_price
        fees = sum(float(exit_row[name]) for name in required_fee)
        notional = float(entry.get("notional_yen", 1_000_000))
        result.append({"team":key[0],"side":key[1],"code":key[2],"gross_pnl_yen":gross*notional,"fees_yen":fees,"net_pnl_yen":gross*notional-fees,"gross_return_pct":gross*100})
    return ledger.append({"kind":"score", "entry_date":entry_date, "exit_date":exit_date, "scored_at":moment.isoformat(), "source_sha256":sha256_bytes(raw), "rows":result, "status":"PAPER_ONLY"})


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("ledger_dir", type=Path); sub = parser.add_subparsers(dest="cmd", required=True)
    f=sub.add_parser("freeze"); f.add_argument("date"); f.add_argument("snapshot",type=Path); f.add_argument("captured_at"); f.add_argument("fixed_at")
    e=sub.add_parser("entries"); e.add_argument("date"); e.add_argument("entries",type=Path); e.add_argument("recorded_at")
    s=sub.add_parser("score"); s.add_argument("entry_date"); s.add_argument("exit_date"); s.add_argument("exits",type=Path); s.add_argument("scored_at")
    sub.add_parser("verify"); args=parser.parse_args(); ledger=Ledger(args.ledger_dir)
    if args.cmd=="freeze": event=freeze(ledger,args.date,args.snapshot,args.captured_at,args.fixed_at)
    elif args.cmd=="entries": event=record_entries(ledger,args.date,args.entries,args.recorded_at)
    elif args.cmd=="score": event=score(ledger,args.entry_date,args.exit_date,args.exits,args.scored_at)
    else: ledger.verify(); event={"status":"PASS","events":len(ledger.events())}
    print(json.dumps(event,ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
