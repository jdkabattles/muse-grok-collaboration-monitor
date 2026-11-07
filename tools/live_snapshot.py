#!/usr/bin/env python3
"""Private mailbox -> public metadata only. No payload handlers, ACKs or schedules.

export: refresh private read cache, validate immutable commit, write safe snapshot.
publish: same, plus ONE guarded normal commit/push of mailbox-snapshot.json only.
No source code from the private repo is imported, checked out or executed.
"""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import mailbox_validator as validator

SOURCE_REPO = 'jdkabattles/muse-bot-collab'
SOURCE_REF = 'collective/mailbox-v1'
SOURCE_URL = 'https://github.com/' + SOURCE_REPO + '.git'
SOURCE_TRACKING = 'refs/heads/mailbox-source'
SOURCE_BASELINE = 'ff14560830b17b959ae9eab74afb1a5f93a86490'
MONITOR_URL = 'https://github.com/jdkabattles/muse-grok-collaboration-monitor.git'
ROOT = Path(__file__).absolute().parent.parent
OUTPUT = ROOT / 'mailbox-snapshot.json'
SAFE_ROSTER = Path(__file__).absolute().with_name('public_roster.json')
MAX_TREE_BYTES = 8 * 1024 * 1024
FAILURE = 'Mailbox source check or validation failed.'


def require(ok, message):
    validator.require(ok, message)


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class AuthSelectionError(RuntimeError):
    pass


def git(repo, *args, authenticated=False, normal=False, timeout=30):
    # Transport/commit preserve ordinary host auth/config selection. Merely
    # detect ambiguous variable PRESENCE; never inspect or compare token values.
    if authenticated and 'GH_TOKEN' in os.environ and 'GITHUB_TOKEN' in os.environ:
        raise AuthSelectionError()
    if authenticated or normal:
        env = dict(os.environ)
        for key in list(env):
            if key.startswith('GIT_TRACE') or key in {'GIT_CURL_VERBOSE', 'GH_DEBUG'}:
                env.pop(key, None)  # diagnostic logging only, not auth selection
    else:
        env = {'PATH': os.defpath, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
    env.update(GIT_NO_LAZY_FETCH='1', GIT_NO_REPLACE_OBJECTS='1', GIT_OPTIONAL_LOCKS='0')
    result = subprocess.run(['git', '--no-pager'] + list(args), cwd=repo, env=env, check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return result.stdout


def reject_url_rewrites(repo):
    # Conservative: even unrelated rewrite rules require manual review. Query
    # effective normal config, including includes; never print matching values.
    try:
        rules = git(repo, 'config', '--includes', '--get-regexp',
                    r'^url\..*\.(insteadof|pushinsteadof)$', normal=True)
    except subprocess.CalledProcessError as error:
        require(error.returncode == 1, 'unreadable transport configuration')
        return
    require(not rules, 'Git URL rewrites refused; normal transport requires review')


def verify_monitor_transport():
    reject_url_rewrites(ROOT)
    for option in ([], ['--push']):
        urls = git(ROOT, 'remote', 'get-url', *option, '--all', 'origin', normal=True).decode().splitlines()
        require(urls == [MONITOR_URL], 'expected exactly one authorized effective fetch/push destination')


def head(repo):
    value = git(repo, 'rev-parse', 'HEAD').decode().strip()
    require(bool(validator.COMMIT.fullmatch(value)), 'invalid HEAD')
    return value


def clean(repo):
    if git(repo, 'rev-parse', '--is-bare-repository').strip() == b'true':
        return
    require(not git(repo, 'status', '--porcelain', '--untracked-files=all'), 'dirty source')


def remote_head(repo, url, ref):
    reject_url_rewrites(repo)
    rows = git(repo, 'ls-remote', '--exit-code', '--heads', url, ref,
               authenticated=True).decode().strip().splitlines()
    require(len(rows) == 1, 'ambiguous remote head')
    pin, actual = rows[0].split('\t')
    require(validator.COMMIT.fullmatch(pin) and actual == ref, 'wrong remote ref')
    return pin


@contextmanager
def exclusive_lock(path):
    validator.no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def prepare_cache(cache):
    validator.no_symlinks(cache)
    require(cache.is_absolute() and '..' not in cache.parts, 'cache must be an absolute safe path')
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        git(cache.parent, 'init', '--bare', str(cache))
    require(git(cache, 'rev-parse', '--is-bare-repository').strip() == b'true', 'cache must be bare')
    # Never read another agent's working tree, alternates or a partial clone.
    require(not (cache / 'objects/info/alternates').exists(), 'object alternates refused')
    require(not (cache / 'shallow').exists(), 'shallow source refused')
    config = git(cache, 'config', '--local', '--list').decode()
    require(not re.search(r'(partialclone|\.promisor=)', config, re.I), 'partial source refused')


def tree(repo, pin, path='mailbox'):
    raw = git(repo, 'ls-tree', '-r', '-z', '--full-tree', pin, '--', path)
    require(len(raw) <= 512000, 'tree listing too large')
    entries = {}
    for row in raw.split(b'\0'):
        if not row:
            continue
        meta, name = row.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        name = name.decode('ascii')
        require(validator.REF.fullmatch(name) and all(p not in {'.', '..'} for p in name.split('/')),
                'unsafe tree path')
        require(name not in entries, 'duplicate tree path')
        entries[name] = (mode, kind, oid)
        require(len(entries) <= 2200, 'tree entry limit')
    return entries


def blob(repo, entry):
    mode, kind, oid = entry
    require(mode == '100644' and kind == 'blob', 'non-regular source refused')
    require(int(git(repo, 'cat-file', '-s', oid)) <= validator.MAX_BYTES, 'oversized source')
    return git(repo, 'cat-file', 'blob', oid)


def membership(repo, pin, path, expected, ancestors):
    # Exact immutable bytes and ancestry, not identity/authentication/truth.
    require(isinstance(pin, str) and validator.COMMIT.fullmatch(pin), 'invalid source pin')
    if pin not in ancestors:
        git(repo, 'merge-base', '--is-ancestor', pin, ancestors['head'])
        ancestors[pin] = True
    entries = tree(repo, pin, path)
    require(set(entries) == {path} and blob(repo, entries[path]) == expected, 'source membership mismatch')


def generic_summary(message, status, now):
    kind = 'Request' if message['type'] == 'request' else 'Response'
    state = ('Recorded completion; not independently verified.' if status == 'completed'
             else 'Receipt state only; not proof of execution.')
    expiry = ('Expired at validation; no new task authority.'
              if validator.time(message['expires_at']) <= now
              else 'Scope and expiry require mailbox review.')
    return f'{kind} record · {status}. {state} {expiry}'


def capture(repo, pin, *, now=None, drift_check=None):
    """Read-only full tree capture at a commit. Network wrapper attests last check.

    Temporary snapshot has DATA files only; fetched Python is never imported.
    Non-bare test/source trees must be completely clean before and after capture.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    observed = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    validator.no_symlinks(repo)
    clean(repo)
    before = git(repo, 'rev-parse', pin).decode().strip()
    require(before == pin and validator.COMMIT.fullmatch(pin), 'source pin mismatch')
    refs_before = git(repo, 'show-ref')
    entries = tree(repo, pin)
    for name, entry in entries.items():
        require(entry[0] == '100644' and entry[1] == 'blob', 'source symlink/submodule refused')
    selected = {p: e for p, e in entries.items() if p == 'mailbox/agents.json'
                or p.startswith(('mailbox/inbox/', 'mailbox/events/'))}
    total = 0
    with tempfile.TemporaryDirectory(prefix='mailbox-data-') as directory:
        root = Path(directory) / 'mailbox'
        raw_files = {}
        for name, entry in selected.items():
            raw = blob(repo, entry)
            total += len(raw)
            require(total <= MAX_TREE_BYTES, 'source data too large')
            path = Path(directory) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            raw_files[name] = raw
        # Empty trees cannot appear in Git; these data dirs may be empty.
        for sub in ('inbox', 'events'):
            (root / sub).mkdir(parents=True, exist_ok=True)
        messages, chains = validator.scan(root, now=now)
        roster = validator.registry(root)
        safe_roster = validator.load(SAFE_ROSTER)
        require(roster == safe_roster, 'unreviewed public roster: stop, review all entries')
        require(len(roster) <= 60 and len(messages) <= 200, 'public snapshot record limit')
        ancestors = {'head': pin}
        for mid, chain in chains.items():
            message = messages[mid]
            message_path = 'mailbox/inbox/' + message['to'] + '/' + mid + '.json'
            for event in chain:
                source = event['source_commit']
                membership(repo, source, message_path, raw_files[message_path], ancestors)
                if event['status'] == 'completed' and not validator.is_legacy(event):
                    response = messages[event['completion_response_id']]
                    path = 'mailbox/inbox/' + response['to'] + '/' + response['id'] + '.json'
                    membership(repo, source, path, raw_files[path], ancestors)
                if event['status'] == 'completion-revoked' or event['sequence'] == 6:
                    path = 'mailbox/' + validator.legacy_path().as_posix()
                    membership(repo, source, path, raw_files[path], ancestors)
                if event['sequence'] == 6:
                    previous = chain[4]
                    path = 'mailbox/' + validator.event_path(previous).as_posix()
                    membership(repo, source, path, raw_files[path], ancestors)
        agents = [{'id': ident, **safe_roster[ident], 'status': 'unknown', 'lastTurnAt': None}
                  for ident in sorted(roster)]
        public_messages = []
        for message in sorted(messages.values(), key=lambda m: (m['timestamp'], m['id'])):
            status = chains[message['id']][-1]['status'] if chains.get(message['id']) else 'queued'
            public_messages.append({key: message[key] for key in ('id', 'from', 'to', 'timestamp', 'type')}
                                   | {'status': status, 'payloadSummary': generic_summary(message, status, now)})
        counts = {'agents': len(agents), 'messages': len(messages), 'events': sum(map(len, chains.values()))}
    if drift_check:
        drift_check()  # Test-only injected local callback, never data-driven.
    clean(repo)
    require(git(repo, 'rev-parse', pin).decode().strip() == before
            and git(repo, 'show-ref') == refs_before, 'source drift')
    committed = git(repo, 'show', '-s', '--format=%cI', pin).decode().strip()
    committed = dt.datetime.fromisoformat(committed).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'schemaVersion': 2, 'state': 'ready', 'agents': agents, 'messages': public_messages,
            'source': {'repo': SOURCE_REPO, 'ref': SOURCE_REF, 'path': 'mailbox', 'commit': pin,
                       'committedAt': committed}, 'observedAt': observed, 'validatedAt': stamp(),
            'remoteCheckedAt': None, 'counts': counts}


def source_state_path(cache):
    return cache.with_name(cache.name + '.last-success.json')


def read_source_guard(cache):
    path = source_state_path(cache)
    validator.no_symlinks(path)
    if not path.exists():
        return SOURCE_BASELINE
    state = validator.load(path)
    validator.keys(state, 'version repo ref commit')
    require(type(state['version']) is int and state['version'] == 1
            and state['repo'] == SOURCE_REPO and state['ref'] == SOURCE_REF
            and isinstance(state['commit'], str) and validator.COMMIT.fullmatch(state['commit']),
            'invalid last-successful source guard')
    return state['commit']


def record_source_success(cache, pin):
    path = source_state_path(cache)
    validator.no_symlinks(path)
    require(not path.absolute().is_relative_to(ROOT.absolute()), 'source guard must remain outside public repo')
    require(isinstance(pin, str) and validator.COMMIT.fullmatch(pin), 'invalid successful source pin')
    raw = (json.dumps({'version': 1, 'repo': SOURCE_REPO, 'ref': SOURCE_REF, 'commit': pin}, sort_keys=True) + '\n').encode('ascii')
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.source-guard-', delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def verify_history(cache, expected, last_successful):
    git(cache, 'merge-base', '--is-ancestor', SOURCE_BASELINE, expected)
    git(cache, 'merge-base', '--is-ancestor', last_successful, expected)
    rows = git(cache, 'rev-list', '--parents', '--reverse', '--max-count=1001', SOURCE_BASELINE + '..' + expected).decode().splitlines()
    require(len(rows) <= 1000, 'history review limit exceeded')
    for row in rows:
        commit, *parents = row.split()
        require(validator.COMMIT.fullmatch(commit) and parents, 'invalid source history')
        # EVERY intervening commit, against EVERY parent, not only net endpoint
        # diff. Modify/delete/restore and merge-side rewrites cannot disappear.
        for parent in parents:
            delta = git(cache, 'diff-tree', '--no-commit-id', '--no-renames', '--name-status', '-r',
                        parent, commit, '--', 'mailbox/inbox', 'mailbox/events')
            require(len(delta) <= 512000, 'history diff limit exceeded')
            require(all(line.startswith(b'A\t') for line in delta.splitlines()),
                    'immutable path modified/deleted in intervening history')


def refresh(cache):
    prepare_cache(cache)
    last_successful = read_source_guard(cache)
    ref = 'refs/heads/' + SOURCE_REF
    expected = remote_head(cache, SOURCE_URL, ref)
    git(cache, 'fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head',
        SOURCE_URL, ref + ':' + SOURCE_TRACKING, authenticated=True, timeout=90)
    require(git(cache, 'rev-parse', SOURCE_TRACKING).decode().strip() == expected, 'source moved during fetch')
    verify_history(cache, expected, last_successful)
    snapshot = capture(cache, expected)
    require(git(cache, 'rev-parse', SOURCE_TRACKING).decode().strip() == expected, 'cache ref drift')
    require(remote_head(cache, SOURCE_URL, ref) == expected, 'source moved during validation')
    snapshot['remoteCheckedAt'] = stamp()
    return snapshot


def validate_public(snapshot):
    if snapshot.get('state') == 'unavailable':
        validator.keys(snapshot, 'schemaVersion state attemptedAt reason')
        require(snapshot['schemaVersion'] == 2 and snapshot['reason'] == FAILURE, 'unsafe failure metadata')
        validator.time(snapshot['attemptedAt'])
        return
    validator.keys(snapshot, 'schemaVersion state agents messages source observedAt validatedAt remoteCheckedAt counts')
    require(snapshot['schemaVersion'] == 2 and snapshot['state'] == 'ready', 'invalid public version')
    source = snapshot['source']
    validator.keys(source, 'repo ref path commit committedAt')
    require(source['repo'] == SOURCE_REPO and source['ref'] == SOURCE_REF and source['path'] == 'mailbox'
            and isinstance(source['commit'], str) and validator.COMMIT.fullmatch(source['commit']), 'unsafe public source')
    now = dt.datetime.now(dt.timezone.utc)
    observed, validated, checked = [validator.time(snapshot[k]) for k in ('observedAt', 'validatedAt', 'remoteCheckedAt')]
    require(observed <= validated <= checked <= now + dt.timedelta(seconds=30)
            and now - observed <= dt.timedelta(minutes=20), 'public metadata stale/inconsistent')
    require(validator.time(source['committedAt']) <= now + dt.timedelta(seconds=30), 'future source commit')
    roster = validator.load(SAFE_ROSTER)
    require(isinstance(snapshot['agents'], list) and len(snapshot['agents']) == len(roster), 'public roster mismatch')
    ids = set()
    for agent in snapshot['agents']:
        validator.keys(agent, 'id name kind status lastTurnAt')
        require(agent['id'] not in ids and agent['id'] in roster, 'public agent mismatch')
        ids.add(agent['id'])
        require({key: agent[key] for key in ('name', 'kind')} == roster[agent['id']]
                and agent['status'] == 'unknown' and agent['lastTurnAt'] is None, 'unsafe public agent fields')
    require(isinstance(snapshot['messages'], list) and len(snapshot['messages']) <= 200, 'public message limit')
    mids = set()
    for message in snapshot['messages']:
        validator.keys(message, 'id from to timestamp type status payloadSummary')
        require(isinstance(message['id'], str) and validator.UUID.fullmatch(message['id'])
                and message['id'] not in mids, 'public message ID')
        mids.add(message['id'])
        require(message['from'] in ids and message['to'] in ids and message['from'] != message['to'], 'public route')
        require(message['type'] in {'request', 'response'} and message['status'] in
                {'queued', 'received', 'validated', 'accepted', 'completed', 'failed', 'rejected', 'completion-revoked'}, 'public state')
        require(validator.time(message['timestamp']) <= now + dt.timedelta(seconds=30), 'future public message')
        # The only variable summary text is the enum type/status and expiry bit.
        samples = [generic_summary({'type': message['type'], 'expires_at': end}, message['status'], now)
                   for end in ('2000-01-01T00:00:00Z', '2100-01-01T00:00:00Z')]
        require(message['payloadSummary'] in samples, 'private/non-generated summary refused')
    validator.keys(snapshot['counts'], 'agents messages events')
    require(snapshot['counts']['agents'] == len(ids) and snapshot['counts']['messages'] == len(mids)
            and type(snapshot['counts']['events']) is int and 0 <= snapshot['counts']['events'] <= 1000, 'public count mismatch')


def encode(snapshot):
    validate_public(snapshot)
    raw = (json.dumps(snapshot, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('ascii')
    require(len(raw) <= 262144, 'public snapshot too large')
    # Defence in depth only; strict construction is the privacy boundary.
    require(not re.search(rb'(github_pat_|gh[pousr]_[A-Za-z0-9]|-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16})', raw),
            'potential secret pattern in public metadata')
    return raw


def write_snapshot(snapshot):
    validator.no_symlinks(OUTPUT)
    raw = encode(snapshot)
    with tempfile.NamedTemporaryFile(dir=ROOT, prefix='.snapshot-', delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.chmod(temp, 0o644)
        os.replace(temp, OUTPUT)
    finally:
        temp.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def guard_publication():
    require(git(ROOT, 'branch', '--show-current').strip() == b'main', 'publisher requires main')
    clean(ROOT)
    verify_monitor_transport()
    expected = remote_head(ROOT, MONITOR_URL, 'refs/heads/main')
    require(head(ROOT) == expected, 'local main differs from remote: manual review required')
    return expected


def publish(expected, expected_digest):
    require(head(ROOT) == expected, 'monitor HEAD drift')
    changes = git(ROOT, 'status', '--porcelain', '--untracked-files=all').decode().splitlines()
    require(changes in ([], [' M mailbox-snapshot.json'], ['?? mailbox-snapshot.json']), 'unexpected monitor changes')
    if not changes:
        return head(ROOT)
    validator.no_symlinks(OUTPUT)
    require(hashlib.sha256(OUTPUT.read_bytes()).hexdigest() == expected_digest, 'snapshot file drift')
    # No destructive recovery. A rejected push leaves a local commit for review;
    # subsequent scheduled runs stop at guard_publication rather than overwrite it.
    require(remote_head(ROOT, MONITOR_URL, 'refs/heads/main') == expected, 'remote main moved: stop')
    git(ROOT, 'add', '--', 'mailbox-snapshot.json', normal=True)
    require(git(ROOT, 'diff', '--cached', '--name-only').strip() == b'mailbox-snapshot.json', 'unexpected staged file')
    require(hashlib.sha256(git(ROOT, 'show', ':mailbox-snapshot.json')).hexdigest() == expected_digest, 'snapshot index drift')
    # Reserved automation author avoids exposing any local personal email.
    # This label is not an authenticated bot/recipient identity. Hooks still apply.
    git(ROOT, '-c', 'user.name=Grok Bot', '-c', 'user.email=grok-bot@users.invalid',
        'commit', '-m', 'Refresh validated mailbox metadata snapshot', normal=True)
    commit = head(ROOT)
    require(git(ROOT, 'rev-parse', 'HEAD^').decode().strip() == expected
            and git(ROOT, 'diff-tree', '--no-commit-id', '--name-only', '-r', commit).strip() == b'mailbox-snapshot.json'
            and hashlib.sha256(git(ROOT, 'show', 'HEAD:mailbox-snapshot.json')).hexdigest() == expected_digest,
            'committed snapshot/parent/scope drift')
    verify_monitor_transport()
    git(ROOT, 'push', MONITOR_URL, 'HEAD:refs/heads/main', authenticated=True, normal=True, timeout=90)
    require(remote_head(ROOT, MONITOR_URL, 'refs/heads/main') == commit, 'remote publication not verified')
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['export', 'publish'])
    parser.add_argument('--cache', required=True, type=Path, help='Own absolute private bare cache; never Forge checkout')
    args = parser.parse_args()
    try:
        validator.no_symlinks(args.cache)
        require(args.cache.is_absolute() and '..' not in args.cache.parts
                and not args.cache.is_relative_to(ROOT), 'cache/guard must remain outside public repo')
        with exclusive_lock(ROOT / '.git' / 'mailbox-snapshot-publisher.lock'):
            expected = guard_publication() if args.operation == 'publish' else None
            # A separate cache lock also serializes users of the same private mirror.
            with exclusive_lock(args.cache.with_name(args.cache.name + '.lock')):
                try:
                    snapshot = refresh(args.cache)
                    encode(snapshot)  # Public contract/age validation belongs to the same fail-closed gate.
                except (ValueError, OSError, subprocess.SubprocessError, TypeError, KeyError, RecursionError):
                    snapshot = {'schemaVersion': 2, 'state': 'unavailable', 'attemptedAt': stamp(), 'reason': FAILURE}
                digest = write_snapshot(snapshot)
                if snapshot['state'] == 'ready':
                    record_source_success(args.cache, snapshot['source']['commit'])
            commit = publish(expected, digest) if args.operation == 'publish' else None
            print(json.dumps({'state': snapshot['state'], 'sha256': digest,
                              'sourceCommit': snapshot.get('source', {}).get('commit'),
                              'counts': snapshot.get('counts'), 'publishedCommit': commit}))
            return 0 if snapshot['state'] == 'ready' else 3
    except AuthSelectionError:
        print('STOP: both GH_TOKEN and GITHUB_TOKEN are defined; review normal host auth selection. No credentials read or changed.', file=sys.stderr)
        return 2
    except (ValueError, OSError, subprocess.SubprocessError, TypeError, KeyError, RecursionError):
        # Never print subprocess stderr, source text, credential values or payloads.
        print('STOP: snapshot publication/export blocked; manual review required.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
