"""Smoke test a running HTTP container as if behind an HTTPS reverse proxy."""
import http.client,json,sys
from http.cookies import SimpleCookie
port=int(sys.argv[1]);host='panel.example.test';origin='https://'+host;cookies={}
def call(path,body=None,csrf=''):
    headers={'Host':host}
    if cookies:headers['Cookie']='; '.join(k+'='+v for k,v in cookies.items())
    if body is not None:headers.update({'Origin':origin,'X-CSRF-Token':csrf,'Content-Type':'application/json'})
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=10);c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
    r=c.getresponse();raw=r.read()
    for key,value in r.getheaders():
        if key.lower()=='set-cookie':
            parsed=SimpleCookie();parsed.load(value)
            for k,v in parsed.items():cookies[k]=v.value
    status=r.status;c.close()
    return status,raw
assert call('/healthz')[0]==200
assert call('/api/workspace')[0]==401
csrf=json.loads(call('/api/login-session')[1])['csrf']
assert call('/api/login',{'username':'admin','password':'container-password-123'},csrf)[0]==200
csrf=json.loads(call('/api/session')[1])['csrf']
status,raw=call('/api/workspace');assert status==200
view=json.loads(raw);assert view['settings']['serverManaged']
view['data']['videos'][0]['rotation']='Docker persistent draft'
assert call('/api/save',{'data':view['data'],'revision':view['revision']},csrf)[0]==200
assert call('/api/save',{},'bad')[0]==403
assert call('/api/logout',{},csrf)[0]==200
assert call('/api/workspace')[0]==401
print('Container smoke passed: health, login, session, saved draft, CSRF and logout.')
