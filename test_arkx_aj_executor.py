import csv
import tempfile
import unittest
from pathlib import Path

import arkx_aj_executor as x


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)


def candidates():
    rows=[]
    for i in range(30):
        rows.append(dict(code=str(1300+i),name=f"Stock{i}",price=1000+i,turnover_yen=10_000_000_000,borrow_ok="true",restricted="false",halted="false",delisting_watch="false",sector=f"S{i%5}",theme=f"T{i%8}",momentum_5d=i/100,reversal_1d=(30-i)/100,zero_line_distance=(i-15)/100,volume_ratio=1+i/100))
    return rows


class AjExecutorTest(unittest.TestCase):
    def test_full_paper_lifecycle_and_hash_chain(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); snapshot=d/"snapshot.csv"; write_csv(snapshot,candidates()); ledger=x.Ledger(d/"ledger")
            frozen=x.freeze(ledger,"2026-10-21",snapshot,"2026-10-21T14:35:00+09:00","2026-10-21T14:59:00+09:00")
            self.assertEqual(len(frozen["picks"]),100)
            self.assertTrue(all(p["snapshot_sha256"]==frozen["snapshot_sha256"] for p in frozen["picks"]))
            with self.assertRaises(ValueError): x.freeze(ledger,"2026-10-21",snapshot,"2026-10-21T14:35:00+09:00","2026-10-21T14:59:00+09:00")
            entries=d/"entries.csv"; write_csv(entries,[dict(team=p["team"],side=p["side"],code=p["code"],entry_price="1000",notional_yen="1000000") for p in frozen["picks"]])
            x.record_entries(ledger,"2026-10-21",entries,"2026-10-21T15:30:00+09:00")
            exits=d/"exits.csv"; write_csv(exits,[dict(team=p["team"],side=p["side"],code=p["code"],exit_price="1010",brokerage_yen="100",borrow_fee_yen="2",reverse_interest_yen="0",other_fee_yen="3") for p in frozen["picks"]])
            scored=x.score(ledger,"2026-10-21","2026-10-22",exits,"2026-10-22T15:30:00+09:00")
            self.assertEqual(len(scored["rows"]),100); x.Ledger(d/"ledger").verify()

    def test_late_freeze_and_missing_fee_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); snapshot=d/"snapshot.csv"; write_csv(snapshot,candidates()); ledger=x.Ledger(d/"ledger")
            with self.assertRaises(ValueError): x.freeze(ledger,"2026-10-21",snapshot,"2026-10-21T14:35:00+09:00","2026-10-21T15:01:00+09:00")
            frozen=x.freeze(ledger,"2026-10-21",snapshot,"2026-10-21T14:35:00+09:00","2026-10-21T14:59:00+09:00")
            entries=d/"entries.csv"; write_csv(entries,[dict(team=p["team"],side=p["side"],code=p["code"],entry_price="1000") for p in frozen["picks"]])
            x.record_entries(ledger,"2026-10-21",entries,"2026-10-21T15:30:00+09:00")
            exits=d/"exits.csv"; write_csv(exits,[dict(team=p["team"],side=p["side"],code=p["code"],exit_price="1010",brokerage_yen="0",borrow_fee_yen="",reverse_interest_yen="0",other_fee_yen="0") for p in frozen["picks"]])
            with self.assertRaises(ValueError): x.score(ledger,"2026-10-21","2026-10-22",exits,"2026-10-22T15:30:00+09:00")


if __name__ == "__main__": unittest.main()
