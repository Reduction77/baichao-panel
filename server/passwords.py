import hashlib, hmac, secrets

def hash_password(password):
    if not isinstance(password,str) or not 12<=len(password)<=256:
        raise ValueError('管理员密码须为 12～256 个字符')
    salt=secrets.token_bytes(16)
    key=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
    return 'scrypt:16384:8:1:'+salt.hex()+':'+key.hex()

def valid_hash(value):
    try:
        kind,n,r,p,salt,key=value.split(':')
        return (kind,n,r,p)==('scrypt','16384','8','1') and len(bytes.fromhex(salt))==16 and len(bytes.fromhex(key))==32
    except (ValueError,AttributeError):return False

def verify_password(password,stored):
    if not isinstance(password,str) or len(password)>256 or not valid_hash(stored):return False
    _,n,r,p,salt,key=stored.split(':')
    actual=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p),dklen=32)
    return hmac.compare_digest(actual,bytes.fromhex(key))
