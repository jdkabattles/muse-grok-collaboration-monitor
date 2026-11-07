"""All actor events below are isolated TEST fixtures, never real mailbox writes."""
import copy
import contextlib
import io
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).absolute().parent.parent / 'tools'))
import live_snapshot as live
import mailbox_validator as v

ROSTER = v.load(live.SAFE_ROSTER)
A = '03a46df8-5836-41a8-ab34-f229c31a8a46'
B = 'd10e442c-22cc-46e7-a879-479372fb9fbf'


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='live-unit-')
        self.repo = Path(self.temp.name)
        self.cache_temp = tempfile.TemporaryDirectory(prefix='live-cache-unit-')
        self.cache = Path(self.cache_temp.name) / 'private.git'
        self.root = self.repo / 'mailbox'
        (self.root / 'inbox').mkdir(parents=True)
        (self.root / 'events').mkdir()
        (self.root / 'events/.gitkeep').touch()
        self.write(self.root / 'agents.json', {'version': 1, 'agents': ROSTER, 'pending': []})
        live.git(self.repo, 'init', '-q', '-b', 'main')
        live.git(self.repo, 'config', 'user.name', 'Fixture Author')
        live.git(self.repo, 'config', 'user.email', 'fixture@users.invalid')
        live.git(self.repo, 'remote', 'add', 'origin', live.MONITOR_URL)
        self.now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.message = self.make_message()
        self.message_path = self.path(self.message)
        self.write(self.message_path, self.message)
        self.pin = self.commit()

    def tearDown(self):
        self.temp.cleanup()
        self.cache_temp.cleanup()

    @staticmethod
    def write(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2) + '\n')

    def at(self, seconds):
        return (self.now + dt.timedelta(seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%SZ')

    def make_message(self, parent=None, expires=86400):
        ident = str(uuid.uuid4())
        return v.seal({'version': 1, 'id': ident, 'from': B if parent else A, 'to': A if parent else B,
                      'timestamp': self.at(-20 if parent else -60), 'expires_at': self.at(expires),
                      'nonce': str(uuid.uuid4()), 'type': 'response' if parent else 'request',
                      'thread_id': parent['id'] if parent else ident, 'in_reply_to': parent['id'] if parent else None,
                      'payload': {'action': 'handoff-response' if parent else 'handoff-request',
                                  'subject': 'PRIVATE_SUBJECT_SENTINEL', 'text': 'PRIVATE_BODY_SENTINEL',
                                  'scope': 'local-review-only', 'origin': 't95u',
                                  'evidence': [{'label': 'local-observed', 'reference': 'private-artifact.txt', 'sha256': 'a' * 64}] if parent else []},
                      'status': 'queued'})

    def path(self, message):
        return self.root / 'inbox' / message['to'] / (message['id'] + '.json')

    def commit(self):
        live.git(self.repo, 'add', '.')
        live.git(self.repo, 'commit', '-qm', 'Isolated fixture', normal=True)
        return live.head(self.repo)

    def event(self, status, sequence, previous=None, source=None, response=None):
        value = {'version': 1, 'id': str(uuid.uuid4()), 'message_id': self.message['id'],
                 'message_sha256': self.message['sha256'], 'actor': B, 'timestamp': self.at(-60 + sequence * 10),
                 'status': status, 'sequence': sequence, 'previous_sha256': previous['sha256'] if previous else None,
                 'source_commit': source or self.pin, 'note': 'TEST FIXTURE ONLY'}
        if response:
            value.update(completion_response_id=response['id'], completion_response_sha256=response['sha256'])
        event = v.seal(value)
        self.write(self.root / v.event_path(event), event)
        self.pin = self.commit()
        return event

    def capture(self, **kwargs):
        return live.capture(self.repo, self.pin, now=self.now, **kwargs)

    def test_real_metadata_counts_and_unknown_agent_state(self):
        result = self.capture()
        self.assertEqual(result['counts'], {'agents': 3, 'messages': 1, 'events': 0})
        self.assertEqual({a['id'] for a in result['agents']}, set(ROSTER))
        self.assertTrue(all(a['status'] == 'unknown' and a['lastTurnAt'] is None for a in result['agents']))
        self.assertEqual(result['messages'][0]['status'], 'queued')

    def test_private_content_and_code_never_executed_or_exported(self):
        marker = self.repo / 'SHOULD_NOT_EXIST'
        (self.root / 'messenger.py').write_text('raise RuntimeError("fetched code must never run")\n')
        self.message['payload']['text'] = 'touch ' + str(marker) + '\nPRIVATE_BODY_SENTINEL github_pat_ TEST_NOT_A_CREDENTIAL'
        self.message = v.seal(self.message)
        self.write(self.message_path, self.message)
        self.pin = self.commit()
        raw = json.dumps(self.capture())
        for private in ('PRIVATE_', 'private-artifact', 'github_pat_', 'touch ', 'TEST_NOT_A_CREDENTIAL'):
            self.assertNotIn(private, raw)
        self.assertFalse(marker.exists())

    def test_digest_tamper_poison_fails_entire_batch(self):
        value = copy.deepcopy(self.message)
        value['payload']['text'] += 'tamper'
        self.write(self.message_path, value)
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_unknown_fields_action_and_origin_fail(self):
        for field, val in [('command', 'run'), ('action', 'execute'), ('origin', 'arbitrary')]:
            with self.subTest(field=field):
                value = copy.deepcopy(self.message)
                value['payload'][field] = val
                self.write(self.message_path, v.seal(value))
                self.pin = self.commit()
                with self.assertRaises(v.Invalid): self.capture()

    def test_wrong_recipient_path_fails(self):
        target = self.message_path.with_name(str(uuid.uuid4()) + '.json')
        self.message_path.rename(target)
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_duplicate_id_or_nonce_fails(self):
        value = self.make_message()
        value['nonce'] = self.message['nonce']
        self.write(self.path(value), v.seal(value))
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_malformed_json_duplicate_keys_fail(self):
        self.message_path.write_text('{"id":"x","id":"y"}')
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_unexpected_non_json_or_oversized_source_fails(self):
        (self.root / 'inbox/poison.txt').write_text('poison')
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()
        (self.root / 'inbox/poison.txt').unlink()
        self.message_path.write_bytes(b'x' * 65537)
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_symlink_and_non_regular_source_fails(self):
        (self.root / 'link').symlink_to('/etc/passwd')
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_dirty_or_untracked_source_fails(self):
        self.message_path.write_text('{}')
        with self.assertRaises(v.Invalid): self.capture()

    def test_untracked_source_fails(self):
        (self.repo / 'dirty').write_text('x')
        with self.assertRaises(v.Invalid): self.capture()

    def test_source_ref_drift_fails(self):
        def drift():
            live.git(self.repo, 'update-ref', 'refs/heads/drift-fixture', self.pin)
        with self.assertRaises(v.Invalid): self.capture(drift_check=drift)

    def test_future_source_message_fails(self):
        self.message['timestamp'] = self.at(600)
        self.write(self.message_path, v.seal(self.message))
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_unreviewed_roster_never_exported(self):
        roster = copy.deepcopy(ROSTER)
        roster[A]['name'] = 'PRIVATE_NAME_SENTINEL'
        self.write(self.root / 'agents.json', {'version': 1, 'agents': roster, 'pending': []})
        self.pin = self.commit()
        with self.assertRaises(v.Invalid): self.capture()

    def test_expired_queued_retained_as_record_not_actionable(self):
        self.message['expires_at'] = self.at(-1)
        self.message = v.seal(self.message)
        self.write(self.message_path, self.message)
        self.pin = self.commit()
        result = self.capture()
        self.assertEqual(result['messages'][0]['status'], 'queued')
        self.assertIn('Expired at validation; no new task authority.', result['messages'][0]['payloadSummary'])

    def test_expired_received_and_accepted_remain_visible(self):
        self.message['expires_at'] = self.at(-25)
        self.message = v.seal(self.message)
        self.write(self.message_path, self.message)
        self.pin = self.commit()
        first = self.event('received', 1)
        self.assertEqual(self.capture()['messages'][0]['status'], 'received')
        second = self.event('validated', 2, first)
        self.event('accepted', 3, second)
        self.assertEqual(self.capture()['messages'][0]['status'], 'accepted')

    def test_acceptance_after_expiry_is_poison(self):
        self.message['expires_at'] = self.at(-35)
        self.message = v.seal(self.message)
        self.write(self.message_path, self.message)
        self.pin = self.commit()
        first = self.event('received', 1)
        second = self.event('validated', 2, first)
        self.event('accepted', 3, second)
        with self.assertRaises(v.Invalid): self.capture()

    def test_fork_status_chain_is_poison(self):
        self.event('received', 1)
        self.event('received', 1)
        with self.assertRaises(v.Invalid): self.capture()

    def test_source_commit_must_really_contain_message(self):
        self.event('received', 1, source='a' * 40)
        with self.assertRaises(subprocess.CalledProcessError): self.capture()

    def test_completion_without_response_is_poison(self):
        first = self.event('received', 1)
        second = self.event('validated', 2, first)
        third = self.event('accepted', 3, second)
        self.event('completed', 4, third)
        with self.assertRaises(v.Invalid): self.capture()

    def test_completion_retains_evidence_pinned_record_not_independent_truth(self):
        first = self.event('received', 1)
        second = self.event('validated', 2, first)
        third = self.event('accepted', 3, second)
        response = self.make_message(self.message)
        self.write(self.path(response), response)
        source = self.commit()
        # Response precedes completion (-20 -> -10); all fixtures are local-only.
        final = {'version': 1, 'id': str(uuid.uuid4()), 'message_id': self.message['id'],
                 'message_sha256': self.message['sha256'], 'actor': B, 'timestamp': self.at(-10),
                 'status': 'completed', 'sequence': 4, 'previous_sha256': third['sha256'],
                 'source_commit': source, 'note': 'TEST FIXTURE ONLY',
                 'completion_response_id': response['id'], 'completion_response_sha256': response['sha256']}
        self.write(self.root / v.event_path(final), v.seal(final))
        self.pin = self.commit()
        result = self.capture()
        completed = next(m for m in result['messages'] if m['id'] == self.message['id'])
        self.assertEqual(completed['status'], 'completed')
        self.assertIn('not independently verified', completed['payloadSummary'])
        self.assertNotIn('private-artifact', json.dumps(result))

    def test_snapshot_allowlist_rejects_private_extra_fields(self):
        result = self.capture()
        result['remoteCheckedAt'] = live.stamp()
        result['messages'][0]['payload'] = {'text': 'PRIVATE'}
        with self.assertRaises(v.Invalid): live.encode(result)

    def test_snapshot_allowlist_rejects_private_summary(self):
        result = self.capture()
        result['remoteCheckedAt'] = live.stamp()
        result['messages'][0]['payloadSummary'] = 'PRIVATE'
        with self.assertRaises(v.Invalid): live.encode(result)

    def test_atomic_snapshot_and_symlink_refusal(self):
        result = self.capture()
        result['remoteCheckedAt'] = live.stamp()
        output = self.repo / 'snapshot.json'
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'OUTPUT', output):
            digest = live.write_snapshot(result)
            self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())
            output.unlink()
            output.symlink_to(self.message_path)
            with self.assertRaises(v.Invalid): live.write_snapshot(result)
        self.assertEqual(v.load(self.message_path), self.message)

    def test_failure_envelope_contains_no_source_or_private_error(self):
        value = {'schemaVersion': 2, 'state': 'unavailable', 'attemptedAt': live.stamp(), 'reason': live.FAILURE}
        self.assertEqual(set(json.loads(live.encode(value))), {'schemaVersion', 'state', 'attemptedAt', 'reason'})

    def test_fresh_remote_check_cannot_launder_stale_data(self):
        result = self.capture()
        result['remoteCheckedAt'] = live.stamp()
        result['observedAt'] = self.at(-1201)
        with self.assertRaises(v.Invalid): live.encode(result)

    def test_twenty_minute_public_contract_boundary(self):
        result = self.capture()
        for key in ('observedAt', 'validatedAt', 'remoteCheckedAt'):
            result[key] = self.at(-1199)
        live.encode(result)
        for key in ('observedAt', 'validatedAt', 'remoteCheckedAt'):
            result[key] = self.at(-1201)
        with self.assertRaises(v.Invalid): live.encode(result)

    def test_publisher_lock_is_exclusive(self):
        path = self.repo / 'lock'
        with live.exclusive_lock(path):
            with self.assertRaises(BlockingIOError):
                with live.exclusive_lock(path): pass

    def test_publish_guard_accepts_exact_clean_main(self):
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'remote_head', return_value=self.pin):
            self.assertEqual(live.guard_publication(), self.pin)

    def test_publish_guard_rejects_other_origin_before_network(self):
        live.git(self.repo, 'remote', 'set-url', 'origin', 'https://example.invalid/not-the-monitor.git')
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'remote_head') as remote:
            with self.assertRaises(v.Invalid): live.guard_publication()
            remote.assert_not_called()

    def test_publish_guard_rejects_dirty_without_network(self):
        (self.repo / 'dirty').touch()
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'remote_head') as remote:
            with self.assertRaises(v.Invalid): live.guard_publication()
            remote.assert_not_called()

    def test_publish_guard_rejects_changed_remote(self):
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'remote_head', return_value='b' * 40):
            with self.assertRaises(v.Invalid): live.guard_publication()

    def test_snapshot_race_stops_before_stage(self):
        output = self.repo / 'mailbox-snapshot.json'
        output.write_text('changed by another writer')
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'OUTPUT', output):
            with self.assertRaises(v.Invalid): live.publish(self.pin, 'a' * 64)
            self.assertFalse(live.git(self.repo, 'diff', '--cached', '--name-only'))

    def test_plain_push_once_and_rejection_preserves_commit(self):
        output = self.repo / 'mailbox-snapshot.json'
        result = self.capture()
        result['remoteCheckedAt'] = live.stamp()
        raw = live.encode(result)
        output.write_bytes(raw)
        calls = []
        original = live.git
        def intercepted(repo, *args, **kwargs):
            calls.append((args, kwargs))
            if args[0] == 'push':
                raise subprocess.CalledProcessError(1, ['git', 'push'])
            return original(repo, *args, **kwargs)
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'OUTPUT', output), \
             patch.object(live, 'remote_head', return_value=self.pin), patch.object(live, 'git', side_effect=intercepted):
            with self.assertRaises(subprocess.CalledProcessError): live.publish(self.pin, hashlib.sha256(raw).hexdigest())
            self.assertNotEqual(live.head(self.repo), self.pin)
            with self.assertRaises(v.Invalid): live.guard_publication()
        pushes = [a for a, k in calls if a[0] == 'push']
        self.assertEqual(pushes, [('push', live.MONITOR_URL, 'HEAD:refs/heads/main')])
        self.assertTrue(all('--force' not in a and '--no-verify' not in a for a, k in calls))

    def test_remote_or_cache_drift_stops_refresh(self):
        with patch.object(live, 'prepare_cache'), patch.object(live, 'remote_head', return_value='a' * 40), \
             patch.object(live, 'git', side_effect=[b'', b'b' * 40]), patch.object(live, 'capture') as capture:
            with self.assertRaises(v.Invalid): live.refresh(self.repo)
            capture.assert_not_called()

    def test_modified_then_restored_history_fails_despite_empty_endpoint_diff(self):
        base = self.pin
        original = self.message_path.read_bytes()
        self.message_path.write_bytes(original + b' ')
        self.commit()
        self.message_path.write_bytes(original)
        restored = self.commit()
        self.assertEqual(live.git(self.repo, 'diff', '--name-status', base, restored, '--', 'mailbox/inbox'), b'')
        with patch.object(live, 'SOURCE_BASELINE', base):
            with self.assertRaises(v.Invalid): live.verify_history(self.repo, restored, base)

    def test_deleted_then_restored_history_fails(self):
        base = self.pin
        original = self.message_path.read_bytes()
        self.message_path.unlink()
        self.commit()
        self.message_path.write_bytes(original)
        restored = self.commit()
        with patch.object(live, 'SOURCE_BASELINE', base):
            with self.assertRaises(v.Invalid): live.verify_history(self.repo, restored, base)

    def test_success_pin_guard_survives_cache_recreation_and_rejects_rollback(self):
        base = self.pin
        extra = self.make_message()
        self.write(self.path(extra), extra)
        first = self.commit()
        extra = self.make_message()
        self.write(self.path(extra), extra)
        latest = self.commit()
        live.record_source_success(self.cache, latest)
        self.assertEqual(live.read_source_guard(self.cache), latest)
        self.cache.mkdir()
        self.cache.rmdir()  # cache recreation must not remove its sibling guard
        self.assertEqual(live.read_source_guard(self.cache), latest)
        with patch.object(live, 'SOURCE_BASELINE', base):
            with self.assertRaises(subprocess.CalledProcessError):
                live.verify_history(self.repo, first, live.read_source_guard(self.cache))
            live.verify_history(self.repo, latest, latest)

    def test_all_addition_history_is_permitted(self):
        base = self.pin
        extra = self.make_message()
        self.write(self.path(extra), extra)
        latest = self.commit()
        with patch.object(live, 'SOURCE_BASELINE', base):
            live.verify_history(self.repo, latest, base)

    def test_source_guard_refuses_public_repo_location(self):
        with patch.object(live, 'ROOT', self.repo):
            with self.assertRaises(v.Invalid):
                live.record_source_success(self.repo / 'private.git', self.pin)

    def test_malicious_pushurl_is_rejected_before_network(self):
        live.git(self.repo, 'remote', 'set-url', '--push', 'origin', 'https://example.invalid/other.git')
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'remote_head') as remote:
            with self.assertRaises(v.Invalid): live.guard_publication()
            remote.assert_not_called()

    def test_multiple_pushurls_are_rejected(self):
        for url in (live.MONITOR_URL, 'https://example.invalid/other.git'):
            live.git(self.repo, 'config', '--add', 'remote.origin.pushurl', url)
        with patch.object(live, 'ROOT', self.repo):
            with self.assertRaises(v.Invalid): live.verify_monitor_transport()

    def test_push_and_fetch_url_rewrites_are_rejected(self):
        for kind in ('insteadOf', 'pushInsteadOf'):
            key = 'url.https://example.invalid/.' + kind
            live.git(self.repo, 'config', key, 'https://github.com/')
            with patch.object(live, 'ROOT', self.repo):
                with self.assertRaises(v.Invalid): live.verify_monitor_transport()
            live.git(self.repo, 'config', '--unset', key)

    def test_normal_host_auth_selection_preserved_no_helper_override(self):
        for token_name in ('GH_TOKEN', 'GITHUB_TOKEN'):
            with patch.dict(os.environ, {'PATH': os.defpath, token_name: 'SYNTHETIC_TEST_ONLY'}, clear=True), \
                 patch.object(live.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'')) as run:
                live.git(self.repo, 'ls-remote', live.SOURCE_URL, authenticated=True)
                command = run.call_args.args[0]
                env = run.call_args.kwargs['env']
                self.assertEqual(env[token_name], 'SYNTHETIC_TEST_ONLY')
                self.assertFalse(any('credential.helper' in arg for arg in command))
                self.assertNotIn('GIT_CONFIG_GLOBAL', env)

    def test_conflicting_auth_presence_stops_without_reading_or_calling_transport(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'TEST_ONLY_A', 'GITHUB_TOKEN': 'TEST_ONLY_B'}, clear=True), \
             patch.object(live.subprocess, 'run') as run:
            with self.assertRaises(live.AuthSelectionError):
                live.git(self.repo, 'ls-remote', live.SOURCE_URL, authenticated=True)
            run.assert_not_called()

    def test_export_large_public_snapshot_fails(self):
        result = self.capture()
        result['remoteCheckedAt'] = live.stamp()
        result['messages'] *= 201
        with self.assertRaises(v.Invalid): live.encode(result)

    def test_source_check_failure_writes_sanitized_failure_without_publish(self):
        output = self.repo / 'mailbox-snapshot.json'
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'OUTPUT', output), \
             patch.object(sys, 'argv', ['live_snapshot.py', 'export', '--cache', str(self.cache)]), \
             patch.object(live, 'refresh', side_effect=OSError('PRIVATE_ERROR_SENTINEL')), \
             patch.object(live, 'publish') as publish:
            self.assertEqual(live.main(), 3)
            self.assertEqual(json.loads(output.read_text())['state'], 'unavailable')
            self.assertNotIn('PRIVATE', output.read_text())
            publish.assert_not_called()
    def run_main(self, operation, *, snapshot=None, source_error=None, publication_error=None):
        output = self.repo / 'mailbox-snapshot.json'
        snapshot = snapshot or self.capture()
        snapshot['remoteCheckedAt'] = live.stamp()
        out, err = io.StringIO(), io.StringIO()
        with patch.object(live, 'ROOT', self.repo), patch.object(live, 'OUTPUT', output), \
             patch.object(sys, 'argv', ['live_snapshot.py', operation, '--cache', str(self.cache)]), \
             patch.object(live, 'guard_publication', return_value=self.pin), \
             patch.object(live, 'refresh', return_value=snapshot, side_effect=source_error), \
             patch.object(live, 'publish', return_value='c' * 40, side_effect=publication_error), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = live.main()
        return code, out.getvalue(), err.getvalue()

    def test_exit_zero_valid_source_and_verified_publish(self):
        code, out, err = self.run_main('publish')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['state'], 'ready')
        self.assertEqual(json.loads(out)['publishedCommit'], 'c' * 40)
        self.assertEqual(err, '')

    def test_exit_three_source_failure_but_sanitized_envelope_published(self):
        code, out, err = self.run_main('publish', source_error=OSError('PRIVATE_SOURCE_ERROR'))
        self.assertEqual(code, 3)
        report = json.loads(out)
        self.assertEqual(report['state'], 'unavailable')
        self.assertEqual(report['publishedCommit'], 'c' * 40)
        self.assertIsNone(report['sourceCommit'])
        self.assertIsNone(report['counts'])
        self.assertNotIn('PRIVATE_SOURCE_ERROR', out + err)

    def test_exit_two_publication_or_auth_failure_no_success_claim(self):
        code, out, err = self.run_main('publish', publication_error=PermissionError('PRIVATE_AUTH_ERROR'))
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertIn('STOP', err)
        self.assertNotIn('PRIVATE_AUTH_ERROR', err)

    def test_exit_two_conflicting_auth_presence_has_sanitized_diagnostic(self):
        code, out, err = self.run_main('publish', source_error=live.AuthSelectionError())
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertIn('both GH_TOKEN and GITHUB_TOKEN', err)



class PinnedSourceIntegration(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('MAILBOX_TEST_CACHE'), 'set MAILBOX_TEST_CACHE to own read-only bare cache; no network in tests')
    def test_current_real_snapshot_recomputed_counts_status_and_pins(self):
        cache = Path(os.environ['MAILBOX_TEST_CACHE'])
        initial = json.loads((live.ROOT / 'mailbox-snapshot.json').read_text())
        pin = initial['source']['commit']
        result = live.capture(cache, pin)
        self.assertEqual(result['counts'], initial['counts'])
        self.assertEqual(result['agents'], initial['agents'])
        self.assertEqual([(m['id'], m['status']) for m in result['messages']],
                         [(m['id'], m['status']) for m in initial['messages']])
        live.git(cache, 'merge-base', '--is-ancestor', live.SOURCE_BASELINE, pin)
        self.assertEqual(result['counts']['agents'], len(result['agents']))
        self.assertEqual(result['counts']['messages'], len(result['messages']))
        for field in ('PRIVATE_', '"payload"', '"evidence"', 'github_pat_', '"note"'):
            self.assertNotIn(field, json.dumps(result))


if __name__ == '__main__': unittest.main()
