"""Build a Windows x64 one-file admin executable and portable ZIP."""
import hashlib, json, os, pathlib, subprocess, sys, zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

def main():
    if sys.platform!='win32':raise SystemExit('请在 Windows x64 下构建 EXE。')
    source=ROOT/'admin/windows'; work=ROOT/'build/windows-admin'; dist=ROOT/'dist'
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--console','--noupx','--name','BaichaoWikiAdmin',
        '--distpath',str(dist),'--workpath',str(work/'temp'),'--specpath',str(work),
        '--add-data',str(source/'static')+os.pathsep+'static','--add-data',str(source/'seed')+os.pathsep+'seed',str(source/'app.py')],check=True,cwd=ROOT)
    exe=dist/'BaichaoWikiAdmin.exe'
    subprocess.run([sys.executable,str(source/'test_frozen.py'),str(exe)],check=True,cwd=ROOT)
    digest=hashlib.sha256(exe.read_bytes()).hexdigest()
    starter='''@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\nBaichaoWikiAdmin.exe\r\necho.\r\necho 管理后台已退出。\r\npause\r\n'''
    output=dist/f'baichao-panel-windows-v{VERSION}.zip'
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        archive.write(exe,'BaichaoWikiAdmin/BaichaoWikiAdmin.exe')
        archive.writestr('BaichaoWikiAdmin/启动管理后台.bat',starter.encode('utf-8'))
        archive.writestr('BaichaoWikiAdmin/使用说明.txt',(source/'便携版说明.md').read_text(encoding='utf-8').encode('utf-8-sig'))
        archive.writestr('BaichaoWikiAdmin/SHA256SUMS.txt',digest+'  BaichaoWikiAdmin.exe\n')
        archive.write(ROOT/'LICENSE','BaichaoWikiAdmin/LICENSE')
    print(json.dumps({'zip':str(output),'exe_sha256':digest,'size_bytes':output.stat().st_size}))

if __name__=='__main__':main()
