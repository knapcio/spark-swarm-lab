"""Fake HTTP only: exact wire bytes, metadata, cancellation and concurrent overrides."""
from concurrent.futures import CancelledError,ThreadPoolExecutor
import hashlib,io,json,threading,urllib.error
import unittest
from unittest.mock import patch
import harness as h
from followup72_client import FollowupClient
import followup72 as f
from test_followup72 import Recorder,engine,PLAN


def response(content=None,finish='length',reasoning='own reasoning',tokens=7):
    return io.BytesIO(json.dumps(dict(model='nemotron-lightning',choices=[dict(finish_reason=finish,message=dict(content=content,reasoning_content=reasoning))],usage=dict(prompt_tokens=10,completion_tokens=tokens,total_tokens=tokens+10,completion_tokens_details={'reasoning_tokens':tokens},prompt_tokens_details={'cached_tokens':3}))).encode())

def client(max_calls=2):
    return FollowupClient(['http://offline.invalid/v1'],'nemotron-lightning',3,8192,210,h.Budget(max_calls,8192),Recorder(),7,True)


class ClientOverrideTests(unittest.TestCase):
    def test_default_wire_payload_byte_identical_to_original_and_parser_metadata(self):
        c=client();seen=[]
        def transport(request,timeout):seen.append(request.data);return response(json.dumps(PLAN),'stop','retained',7)
        with patch('urllib.request.urlopen',side_effect=transport):parsed,meta=c.call(0,'plan','golden prompt',return_meta=True)
        seed=int.from_bytes(hashlib.sha256(b'7:0:plan:golden prompt').digest()[:4],'big')
        old=dict(model='nemotron-lightning',messages=[{'role':'system','content':'Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.'},{'role':'user','content':'golden prompt'}],max_tokens=8192,temperature=.8,seed=seed,stream=False,chat_template_kwargs={'enable_thinking':True})
        self.assertEqual(seen,[json.dumps(old).encode()]);self.assertEqual(parsed,PLAN);self.assertEqual(meta['reasoning'],'retained');self.assertTrue(meta['response_received'])
        start,end=c.events.rows;self.assertEqual(start['request_body'],old);self.assertEqual(start['request_body_sha256'],hashlib.sha256(seen[0]).hexdigest());self.assertEqual(meta['request_id'],start['request_id']);self.assertEqual(end['request_id'],meta['request_id']);self.assertEqual(meta['usage']['completion_tokens'],7)
        self.assertEqual(meta['response_model'],'nemotron-lightning');self.assertEqual(end['raw_usage'],meta['raw_usage']);self.assertEqual(meta['raw_usage']['completion_tokens_details']['reasoning_tokens'],7);self.assertEqual(meta['raw_usage']['prompt_tokens_details']['cached_tokens'],3)
        c=client()
        with patch('urllib.request.urlopen',return_value=response('{}','length')):parsed,meta=c.call(0,'plan','p',return_meta=True)
        self.assertEqual(parsed,{});self.assertTrue(meta['response_received']);self.assertIsNone(meta['error'])

    def test_actual_length_parse_failure_then_scribe_settles_exact_global_budget(self):
        c=client();bodies=[]
        def transport(request,timeout):
            body=json.loads(request.data);bodies.append(body)
            return response(None,'length','own unfinished notes',7936)if len(bodies)==1 else response(json.dumps(PLAN),'stop',None,256)
        with patch('urllib.request.urlopen',side_effect=transport):result=f.run_followup(engine(c),(2,3,7),'p','scribe_full')
        self.assertTrue(result['solved']);self.assertEqual([x['max_tokens']for x in bodies],[7936,256]);self.assertEqual([x['chat_template_kwargs']['enable_thinking']for x in bodies],[True,False]);self.assertEqual((c.max_tokens,c.thinking),(8192,True));self.assertEqual(c.budget.snapshot()['completion_tokens_charged'],8192);self.assertEqual(c.budget.snapshot()['completion_tokens_reserved'],0)
        starts=[e for e in c.events.rows if e['type']=='request_start'];ends=[e for e in c.events.rows if e['type']=='request_end'];self.assertEqual(len(starts),2);self.assertEqual(len(ends),2);self.assertIsNotNone(ends[0]['error']);self.assertTrue(ends[0]['response_received']);self.assertEqual(c.infra_failures,0)
        self.assertEqual(starts[1]['parent_request_id'],starts[0]['request_id']);self.assertEqual(starts[1]['selected_notes_sha256'],f.sha('own unfinished notes'))

    def test_overrides_are_local_under_concurrent_dispatch_and_sha_matches_wire(self):
        c=client(3);barrier=threading.Barrier(3);seen=[];lock=threading.Lock();caps=[101,211,307];thinking=[False,True,False]
        def transport(request,timeout):
            with lock:seen.append((json.loads(request.data),hashlib.sha256(request.data).hexdigest()))
            barrier.wait(timeout=2);return response(json.dumps(PLAN),'stop',None,7)
        with patch('urllib.request.urlopen',side_effect=transport),ThreadPoolExecutor(3)as pool:
            results=list(pool.map(lambda i:c.call(i,'parallel','thread-'+str(i),thinking=thinking[i],max_tokens=caps[i],return_meta=True),range(3)))
        for body,wire_sha in seen:
            i=int(body['messages'][1]['content'].split('-')[1]);self.assertEqual(body['max_tokens'],caps[i]);self.assertEqual(body['chat_template_kwargs']['enable_thinking'],thinking[i]);start=next(e for e in c.events.rows if e['type']=='request_start'and e['request_body_sha256']==wire_sha);self.assertEqual(start['request_body'],body)
        self.assertEqual((c.max_tokens,c.thinking),(8192,True));self.assertEqual(c.budget.tokens,21);self.assertTrue(all(r[0]==PLAN for r in results));self.assertEqual(c.budget.reserved,0)

    def test_transport_error_preparation_error_and_cancellation_preserve_accounting(self):
        c=client()
        with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('offline')):parsed,meta=c.call(0,'plan','p',max_tokens=41,return_meta=True)
        self.assertIsNone(parsed);self.assertFalse(meta['response_received']);self.assertEqual(c.budget.tokens,41);self.assertEqual(c.infra_failures,1);self.assertEqual(c.events.rows[-1]['type'],'request_end')
        c=client()
        with patch('urllib.request.urlopen')as transport:parsed,meta=c.call(0,'plan',{'bad':object()},max_tokens=41,return_meta=True)
        transport.assert_not_called();self.assertFalse(meta['request_dispatched']);self.assertIsNone(c.events.rows[0]['request_body']);self.assertEqual(c.budget.reserved,0)
        for error in (CancelledError(),KeyboardInterrupt()):
            c=client()
            with self.subTest(error=type(error).__name__),patch('urllib.request.urlopen',side_effect=error),self.assertRaises(type(error)):c.call(0,'plan','p',max_tokens=41,return_meta=True)
            self.assertTrue(c.events.rows[-1]['cancelled']);self.assertEqual(c.budget.tokens,41);self.assertEqual(c.budget.reserved,0);self.assertEqual(c.infra_failures,0)
        c=client();c.response_parser=lambda *args:(_ for _ in ()).throw(CancelledError())
        with patch('urllib.request.urlopen',return_value=response('{}','stop','still retained',7)),self.assertRaises(CancelledError):c.call(0,'plan','p',return_meta=True)
        self.assertEqual(c.events.rows[-1]['reasoning'],'still retained');self.assertEqual(c.events.rows[-1]['usage']['completion_tokens'],7);self.assertEqual(c.budget.tokens,7)

    def test_server_overrun_denies_commit_without_inventing_dispatched_request(self):
        c=client();count=[]
        def transport(*args,**kwargs):count.append(1);return response(None,'length','notes',7937)
        with patch('urllib.request.urlopen',side_effect=transport):result=f.run_followup(engine(c),(2,3,7),'p','scribe_empty')
        self.assertEqual(len(count),1);self.assertFalse(result['commit_dispatched']);self.assertIsNone(result['commit_request_id']);self.assertEqual(result['commit_error'],'budget_exhausted');self.assertEqual(c.budget_failures,1);self.assertEqual(c.budget.calls,1)

if __name__=='__main__':unittest.main()
