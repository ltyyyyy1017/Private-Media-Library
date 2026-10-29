"""Local-only administrative control panel."""
import os
import ctypes
import sys
import base64
import json
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import urllib.request
import queue
from desktop_support import SingleInstance, load_preferences, save_preferences

BASE = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
class Manager:
    def __init__(self, instance=None):
        self.instance=instance
        self.commands=queue.Queue()
        self.sharing_state='idle'
        self.tray=None
        self.exiting=False
        self.root = tk.Tk()
        self.root.title('热点文件柜 · 管理面板')
        if (BASE/'映屿.ico').exists():self.root.iconbitmap(str(BASE/'映屿.ico'))
        self.root.geometry('690x610')
        self.root.minsize(620,590)
        self.process = None
        self.folder = tk.StringVar()
        self.password = tk.StringVar()
        self.remember=tk.BooleanVar(value=True)
        try:
            saved=load_preferences()
            self.folder.set(saved.get('folder',''))
            self.password.set(saved.get('password',''))
        except Exception:
            self.root.after(800,lambda:messagebox.showwarning('无法读取记忆','已保存的密码无法由当前 Windows 账户解密，请重新设置。'))
        self.status = tk.StringVar(value='尚未启动共享')
        frame = ttk.Frame(self.root,padding=28)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='热点文件柜',font=('Microsoft YaHei UI',24,'bold')).pack(anchor='w')
        ttk.Label(frame,text='管理面板仅在这台电脑上打开。手机、Mac 用浏览器访问文件。').pack(anchor='w',pady=(5,20))
        ttk.Label(frame,text='1  开启 Windows 移动热点').pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=6)
        ttk.Button(row,text='打开热点设置',command=lambda:os.startfile('ms-settings:network-mobilehotspot')).pack(side='left')
        self.setup=ttk.Button(row,text='首次使用：配置访问隔离',command=self.configure)
        self.setup.pack(side='left',padx=8)
        ttk.Label(frame,text='2  选择要共享的文件夹').pack(anchor='w',pady=(12,4))
        row=ttk.Frame(frame);row.pack(fill='x')
        ttk.Entry(row,textvariable=self.folder).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='选择文件夹',command=self.choose).pack(side='left',padx=8)
        ttk.Label(frame,text='3  设置访问密码（至少 12 个字符）').pack(anchor='w',pady=(12,4))
        password_entry=ttk.Entry(frame,textvariable=self.password,show='●')
        password_entry.pack(fill='x')
        password_entry.bind('<FocusOut>',lambda event:self.save_settings())
        memory_row=ttk.Frame(frame);memory_row.pack(fill='x',pady=6)
        ttk.Checkbutton(memory_row,text='记住文件夹与密码（Windows 账户加密）',variable=self.remember,command=self.save_settings).pack(side='left')
        ttk.Button(memory_row,text='清除记忆',command=self.forget).pack(side='right')
        row=ttk.Frame(frame);row.pack(fill='x',pady=18)
        self.start_button=ttk.Button(row,text='开始共享',command=self.start)
        self.start_button.pack(side='left')
        ttk.Button(row,text='停止共享',command=self.stop).pack(side='left',padx=8)
        ttk.Button(row,text='复制访问地址',command=self.copy).pack(side='left')
        ttk.Label(frame,textvariable=self.status,wraplength=600).pack(anchor='w')
        ttk.Label(frame,text='访问地址：https://192.168.137.1:8443').pack(anchor='w',pady=8)
        ttk.Button(frame,text='配置苹果设备证书（重新签发后需在设备信任）',command=self.apple_certificate).pack(anchor='w',pady=4)
        ttk.Button(frame,text='打开使用说明 / 证书信任说明',command=lambda:os.startfile(str(BASE/'README.md'))).pack(anchor='w')
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.bind('<Unmap>',self.minimized)
        self.setup_tray()
        self.root.after(150,self.check_commands)
        if '--autostart' in sys.argv and self.tray:self.root.withdraw()
        self.root.after(1000,self.poll)

    def apple_certificate(self):
        if not messagebox.askyesno('配置苹果设备证书','这会重新签发本机 HTTPS 证书，短暂停止共享。需要在 iPhone / Mac 安装并信任导出的根证书。继续？'):return
        was_running=self.process is not None
        self.stop()
        try:
            state=BASE/'private-state';state.mkdir(exist_ok=True)
            env=os.environ.copy();env['YINGYU_CERT_STATE']=str(state)
            script="$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; & icacls.exe $env:YINGYU_CERT_STATE /inheritance:r /grant:r \"*$($sid):(OI)(CI)F\" '*S-1-5-18:(OI)(CI)F'; exit $LASTEXITCODE"
            subprocess.run(['powershell.exe','-NoProfile','-Command',script],env=env,check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            from tls_support import prepare_apple_certificate
            public,fingerprint=prepare_apple_certificate(state)
            exported=BASE/'苹果设备根证书.crt';exported.write_bytes(public.read_bytes())
            guide=BASE/'苹果证书安装说明.txt'
            guide.write_text('只传送本目录的 苹果设备根证书.crt，切勿传送 private-state 中的 key 文件。\n根证书 SHA-256：'+fingerprint+'\n\niPhone：通过可信渠道传送并安装证书描述文件，然后 设置→通用→关于本机→证书信任设置，启用 Yingyu Private Hotspot CA 的完全信任。\nMac：在钥匙串访问中导入该证书，打开“信任”，将 SSL 设为始终信任。\n完成后关闭旧网页，重新访问 https://192.168.137.1:8443/ 。\n只在你自己的设备上信任并核对指纹。\n',encoding='utf-8')
            os.startfile(str(guide))
            subprocess.Popen(['explorer.exe','/select,',str(exported)],creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            messagebox.showerror('配置未完成','证书配置失败，请检查程序目录写入权限；共享保持停止。');return
        if was_running:self.start()

    def save_settings(self):
        try:save_preferences(self.folder.get(),self.password.get(),self.remember.get())
        except Exception as exc:
            self.status.set('设置记忆未保存：'+str(exc))

    def forget(self):
        self.remember.set(False)
        save_preferences('','',False)
        self.password.set('')
        self.folder.set('')
        self.status.set('已清除保存的文件夹和密码；正在运行的共享不受影响。')

    def setup_tray(self):
        try:
            import pystray
            self.tray=pystray.Icon('YingyuMediaLibrary',self.tray_image('idle'),'映屿 · 未共享',pystray.Menu(
                pystray.MenuItem('打开管理面板',lambda icon,item:self.commands.put('show'),default=True),
                pystray.MenuItem('开始共享',lambda icon,item:self.commands.put('start'),enabled=lambda item:self.process is None),
                pystray.MenuItem('停止共享',lambda icon,item:self.commands.put('stop'),enabled=lambda item:self.process is not None),
                pystray.MenuItem('复制访问地址',lambda icon,item:self.commands.put('copy')),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('退出程序',lambda icon,item:self.commands.put('quit'))))
            threading.Thread(target=self.tray.run,daemon=True).start()
        except Exception as exc:
            self.tray=None
            self.status.set('托盘启动失败，关闭窗口将退出：'+str(exc))

    def tray_image(self,state):
        from PIL import Image,ImageDraw
        image=Image.open(BASE/'映屿.ico').convert('RGBA').resize((128,128))
        draw=ImageDraw.Draw(image)
        color={'idle':'#8b95a5','starting':'#f4b441','active':'#28c984','error':'#ee5362'}[state]
        draw.ellipse((76,76,126,126),fill=color,outline='white',width=5)
        return image

    def set_state(self,state):
        if state==self.sharing_state:return
        self.sharing_state=state
        if self.tray:
            self.tray.icon=self.tray_image(state)
            self.tray.title='映屿 · '+{'idle':'未共享','starting':'启动中','active':'共享中','error':'启动失败或共享中断'}[state]
            self.tray.update_menu()

    def show(self):
        self.root.deiconify();self.root.state('normal');self.root.lift()
        self.root.attributes('-topmost',True)
        self.root.after(150,lambda:self.root.attributes('-topmost',False))

    def minimized(self,event):
        if event.widget==self.root and self.tray and self.root.state()=='iconic':self.root.withdraw()

    def check_commands(self):
        if self.exiting:return
        if self.instance and self.instance.was_requested():self.show()
        while not self.commands.empty():
            command=self.commands.get_nowait()
            if command=='show':self.show()
            elif command=='start':self.start()
            elif command=='stop':self.stop()
            elif command=='copy':self.copy()
            elif command=='quit':self.quit();return
        self.root.after(150,self.check_commands)

    def choose(self):
        value=filedialog.askdirectory(title='选择专用共享文件夹')
        if value:self.folder.set(value);self.save_settings()

    def configure(self):
        if self.process and self.process.poll() is None:
            messagebox.showinfo('请先停止共享','停止共享后才能重新配置隔离规则。');return
        self.setup.config(state='disabled')
        self.status.set('请在 Windows 权限提示中允许配置防火墙；配置完成前不会启动共享。')
        def run():
            try:
                result_path=BASE/'setup-result.json'
                result_path.unlink(missing_ok=True)
                script=str(BASE/'Setup-Firewall.ps1').replace("'","''")
                command="$ErrorActionPreference='Stop'; try { $p=Start-Process powershell.exe -WindowStyle Hidden -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \""+script+"\"'; exit $p.ExitCode } catch { Write-Error $_; exit 1 }"
                encoded=base64.b64encode(command.encode('utf-16le')).decode('ascii')
                result=subprocess.run(['powershell.exe','-NoProfile','-EncodedCommand',encoded],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                detail=''
                if result.returncode:
                    if result_path.exists():
                        info=json.loads(result_path.read_text(encoding='utf-8-sig'))
                        detail=f"失败阶段：{info.get('stage','')}\n{info.get('message','')}\n\n{info.get('location','')}"
                    else:
                        detail='管理员进程未能启动或授权被取消。\n'+result.stderr.decode(errors='replace')[-1500:]
                self.root.after(0,lambda code=result.returncode,detail=detail:self.configured(code,detail))
            except Exception as exc:
                self.root.after(0,lambda detail=str(exc):self.configured(1,detail))
        threading.Thread(target=run,daemon=True).start()

    def configured(self,code,detail=''):
        self.setup.config(state='normal')
        self.status.set('隔离规则配置成功。选择文件夹并设置密码即可开始。' if code==0 else '配置失败，具体原因已显示在弹窗中。')
        if code:messagebox.showerror('配置失败的具体原因',detail or '未收到配置结果，请重新配置。')
        if code:self.set_state('error')

    def start(self):
        if ctypes.windll.shell32.IsUserAnAdmin():
            messagebox.showerror('需要普通权限','请关闭此面板并重新打开，程序会自动切换为普通权限。');return
        if self.process and self.process.poll() is None:return
        if not Path(self.folder.get()).is_dir() or not self.folder.get():
            messagebox.showerror('选择文件夹','请选择存在的共享文件夹。');return
        if len(self.password.get())<12:
            messagebox.showerror('设置密码','访问密码至少需要 12 个字符。');return
        if not (BASE/'hotspot.json').exists():
            messagebox.showinfo('首次配置','请先点击“首次使用：配置访问隔离”。');return
        env=os.environ.copy();env['HOTSPOTFILES_SESSION_PASSWORD']=self.password.get()
        env['PYTHONIOENCODING']='utf-8'
        self.log=open(BASE/'manager.log','w',encoding='utf-8')
        self.process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(BASE/'Start.ps1'),'-ShareFolder',self.folder.get()],env=env,stdout=self.log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        self.save_settings()
        self.start_button.config(state='disabled')
        self.status.set('正在启动并检查安全配置，请稍候…')
        self.set_state('starting')

    def poll(self):
        if self.process:
            if self.process.poll() is not None:
                self.log.close();self.process=None
                self.start_button.config(state='normal')
                self.status.set('服务已停止。若启动失败，请查看错误详情。')
                self.set_state('error')
                detail=(BASE/'manager.log').read_text(encoding='utf-8',errors='replace')[-3500:]
                if detail:messagebox.showerror('启动或运行信息',detail)
            else:
                # Complete a verified TLS request instead of aborting one handshake per second.
                import time
                if time.monotonic()-getattr(self,'last_health',0)>=5:
                    self.last_health=time.monotonic()
                    from tls_support import check_service
                    try:
                        if check_service(BASE):
                            self.status.set('共享服务正在响应 HTTPS 请求。苹果设备需完成证书信任。')
                            self.set_state('active')
                    except (OSError,ValueError):
                        self.status.set('暂时无法完成 HTTPS 检查；若持续失败，请停止后重新开始共享。')
                        self.set_state('error')
        self.root.after(1000,self.poll)

    def stop(self):
        if self.process and self.process.poll() is None:
            subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            self.process.wait(timeout=10);self.log.close()
        self.process=None;self.start_button.config(state='normal');self.status.set('共享已停止')
        self.set_state('idle')

    def copy(self):
        self.root.clipboard_clear();self.root.clipboard_append('https://192.168.137.1:8443')

    def close(self):
        self.save_settings()
        if self.tray:self.root.withdraw()
        else:self.quit()

    def quit(self):
        self.exiting=True
        self.save_settings()
        self.stop()
        if self.tray:self.tray.stop()
        self.root.destroy()
        if self.instance:self.instance.close()

if __name__=='__main__':
    if '--serve' in sys.argv:
        if ctypes.windll.shell32.IsUserAnAdmin():sys.exit(1)
        service_instance=SingleInstance('server')
        if not service_instance.primary:sys.exit(2)
        sys.argv.remove('--serve')
        # Windowed executables have no console streams. Retain diagnostic logs.
        if sys.stdout is None:sys.stdout=open(BASE/'server.log','a',encoding='utf-8',buffering=1)
        if sys.stderr is None:sys.stderr=sys.stdout
        from app import run_server
        run_server()
        sys.exit(0)
    if '--self-test' in sys.argv:
        import app, flask, cheroot, cryptography, ssl
        assert (Path(app.__file__).with_name('index.html')).exists()
        assert (BASE/'Gate.ps1').exists()
        import tempfile,numpy as np,png,rawpy,pillow_heif
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            Image.new('RGB',(32,32),'red').save(root/'photo.tiff')
            data=np.full((16,16,3),32768,dtype=np.uint16)
            pillow_heif.from_bytes('RGB;16',(16,16),data.tobytes()).save(root/'apple.heic',quality=100,bit_depth=10)
            client=app.create_app(root,'192.168.137.0/24','package-test-password').test_client()
            args=dict(base_url='https://192.168.137.1:8443',environ_overrides={'REMOTE_ADDR':'192.168.137.2'})
            response=client.post('/login',json={'password':'package-test-password'},headers={'Origin':'https://192.168.137.1:8443'},**args)
            assert response.status_code==200
            for filename in ('photo.tiff','apple.heic'):
                with client.get('/image?path='+filename,**args) as response:
                    assert response.status_code==200,(filename,response.status_code)
                    width,height,rows,info=png.Reader(bytes=response.data).read()
                    if filename=='apple.heic':assert (width,height,info['bitdepth'])==(16,16,16)
        (BASE/'package-test.txt').write_text('PASS: bundled runtime, TIFF/HEIC conversion, 16-bit full-resolution PNG, RAW decoder imports, HTML and launcher resources',encoding='utf-8')
        sys.exit(0)
    if ctypes.windll.shell32.IsUserAnAdmin():
        if '--normal-user' not in sys.argv:
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(BASE/'Relaunch-Normal.ps1'),'-ProgramFolder',str(BASE)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                sys.exit(0)
        root=tk.Tk();root.withdraw()
        messagebox.showerror('无法切换到普通权限','当前 Windows 桌面也可能具有管理员权限。请从普通权限的资源管理器双击“打开管理面板.cmd”。文件服务不能以管理员权限运行。')
        root.destroy();sys.exit(1)
    instance=SingleInstance()
    if not instance.primary:
        instance.close()
        sys.exit(0)
    Manager(instance).root.mainloop()
