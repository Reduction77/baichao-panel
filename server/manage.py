import argparse, getpass, json, os, pathlib, secrets
from server.passwords import hash_password

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['hash-password','healthcheck']);args=parser.parse_args()
    if args.command=='hash-password':
        first=getpass.getpass('管理员密码（至少12字符）：');second=getpass.getpass('再次输入：')
        if first!=second:raise SystemExit('两次输入不一致')
        print('\n将以下值填写到 .env 的 PANEL_PASSWORD_HASH：\n'+hash_password(first));return
    from urllib.request import urlopen
    with urlopen('http://127.0.0.1:8080/healthz',timeout=3) as response:
        if response.status!=200:raise SystemExit(1)

if __name__=='__main__':main()
