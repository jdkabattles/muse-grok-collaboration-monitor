# Muse × Grok collaboration monitor

Read-only mailbox dashboard. It connects automatically to the same-origin
`./mailbox-snapshot.json`, polling every 30 seconds. Real routing records and
receipt states are shown—not inferred agent activity or independently verified
work. Invalid, unavailable, failed or older-than-20-minute snapshots clear the view.
Demo is an explicit optional action, never a fallback.

The canonical mailbox is **private**. A separate local authenticated publisher
validates an exact source commit and exports only reviewed public metadata.
No message subjects/bodies, evidence, event notes, credentials, private source
code or consumer cursors are published. No credentials are stored in this repo,
HTML or Actions. No agent tasks/ACKs are executed. See [LIVE.md](LIVE.md).

A ten-minute producer schedule is an operator setup step, **not installed by
this implementation**. Without it the initial snapshot expires; browser polling
alone cannot refresh the private source or wake an agent.

Tests (stdlib / Node built-ins, no dependencies):

```sh
node --test tests/monitor.test.mjs
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

[REVIEW.md](REVIEW.md) records visual review scope and remaining gates.
