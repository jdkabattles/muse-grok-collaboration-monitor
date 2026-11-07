# Collaboration monitor — review status

## Already-published mobile baseline

Commit `39984d1ae6b8c28fca86c0fc9984ce1d80016bf2`, index SHA256
`11b17fbe1fce082f674de693e58f406ea892c54cd190604ff39eac83d1a14bf4`.
That baseline was deployed successfully to Pages and publicly read back byte-for-byte.
Its 40 tests passed. Parent-reported FILE-URL browser QA covered 320/360/390/430/
768/1280 px and 200% zoom, full six demo names/statuses, expanded wrapping IDs,
error clearing and explicit demo return. Local HTTP browser access failed despite
separate HTTP 200 smoke checks; no HTTP-browser proof was claimed.

Visual direction adapts only palette/hierarchy from the Mandate Check IMAGE brief:
project-chimera `5af11a3b4463b0dff8f60143f8fe6706598c6aa3`,
`visuals/forgingstack/STYLE-BRIEF.md`, blob
`9c4717ef88792059cb17a43d54ea4404a8adaa78`. It is not a dashboard specification.
Dark steel, restrained rivets, high contrast, red-only accent; no gradients,
CDNs, external fonts/trackers or invented product claims. Muse style advice has now been read from response
`a3958a65-de8a-46e1-9f6b-f77eb37bac62` at source commit
`bdcd5bc785084b7ab043bfa104a710ab35310524`. It recommends dark steel/red
restraint, system fonts, wrapping mobile layout and explicitly labeled states.
Advice was treated as attributed source data, not authority or endorsement. No
major UI changes or suggested extra status colors were introduced for publication.

## Live integration candidate (t117u)

See [LIVE.md](LIVE.md) for architecture, privacy boundary, exact commands and
proposed (NOT installed) ten-minute routine. Read-only private-source capture
has produced a real metadata-only snapshot from a freshly checked remote pin.
At pre-publication handoff, parent relayed a fixes-only Chimera static review of
index SHA256 `3815b0f6c05fc1cdaee221bac7d275dc8a802b1d62ee194da0309f2cf4509d5d`
and publisher SHA256 `613983fbc533535d85de43aa316ce5a2cd68a939e9aebdbba49ad229e47c051f`,
with no residual material blocker. Public live browser end-to-end QA is pending;
this static review does not prove browser connectivity or deployment.

Changes preserve the mobile layout, canvas DPR/ResizeObserver, deterministic
collision-free cells, safe textContent rendering and full wrapping names/IDs.
Default load now connects live rather than demo. Added real source coordinates/
links, recorded commit time, observed/validated/check times, check age, event
count and explicit unknown agent activity. Message completion is marked recorded,
not independently verified. The real roster replaces synthetic Muse duplicates.
Source and snapshot failures clear the view; no automatic demo fallback. Freshness
is now 20 minutes, appropriate to a ten-minute producer plus build delay, not
90 seconds. Independent source checks do not infer heartbeat or agent turns.

Tests use Node built-ins and Python stdlib; no browser/headless engine is launched:

```sh
node --test tests/monitor.test.mjs
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The pinned real-source test is explicitly skipped without `MAILBOX_TEST_CACHE`.
With an OWN bare cache available after an authenticated export, enable it:

```sh
MAILBOX_TEST_CACHE=/workspace/monitor-live-source/mailbox.git \
  python3 -m unittest discover -s tests -p 'test_*.py' -v
```

It compares actual source validation, full registry, counts, effective states and
pins with the initial snapshot; no private bodies are test fixtures in this repo.
Other events/messages are synthetic fixtures ONLY in temporary test repositories,
never recipient actions. Tests cover poison/tampering, expiry visibility, receipt
forks, response-backed completion, Git membership, dirty/ref drift, symlinks, full intervening immutable-path history, monotonic
last-success pin, malicious pushurls/rewrites, unchanged normal auth selection,
privacy allowlists, failed/offline source export, atomic output, locks, expected
heads, one-push rejection and preserving the local commit for manual review. Distinct
exit codes cover successful ready publication, published sanitized source failure,
and blocked/unverified publication/auth failures.
Frontend tests cover strict parsing, XSS/static DOM safety, caps/offline/staleness,
default live and explicit network-free demo, Pages subpath, source links,
bfcache revalidation, actual snapshot contract and chronological ordering.

Publication go-ahead has been relayed by the parent under t117u. The publication
workflow reruns tests/scans, exports freshly, checks the expected main head and
verifies exact remote/Pages bytes. Parent must still perform PUBLIC live browser
end-to-end QA and save/verify the ten-minute publication routine after the first
integration. No static test or successful push proves either of those steps. No mailbox
writes, product deployment, additional source identity, schedule or agent
installation was performed. This document does not authorize publication.
