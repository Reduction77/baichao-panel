import copy, json, tempfile, unittest
from pathlib import Path
from server.app import create_app,ServerWorkspace
from server.passwords import hash_password,verify_password
from admin.windows.app import UserError

class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.password='correct-password-123';cls.password_hash=hash_password(cls.password)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.ws=ServerWorkspace(self.temp.name,'Reduction77/baichao-wiki','main','server_test_token')
        self.app=create_app({'TESTING':True,'DATA_DIR':self.temp.name,'PUBLIC_URL':'https://panel.example.test','ADMIN_USER':'admin','PASSWORD_HASH':self.password_hash},workspace=self.ws)
        self.addCleanup(self.close_logger)
        self.client=self.app.test_client();self.base='https://panel.example.test';self.csrf=''
    def close_logger(self):
        logger=self.app.extensions['audit_logger']
        for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)
    def get(self,path):return self.client.get(path,base_url=self.base)
    def post(self,path,data,csrf=None,origin=None):return self.client.post(path,json=data,base_url=self.base,headers={'Origin':origin or self.base,'X-CSRF-Token':self.csrf if csrf is None else csrf})
    def login(self,password=None):
        self.csrf=self.get('/api/login-session').json['csrf'];response=self.post('/api/login',{'username':'admin','password':password or self.password})
        if response.status_code==200:self.csrf=self.get('/api/session').json['csrf']
        return response
    def test_password_hash(self):
        self.assertTrue(verify_password(self.password,self.password_hash));self.assertFalse(verify_password('wrong',self.password_hash));self.assertFalse(verify_password('x','bad'))
    def test_authentication_and_cookie(self):
        self.assertEqual(self.get('/').status_code,302);self.assertEqual(self.get('/api/workspace').status_code,401)
        response=self.login();self.assertEqual(response.status_code,200)
        cookie=response.headers['Set-Cookie'];self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
        self.assertEqual(self.get('/').status_code,200);self.assertEqual(self.get('/api/workspace').status_code,200)
        view=self.get('/api/workspace').json;self.assertTrue(view['settings']['serverManaged']);self.assertNotIn('server_test_token',json.dumps(view))
    def test_csrf_origin_and_host(self):
        self.login()
        self.assertEqual(self.post('/api/save',{},csrf='invalid').status_code,403)
        self.assertEqual(self.post('/api/save',{},origin='https://attacker.example').status_code,403)
        self.assertEqual(self.client.get('/api/workspace',base_url='https://attacker.example').status_code,400)
    def test_login_csrf_rejected(self):self.assertEqual(self.post('/api/login',{'username':'admin','password':self.password},csrf='').status_code,403)
    def test_rate_limit(self):
        for i in range(10):self.assertEqual(self.login('bad-password').status_code,401)
        self.assertEqual(self.login().status_code,429)
    def test_logout(self):
        self.login();self.assertEqual(self.post('/api/logout',{}).status_code,200);self.assertEqual(self.get('/api/workspace').status_code,401)
    def test_expired_session(self):
        self.login()
        for v in self.app.extensions['panel_sessions'].values():v['expires']=0
        self.assertEqual(self.get('/api/workspace').status_code,401)
    def test_save_and_server_settings(self):
        self.login();view=self.get('/api/workspace').json
        view['data']['videos'][0]['rotation']='server draft'
        result=self.post('/api/save',{'data':view['data'],'revision':view['revision']});self.assertEqual(result.status_code,200);self.assertEqual(result.json['data']['videos'][0]['rotation'],'server draft')
        self.assertEqual(self.post('/api/settings',{'token':'do_not_persist'}).status_code,400)
        self.assertEqual(self.ws.token,'server_test_token')
        self.assertEqual(self.post('/api/publish',{'previewId':'bad'}).status_code,409)
    def test_headers_health_and_audit(self):
        result=self.get('/healthz');self.assertEqual(result.status_code,200);self.assertIn('frame-ancestors',result.headers['Content-Security-Policy'])
        self.login('a-wrong-secret');self.login()
        log=(Path(self.temp.name)/'audit.log').read_text(encoding='utf-8');self.assertIn('login_success',log);self.assertNotIn('server_test_token',log);self.assertNotIn('a-wrong-secret',log)
    def test_no_path_traversal(self):
        self.login();self.assertEqual(self.get('/../.env').status_code,404);self.assertEqual(self.get('/server/app.py').status_code,404)
    def test_secure_configuration_required(self):
        with self.assertRaises(RuntimeError):create_app({'DATA_DIR':self.temp.name,'PUBLIC_URL':'http://panel.example.test','PASSWORD_HASH':self.password_hash})
        with self.assertRaises(RuntimeError):create_app({'DATA_DIR':self.temp.name,'PUBLIC_URL':self.base,'PASSWORD_HASH':'CHANGE_ME'})

if __name__=='__main__':unittest.main(verbosity=2)
