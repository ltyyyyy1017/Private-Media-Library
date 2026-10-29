"""Windows single instance, wake event and current-user encrypted preferences."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets

kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
kernel.CreateMutexW.restype=wintypes.HANDLE
kernel.CreateEventW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
kernel.CreateEventW.restype=wintypes.HANDLE
kernel.SetEvent.argtypes=[wintypes.HANDLE]
kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
class SingleInstance:
    def __init__(self,role='manager'):
        name='Local\\Yingyu.MediaLibrary.v1.'+role
        self.mutex=kernel.CreateMutexW(None,False,name)
        if not self.mutex:raise ctypes.WinError(ctypes.get_last_error())
        self.primary=ctypes.get_last_error()!=183
        self.event=kernel.CreateEventW(None,False,False,name+'.wake')
        if not self.event:raise ctypes.WinError(ctypes.get_last_error())
        if not self.primary:kernel.SetEvent(self.event)
    def was_requested(self):
        return kernel.WaitForSingleObject(self.event,0)==0
    def close(self):
        for handle in (self.event,self.mutex):
            if handle:kernel.CloseHandle(handle)
        self.event=self.mutex=None

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def protect_secret(value,decrypt=False):
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    raw=base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    output=Blob()
    if decrypt:
        fn=crypt.CryptUnprotectData
        ok=fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output))
    else:
        fn=crypt.CryptProtectData
        ok=fn(ctypes.byref(source),'Yingyu password',None,None,None,1,ctypes.byref(output))
    if not ok:raise ctypes.WinError(ctypes.get_last_error())
    try:
        result=ctypes.string_at(output.data,output.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        kernel.LocalFree.argtypes=[ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(output.data,ctypes.c_void_p))

def preferences_path():
    return Path(os.environ['LOCALAPPDATA'])/'YingyuMediaLibrary'/'preferences.json'

def load_preferences():
    path=preferences_path()
    if not path.exists():return {}
    data=json.loads(path.read_text(encoding='utf-8'))
    data['password']=protect_secret(data['encrypted_password'],decrypt=True)
    return data

def save_preferences(folder,password,remember=True):
    path=preferences_path()
    if not remember:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(exist_ok=True,parents=True)
    temporary=path.with_name(secrets.token_hex(12)+'.tmp')
    try:
        temporary.write_text(json.dumps({'folder':folder,'encrypted_password':protect_secret(password)},ensure_ascii=False),encoding='utf-8')
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
