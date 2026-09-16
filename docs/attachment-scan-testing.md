# Attachment Scan — Test Walkthrough (Cloudmersive free tier)

Branch: `ceo/attachment-scan-free` · Date: 2026-09-16
Worker: `malware_scan_worker.py` · Callback: `POST /document-storage/{id}/scan-result` (existing route) ·
Sweeper: `GET /document-storage/scan-sweep` (Vercel cron, hourly)

> **Do not run live scans without a key.** The worker refuses to start unless
> `CLOUDMERSIVE_API_KEY` and `MALWARE_SCAN_CALLBACK_SECRET` are set in the
> environment. Provide them via Secure Vault — never in chat, code, or logs.

## Prerequisites

1. Owner signs up at https://www.cloudmersive.com (free tier: 800 scans/month) and
   supplies `CLOUDMERSIVE_API_KEY` via Secure Vault.
2. Owner generates the callback secret and supplies `MALWARE_SCAN_CALLBACK_SECRET`
   via Secure Vault: `openssl rand -hex 32`
3. Set both as Vercel env vars (production) and locally for the worker run.
4. Deploy the branch (merge to main first — needs Juan's approval).

## A. Unit tests (no keys, no network)

```bash
pytest tests/test_malware_scan_worker.py -v
```

Covers: EICAR signature constant, Cloudmersive verdict mapping (unexpected shape
=> fail-closed `ValueError`), callback state-guard matrix (terminal states are
sticky), lease stuck detection, sweeper releasing only stuck leases, SHA-256
dedup reuse, monthly quota counting, `scan_failed` never marking clean + owner
alert event, worker refusing to start without secrets.

## B. EICAR live walkthrough (minimum live path — staging first)

The EICAR string is the industry-standard harmless antivirus test signature
(inert by design — it is not malware):

```
X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*
```

1. Create a document record and authorize an upload:
   `POST /document-storage/{id}/upload` with `filename: "eicar-test.txt"`,
   `content_type: "text/plain"`, `size_bytes: 68`.
2. PUT the 68-byte EICAR string (exactly, no trailing newline) to the signed URL.
3. `POST /document-storage/{id}/complete` → expect `storage_status: "scan_pending"`,
   `malware_scan_status: "pending"`.
4. Run the worker: `python malware_scan_worker.py`
5. Expect:
   - callback `infected` from provider `cloudmersive` (detail names EICAR-Test-File),
   - object moved to `quarantine/trade-cases/...`,
   - `storage_status: "quarantined"`, `malware_scan_status: "infected"`,
   - `GET /document-storage/{id}/download` → **423** (fail-closed holds).
6. Upload the identical 68 bytes as a second document and re-run: expect
   `dedup_infected` in worker stats — no second API call, no quota consumed.

## C. Clean-file walkthrough

Upload a real small PDF via the signed-URL flow, run the worker, expect
`malware_scan_status: "clean"`, `storage_status: "clean"`, download → 200.

## D. Outage / fail-closed walkthrough

Point the worker at an invalid `CLOUDMERSIVE_API_KEY` and run against a pending
document three times. Expect: each run posts `error` (document returns to
`pending`), the third run sets `malware_scan_status: "scan_failed"` and logs a
`scan_failed` event containing "OWNER ATTENTION". **At no point may the document
become `clean`.**

## E. Stuck-lease walkthrough

Manually set a document to `malware_scan_status: "scanning"` with
`scan_locked_at` 2h in the past, then hit `GET /document-storage/scan-sweep`
(with `Authorization: Bearer $CRON_SECRET`). Expect `{"reset": 1, ...}` and the
row back at `pending`.

## F. Spoofed-callback walkthrough

`POST /document-storage/{id}/scan-result` with a wrong `X-Scan-Secret` →
expect **403** and no state change.

## Free-tier quota notes

- Default `SCAN_MONTHLY_QUOTA=800` matches the Cloudmersive free tier.
- The worker counts consumed scans in `malware_scan_records` per calendar month
  and defers new API scans when exhausted (documents stay `pending`, fail-closed).
- Dedup cache hits never consume quota.
- If real volume approaches 800/mo, the owner decision is: paid Cloudmersive
  Basic ($19.99/mo, 20k calls) or attachmentAV — not code changes.
