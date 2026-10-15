"""Authenticated WSGI app. Run one Gunicorn process with multiple threads."""
import hashlib, hmac, json, logging, os, secrets, threading, time
from collections import deque
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, jsonify, request, session, redirect, send_file
from werkzeug.exceptions import HTTPException
from admin.windows.app import Workspace, UserError, ROOT as CONTENT_ROOT, LIMIT
from server.passwords import valid_hash, verify_password

class ServerWorkspace(Workspace):
    def __init__(self,directory,repo,branch,token,github_factory=None):
        kwargs={'github_factory':github_factory} if github_factory else {}
        super().__init__(directory,**kwargs)
        self.settings={'repo':repo,'branch':branch};self.token=token
        if self.base and (self.base.get('repo')!=repo or self.base.get('branch')!=branch):self.base=None
        self.warning=''
    def view(self):
        out=super().view();out['settings'].update(serverManaged=True,canRememberToken=False)
        return out
    def configure(self,payload):
        raise UserError('服务器连接配置由 .env 管理，修改后请重建容器。')

class Attempts:
    def __init__(self):self.buckets={};self.lock=threading.Lock()
    def limited(self,key):
        with self.lock:
            now=time.monotonic();bucket=self.buckets.setdefault(key,deque())
            while bucket and bucket[0]<now-300:bucket.popleft()
            return len(bucket)>=10
    def fail(self,key):
        with self.lock:
            if len(self.buckets)>1000:self.buckets.clear()
            self.buckets.setdefault(key,deque()).append(time.monotonic())
    def clear(self,key):
        with self.lock:self.buckets.pop(key,None)

def create_app(overrides=None,workspace=None):
    app=Flask(__name__,static_folder=None)
    settings={'TESTING':False,'DATA_DIR':os.getenv('PANEL_DATA_DIR','/data'),
      'PUBLIC_URL':os.getenv('PANEL_PUBLIC_URL',''),'ADMIN_USER':os.getenv('PANEL_ADMIN_USER','admin'),
      'PASSWORD_HASH':os.getenv('PANEL_PASSWORD_HASH',''),'REPO':os.getenv('PANEL_GITHUB_REPO','Reduction77/baichao-wiki'),
      'BRANCH':os.getenv('PANEL_GITHUB_BRANCH','main'),'TOKEN':os.getenv('PANEL_GITHUB_TOKEN','')}
    settings.update(overrides or {})
    url=urlsplit(settings['PUBLIC_URL'])
    if url.scheme not in ('https','http') or not url.netloc or url.path not in ('','/') or url.query or url.fragment or url.username or url.password:
        raise RuntimeError('PANEL_PUBLIC_URL 须为管理后台的完整 HTTPS 地址，不含路径')
    if url.scheme!='https' and not settings['TESTING']:raise RuntimeError('服务器公开地址必须使用 HTTPS')
    if not valid_hash(settings['PASSWORD_HASH']):raise RuntimeError('请先生成并配置 PANEL_PASSWORD_HASH')
    if not settings['ADMIN_USER'] or len(settings['ADMIN_USER'])>100:raise RuntimeError('管理员用户名不正确')
    import re
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',settings['REPO']):raise RuntimeError('PANEL_GITHUB_REPO 格式错误')
    if not re.fullmatch(r'[A-Za-z0-9_/-]+',settings['BRANCH']) or '..' in settings['BRANCH']:raise RuntimeError('PANEL_GITHUB_BRANCH 格式错误')
    origin=url.scheme+'://'+url.netloc;directory=Path(settings['DATA_DIR']);directory.mkdir(parents=True,exist_ok=True)
    os.umask(0o077)
    secret_path=directory/'session.key'
    if not secret_path.exists():
        try:
            with secret_path.open('x',encoding='ascii') as handle:handle.write(secrets.token_hex(32))
        except FileExistsError:pass
    secret=secret_path.read_text(encoding='ascii').strip()
    if len(secret)<64:raise RuntimeError('会话密钥文件无效')
    app.config.update(TESTING=settings['TESTING'],SECRET_KEY=secret,SESSION_COOKIE_NAME='baichao_panel_session',
       SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=url.scheme=='https',SESSION_COOKIE_SAMESITE='Strict',
       PERMANENT_SESSION_LIFETIME=timedelta(hours=8),MAX_CONTENT_LENGTH=LIMIT)
    ws=workspace or ServerWorkspace(directory,settings['REPO'],settings['BRANCH'],settings['TOKEN'])
    app.extensions['workspace']=ws;attempts=Attempts();sessions={};session_lock=threading.Lock()
    app.extensions['attempts']=attempts;app.extensions['panel_sessions']=sessions
    audit=logging.getLogger('baichao-panel.'+hashlib.sha256(str(directory).encode()).hexdigest()[:10])
    if not audit.handlers:
        handler=RotatingFileHandler(directory/'audit.log',maxBytes=1024*1024,backupCount=2,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'));audit.addHandler(handler);audit.setLevel(logging.INFO);audit.propagate=False
    app.extensions['audit_logger']=audit
    def identity():
        sid=session.get('sid')
        with session_lock:
            item=sessions.get(sid)
            if item and item['expires']>time.time():return item
            if sid:sessions.pop(sid,None)
        return None
    def json_payload():
        if request.mimetype!='application/json':raise UserError('请求格式错误',415)
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):raise UserError('JSON 格式错误')
        return payload
    @app.before_request
    def guard():
        if request.path=='/healthz':return None
        if request.host.lower()!=url.netloc.lower():raise UserError('请求主机不匹配',400)
        public=request.path in ('/login','/login.js','/api/login-session','/api/login','/style.css')
        who=identity()
        if not public and not who:
            if request.path.startswith('/api/'):return jsonify(error='登录已过期，请重新登录',loginURL='/login'),401
            return redirect('/login')
        if request.method=='POST':
            if request.headers.get('Origin')!=origin:raise UserError('请求来源无效',403)
            expected=(session.get('login_csrf') if request.path=='/api/login' else (who or {}).get('csrf')) or ''
            actual=request.headers.get('X-CSRF-Token','')
            if not expected or not hmac.compare_digest(expected,actual):raise UserError('请求校验失败，请刷新页面重试',403)
    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if url.scheme=='https':response.headers['Strict-Transport-Security']='max-age=31536000'
        return response
    @app.errorhandler(UserError)
    def user_error(error):return jsonify(error=str(error)),error.status
    @app.errorhandler(HTTPException)
    def http_error(error):return jsonify(error='请求无法处理，请检查内容大小和格式'),error.code
    @app.errorhandler(Exception)
    def unexpected(error):
        audit.error('internal_error type=%s',type(error).__name__)
        return jsonify(error='操作未完成，请稍后重试或查看服务器日志'),500
    @app.get('/healthz')
    def health():return jsonify(ok=True)
    @app.get('/login')
    def login_page():
        if identity():return redirect('/')
        return send_file(Path(__file__).parent/'static/login.html')
    @app.get('/login.js')
    def login_js():return send_file(Path(__file__).parent/'static/login.js')
    @app.get('/api/login-session')
    def login_session():
        if not session.get('login_csrf'):session['login_csrf']=secrets.token_urlsafe(32)
        return jsonify(csrf=session['login_csrf'])
    @app.post('/api/login')
    def login():
        payload=json_payload();key=request.remote_addr or 'unknown'
        if attempts.limited(key):raise UserError('登录尝试过多，请 5 分钟后重试',429)
        supplied=payload.get('username');password=payload.get('password')
        password_ok=verify_password(password,settings['PASSWORD_HASH'])
        if not isinstance(supplied,str) or not hmac.compare_digest(supplied.encode(),settings['ADMIN_USER'].encode()) or not password_ok:
            attempts.fail(key);audit.info('login_failed');raise UserError('用户名或密码不正确',401)
        attempts.clear(key);session.clear();session.permanent=True;sid=secrets.token_urlsafe(32)
        with session_lock:
            now=time.time()
            for old in [k for k,v in sessions.items() if v['expires']<now]:sessions.pop(old,None)
            if len(sessions)>=16:sessions.pop(next(iter(sessions)))
            sessions[sid]={'csrf':secrets.token_urlsafe(32),'expires':now+8*3600}
        session['sid']=sid;audit.info('login_success');return jsonify(ok=True)
    @app.post('/api/logout')
    def logout():
        with session_lock:sessions.pop(session.get('sid'),None)
        session.clear();return jsonify(ok=True)
    @app.get('/')
    def index():
        content=(CONTENT_ROOT/'static/index.html').read_text(encoding='utf-8').replace('本地管理后台','服务器管理后台').replace('仅在这台电脑运行','服务器管理模式').replace('草稿保存在本机','草稿保存在服务器').replace('LOCAL CONTENT WORKSPACE','SERVER CONTENT WORKSPACE')
        return app.response_class(content,mimetype='text/html')
    @app.get('/app.js')
    def app_js():return send_file(CONTENT_ROOT/'static/app.js')
    @app.get('/style.css')
    def css():return send_file(CONTENT_ROOT/'static/style.css')
    @app.get('/api/session')
    def api_session():return jsonify(csrf=identity()['csrf'])
    @app.get('/api/workspace')
    def view():
        with ws.lock:return jsonify(ws.view())
    @app.get('/api/deployment')
    def deployment():
        with ws.lock:return jsonify(ws.deployment())
    @app.post('/api/<action>')
    def action(action):
        payload=json_payload()
        with ws.lock:
            if action=='preview':result=ws.make_preview()
            elif action in ('save','settings','pull','publish'):
                result=getattr(ws,{'save':'save','settings':'configure','pull':'pull','publish':'publish'}[action])(payload)
            else:raise UserError('接口不存在',404)
        audit.info('action=%s commit=%s',action,result.get('sha','') if isinstance(result,dict) else '')
        return jsonify(result)
    return app
