import io
import json
import unittest
import zipfile
from notices import classify,message,parse_result

RUN={'id':123,'run_attempt':1,'head_sha':'a'*40}


class Notices(unittest.TestCase):
    def archive(self,value):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('result.json',json.dumps(value))
        return b.getvalue()

    def test_build_failure_proves_only_that_this_run_did_not_dispatch(self):
        result=classify(RUN,[{'name':'cd / build','conclusion':'failure'},{'name':'cd / deploy','conclusion':'skipped'}])
        self.assertEqual(result,{'status':'NOT_DISPATCHED','reason':'BUILD_FAILED'})

    def test_missing_receipt_does_not_claim_unchanged_server(self):
        self.assertEqual(classify(RUN,[])['status'],'UNKNOWN')

    def test_untrusted_messages_and_mentions_never_leak(self):
        payload={'commit':'a'*40,'run_id':'123','attempt':'1','status':'ROLLED_BACK','reason':'SECRET_TOKEN','stderr':'private value'}
        outcome=parse_result(self.archive(payload),RUN)
        _,body=message('KW-coworker/JJIKMUK-Backend',RUN,outcome,['Alphrit','fisfin','bad\n@everyone'])
        self.assertIn('@Alphrit',body);self.assertEqual(body.count('@fisfin'),1)
        for secret in ('SECRET_TOKEN','private value','@everyone'):self.assertNotIn(secret,body)
        self.assertIn('복귀',body)

    def test_wrong_run_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'IDENTITY'):
            parse_result(self.archive({'commit':'a'*40,'run_id':'124','attempt':'1','status':'SUCCEEDED'}),RUN)

    def test_schema_failure_has_actionable_guidance(self):
        _,body=message('KW-coworker/PRE_REPO',RUN,
            {'status':'REJECTED','reason':'CHATBOT_SCHEMA_MISMATCH'},['Alphrit'])
        self.assertIn('DB 구조',body);self.assertIn('자동 SQL 실행 없이',body)
        self.assertIn('https://github.com/KW-coworker/PRE_REPO/actions/runs/123/',body)

    def test_old_chatbot_name_is_not_a_notification_target(self):
        with self.assertRaisesRegex(ValueError,'NOTICE_TARGET'):
            message('Alphrit/jjikmuk-CO-WORKER-',RUN,{},[])

    def test_archive_member_names_are_not_extracted(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('../result.json','{}')
        with self.assertRaisesRegex(ValueError,'MEMBERS'):parse_result(b.getvalue(),RUN)
