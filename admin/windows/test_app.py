import base64, copy, http.client, json, sys, tempfile, threading, unittest
from pathlib import Path
import app

class FakeGitHub:
    def __init__(self):
        self.sha='a'*40; self.data={key:app.read_json(app.ROOT/'seed'/Path(path).name) for key,path in app.FILES.items()}
        self.profiles=app.read_json(app.ROOT/'seed/profiles.json'); self.calls=[]; self.race=False
    def head(self,branch): return self.sha
    def file(self,path,sha):
        assert sha==self.sha
        if path==app.PROFILE:return copy.deepcopy(self.profiles)
        return copy.deepcopy(self.data[next(k for k,p in app.FILES.items() if p==path)])
    def call(self,method,path,payload=None):
        self.calls.append((method,path,payload))
        if path.startswith('/git/commits/') and method=='GET':return {'tree':{'sha':'base-tree'}}
        if path=='/git/trees':self.tree=payload;return {'sha':'new-tree'}
        if path=='/git/commits':self.commit=payload;return {'sha':'b'*40}
        if path.startswith('/git/refs/'):
            assert payload['force'] is False
            if self.race:raise app.UserError('仓库存在版本冲突，请重新同步',409)
            assert self.commit['parents']==[self.sha]
            for entry in self.tree['tree']:
                key=next(k for k,p in app.FILES.items() if p==entry['path']);self.data[key]=json.loads(entry['content'])
            self.sha=payload['sha'];return {'object':{'sha':self.sha}}
        if path.startswith('/actions/runs'):return {'workflow_runs':[{'head_sha':self.sha,'path':'.github/workflows/pages.yml','status':'completed','conclusion':'success','html_url':'https://github.com/example/run'}]}
        raise AssertionError((method,path))

class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.remote=FakeGitHub()
        self.w=app.Workspace(self.temp.name,lambda repo,token:self.remote);self.w.token='test-token'
    def pull(self):self.w.pull({'replaceDraft':True})
    def save(self,data):return self.w.save({'data':data,'revision':self.w.revision})
    def edit(self):
        d=copy.deepcopy(self.w.data);d['videos'][0]['rotation']='更新后的循环说明';d['matrix']['current']=['1304'];return d
    def test_publish_atomic_and_status(self):
        self.pull();self.save(self.edit());p=self.w.make_preview();self.assertEqual(len(p['files']),2)
        self.assertIn('更新后的循环说明',p['files'][0]['diff'])
        out=self.w.publish({'previewId':p['previewId']});self.assertEqual(out['sha'],'b'*40)
        tree=self.remote.tree['tree'];self.assertEqual({e['path'] for e in tree},{app.FILES['videos'],app.FILES['matrix']})
        self.assertEqual(self.remote.commit['parents'],['a'*40]);self.assertEqual(self.w.deployment()['conclusion'],'success')
        self.assertEqual(self.w.base['sha'],out['sha']);self.assertIsNone(self.w.preview)
    def test_preview_requires_sync_and_changes(self):
        with self.assertRaises(app.UserError):self.w.make_preview()
        self.pull()
        with self.assertRaises(app.UserError):self.w.make_preview()
    def test_remote_conflict_before_and_during_publish(self):
        self.pull();self.save(self.edit());p=self.w.make_preview();self.remote.sha='c'*40
        with self.assertRaises(app.UserError):self.w.publish({'previewId':p['previewId']})
        self.assertFalse(any(m=='PATCH' for m,_,_ in self.remote.calls));self.assertEqual(self.w.base['sha'],'a'*40)
        self.remote.sha='a'*40;p=self.w.make_preview();self.remote.race=True
        with self.assertRaises(app.UserError):self.w.publish({'previewId':p['previewId']})
        self.assertEqual(self.w.base['sha'],'a'*40)
    def test_edit_invalidates_preview_and_revision(self):
        self.pull();self.save(self.edit());p=self.w.make_preview();self.save(self.w.data)
        with self.assertRaises(app.UserError):self.w.publish({'previewId':p['previewId']})
        with self.assertRaises(app.UserError):self.w.save({'data':self.w.data,'revision':-1})
    def test_schema_validation(self):
        variants=[]
        def case(fn):d=copy.deepcopy(self.w.data);fn(d);variants.append(d)
        case(lambda d:d['videos'][0].update(characters=[1304,1304,1503]))
        case(lambda d:d['videos'][0].update(characters=[1304,1501,1309]))
        case(lambda d:d['videos'][0]['videos'][0].update(url='https://www.bilibili.com.attacker.test/video/x'))
        case(lambda d:d['videos'][0]['videos'][0].update(url='javascript:alert(1)'))
        case(lambda d:d['videos'][0]['videos'][0].update(up='长风ei'))
        case(lambda d:d['recommendations']['teams'][0].update(sourceIds=['missing']))
        case(lambda d:d['recommendations']['teams'][0].update(mains=['1509']))
        case(lambda d:d['recommendations']['teams'].append(d['recommendations']['teams'][0]))
        case(lambda d:d['matrix'].update(current=[d['matrix']['permanent'][0]]))
        case(lambda d:d['matrix'].update(current=['99999']))
        case(lambda d:d.update(path='web/assets/app.js'))
        for d in variants:
            with self.subTest(d=d.keys()):
                with self.assertRaises(app.UserError):app.validate(d,self.w.profiles)
    def test_referenced_source_delete_rejected(self):
        d=copy.deepcopy(self.w.data);del d['recommendations']['sources'][d['recommendations']['teams'][0]['sourceIds'][0]]
        with self.assertRaises(app.UserError):self.save(d)
    def test_restore_and_backup_limit_no_secret(self):
        self.pull()
        for _ in range(13):self.save(self.edit())
        self.assertLessEqual(len(list((Path(self.temp.name)/'backups').glob('*.json'))),10)
        restored=app.Workspace(self.temp.name);self.assertEqual(restored.data,self.w.data);self.assertEqual(restored.base['sha'],self.w.base['sha'])
        all_text=''.join(p.read_text(encoding='utf-8') for p in Path(self.temp.name).rglob('*.json'))
        self.assertNotIn('test-token',all_text);self.assertNotIn('test-token',json.dumps(self.w.view()))
    def test_single_instance_lock(self):
        handle=app.instance_lock(Path(self.temp.name))
        try:
            with self.assertRaises(app.UserError):app.instance_lock(Path(self.temp.name))
        finally:handle.close()
        handle=app.instance_lock(Path(self.temp.name));handle.close()
    def test_settings_changed_invalidates_sync(self):
        self.pull();self.w.configure({'repo':'Example/wiki','branch':'main','token':'another_token','remember':False});self.assertIsNone(self.w.base)
        self.assertNotIn('another_token',(Path(self.temp.name)/'settings.json').read_text(encoding='utf-8'))
    @unittest.skipUnless(sys.platform=='win32','Windows DPAPI only')
    def test_windows_dpapi(self):
        encrypted=app.protect('private-test-token');self.assertNotIn('private-test-token',encrypted);self.assertEqual(app.protect(encrypted,True),'private-test-token')
        self.w.configure({'repo':'Reduction77/baichao-wiki','branch':'main','token':'private_test_token','remember':True})
        self.assertNotIn('private_test_token',(Path(self.temp.name)/'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(app.Workspace(self.temp.name).token,'private_test_token')

class HTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.w=app.Workspace(self.temp.name);self.s=app.Server(('127.0.0.1',0),self.w)
        self.thread=threading.Thread(target=self.s.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.s.shutdown();self.s.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path='/',method='GET',body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.s.server_port,timeout=3)
        c.request(method,path,body=body,headers=headers or {});r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
    def headers(self):return {'Cookie':'baichao_session='+self.s.session,'Origin':self.s.origin,'X-CSRF-Token':self.s.csrf,'Content-Type':'application/json'}
    def test_launch_cookie_and_static(self):
        status,h,_=self.request('/?key='+self.s.launch_key);self.assertEqual(status,302);self.assertEqual(h['Location'],'/');self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
        status,h,body=self.request('/',headers=self.headers());self.assertEqual(status,200);self.assertIn('白潮'.encode(),body);self.assertIn("frame-ancestors 'none'",h['Content-Security-Policy'])
        self.assertNotIn(self.s.launch_key.encode(),body)
        status,_,_=self.request('/api/workspace',headers=self.headers());self.assertEqual(status,200)
    def test_auth_origin_csrf_host_and_paths(self):
        self.assertEqual(self.request('/api/workspace')[0],403)
        self.assertEqual(self.request('/api/save','POST','{}',{'Content-Type':'application/json'})[0],403)
        for key,value in [('Origin','https://evil.example'),('X-CSRF-Token','invalid'),('Host','evil.example')]:
            h=self.headers();h[key]=value;self.assertEqual(self.request('/api/save','POST','{}',h)[0],403)
        self.assertEqual(self.request('/../app.py',headers=self.headers())[0],404)
        self.assertEqual(self.request('/api/arbitrary-file','POST','{}',self.headers())[0],404)
    def test_save_and_bad_body(self):
        body=json.dumps({'data':self.w.data,'revision':0});self.assertEqual(self.request('/api/save','POST',body,self.headers())[0],200)
        self.assertEqual(self.request('/api/save','POST','{',self.headers())[0],400)
        self.assertEqual(self.request('/api/save','POST','[]',self.headers())[0],400)
        h=self.headers();h['Content-Type']='text/plain';self.assertEqual(self.request('/api/save','POST','{}',h)[0],415)

if __name__=='__main__':unittest.main(verbosity=2)
