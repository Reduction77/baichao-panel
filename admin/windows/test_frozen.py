"""Native smoke test of the final EXE, not the source interpreter."""
import http.cookiejar, json, os, pathlib, queue, re, shutil, subprocess, sys, tempfile, threading, time
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError

def start(exe,state):
    process=subprocess.Popen([str(exe),'--no-browser','--port','0','--data-dir',str(state)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    lines=queue.Queue()
    def read():
        for line in process.stdout:lines.put(line)
    threading.Thread(target=read,daemon=True).start()
    deadline=time.monotonic()+60
    try:
        while time.monotonic()<deadline:
            if process.poll() is not None:raise AssertionError('EXE 在后台就绪前退出')
            try:line=lines.get(timeout=.2)
            except queue.Empty:continue
            if line.startswith('http://127.0.0.1:'):
                url=line.strip();opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
                with opener.open(url,timeout=5) as response:html=response.read().decode('utf-8')
                assert '白潮' in html and '/app.js' in html
                return process,url.split('/?')[0],opener
        raise AssertionError('EXE 启动超时')
    except BaseException:
        stop(process);raise

def stop(process):
    if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
    if process.stdout:process.stdout.close()

def fetch(opener,origin,path,data=None,csrf=''):
    headers={}
    if data is not None:headers={'Content-Type':'application/json','Origin':origin,'X-CSRF-Token':csrf}
    request=Request(origin+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
    with opener.open(request,timeout=10) as response:return response.read()

def main():
    exe=pathlib.Path(sys.argv[1]).resolve()
    assert exe.read_bytes()[:2]==b'MZ'
    with tempfile.TemporaryDirectory() as folder:
        root=pathlib.Path(folder);target=root/'白潮 后台测试';target.mkdir()
        portable=target/'BaichaoWikiAdmin.exe';shutil.copy2(exe,portable)
        state=root/'state'
        process,origin,opener=start(portable,state)
        try:
            for asset,marker in [('/style.css','--bg:'),('/app.js','saveEditor')]:assert marker in fetch(opener,origin,asset).decode()
            current=json.loads(fetch(opener,origin,'/api/workspace'));assert len(current['profiles']['characters'])>=60
            csrf=json.loads(fetch(opener,origin,'/api/session'))['csrf']
            current['data']['videos'][0]['rotation']='EXE 草稿保存测试'
            saved=json.loads(fetch(opener,origin,'/api/save',{'data':current['data'],'revision':current['revision']},csrf))
            assert saved['data']['videos'][0]['rotation']=='EXE 草稿保存测试'
            settings=json.loads(fetch(opener,origin,'/api/settings',{'repo':'Reduction77/baichao-wiki','branch':'main','token':'dummy_smoke_token','remember':True},csrf))
            assert settings['settings']['tokenConfigured'] is True
            assert 'dummy_smoke_token' not in (state/'settings.json').read_text(encoding='utf-8')
            try:fetch(opener,origin,'/api/save',{},'invalid')
            except HTTPError as error:assert error.code==403
            else:raise AssertionError('EXE 未拒绝错误 CSRF')
        finally:stop(process)
        process,origin,opener=start(portable,state)
        try:
            restored=json.loads(fetch(opener,origin,'/api/workspace'))
            assert restored['data']['videos'][0]['rotation']=='EXE 草稿保存测试'
            assert restored['settings']['tokenConfigured'] is True
        finally:stop(process)
    print('Frozen EXE smoke passed: embedded assets, Unicode path, local session, draft persistence, CSRF and DPAPI restore.')

if __name__=='__main__':main()
