import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import recover_regex as recovery


class MissingDocument(Exception):
    response = {'Error': {'Code': 'InvalidDocument'}}


class RegexRecoveryTests(unittest.TestCase):
    def test_all_recovery_requests_match_the_locked_aws_sdk(self):
        import botocore.session
        from botocore import xform_name
        from botocore.validate import validate_parameters
        api, old, _, _ = self.fixture()
        with tempfile.TemporaryDirectory() as td:
            self.run_repair(api, old, Path(td) / 'repair.json')
        session = botocore.session.get_session()
        for service, client in api.items():
            model = session.get_service_model(service)
            methods = {xform_name(name): name for name in model.operation_names}
            for name, args, kwargs in client.method_calls:
                self.assertFalse(args)
                validate_parameters(kwargs, model.operation_model(methods[name]).input_shape)

    def test_main_must_contain_exact_corrected_helper(self):
        main = MagicMock()
        main.__enter__.return_value.read.return_value = json.dumps({'object': {'sha': 'a' * 40}}).encode()
        helper = MagicMock()
        helper.__enter__.return_value.read.return_value = b'old helper'
        with patch('recover_regex.urllib.request.urlopen', side_effect=[main, helper]):
            with self.assertRaisesRegex(ValueError, 'CORRECTED_HELPER_NOT_IN_MAIN'):
                recovery.verify_github('a' * 40)
        helper.__enter__.return_value.read.return_value = Path(__file__).resolve().parents[1].joinpath('connect_once.py').read_bytes()
        with patch('recover_regex.urllib.request.urlopen', side_effect=[main, helper]):
            recovery.verify_github('a' * 40)

    def fixture(self, existing_provider=True):
        original = json.loads(Path(__file__).with_name('fixtures').joinpath('failed-connection-template.json').read_bytes())
        new = recovery.corrected_template(original)
        state = {'updated': False}
        api = {s: MagicMock() for s in ('sts', 'ssm', 's3', 'cloudformation')}
        api['sts'].get_caller_identity.return_value = {'Account': recovery.ACCOUNT}
        cf = api['cloudformation']
        def stack(**kwargs):
            return {'Stacks': [{'StackId': recovery.STACK,
                'StackStatus': 'UPDATE_COMPLETE' if state['updated'] else 'CREATE_FAILED',
                'DisableRollback': True, 'Parameters': [{'ParameterKey': 'ExistingGitHubProvider',
                                                       'ParameterValue': str(existing_provider).lower()}]}]}
        cf.describe_stacks.side_effect = stack
        cf.get_template.side_effect = lambda **kwargs: {'TemplateBody': new if state['updated'] else original}
        def rows(**kwargs):
            return {'StackResourceSummaries': [
                {'LogicalResourceId': k, 'PhysicalResourceId': 'physical-' + k,
                 'ResourceType': v['Type'],
                 'ResourceStatus': ('UPDATE_COMPLETE' if state['updated'] else 'CREATE_FAILED')
                    if k in recovery.FIELDS else 'CREATE_COMPLETE'}
                for k, v in original['Resources'].items()
                if not (existing_provider and k == 'GitHubProvider')]}
        cf.list_stack_resources.side_effect = rows
        api['ssm'].describe_document.side_effect = MissingDocument()
        by_name = {v['Properties']['Name']: v['Properties']['Content']
                   for v in new['Resources'].values() if v['Type'] == 'AWS::SSM::Document'}
        api['ssm'].get_document.side_effect = lambda **kwargs: {'Content': json.dumps(by_name[kwargs['Name']])}
        cf.create_change_set.return_value = {'StackId': recovery.STACK, 'Id': 'exact-change-set'}
        changes = [{'Type': 'Resource', 'ResourceChange': {'LogicalResourceId': k,
                    'ResourceType': 'AWS::SSM::Document', 'Action': 'Modify',
                    'Replacement': 'True', 'Scope': ['Properties']}} for k in recovery.FIELDS]
        cf.describe_change_set.return_value = {'StackId': recovery.STACK, 'Status': 'CREATE_COMPLETE',
                                               'ExecutionStatus': 'AVAILABLE', 'Changes': changes}
        cf.execute_change_set.side_effect = lambda **kwargs: state.update(updated=True)
        old = {'status': 'STOPPED_KEEP_RECORDS_NO_RETRY', 'template_sha256': recovery.OLD_SHA,
               'stack_id': recovery.STACK}
        return api, old, original, new

    def run_repair(self, api, old, path):
        return recovery.repair(api, old, path, 'a' * 40,
                               confirm=lambda _: 'REPAIR JJIKMUK SSM REGEX ONLY', sleep=lambda _: None)

    def test_exact_four_field_patch_preserves_every_other_value(self):
        _, _, original, new = self.fixture()
        reverted = copy.deepcopy(new)
        for name, fields in recovery.FIELDS.items():
            for field in fields:
                path = reverted['Resources'][name]['Properties']['Content']['parameters'][field]
                path['allowedPattern'] = original['Resources'][name]['Properties']['Content']['parameters'][field]['allowedPattern']
        self.assertEqual(original, reverted)
        altered = copy.deepcopy(original)
        altered['Resources']['ReadRole']['Properties']['MaxSessionDuration'] = 7200
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_TEMPLATE_CHANGED'):
            recovery.corrected_template(altered)

    def test_preserves_successful_resources_and_updates_only_absent_documents(self):
        for existing in (True, False):
            api, old, _, _ = self.fixture(existing)
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'repair.json'
                report = self.run_repair(api, old, path)
                self.assertEqual('CONNECTION_CREATED', report['status'])
                cf = api['cloudformation']
                self.assertEqual('UPDATE', cf.create_change_set.call_args.kwargs['ChangeSetType'])
                self.assertTrue(cf.execute_change_set.call_args.kwargs['DisableRollback'])
                self.assertEqual(1, cf.execute_change_set.call_count)
                cf.create_stack.assert_not_called(); cf.delete_stack.assert_not_called()
                api['ssm'].send_command.assert_not_called()
                self.assertEqual('*', api['s3'].put_object.call_args.kwargs['IfNoneMatch'])
                self.assertEqual('RECOVERED_VERIFIED', json.loads(path.read_bytes())['status'])
                with self.assertRaisesRegex(ValueError, 'KEEP_RECOVERY_JOURNAL'):
                    self.run_repair(api, old, path)

    def test_preview_rejects_iam_delete_extra_resources_and_unknown_replacement(self):
        for mutation in ('iam', 'delete', 'extra', 'conditional'):
            api, old, _, _ = self.fixture()
            preview = api['cloudformation'].describe_change_set.return_value
            change = preview['Changes'][0]['ResourceChange']
            if mutation == 'iam': change['ResourceType'] = 'AWS::IAM::Role'
            if mutation == 'delete': change['Action'] = 'Remove'
            if mutation == 'extra': preview['Changes'].append(copy.deepcopy(preview['Changes'][0]))
            if mutation == 'conditional': change['Replacement'] = 'Conditional'
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                with self.assertRaises(ValueError): self.run_repair(api, old, Path(td) / 'repair.json')
                api['cloudformation'].execute_change_set.assert_not_called()

    def test_existing_document_wrong_account_or_original_journal_blocks_writes(self):
        for mutation in ('exists', 'account', 'journal'):
            api, old, _, _ = self.fixture()
            if mutation == 'exists': api['ssm'].describe_document.side_effect = None
            if mutation == 'account': api['sts'].get_caller_identity.return_value = {'Account': 'other'}
            if mutation == 'journal': old['stack_id'] = 'another-stack'
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                with self.assertRaises(ValueError): self.run_repair(api, old, Path(td) / 'repair.json')
                api['cloudformation'].create_change_set.assert_not_called()

    def test_uncertain_writes_preserve_stage_and_block_replay(self):
        for stage in ('preview', 'execute', 'receipt'):
            api, old, _, _ = self.fixture()
            call = {'preview': api['cloudformation'].create_change_set,
                    'execute': api['cloudformation'].execute_change_set,
                    'receipt': api['s3'].put_object}[stage]
            call.side_effect = TimeoutError()
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'repair.json'
                with self.assertRaises(TimeoutError): self.run_repair(api, old, path)
                state = json.loads(path.read_bytes())
                self.assertEqual('STOPPED_KEEP_RECORDS_NO_RETRY', state['status'])
                self.assertIn(state['last_stage'], ('CHANGE_SET_INTENT', 'EXECUTE_INTENT', 'RECEIPT_INTENT'))
                with self.assertRaisesRegex(ValueError, 'KEEP_RECOVERY_JOURNAL'):
                    self.run_repair(api, old, path)
                self.assertEqual(1, call.call_count)

    def test_late_document_collision_and_changed_physical_id_stop(self):
        api, old, _, _ = self.fixture()
        api['ssm'].describe_document.side_effect = [MissingDocument(), MissingDocument(), {}]
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, 'FAILED_DOCUMENT_ALREADY_EXISTS'):
                self.run_repair(api, old, Path(td) / 'repair.json')
            api['cloudformation'].execute_change_set.assert_not_called()
        api, old, _, _ = self.fixture()
        cf = api['cloudformation']; original = cf.list_stack_resources.side_effect
        count = 0
        def changed(**kwargs):
            nonlocal count
            count += 1; response = original(**kwargs)
            if count == 3:
                next(r for r in response['StackResourceSummaries'] if r['LogicalResourceId'] == 'ReadRole')['PhysicalResourceId'] = 'changed'
            return response
        cf.list_stack_resources.side_effect = changed
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, 'EXISTING_RESOURCE_CHANGED'):
                self.run_repair(api, old, Path(td) / 'repair.json')
            api['s3'].put_object.assert_not_called()

    def test_observe_after_uncertain_receipt_never_replays_or_writes_journal(self):
        api, old, _, _ = self.fixture()
        api['s3'].put_object.side_effect = TimeoutError()
        class MissingReceipt(Exception):
            response = {'Error': {'Code': 'NoSuchKey'}}
        api['s3'].get_object.side_effect = MissingReceipt()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'repair.json'
            with self.assertRaises(TimeoutError): self.run_repair(api, old, path)
            before = path.read_bytes()
            result = recovery.observe(api, path)
            self.assertTrue(result['connection_resources_verified'])
            self.assertEqual('MISSING_NO_UPLOAD_PERFORMED', result['receipt'])
            self.assertEqual(0, result['writes'])
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(1, api['s3'].put_object.call_count)
            self.assertEqual(1, api['cloudformation'].execute_change_set.call_count)

    def test_observe_binds_receipt_to_exact_recovery_context(self):
        api, old, _, _ = self.fixture()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'repair.json'
            report = self.run_repair(api, old, path)
            for key in (None, 'main', 'account', 'region', 'recovered_from_template_sha256'):
                receipt = dict(report)
                if key is not None: receipt[key] = 'wrong'
                raw = json.dumps(receipt).encode()
                api['s3'].get_object.return_value = {'ContentLength': len(raw), 'Body': io.BytesIO(raw)}
                if key is None:
                    self.assertEqual('VERIFIED', recovery.observe(api, path)['receipt'])
                else:
                    with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'RECEIPT_MISMATCH'):
                        recovery.observe(api, path)
