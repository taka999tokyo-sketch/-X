# ARK-X paper calculation runner — deployment candidate

NOT DEPLOYED. No 24-hour operation claim. This package contains code only; no input data or secrets.

One authenticated HTTP service accepts jobs and runs a durable single-worker queue on an attached disk. The web service is needed for n8n's job submission. It is limited to the existing 2026-10-07/08 paper calculation, not a generic AI executor or daily selector. No broker connection or order execution exists.

POST /jobs with Bearer RUNNER_TOKEN and JSON: id, kind=paper_20261008, source_csv, daily_csv, table_html. GET /jobs/ID and /jobs/ID/table require the same token. Only /health is public. Job IDs are idempotent; changed payloads conflict. Three total attempts with backoff. Interrupted work resumes on restart. Invalid data remains failed; it is never converted into a result.

Calculator is the existing fixed-date reference calculation. Fee and intraday uncertainty labels are retained. Outputs remain inside the service. n8n submission, independent FAL audit, and writeback to the existing Library/Drive table are NOT connected yet. This cannot autonomously complete the full daily workflow until those adapters are configured and tested. Only one instance is supported.

Deploy render.yaml with its persistent disk. Do not create a diskless service through an incomplete creation API. CEO approved publication of this deployment candidate to taka999tokyo-sketch/-X on 2026-10-09 JST. No input datasets or credentials are included. Confirm current plan and disk prices before provisioning.
