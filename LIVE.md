# Private mailbox → safe live metadata

## Architecture and trust boundary

Canonical source: private `jdkabattles/muse-bot-collab`, branch
`collective/mailbox-v1`, directory `mailbox/`. Authenticated GitHub metadata
reported private; an anonymous pinned `mailbox/agents.json` request returned 404.
This is not evidence that the repository/file is absent. Consequently no public
Actions job, new remote secret, repository visibility change or browser PAT is used.

`tools/live_snapshot.py export`:

1. Takes exclusive non-blocking publisher and private-cache locks. Uses its OWN
   bare read cache, never Forge's working checkout. Normal Git authentication preserves host environment/configuration and credential
   helper/account selection, including GH_TOKEN/GITHUB_TOKEN precedence. If both
   variable names are present, it stops with a sanitized diagnostic for operator
   review rather than clearing either or silently choosing an account. No
   credential value is inspected, printed, persisted,
   configured into a URL or forwarded to another bot.
2. Checks the exact remote branch, fetches full history (no checkout of source
   code, submodule recursion, shallow/partial clone or arbitrary URL), and requires
   the fetched branch to match. It requires descent from the reviewed baseline below
   and checks EVERY intervening commit against EVERY parent, allowing only additions
   to inbox/event paths. Modify/delete/restore and merge-side rewrites fail even
   when endpoint bytes match. A private non-secret last-successful source pin
   additionally requires monotonic ancestry; rollback after the baseline fails.
   Local object queries cannot lazy-fetch.
3. Materializes only registry/inbox/events DATA at that immutable commit into a
   temporary directory. Rejects symlinks/non-regular modes, unsafe paths, poison,
   incomplete data, limits, changed refs or dirty non-bare sources. No fetched
   Python, payload, evidence reference, executable, command or shell is executed.
4. Runs the reviewed **local** read-only validator on the WHOLE message/event
   tree: shape, canonical SHA256, duplicates/nonces, threading, expiry rules,
   transitions, legacy correction and completed-response evidence links. For EVERY
   imported event it additionally requires its source commit to be a local
   ancestor containing the exact message bytes. Completion also source-pins its
   response; correction pins its legacy event/revocation as applicable. These are
   object membership/integrity checks, NOT authentication or independent truth.
5. Requires the complete registry to match `tools/public_roster.json`. All real
   entries are included; a changed/new name/identity stops export pending explicit
   public-name review. No arbitrary private display name passes through. Current
   Muse label remains pending endpoint confirmation; this does not invent a
   confirmed identity or consumer installation.
6. Rechecks the remote branch after validation. Only then records
   `remoteCheckedAt`, validates the PUBLIC allowlist, and atomically replaces the
   snapshot. Source/check/validation failure instead writes a tiny sanitized
   `unavailable` envelope. No old-data or demo fallback is exported.

The reviewed validator subset derives from source commit
`ff14560830b17b959ae9eab74afb1a5f93a86490`, `mailbox/messenger.py` (original
SHA256 `a97e63f065cb1257f4d900b00f1e6f069051175780909dc398a863ec88f23ea5`).
It ends after cross-file validation; ACK/create/cursor/lock/publish/main code and
unused imports are removed. It is vendored here for review, never dynamically
loaded from fetched source. Changing the source protocol requires a separate
reviewed validator update; there is no auto-update or compatibility bypass.
`mailbox_validator.py` SHA256:
`d10cc3a6baf05b6860705987b5ae16824c3d27c0dcad53e4372e3bde7964cd08`.

## Public v2 contract

Existing Agent and Message fields are retained:

- Agent: `{id,name,kind:'grok'|'muse',status,lastTurnAt}`. Real status is always
  `unknown`, actual turn time always `null`: no turn/heartbeat source exists here.
- Message: `{id,from,to,timestamp,type,status,payloadSummary}`. Status is the last
  validated event, or `queued` if none. Expired queued messages remain historical
  records, explicitly not actionable; received/accepted expired work is not lost.
  Summaries are generated ONLY from type/status/expiry, never copied from payload.
  A recorded completion is explicitly not independently verified work.

Ready envelope has EXACTLY:

```
{schemaVersion:2, state:'ready', agents:[], messages:[],
 source:{repo,ref,path,commit,committedAt},
 observedAt,validatedAt,remoteCheckedAt,counts:{agents,messages,events}}
```

Failure envelope has EXACTLY:

```
{schemaVersion:2,state:'unavailable',attemptedAt,
 reason:'Mailbox source check or validation failed.'}
```

No subjects, body text, notes, evidence references/hashes/artifacts, consumer
cursors, pending-list prose, account details, tokens or arbitrary source URLs.
Public routing IDs, safe roster names, timestamps, enums, counts and source pins
are intentional metadata disclosures. A second strict export allowlist plus a
heuristic credential-pattern check guards accidental expansion. Privacy relies
on construction/allowlisting, not on a regex detecting every possible secret.

Limits: 60 public agents, 200 messages, 256 KiB snapshot; whole source validation
retains v1's 64 KiB/file and 1,000 files per message/event tree, with an 8 MiB total
data cap. Capacity overflow fails closed; no silent subset is displayed.

`observedAt` is capture time; `validatedAt` is successful full validation time;
`remoteCheckedAt` is successful matching remote-head check time. `committedAt` is
Git's recorded commit time, NOT a heartbeat or independent trusted clock. An old
unchanged commit may have a fresh source check. All raw timestamps are UTC;
the dashboard renders America/Chicago with CST/CDT labels. It shows commit time,
check time, counts, source links and elapsed check age separately.

Frontend defaults to `./mailbox-snapshot.json` relative to the Pages subpath.
Same-origin only; credentials omitted; redirects rejected; 8 s timeout; streamed
256 KiB bound; strict JSON/shape/source/summary/timestamps. A failed fetch, source
failure envelope, malformed data or >20 min observed/check age clears ALL data.
No persistent local storage, stale cache fallback or automatic mock restoration.
Pagehide clears data/timers; bfcache pageshow restarts validation. Browser refresh
is every 30 s; source cadence target is 10 min plus Pages build delay. No promise
of instant publication, scheduler availability, consumer installation or agent wake.
Private source links are fixed GitHub repo/branch/commit/message-file paths and
require viewer access. No browser request is made to the private mailbox.

## Exact operator commands

The FIRST integration publishes the reviewed code and initial safe snapshot by a
normal reviewed commit/push. A recurring routine is NOT a prerequisite for that
first publication; the parent saves it afterwards.

Python 3, Git and gh are needed locally. Snapshot commits use the reserved
automation author `Grok Bot <grok-bot@users.invalid>` (matching the reviewed
mobile baseline convention), not a personal email or authenticated agent identity.
Existing host-managed authentication must grant source read and monitor write.
No remote Actions secret is needed. The private cache must remain OUTSIDE the
public repo. From the monitor checkout:

```sh
# Local export only, safe to rerun before review/publication:
python3 tools/live_snapshot.py export --cache /workspace/monitor-live-source/mailbox.git

# ONLY after the reviewed integration has been committed/pushed and the parent
# has authorized/saved the recurring publication routine; requires clean main:
python3 tools/live_snapshot.py publish --cache /workspace/monitor-live-source/mailbox.git
```

Publisher requires clean `main`, exactly one effective authorized fetch AND push
URL (normal `remote get-url --all` and `--push --all`), no URL rewrite rules, and
local HEAD equal to
current remote main. It refreshes the source, then stages/commits ONLY the
snapshot, checks expected parent, scope and exact generated file/index/commit
hash, and performs ONE normal non-force push to the explicit authorized monitor HTTPS
URL, with ordinary host authentication/config and hooks intact. Destination checks
are repeated immediately before push; alternate pushurls/multiple destinations
and insteadOf/pushInsteadOf rewrites fail closed (even unrelated rewrite rules
require manual review). No auth-helper override, GH_TOKEN clearing, alternate
credential/transport route or account switching occurs. Even a check
failure can publish the sanitized unavailable envelope, provided publication
checks pass. Conflicts, local edits, changed remote main, failed auth, hooks or
push failure STOP. No reset, amend, rebase, force, hook skipping, retry loop,
credential fallback or automatic conflict resolution. A rejected push may leave a
local commit: preserve it for review; later runs stop rather than overwrite it.
Do not use this checkout for simultaneous manual edits and recurring publication.
A trusted local filesystem/operator is assumed; locks coordinate cooperating
writers, not a hostile process with filesystem ownership. Remote-head checks are
observations at a time, not a distributed transaction or authenticated actor proof.

The non-secret source guard lives beside the PRIVATE cache, outside the public
repo: with the documented command it is
`/workspace/monitor-live-source/mailbox.git.last-success.json`. It records the last
fully validated, freshly checked source pin AFTER safe local snapshot replacement;
it does not claim dashboard publication or deployment. It survives cache-directory
recreation. Do not delete, repoint or reset this guard to work around rollback.
Missing guard bootstraps from the explicitly reviewed source baseline; moving to a
new cache/state path is an operator trust decision, never source-driven. All new
history since the baseline is still checked on every run, with a 1,000-commit bound.
The snapshot and guard are coordinated by publisher/cache locks; trusted local
filesystem ownership is required. A guard-write failure stops before publication.

## Reviewed publication cadence

Read-only Pages API inspection reports `build_type: legacy`, source main `/`.
GitHub documents a soft limit of 10 Pages builds/hour for legacy builds.
The proposed snapshot publisher runs every **10 minutes, 24/7** (6 builds/hour),
leaving headroom below that soft limit. Browser polling remains 30 seconds;
the existing separate five-minute mailbox collaboration workflow is unchanged.
The 20-minute snapshot cutoff allows publication/build delay, not a promise that
GitHub always deploys instantly or on schedule. Check age remains visible, and
failure/staleness clears data. No workflow, Pages setting, rate-limit bypass,
visibility change or additional credential is installed by this candidate.
Official reference: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits

## Command exit/report semantics

- **0:** source check and full validation succeeded; snapshot was exported locally,
  or `publish` verified remote main equals its resulting commit. JSON `state` is
  `ready`; `publishedCommit` is null for export, a full SHA for publish.
- **3:** source check/validation failed (including possible source authentication
  failure); sanitized `unavailable` snapshot was written. For `publish`, this code
  is returned ONLY after successful publication/readback of that failure envelope:
  JSON has `state: unavailable`, no source pin/counts, and a full `publishedCommit`.
  For export, `publishedCommit` is null. This is NOT a successful source read.
- **2:** publication/auth/preflight/locking/output failure, invalid invocation or
  otherwise blocked/unverified completion. No success JSON is printed; only a
  sanitized STOP message (or argument-usage error). A local commit or even an
  unverified remote push may exist: pause and inspect, never automatically retry,
  reset or infer that nothing was published.

Parent routine must pause/report on **2**. Treat **3** as a source failure and
report whether its sanitized unavailable envelope was published; pause for source
review as well, since this category can include source-auth failure. Do not print
raw subprocess errors, credentials or private source details. Exit 0 confirms Git
publication only, NOT successful Pages deployment; deployment must be checked
separately before claiming a public update.

## Proposed routine — NOT installed

Every ten minutes, 24/7, run the `publish` command above from the reviewed monitor
checkout using the existing host-managed auth. Do not run payload tasks or modify
the private mailbox; no new credentials, services or spending. Respect the script's
lock/clean/expected-head gates. On nonzero exit, report sanitized failure once and
stop for review; do not force, repair/retry Git, publish raw data or change auth.
If source check failed but the script published `unavailable`, do not represent it
as a fresh source read. Do not report a successful Git push as successful Pages
deployment; check deployment separately when reporting public freshness.
Send failures to the user in this Grok Bot chat; stay silent on ordinary successful
refreshes, including an unchanged source.

Parent must save/verify the actual routine and its permissions. This code does not
install any cron job, service, webhook, agent consumer or bot wake mechanism.
Without recurring publication a one-off snapshot expires after 20 minutes.
