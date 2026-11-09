import unittest
from notify import observe


class API:
    repo='KW-coworker/JJIKMUK-Backend'
    def __init__(self,pr=True):
        self.run=dict(id=21,head_sha='a'*40,run_attempt=1,repository={'full_name':self.repo},
            head_repository={'full_name':self.repo},head_branch='main',event='push',name='Backend CD',
            path='.github/workflows/backend-cd.yml',status='completed',conclusion='failure',actor={'login':'merger'})
        self.pr=pr;self.posts=[];self.comments=[];self.artifacts=[]
    def request(self,path,method='GET',body=None):
        if method=='POST':self.posts.append((path,body));return {}
        if path=='/actions/runs/21':return self.run
        if path=='/pulls/7':return {'user':{'login':'author'},'merged_by':{'login':'merger'}}
        raise AssertionError(path)
    def pages(self,path,key=None):
        if path.endswith('/jobs'):return [{'name':'build','conclusion':'failure'},{'name':'deploy','conclusion':'skipped'}]
        if path.endswith('/artifacts'):return self.artifacts
        if '/commits/' in path:return [dict(number=7,merged_at='now',base={'ref':'main'},merge_commit_sha='a'*40)] if self.pr else []
        if path.endswith('/comments') or path.startswith('/issues?'):return self.comments
        raise AssertionError(path)
    def artifact(self,_):return b'not-a-zip'


class NoticeDeliveryTests(unittest.TestCase):
    def test_pr_authors_and_merger_notified_once(self):
        api=API();event={'workflow_run':dict(api.run)}
        observe(api,event)
        self.assertEqual(api.posts[0][0],'/issues/7/comments')
        body=api.posts[0][1]['body']
        for name in ['@fisfin','@author','@merger']:self.assertIn(name,body)
        api.comments=[{'body':body,'user':{'type':'Bot'}}]
        observe(api,event);self.assertEqual(len(api.posts),1)
    def test_direct_push_issue_and_dedupe(self):
        api=API(False);event={'workflow_run':dict(api.run)}
        observe(api,event);self.assertEqual(api.posts[0][0],'/issues')
        api.comments=[api.posts[0][1]]
        observe(api,event);self.assertEqual(len(api.posts),1)
    def test_success_and_foreign_runs_cannot_post(self):
        api=API();api.run['conclusion']='success'
        observe(api,{'workflow_run':dict(api.run)});self.assertEqual(api.posts,[])
        api.run['head_repository']={'full_name':'other/repo'}
        with self.assertRaises(ValueError):observe(api,{'workflow_run':dict(api.run)})
        self.assertEqual(api.posts,[])
    def test_bad_artifact_still_notifies_build_failure(self):
        api=API();api.artifacts=[{'id':1,'name':'deployment-result-21-1','expired':False}]
        result=observe(api,{'workflow_run':dict(api.run)})
        self.assertEqual(result['outcome'],'NOT_DISPATCHED')
    def test_delivery_failure_is_failure_without_retry(self):
        api=API();original=api.request
        def request(path,method='GET',body=None):
            if method=='POST':raise OSError('network')
            return original(path,method,body)
        api.request=request
        with self.assertRaises(OSError):observe(api,{'workflow_run':dict(api.run)})
        self.assertEqual(api.posts,[])
