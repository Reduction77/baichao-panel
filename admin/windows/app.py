"""Baichao Wiki local editor. Python 3.11+, standard library only."""
from __future__ import annotations
import argparse, base64, copy, ctypes, difflib, hashlib, json, os, re, secrets, sys, threading, time, webbrowser
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

VERSION = '1.2.0'
ROOT = Path(__file__).resolve().parent
FILES = {'videos': 'web/data/teams.json', 'recommendations': 'web/data/team-recommendations.json', 'matrix': 'web/data/matrix-rules.json'}
PROFILE = 'web/data/team-builder.json'
LIMIT = 2_000_000
EXCLUDED_UPS = ('打游戏的老二', '长风ei', '久晨ovo')

class UserError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message); self.status = status

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_bytes(encoded(value)); os.replace(temp, path)

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def text(value, name, maximum=2000, required=False):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value or (required and not value.strip()):
        raise UserError(f'{name}格式不正确或超过 {maximum} 字')
    return value

def video_url(value):
    value = text(value, '视频链接', 500, True)
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or u.hostname not in ('www.bilibili.com', 'bilibili.com', 'b23.tv') or u.username or u.password or u.port not in (None, 443):
            raise ValueError()
    except ValueError:
        raise UserError('视频链接须为 HTTPS 的 bilibili.com 或 b23.tv 链接')
    return value

def validate(data, profiles):
    """Validate all editable data before saving and publishing; never accept file paths."""
    if not isinstance(data, dict) or set(data) != set(FILES):
        raise UserError('备份必须包含 videos、recommendations、matrix 三项')
    data = copy.deepcopy(data)
    chars = {p['id']: p for p in profiles['characters']}
    families = {p['family'] for p in chars.values()}
    def ids(values, exactly=None):
        if not isinstance(values, list) or (exactly is not None and len(values) != exactly):
            raise UserError('配队须选择三名角色')
        if any(not isinstance(v, str) or v not in chars for v in values):
            raise UserError('角色不存在，请重新同步角色资料')
        if len({chars[v]['family'] for v in values}) != len(values):
            raise UserError('同队不能重复角色或漂泊者形态')
        return values
    videos = data['videos']
    if not isinstance(videos, list) or len(videos) > 500:
        raise UserError('最多保存 500 条配队视频记录')
    def source(v):
        if not isinstance(v, dict): raise UserError('视频来源格式错误')
        for k in ('title', 'up'): text(v.get(k), k, 300, True)
        if any(up.lower() in v['up'].lower() for up in EXCLUDED_UPS): raise UserError('此 UP 主在排除名单中')
        video_url(v.get('url'))
    for v in videos:
        if not isinstance(v, dict): raise UserError('配队视频格式错误')
        text(v.get('title'), '队伍标题', 200, True)
        raw = v.get('characters')
        if not isinstance(raw, list) or any(type(i) not in (int, str) for i in raw): raise UserError('角色格式错误')
        v['characters'] = [int(i) for i in ids([str(i) for i in raw], 3)]
        for k in ('requirements', 'version', 'rotation'): text(v.get(k, ''), k, 5000)
        if not isinstance(v.get('videos'), list) or not 1 <= len(v['videos']) <= 20: raise UserError('每条队伍需有 1～20 个视频')
        for item in v['videos']: source(item)
    rec = data['recommendations']
    if not isinstance(rec, dict) or rec.get('schema') != 1: raise UserError('推荐配置版本错误')
    text(rec.get('verification'), '推荐依据说明', 2000, True)
    sources = rec.get('sources')
    if not isinstance(sources, dict) or len(sources) > 1000: raise UserError('最多保存 1000 个来源')
    for key, v in sources.items():
        if key in ('__proto__','constructor','prototype') or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', key): raise UserError('来源 ID 格式错误')
        source(v)
        if v.get('gameVersion') is not None: text(v['gameVersion'], '来源版本', 50)
        for k in ('checkedAt', 'verification'):
            if k in v: text(v[k], k, 200)
    teams = rec.get('teams')
    if not isinstance(teams, list) or len(teams) > 1000: raise UserError('最多保存 1000 条推荐组合')
    seen, mains = set(), set()
    for t in teams:
        if not isinstance(t, dict): raise UserError('推荐组合格式错误')
        key = text(t.get('id'), '组合 ID', 150, True)
        if key in seen: raise UserError('推荐组合 ID 重复')
        seen.add(key); selected = ids(t.get('characters'), 3)
        main_ids = ids(t.get('mains'))
        if not main_ids or any(i not in selected for i in main_ids): raise UserError('主 C 必须是队伍中至少一名角色')
        mains.update(main_ids)
        for k in ('name', 'system', 'kind', 'requirements'): text(t.get(k), k, 2000, True)
        refs = t.get('sourceIds')
        if not isinstance(refs, list) or not refs or any(not isinstance(i, str) or i not in sources for i in refs): raise UserError('推荐组合引用的视频来源不存在')
        if len(refs) != len(set(refs)): raise UserError('同一组合不能重复引用来源')
    rec['coveredMains'] = sorted(mains)
    matrix = data['matrix']
    if not isinstance(matrix, dict) or matrix.get('schema') != 1 or set(matrix) != {'schema', 'permanent', 'current'}:
        raise UserError('矩阵配置须包含 schema、permanent、current')
    for k in ('permanent', 'current'):
        values = matrix[k]
        if not isinstance(values, list) or any(not isinstance(i, str) or i not in families for i in values) or len(set(values)) != len(values):
            raise UserError('矩阵次数角色无效或重复')
    if set(matrix['permanent']) & set(matrix['current']): raise UserError('固定名单与本期额外名单请勿重复填写')
    if len(encoded(data)) > LIMIT: raise UserError('资料超过 2 MB 限制')
    return data

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args): return None

class GitHub:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token
    def call(self, method, path, payload=None):
        request = Request('https://api.github.com/repos/' + self.repo + path,
            data=encoded(payload) if payload is not None else None, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'Baichao-Wiki-Local-Admin/1.0', 'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with build_opener(NoRedirect()).open(request, timeout=25) as response:
                return json.load(response)
        except HTTPError as e:
            messages = {401:'GitHub 令牌无效或已过期',403:'GitHub 权限不足、请求受限或令牌需要组织授权',404:'仓库或文件不存在，请检查仓库名及令牌授权',409:'仓库存在版本冲突，请重新同步',422:'GitHub 拒绝提交，分支可能已更新或受到保护'}
            raise UserError(messages.get(e.code, f'GitHub 请求失败（HTTP {e.code}）'), 409 if e.code in (409,422) else 400) from None
        except (URLError, TimeoutError, OSError): raise UserError('无法连接 GitHub，请检查网络后重试', 502) from None
    def head(self, branch): return self.call('GET', '/git/ref/heads/' + quote(branch, safe=''))['object']['sha']
    def file(self, path, sha):
        d = self.call('GET', '/contents/' + quote(path, safe='/') + '?ref=' + quote(sha, safe=''))
        if d.get('encoding') != 'base64': raise UserError('GitHub 文件编码不支持')
        return json.loads(base64.b64decode(d['content']))

# Token protection on Windows uses the current user's DPAPI key.
def protect(value, decrypt=False):
    if sys.platform != 'win32': raise UserError('此平台仅支持本次运行使用令牌；持久保存令牌需在 Windows 中使用')
    from ctypes import wintypes
    class Blob(ctypes.Structure): _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    raw = base64.b64decode(value) if decrypt else value.encode()
    buffer = ctypes.create_string_buffer(raw)
    src = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))); dst = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True); kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]; kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)): raise UserError('Windows 无法读取或保护令牌，请重新输入')
    try:
        result = ctypes.string_at(dst.data, dst.size)
        return result.decode() if decrypt else base64.b64encode(result).decode()
    finally: kernel.LocalFree(ctypes.cast(dst.data, ctypes.c_void_p))

class Workspace:
    def __init__(self, directory, github_factory=GitHub):
        self.dir = Path(directory); self.lock = threading.RLock(); self.factory = github_factory
        self.settings = {'repo':'Reduction77/baichao-wiki', 'branch':'main'}; self.token = ''; self.warning = ''
        self.profiles = read_json(ROOT/'seed/profiles.json')
        seed = {key:read_json(ROOT/'seed'/Path(path).name) for key,path in FILES.items()}
        self.data = validate(seed, self.profiles); self.base = None; self.revision = 0; self.preview = None
        self.last_commit = ''
        if (self.dir/'settings.json').exists():
            saved = read_json(self.dir/'settings.json'); self.settings.update({k:saved[k] for k in ('repo','branch') if k in saved})
            if saved.get('tokenDPAPI'):
                try: self.token = protect(saved['tokenDPAPI'], True)
                except UserError: self.warning = '已保存的令牌无法解密，请在设置中重新填写。'
        if (self.dir/'draft.json').exists():
            try:
                saved = read_json(self.dir/'draft.json'); profiles = saved['profiles']; data = validate(saved['data'], profiles); self.profiles = profiles; self.data = data
                base = saved.get('base')
                if base and base.get('repo') == self.settings['repo'] and base.get('branch') == self.settings['branch']: self.base = base
            except (ValueError, KeyError, TypeError, UserError): self.warning = '草稿读取失败，已载入附带资料；原草稿文件仍保留。'
    def github(self):
        if not self.token: raise UserError('请先在设置中填写 GitHub 令牌')
        return self.factory(self.settings['repo'], self.token)
    def view(self):
        return {'data':self.data,'profiles':self.profiles,'revision':self.revision,'settings':{**self.settings,'tokenConfigured':bool(self.token), 'canRememberToken':sys.platform=='win32'},
                'baseHead':self.base['sha'] if self.base else '', 'warning':self.warning, 'lastCommit':self.last_commit}
    def checkpoint(self):
        path = self.dir/'draft.json'
        if path.exists():
            folder=self.dir/'backups'; folder.mkdir(parents=True, exist_ok=True)
            backup=folder/(str(time.time_ns())+'.json'); backup.write_bytes(path.read_bytes())
            for f in sorted(folder.glob('*.json'))[:-10]: f.unlink()
        atomic(path, {'data':self.data,'profiles':self.profiles,'base':self.base})
    def save(self, payload):
        if payload.get('revision') != self.revision: raise UserError('草稿已在其他窗口更新，请刷新页面后重试',409)
        self.data=validate(payload.get('data'), self.profiles); self.revision+=1; self.preview=None; self.checkpoint()
        return self.view()
    def configure(self, payload):
        repo=text(payload.get('repo'), '仓库名', 150, True); branch=text(payload.get('branch'), '分支', 100, True)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo): raise UserError('仓库格式为 owner/repository')
        if not re.fullmatch(r'[A-Za-z0-9_/-]+',branch) or '..' in branch: raise UserError('分支名称格式不正确')
        token=text(payload.get('token',''), '令牌', 500).strip()
        if token and not re.fullmatch(r'[A-Za-z0-9_]+',token): raise UserError('令牌包含无效字符')
        target={'repo':repo,'branch':branch}; changed=target!=self.settings
        saved={**target}; old=read_json(self.dir/'settings.json') if (self.dir/'settings.json').exists() else {}
        if payload.get('clearToken'): self.token=''
        elif token:
            if payload.get('remember'): saved['tokenDPAPI']=protect(token)
            self.token=token
        elif old.get('tokenDPAPI') and not payload.get('clearToken'): saved['tokenDPAPI']=old['tokenDPAPI']
        self.settings=target
        if changed: self.base=None
        self.preview=None; self.revision+=1; atomic(self.dir/'settings.json',saved)
        return self.view()
    def pull(self, payload):
        if payload.get('replaceDraft') is not True: raise UserError('同步前请确认替换本地草稿')
        gh=self.github(); sha=gh.head(self.settings['branch']); profiles=gh.file(PROFILE,sha)
        data={key:gh.file(path,sha) for key,path in FILES.items()}; data=validate(data,profiles)
        self.checkpoint(); self.profiles=profiles; self.data=data; self.base={'sha':sha,'data':copy.deepcopy(data),**self.settings}
        self.revision+=1; self.preview=None; self.checkpoint(); return self.view()
    def make_preview(self):
        if not self.base: raise UserError('发布前需先从 GitHub 同步当前仓库；请先导出未同步草稿备份')
        gh=self.github()
        if gh.head(self.settings['branch']) != self.base['sha']: raise UserError('远端仓库已更新，请导出草稿备份后重新同步并合并修改',409)
        data=validate(self.data,self.profiles); files=[]; rendered=[]
        for key,path in FILES.items():
            before=encoded(self.base['data'][key]).decode(); after=encoded(data[key]).decode()
            if before!=after:
                files.append({'path':path,'mode':'100644','type':'blob','content':after})
                rendered.append({'path':path,'diff':'\n'.join(difflib.unified_diff(before.splitlines(),after.splitlines(),fromfile='线上版本',tofile='本地草稿',lineterm=''))})
        if not files: raise UserError('没有需要发布的修改')
        nonce=secrets.token_urlsafe(24)
        self.preview={'id':nonce,'revision':self.revision,'head':self.base['sha'],'files':files,'expires':time.time()+600}
        return {'previewId':nonce,'files':rendered,'head':self.base['sha'],'revision':self.revision}
    def publish(self,payload):
        preview=self.preview
        if not preview or not secrets.compare_digest(str(payload.get('previewId','')),preview['id']) or preview['revision']!=self.revision or time.time()>preview['expires']:
            raise UserError('预览已失效，请重新查看发布差异',409)
        gh=self.github(); head=preview['head']; branch=self.settings['branch']
        if gh.head(branch)!=head: self.preview=None; raise UserError('远端仓库已更新，本次发布已停止，请重新同步',409)
        base=gh.call('GET','/git/commits/'+head)
        tree=gh.call('POST','/git/trees',{'base_tree':base['tree']['sha'],'tree':preview['files']})
        commit=gh.call('POST','/git/commits',{'message':'Update wiki content from Windows admin','tree':tree['sha'],'parents':[head]})
        # Non-force update rejects a competing commit, preserving remote edits.
        gh.call('PATCH','/git/refs/heads/'+quote(branch,safe=''),{'sha':commit['sha'],'force':False})
        self.last_commit=commit['sha']; self.base={'sha':commit['sha'],'data':copy.deepcopy(self.data),**self.settings}; self.preview=None; self.checkpoint()
        return {'sha':commit['sha'],'url':'https://github.com/'+self.settings['repo']+'/commit/'+commit['sha']}
    def deployment(self):
        if not self.last_commit: return {'status':'none'}
        gh=self.github(); runs=gh.call('GET','/actions/runs?head_sha='+quote(self.last_commit,safe='')+'&per_page=10')
        found=next((r for r in runs.get('workflow_runs',[]) if r.get('head_sha')==self.last_commit and (r.get('path','').split('@')[0]=='.github/workflows/pages.yml')),None)
        return {'status':found.get('status') if found else 'waiting','conclusion':found.get('conclusion') if found else None,'url':found.get('html_url') if found else 'https://github.com/'+self.settings['repo']+'/actions'}

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,workspace):
        super().__init__(address,Handler); self.workspace=workspace
        self.session=secrets.token_urlsafe(32); self.csrf=secrets.token_urlsafe(32); self.launch_key=secrets.token_urlsafe(32)
        self.origin='http://127.0.0.1:'+str(self.server_port)

class Handler(BaseHTTPRequestHandler):
    server_version='BaichaoLocal/1.0'
    def setup(self): super().setup(); self.connection.settimeout(10)
    def log_message(self,*args): pass # Never log launch URLs, cookies, request bodies or tokens.
    def send(self,status,value,kind='application/json; charset=utf-8',headers=None):
        body=encoded(value) if kind.startswith('application/json') else value
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(body)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
                    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",**(headers or {})}.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def trusted(self):
        if self.headers.get('Host')!=self.server.origin.removeprefix('http://'): raise UserError('拒绝非本机访问',403)
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: raise UserError('会话无效，请从启动窗口重新打开',403)
        value=cookie.get('baichao_session')
        if not value or not secrets.compare_digest(value.value,self.server.session): raise UserError('请通过启动窗口提供的地址打开后台',403)
    def do_GET(self):
        try:
            if self.headers.get('Host')!=self.server.origin.removeprefix('http://'): raise UserError('拒绝非本机访问',403)
            url=urlsplit(self.path); key=parse_qs(url.query).get('key',[''])[0]
            if url.path=='/' and key and secrets.compare_digest(key,self.server.launch_key):
                return self.send(302,b'','text/plain',{'Location':'/','Set-Cookie':f'baichao_session={self.server.session}; HttpOnly; SameSite=Strict; Path=/'})
            self.trusted()
            if url.path=='/api/workspace':
                with self.server.workspace.lock: return self.send(200,self.server.workspace.view())
            if url.path=='/api/session': return self.send(200,{'csrf':self.server.csrf})
            if url.path=='/api/deployment':
                with self.server.workspace.lock: return self.send(200,self.server.workspace.deployment())
            static={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
            if url.path not in static: raise UserError('页面不存在',404)
            name=static[url.path]; kind='text/html' if name.endswith('.html') else 'text/javascript' if name.endswith('.js') else 'text/css'
            return self.send(200,(ROOT/'static'/name).read_bytes(),kind+'; charset=utf-8')
        except UserError as e: self.send(e.status,{'error':str(e)})
        except Exception: self.send(500,{'error':'读取失败，请关闭程序后重试；草稿保留在本机'})
    def do_POST(self):
        try:
            self.trusted()
            if self.headers.get('Origin')!=self.server.origin or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),self.server.csrf): raise UserError('请求来源无效，请重新打开后台',403)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise UserError('请求格式错误',415)
            try: size=int(self.headers.get('Content-Length','0'))
            except ValueError: raise UserError('请求大小无效')
            if not 0<size<=LIMIT: raise UserError('请求大小超过限制',413)
            try: payload=json.loads(self.rfile.read(size))
            except (ValueError,UnicodeError): raise UserError('JSON 格式错误')
            if not isinstance(payload,dict): raise UserError('请求格式错误')
            actions={'/api/save':'save','/api/settings':'configure','/api/pull':'pull','/api/publish':'publish'}
            with self.server.workspace.lock:
                if self.path=='/api/preview': result=self.server.workspace.make_preview()
                elif self.path in actions: result=getattr(self.server.workspace,actions[self.path])(payload)
                else: raise UserError('接口不存在',404)
            self.send(200,result)
        except UserError as e: self.send(e.status,{'error':str(e)})
        except Exception: self.send(500,{'error':'操作未完成，请检查本地目录是否可写，或稍后重新同步 GitHub'})

def instance_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    handle=(directory/'instance.lock').open('a+b')
    if handle.tell()==0: handle.write(b'0'); handle.flush()
    handle.seek(0)
    try:
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close(); raise UserError('管理后台已经运行，请使用原启动窗口中的地址；不要重复启动。') from None
    return handle

def main():
    for stream in (sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(); parser.add_argument('--version',action='version',version='Baichao Wiki Admin '+VERSION); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--no-browser',action='store_true'); parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args(); directory=args.data_dir or Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'BaichaoWikiAdmin'
    try: instance=instance_lock(directory)
    except UserError as e: raise SystemExit(str(e))
    server=None
    for port in range(args.port,args.port+20):
        try: server=Server(('127.0.0.1',port),Workspace(directory)); break
        except OSError: continue
    if server is None: raise SystemExit('端口被占用，请使用 --port 指定其他端口。')
    print('白潮 Wiki 管理后台已启动。关闭此窗口或按 Ctrl+C 退出。',flush=True)
    print('本地草稿目录：'+str(directory),flush=True)
    url=server.origin+'/?key='+server.launch_key
    print('若浏览器未打开，请复制此本机地址：\n'+url,flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); instance.close()

if __name__=='__main__':
    try:main()
    except SystemExit as error:
        if getattr(sys,'frozen',False) and error.code not in (None,0):
            print(str(error),flush=True)
            try:input('按回车关闭窗口…')
            except (EOFError,KeyboardInterrupt):pass
        raise
    except Exception:
        print('启动失败，请检查数据目录是否可写，或重新解压程序后重试。',file=sys.stderr,flush=True)
        if getattr(sys,'frozen',False):
            try:input('按回车关闭窗口…')
            except (EOFError,KeyboardInterrupt):pass
        raise SystemExit(1)

