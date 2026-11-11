"""One GitHub check is a progress display, never a deployment authorization."""
import json,os,re,time,urllib.request
from pathlib import Path
from connection import REPO,canonical
from control import NoRedirect
from catalog_progress import safe_error

LABELS={'PREPARING':'준비','SERVICE_CHECK':'기존 서비스 확인','SERVICE_FREEZE':'서비스 일시 중지',
 'METADATA':'DB 구조 확인','VERIFY_ORIGINAL':'복구 상품 전수 대조','PRESERVATION':'기존 자료 보존 확인',
 'BASELINE':'변경 전 상품 기록','RELEASE_PREPARE':'배포 파일 준비','FROZEN':'동결·변경 전 기록 완료',
 'SNAPSHOT_WAIT':'RDS 백업 대기','SNAPSHOT_READY':'RDS 백업 사용 가능','PRODUCT_APPLY':'상품 반영',
 'PRODUCT_VERIFY':'상품 전수 검증','SERVICE_VERIFY':'서비스 정상 확인','RECOVERY':'상품 복구',
 'RECOVERY_VERIFY':'복구 결과 전수 검증','DONE':'단계 완료','FAILED':'단계 실패'}


class Reporter:
    name='상품 DB 작업 진행'
    def __init__(self,ctx,phase,*,clock=time.time,opener=None,folder=Path('operation-results')):
        self.ctx,self.phase,self.clock=ctx,phase,clock;self.folder=Path(folder)
        self.opener=opener or urllib.request.build_opener(NoRedirect())
        self.external=ctx['request_id']+':'+ctx['run_id'];self.check=None;self.last=0;self.ready=False
        try:
            self.folder.mkdir(exist_ok=True)
            record=self.folder/'catalog-progress-check.json';intent=self.folder/'catalog-progress-check-intent.json'
            if record.exists():
                value=json.loads(record.read_bytes())
                assert value['external_id']==self.external and value['commit']==ctx['commit']
                self.check=value['id']
            elif intent.exists():
                rows=self.call('/commits/'+ctx['commit']+'/check-runs?per_page=100')['check_runs']
                found=[r for r in rows if r['name']==self.name and r['external_id']==self.external]
                if len(found)!=1:raise ValueError('PROGRESS_CHECK_OUTCOME_UNKNOWN')
                self.check=found[0]['id']
            else:
                with intent.open('x',encoding='utf-8') as f:json.dump({'external_id':self.external,'commit':ctx['commit']},f)
                result=self.call('/check-runs','POST',{'name':self.name,'head_sha':ctx['commit'],'external_id':self.external,
                    'status':'in_progress','details_url':'https://github.com/'+REPO+'/actions/runs/'+ctx['run_id'],
                    'output':{'title':'상품 작업 준비','summary':'실제 작업 성공 여부는 최종 검증 결과로 확인합니다.'}})
                self.check=result['id']
            observed=self.call('/check-runs/'+str(self.check))
            assert observed['external_id']==self.external and observed['head_sha']==ctx['commit'] and observed['name']==self.name
            assert observed['app']['slug']=='github-actions'
            if not record.exists():
                with record.open('x',encoding='utf-8') as f:json.dump({'id':self.check,'external_id':self.external,'commit':ctx['commit']},f)
            self.ready=True
        except Exception as error:
            self.check=None;self.ready=False;self.unavailable(error)

    def call(self,path,method='GET',value=None):
        request=urllib.request.Request('https://api.github.com/repos/'+REPO+path,method=method,
            data=None if value is None else canonical(value),headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
            'Accept':'application/vnd.github+json','Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'JJIKMUK-Progress'})
        with self.opener.open(request,timeout=10) as response:
            raw=response.read(1048577)
            if len(raw)>1048576:raise ValueError('PROGRESS_RESPONSE_SIZE')
            return json.loads(raw)

    def unavailable(self,error):
        print(json.dumps({'progress_channel':'UNAVAILABLE','code':safe_error(error)}),flush=True)

    def emit(self,stage,*,done=0,total=None,written=None,advanced=None,error_code='',force=False,terminal=None):
        try:
            now=int(self.clock())
            if not force and now-self.last<60:return
            self.last=now
            assert stage in LABELS and type(done) is int and 0<=done<=10_000_000
            assert total is None or type(total) is int and done<=total<=10_000_000
            assert terminal in (None,'success','failure','neutral')
            assert isinstance(error_code,str) and re.fullmatch('[A-Z0-9_]{0,100}',error_code)
            assert written is None and advanced is None or type(written) is int and type(advanced) is int and 0<=advanced<=written
            value={'run_id':self.ctx['run_id'],'phase':self.phase,'stage':stage,'done':done,'total':total,
                   'observed_epoch':now,'written_epoch':written,'advanced_epoch':advanced,'error_code':error_code}
            journal=self.folder/'catalog-progress.jsonl'
            if not journal.exists() or journal.stat().st_size<1024**2:
                with journal.open('a',encoding='utf-8') as f:f.write(json.dumps(value)+'\n')
            print('CATALOG_PROGRESS '+json.dumps(value),flush=True)
            if not self.ready or self.check is None:return
            quantity=f'{done:,}건' if total is None else f'{done:,} / {total:,} ({100*done/total:.1f}%)' if total else '0 / 0'
            summary=f'실행 {self.ctx["run_id"]} · {self.phase}\n\n현재: {LABELS[stage]}\n\n처리: {quantity}'
            if written is not None:summary+=f'\n\n마지막 호스트 보고: {now-written}초 전 · 마지막 실제 진척: {now-advanced}초 전'
            if error_code:summary+='\n\n오류 코드: `'+error_code+'`'
            summary+='\n\n100% 표시는 해당 단계의 건수입니다. 전체 DB 적용·CD 재개 완료를 뜻하지 않습니다.'
            payload={'status':'completed' if terminal else 'in_progress','output':{'title':LABELS[stage],'summary':summary,'text':json.dumps(value)}}
            if terminal:payload['conclusion']=terminal
            self.call('/check-runs/'+str(self.check),'PATCH',payload);self.last=now
        except Exception as error:self.unavailable(error)
