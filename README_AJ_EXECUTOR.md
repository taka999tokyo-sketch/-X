# ARK A--J Daily Executor (paper-only)

This is a new ARK-owned component.  It does not read or copy FAL picks, send orders,
connect to a broker, or claim a live result without a complete evidence chain.

Required adapters still absent from the current environment:

1. A 14:30 JST ARK snapshot CSV, containing the documented columns in the code.
2. A scheduler/queue invocation at 14:30, 15:00, 15:30 and the next trading day.
3. ARK-owned 15:30 entry and next-day exit CSVs including all fees.

Example local paper run:

```bash
python arkx_aj_executor.py ./ledger freeze 2026-10-22 snapshot.csv 2026-10-22T14:30:00+09:00 2026-10-22T14:59:00+09:00
python arkx_aj_executor.py ./ledger entries 2026-10-22 entries.csv 2026-10-22T15:30:00+09:00
python arkx_aj_executor.py ./ledger score 2026-10-22 2026-10-23 exits.csv 2026-10-23T15:30:00+09:00
python arkx_aj_executor.py ./ledger verify
```

Invariants tested: A--J each select BUY5/SELL5 (100 picks), 15:00 cut-off, no
duplicate freeze, exact pick-to-entry matching, all cost fields required, and the
append-only SHA-256 ledger chain.
