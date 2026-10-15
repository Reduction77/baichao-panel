"""Create a deployable server source tarball without secrets or runtime data."""
import hashlib,io,json,os,pathlib,subprocess,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip();dist=ROOT/'dist';dist.mkdir(exist_ok=True)
paths=['Dockerfile','compose.yaml','compose.npm.yaml','.env.example','.dockerignore','requirements-server.txt','README.md','LICENSE','VERSION',
       'server','docs','admin/windows/app.py','admin/windows/static','admin/windows/seed']
files=[]
for value in paths:
    path=ROOT/value
    files.extend([path] if path.is_file() else [p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'])
commit=os.getenv('GITHUB_SHA','')
if not commit:
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except (OSError,subprocess.CalledProcessError):commit='local'
name=f'baichao-panel-server-v{version}.tar.gz';output=dist/name
with tarfile.open(output,'w:gz') as archive:
    checks=[]
    for path in sorted(set(files)):
        rel=path.relative_to(ROOT).as_posix();archive.add(path,arcname='baichao-panel-server/'+rel)
        checks.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+rel)
    for name,payload in [('SHA256SUMS.txt',('\n'.join(checks)+'\n').encode()),('BUILDINFO.json',json.dumps({'version':version,'commit':commit},indent=2).encode())]:
        info=tarfile.TarInfo('baichao-panel-server/'+name);info.size=len(payload);info.mode=0o644;archive.addfile(info,io.BytesIO(payload))
print(output)
