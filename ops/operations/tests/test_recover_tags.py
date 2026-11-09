"""Known failed preview, tag preservation, and strictly bounded recovery continuation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import recover_regex as recovery
import test_recover_regex as baseline


class StackTagRecoveryTests(unittest.TestCase):
    def fixture(self):
        api, old, original, new = baseline.RegexRecoveryTests().fixture(existing_provider=False)
        data = json.loads(Path(__file__).with_name('fixtures').joinpath('tag-preview-user-summary.json').read_bytes())
        physical = data['unchanged_physical_resources_with_tag_only_changes']
        preserved = {k: v[1] for k, v in physical.items()}
        cf = api['cloudformation']
        base_rows = cf.list_stack_resources.side_effect
        def rows(**kwargs):
            result = base_rows(**kwargs)
            for row in result['StackResourceSummaries']:
                if row['LogicalResourceId'] in preserved:
                    row['PhysicalResourceId'] = preserved[row['LogicalResourceId']]
            return result
        cf.list_stack_resources.side_effect = rows
        # The follow-up read supplied the real change-set ID and preserved stack tag.
        change_id = data['metadata']['ChangeSetId']
        changes = []
        for key, (kind, value) in physical.items():
            change = dict(copy.deepcopy(data['common_tag_change']), LogicalResourceId=key,
                          ResourceType=kind, PhysicalResourceId=value)
            changes.append({'Type': 'Resource', 'ResourceChange': change})
        changes.extend({'Type': 'Resource', 'ResourceChange': x} for x in data['document_changes'])
        previous_preview = dict(data['metadata'], Changes=changes)
        current_preview = cf.describe_change_set.return_value
        cf.describe_change_set.side_effect = lambda **kw: previous_preview if kw['ChangeSetName'] == change_id else current_preview
        base_template = cf.get_template.side_effect
        cf.get_template.side_effect = lambda **kw: {'TemplateBody': new} if kw.get('ChangeSetName') == change_id else base_template(**kw)
        previous = {'status': 'STOPPED_KEEP_RECORDS_NO_RETRY', 'last_stage': 'CHANGE_SET_CREATED',
            'stack_id': recovery.STACK, 'old_sha256': recovery.OLD_SHA, 'new_sha256': recovery.NEW_SHA,
            'main': recovery.PREVIOUS_MAIN, 'preserved': preserved, 'change_set_id': change_id}
        return api, old, previous, previous_preview, current_preview

    def test_observed_previous_preview_preserves_project_tag(self):
        api, old, previous, _, _ = self.fixture()
        new, preserved = recovery.preflight(api, old)
        result = recovery.verify_stopped_tag_preview(api['cloudformation'], previous, preserved, new)
        self.assertEqual([{'Key': 'Project', 'Value': 'JJIKMUK'}], result['tags'])

    def run_repair(self, api, old, previous, path):
        return recovery.repair(api, old, path, 'b' * 40, previous=previous,
            confirm=lambda _: recovery.REVIEWED_CONFIRMATION, sleep=lambda _: None)

    def test_completes_exact_reviewed_preview_without_creating_another(self):
        api, old, previous, old_preview, _ = self.fixture()
        before = copy.deepcopy([old, previous, old_preview])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'tags.json'
            self.run_repair(api, old, previous, path)
            state = json.loads(path.read_bytes())
            self.assertEqual('RECOVERED_VERIFIED', state['status'])
            self.assertEqual(15, len(state['previous_preview']['changes']))
            self.assertEqual(15, len(state['preview']['changes']))
            self.assertEqual(before, [old, previous, old_preview])
            cf = api['cloudformation']
            cf.create_change_set.assert_not_called()
            self.assertEqual(recovery.PREVIOUS_CHANGE_ID, cf.execute_change_set.call_args.kwargs['ChangeSetName'])
            self.assertTrue(cf.execute_change_set.call_args.kwargs['DisableRollback'])
            cf.delete_change_set.assert_not_called()
            cf.delete_stack.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'KEEP_RECOVERY_JOURNAL'):
                self.run_repair(api, old, previous, path)
            self.assertEqual(1, cf.execute_change_set.call_count)

    def test_fresh_preview_guard_remains_limited_to_two_documents(self):
        api, old, previous, prior, current = self.fixture()
        with self.assertRaisesRegex(ValueError, 'UNEXPECTED_CHANGE_COUNT'):
            recovery.verify_change_set(prior)

    def test_wrong_prior_state_scope_or_template_cannot_create_a_new_preview(self):
        for case in ('execute_intent', 'main', 'physical', 'id', 'different_valid_id', 'executed', 'tags',
                     'remove', 'properties', 'replacement', 'extra', 'template', 'failure_mode', 'drift_mode'):
            api, old, previous, prior, _ = self.fixture()
            if case == 'execute_intent': previous['last_stage'] = 'EXECUTE_INTENT'
            if case == 'main': previous['main'] = 'c' * 40
            if case == 'physical': previous['preserved']['ReadRole'] = 'different'
            if case == 'id': previous['change_set_id'] = 'unrelated'
            if case == 'different_valid_id': previous['change_set_id'] = previous['change_set_id'][:-1] + '9'
            if case == 'executed': prior['ExecutionStatus'] = 'EXECUTE_COMPLETE'
            if case == 'tags': prior['Tags'] = []
            if case == 'failure_mode': prior['OnStackFailure'] = 'ROLLBACK'
            if case == 'drift_mode': prior['DeploymentMode'] = 'REVERT_DRIFT'
            change = prior['Changes'][0]['ResourceChange']
            if case == 'remove': change['Action'] = 'Remove'
            if case == 'properties': change['Scope'] = ['Properties']
            if case == 'replacement': change['Replacement'] = 'True'
            if case == 'extra': prior['Changes'].append(copy.deepcopy(prior['Changes'][0]))
            if case == 'template':
                base = api['cloudformation'].get_template.side_effect
                api['cloudformation'].get_template.side_effect = lambda **kw: {'TemplateBody': {}} if 'ChangeSetName' in kw else base(**kw)
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                with self.assertRaises(ValueError):
                    self.run_repair(api, old, previous, Path(td) / 'tags.json')
                api['cloudformation'].create_change_set.assert_not_called()
                api['cloudformation'].execute_change_set.assert_not_called()

    def test_fresh_preview_extra_change_or_changed_tag_still_blocks_execution(self):
        for case in ('extra', 'tags'):
            api, old, previous, prior, current = self.fixture()
            if case == 'extra': current['Changes'].append(prior['Changes'][0])
            if case == 'tags': current['Tags'] = []
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'tags.json'
                with self.assertRaises(ValueError): baseline.RegexRecoveryTests().run_repair(api, old, path)
                self.assertEqual('CHANGE_SET_CREATED', json.loads(path.read_bytes())['last_stage'])
                api['cloudformation'].execute_change_set.assert_not_called()

    def test_old_two_document_confirmation_cannot_approve_fifteen_entry_preview(self):
        api, old, previous, _, _ = self.fixture()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'reviewed.json'
            with self.assertRaisesRegex(ValueError, 'NOT_CONFIRMED'):
                recovery.repair(api, old, path, 'b' * 40, previous=previous,
                    confirm=lambda _: 'REPAIR JJIKMUK SSM REGEX ONLY', sleep=lambda _: None)
            self.assertFalse(path.exists())
            api['cloudformation'].execute_change_set.assert_not_called()

    def test_uncertain_existing_preview_execution_is_never_replayed(self):
        api, old, previous, _, _ = self.fixture()
        api['cloudformation'].execute_change_set.side_effect = TimeoutError()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'reviewed.json'
            with self.assertRaises(TimeoutError): self.run_repair(api, old, previous, path)
            state = json.loads(path.read_bytes())
            self.assertEqual('EXECUTE_INTENT', state['last_stage'])
            self.assertEqual(recovery.PREVIOUS_CHANGE_ID, state['change_set_id'])
            with self.assertRaisesRegex(ValueError, 'KEEP_RECOVERY_JOURNAL'):
                self.run_repair(api, old, previous, path)
            self.assertEqual(1, api['cloudformation'].execute_change_set.call_count)

    def test_stack_tags_checked_before_creation_and_after_execution(self):
        for changed_at in (1, 2, 3):
            api, old, previous, _, _ = self.fixture()
            cf = api['cloudformation']; base = cf.describe_stacks.side_effect
            count = 0
            def stack(**kw):
                nonlocal count
                count += 1; response = base(**kw)
                if count >= changed_at: response['Stacks'][0]['Tags'] = []
                return response
            cf.describe_stacks.side_effect = stack
            with self.subTest(changed_at=changed_at), tempfile.TemporaryDirectory() as td:
                with self.assertRaisesRegex(ValueError, 'STACK_TAGS_CHANGED'):
                    self.run_repair(api, old, previous, Path(td) / 'tags.json')
                if changed_at <= 2: cf.execute_change_set.assert_not_called()
                api['s3'].put_object.assert_not_called()

    def test_continuation_requests_match_aws_sdk_shapes(self):
        import botocore.session
        from botocore import xform_name
        from botocore.validate import validate_parameters
        api, old, previous, _, _ = self.fixture()
        with tempfile.TemporaryDirectory() as td:
            self.run_repair(api, old, previous, Path(td) / 'tags.json')
        session = botocore.session.get_session()
        for service, client in api.items():
            model = session.get_service_model(service)
            methods = {xform_name(name): name for name in model.operation_names}
            for name, args, kwargs in client.method_calls:
                self.assertFalse(args)
                validate_parameters(kwargs, model.operation_model(methods[name]).input_shape)
