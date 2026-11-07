# Mobile collaboration monitor — implementation and verification notes

Source baseline main: `35aadd26e4e81ed3d760fcd07b5ba05735422f63`.
Original index SHA-256: `9c4404a2aeaf910d4e5c7198d11b2a401c4f37ac1e193dd80e0bd5aa1298cf19`.
The original remains inspectable as `index.html` at the source baseline commit;
no machine-local backup path is required to inspect the published source history.

## Scope / visual direction

Single-file HTML rewrite; local Node tests; no dependencies, CDN, fonts, trackers,
remote resources in demo, product site changes, or messenger writes. README now
explicitly identifies the dashboard as demo rather than live telemetry.
Dark steel plates, restrained rivets, high-contrast type and red spark accent only.
No gradients, stock imagery, additional logos, fabricated product claims or anvil.
Palette/hierarchy adapted from the Mandate Check IMAGE brief, not represented as a
dashboard specification. Source: project-chimera `5af11a3b4463b0dff8f60143f8fe6706598c6aa3`,
`visuals/forgingstack/STYLE-BRIEF.md`, blob `9c4717ef88792059cb17a43d54ea4404a8adaa78`.
Reviewed brief byte SHA-256: `6b8d179c7ea3351c615786c83eb5a3863f9d87db5d6a40462264e31b183f96ef`.
Muse's separate review response is pending; no invented Muse endorsement.

## What changed

- Mobile-first natural document scrolling; stacked header and panels, minmax(0,1fr)
  grids, wrapping names/statuses, no truncation or global overflow-hiding workaround.
- Canvas uses deterministic nonoverlapping cells, short reference IDs, filled
  label plates and a complete accessible DOM directory. Grok/Muse also differ by
  shape/labels, not color alone. DPR backing store (cap 4) + ResizeObserver/window
  resize. No animation loop, no per-frame DOM rebuild, no motion dependency.
- Clear DEMO/MOCK labels, every agent/message state explicitly marked demo. Actual
  turn times null, no fabricated last-poll clock or inferred online/consumer state.
- Typed bounded records, duplicate IDs/JSON keys rejected, inert textContent DOM,
  atomic validated snapshots and fail-closed error/stale states that remove data.
- Opt-in same-origin read-only snapshot loader: no fetch until Connect is pressed.
  30-second interval, 8-second timeout, no credentials/referrer/redirects, JSON media
  type/256-KiB streamed cap, 90-second snapshot expiry, source commit provenance.
  Remote Git freshness always unknown; UI refresh is not Git sync or agent wake.

## Real snapshot contract / poll hook

Existing Agent fields retained: `{id,name,kind:'grok'|'muse',status,lastTurnAt}`.
Existing Message fields retained: `{id,from,to,timestamp,type,status,payloadSummary}`.
IDs are bounded ASCII routing labels, not authenticated identities. Agent states:
unknown/idle/running/blocked/offline. Message states: queued/received/validated/
accepted/completed/failed/rejected/completion-revoked; request/response types.
Time fields use canonical UTC ISO strings, optional milliseconds. lastTurnAt is
null unless an actual source turn time exists; never infer it from a message.
Agent states/turn times remain source reports, not independent execution proof.

Envelope: `{schemaVersion:1, agents:[], messages:[], sourceCommit:<40-hex>,
validatedAt:<UTC ISO>, remoteFreshness:'unknown'}`. Only these exact fields.
60 agents/200 messages max. Summary/name limits 500/180 characters. Adapter must
export safe summaries, not credentials/private payloads; no such adapter is
installed or claimed by this mock-first rewrite. Do not publish a private snapshot.

The obvious hook is `MailboxPoller.connect()` -> `poll()` -> `readBoundedJSON()` ->
`validateSnapshot()` -> `MonitorState.set()`. Relative .json or
`/api/mailbox-snapshot` endpoint; same origin only, no credentials/query/fragment.
Default endpoint absent intentionally: Connect will show ERROR/NO DATA, not mock
fallback. Return to demo is an explicit user action. Nothing triggers ACKs/tasks.

## Tests and browser review

Run `node --test tests/monitor.test.mjs` (Node built-ins only). Forty tests extract
the inline module; no browser/headless engine is launched. They cover bounded
parsing, XSS/static DOM checks, expiry/failure/races, zero-fetch demo, opt-in fetch
settings, lifecycle restoration and chronological sorting. Pairwise topology
bounds/collisions cover widths 144..1440 and up to 60 nodes. These unit tests do
NOT establish CSS pixel layout or visual quality.

Parent-reported browser QA on November 7, 2026, via a local file URL covered
320/360/390/430/768/1280 px and 200% zoom: no obvious overlap, clipping or horizontal
scrollbar; all six full names/statuses in the accessibility tree; expanded IDs
wrap; Connect clears data/shows error, and Return to demo works. This report is
limited to the reviewed candidate index SHA-256
`11b17fbe1fce082f674de693e58f406ea892c54cd190604ff39eac83d1a14bf4`.

The browser refused the local HTTP preview even though separate HTTP smoke
requests returned 200. Consequently there is NO HTTP-browser network proof and
NO verified real-mailbox integration. Original reported screenshots were not
supplied; screenshot matching is not claimed. Muse's style reply remains pending;
review of the cited brief and the genuine coordination request do not constitute
Muse endorsement.

Publication is scoped to the dashboard under Jonathan's t105u authorization;
this document does not grant permission for future changes or publication.

## Follow-up review fixes

- pagehide now clears real snapshots and suspends timers; pageshow revalidates
  the remembered opt-in same-origin endpoint and restarts polling/freshness.
  Demo restoration remains network-free. Expired bfcache data is never retained.
- Message timestamps sort by parsed instants, including mixed fractional seconds.
- Directory rows expose full routing IDs through wrapping native disclosures.
  Ledger rows expose full message/from/to IDs, with no unsafe HTML insertion.
- Provenance explicitly marks repository/mailbox coordinates unavailable/unverified;
  the strict envelope remains unchanged and is NOT evidence-grade integration.

The added ID disclosures increase directory/feed height. Parent browser review
included expanded IDs. The unit tests themselves are not visual certification.
