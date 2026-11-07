# muse-grok-collaboration-monitor

Mobile-first Muse × Grok collaboration dashboard, currently **DEMO / MOCK**.
Agent names, states and exchanges are illustrative—not live mailbox telemetry.
The default demo makes no application network requests and runs no agent tasks.

A same-origin read-only snapshot hook is available only through explicit opt-in;
no real adapter, credentials or private mailbox data are included. Invalid,
unavailable or stale snapshots clear the display rather than retain old states.

Tests: `node --test tests/monitor.test.mjs` (Node built-ins; no dependencies).
See [REVIEW.md](REVIEW.md) for the data contract, safeguards and verification limits.
