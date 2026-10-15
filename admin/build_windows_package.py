"""Build the Windows Python launcher ZIP; no local settings or tokens included."""
import argparse, pathlib, zipfile
root=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('output',type=pathlib.Path);args=parser.parse_args()
source=root/'admin/windows';args.output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for path in sorted(source.rglob('*')):
        rel=path.relative_to(source)
        if path.is_file() and '__pycache__' not in rel.parts and path.suffix!='.pyc' and '.local' not in rel.parts:
            z.write(path,'BaichaoWikiAdmin/'+rel.as_posix())
    z.writestr('BaichaoWikiAdmin/使用说明.txt',(source/'使用说明.md').read_text(encoding='utf-8').encode('utf-8-sig'))
    z.write(root/'LICENSE','BaichaoWikiAdmin/LICENSE')
print(args.output)
