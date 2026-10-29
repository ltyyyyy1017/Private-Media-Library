"""HTTPS file browser. Start through Start.ps1, not directly."""
import argparse
import datetime
import ipaddress
import os
import json
import hashlib
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import threading
import time

from flask import Flask, abort, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash


def create_app(root, network, password):
    root = Path(root).resolve(strict=True)
    app = Flask(__name__, static_folder=None)
    # Stable only for the same shared directory and password. Changing either
    # revokes old login cookies, without persisting the password on disk.
    app.secret_key = hashlib.scrypt(password.encode(), salt=hashlib.sha256(str(root).encode()).digest(), n=32768, r=8, p=1, maxmem=64*1024*1024)
    app.config.update(MAX_CONTENT_LENGTH=4 * 1024**3,
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict',
                      PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=7))
    digest = generate_password_hash(password)
    subnet = ipaddress.ip_network(network, strict=False)
    failures = {}
    lock = threading.Lock()
    favorites_path = root / '.hotspot-favorites.json'
    favorite_lock = threading.RLock()
    thumbnail_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='thumbnails')
    thumbnail_jobs = set()
    image_lock = threading.Semaphore(1)

    def metadata_dir(name):
        p = root / name
        if p.is_symlink() or (p.exists() and getattr(p.lstat(),'st_file_attributes',0) & 0x400):
            abort(403)
        p.mkdir(exist_ok=True)
        return p

    def favorites_read():
        if favorites_path.is_symlink() or (favorites_path.exists() and getattr(favorites_path.lstat(), 'st_file_attributes', 0) & 0x400):
            abort(403)
        return set(json.loads(favorites_path.read_text(encoding='utf-8'))) if favorites_path.exists() else set()

    def favorites_write(values):
        temporary = root / ('.hotspot-' + secrets.token_hex(12))
        try:
            with temporary.open('x', encoding='utf-8') as out:
                json.dump(sorted(values), out, ensure_ascii=False)
            os.replace(temporary, favorites_path)
        finally:
            temporary.unlink(missing_ok=True)

    def target(name):
        if not isinstance(name, str) or '\\' in name or ':' in name or '\x00' in name:
            abort(400)
        p = root
        for part in name.split('/'):
            if not part:
                continue
            if part.lower().startswith('.hotspot-'):
                abort(403)
            if part in ('.', '..') or part.endswith((' ', '.')) or any(c in part for c in '<>"|?*'):
                abort(400)
            if part.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(10)),*(f'LPT{i}' for i in range(10))}:
                abort(400)
            p = p / part
            # Reject symlinks, junctions and other reparse points, even inside root.
            if p.is_symlink() or (p.exists() and getattr(p.lstat(), 'st_file_attributes', 0) & 0x400):
                abort(403)
        if not p.resolve().is_relative_to(root):
            abort(403)
        return p

    @app.before_request
    def protect():
        if request.host != '192.168.137.1:8443':
            abort(403)
        if request.path == '/login':
            request.max_content_length = 4096
        try:
            if ipaddress.ip_address(request.remote_addr) not in subnet:
                abort(403)
        except ValueError:
            abort(403)
        # No reverse proxy / forwarded headers are trusted.
        if request.method not in ('GET', 'HEAD'):
            if request.headers.get('Origin') != 'https://' + request.host:
                abort(403)
        if request.path in ('/', '/login') or request.path.startswith('/assets/'):
            return
        if not session.get('ok') or session.get('expires', 0) <= time.time():
            session.clear()
            abort(401)
        if request.method not in ('GET', 'HEAD'):
            if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', 'INVALID')):
                abort(403)

    @app.after_request
    def headers(response):
        response.headers.update({'X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            'Referrer-Policy':'no-referrer', 'Cache-Control':'no-store',
            'X-Frame-Options':'DENY'})
        return response

    @app.get('/')
    def index():
        return Path(__file__).with_name('index.html').read_text(encoding='utf-8')

    @app.post('/login')
    def login():
        now = time.monotonic()
        with lock:
            old = failures.get(request.remote_addr, (0, now))
            count = old[0] if now - old[1] < 60 else 0
            if count >= 5:
                abort(429)
            failures[request.remote_addr] = (count + 1, old[1] if count else now)
        if not check_password_hash(digest, (request.get_json() or {}).get('password', '')[:1024]):
            abort(401)
        session.clear()
        remember = (request.get_json() or {}).get('remember') is True
        session.update(ok=True, csrf=secrets.token_hex(32), expires=time.time() + (7*86400 if remember else 2*3600))
        session.permanent = remember
        return jsonify(csrf=session['csrf'])

    @app.post('/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/assets/<name>')
    def assets(name):
        if name not in ('video.min.js', 'video-js.min.css', 'library.js', 'library.css', 'features.js', 'features.css', 'mobile.js', 'mobile.css', 'batch.js', 'images.js', 'organize.js', 'organize.css', 'tags.js'):
            abort(404)
        return send_file(Path(__file__).with_name('assets') / name)

    @app.get('/session')
    def current_session():
        return jsonify(csrf=session['csrf'])

    @app.get('/thumbnail')
    def thumbnail():
        p = target(request.args.get('path',''))
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS:
            abort(404)
        stat = p.stat()
        key = hashlib.sha256(('hq2'+str(p)+str(stat.st_mtime_ns)+str(stat.st_size)).encode()).hexdigest()
        cache = metadata_dir('.hotspot-thumbnails')
        output = cache / (key+'.png')
        with favorite_lock:
            if output.exists():
                return send_file(output,mimetype='image/png',conditional=True)
            if key in thumbnail_jobs:
                return jsonify(pending=True),202
            failed = cache/(key+'.failed')
            if failed.exists() and time.time()-failed.stat().st_mtime < 60:
                abort(422)
            if len(thumbnail_jobs)>=48:
                return jsonify(pending=True),202
            thumbnail_jobs.add(key)
        def generate():
            temporary = cache/(key+'.tmp.png')
            try:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
                for position in ('1','0'):
                    command=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-protocol_whitelist','file','-threads','1','-ss',position,'-i',str(p),'-an','-frames:v','1','-vf',"scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease",'-y',str(temporary)]
                    try:
                        result=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=35,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    except subprocess.TimeoutExpired:
                        continue
                    if result.returncode==0 and temporary.exists() and temporary.stat().st_size:
                        os.replace(temporary,output)
                        return
                raise RuntimeError('Cannot decode video')
            except Exception:
                (cache/(key+'.failed')).touch()
            finally:
                temporary.unlink(missing_ok=True)
                with favorite_lock:
                    thumbnail_jobs.discard(key)
        thumbnail_pool.submit(generate)
        return jsonify(pending=True),202

    @app.post('/delete')
    def delete():
        recycle_file((request.get_json() or {}).get('path',''))
        return jsonify(ok=True,recoverable=True)

    def recycle_file(path):
        p=target(path)
        if p==root or not p.exists():
            abort(400)
        with favorite_lock:
            values=favorites_read()
            trash=metadata_dir('.hotspot-trash') / secrets.token_hex(12)
            trash.mkdir()
            old=p.relative_to(root).as_posix()
            (trash/'original-path.txt').write_text(old,encoding='utf-8')
            destination=trash/p.name
            p.rename(destination)
            try:
                favorites_write({x for x in values if x!=old and not x.startswith(old+'/')})
                record_operation(old,destination.relative_to(root).as_posix(),destination,{x for x in values if x==old or x.startswith(old+'/')},trash=True)
            except Exception:
                destination.rename(p)
                favorites_write(values)
                raise
    app.extensions['recycle_file']=recycle_file

    @app.route('/favorites', methods=['GET', 'POST'])
    def favorites():
        with favorite_lock:
            values = favorites_read()
            if request.method == 'POST':
                data = request.get_json() or {}
                p = target(data.get('path', ''))
                if p == root or not p.exists():
                    abort(404)
                path = p.relative_to(root).as_posix()
                if data.get('favorite') is True:
                    values.add(path)
                elif data.get('favorite') is False:
                    values.discard(path)
                else:
                    abort(400)
                favorites_write(values)
            result = []
            for path in sorted(values):
                try:
                    p = target(path)
                    if p.exists():
                        result.append(dict(path=path, name=p.name, directory=p.is_dir(), size=p.stat().st_size, modified=p.stat().st_mtime))
                except OSError:
                    continue
            return jsonify(result)

    @app.get('/list')
    def listing():
        p = target(request.args.get('path', ''))
        if not p.is_dir():
            abort(404)
        items = []
        for child in p.iterdir():
            if child.name.startswith('.hotspot-'):
                continue
            try:
                target(child.relative_to(root).as_posix())
                items.append(dict(name=child.name, directory=child.is_dir(),
                                  size=child.stat().st_size, modified=child.stat().st_mtime))
            except Exception as exc:
                # HTTP exceptions for inaccessible reparse points are deliberately hidden.
                if not isinstance(exc, (OSError,)) and getattr(exc, 'code', None) is None:
                    raise
        return jsonify(sorted(items, key=lambda x: (not x['directory'], x['name'].lower())))

    @app.get('/file')
    def file():
        p = target(request.args.get('path', ''))
        if not p.is_file():
            abort(404)
        # Active documents (HTML, SVG, PDF etc.) are downloads, never same-origin code.
        types = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png',
                 '.webp':'image/webp','.gif':'image/gif','.mp4':'video/mp4',
                 '.webm':'video/webm','.mov':'video/quicktime','.m4v':'video/mp4',
                 '.mkv':'video/x-matroska','.avi':'video/x-msvideo','.ts':'video/mp2t',
                 '.mts':'video/mp2t','.m2ts':'video/mp2t','.mpeg':'video/mpeg','.mpg':'video/mpeg',
                 '.ogv':'video/ogg','.3gp':'video/3gpp','.flv':'video/x-flv','.wmv':'video/x-ms-wmv',
                 '.avif':'image/avif','.txt':'text/plain; charset=utf-8'}
        mime = types.get(p.suffix.lower())
        return send_file(p, mimetype=mime or 'application/octet-stream',
                         as_attachment=not mime or request.args.get('download') == '1',
                         conditional=True)

    @app.get('/image')
    def image_preview():
        p=target(request.args.get('path',''))
        native={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.jpe':'image/jpeg','.jfif':'image/jpeg',
                '.png':'image/png','.apng':'image/apng','.gif':'image/gif',
                '.webp':'image/webp','.avif':'image/avif','.bmp':'image/bmp'}
        raw_formats={'.dng','.cr2','.cr3','.nef','.nrw','.arw','.sr2','.srf','.raf','.orf','.rw2','.pef','.raw'}
        converted={'.tif','.tiff','.ico','.dib','.heic','.heif','.hif','.psd','.tga','.ppm','.pgm','.pbm','.pnm','.pcx'} | raw_formats
        ext=p.suffix.lower()
        if not p.is_file() or ext not in set(native)|converted:
            abort(404)
        # Preserve native animations, including APNG stored with a .png suffix.
        if ext in native and request.args.get('convert')!='1':
            return send_file(p,mimetype=native[ext],conditional=True)
        if p.stat().st_size>256*1024*1024:
            abort(413)
        stat=p.stat()
        key=hashlib.sha256((str(p)+str(stat.st_mtime_ns)+str(stat.st_size)).encode()).hexdigest()
        cache=metadata_dir('.hotspot-images')
        output=cache/(key+'.png')
        with image_lock:
            if not output.exists():
                temporary=cache/(key+'.'+secrets.token_hex(6)+'.png')
                from PIL import Image, ImageOps
                try:
                    import warnings
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                    if ext in {'.heic','.heif','.hif'}:
                        heif=pillow_heif.open_heif(p,convert_hdr_to_8bit=False)
                        width,height=heif.size
                        if width*height>64_000_000:
                            abort(413)
                        if ';16' in heif.mode:
                            import numpy as np
                            import png
                            channels=4 if heif.mode.startswith('RGBA') else 3
                            pixels=np.frombuffer(heif.data,dtype='<u2').reshape(height,heif.stride//2)[:,:width*channels]
                            with temporary.open('wb') as out:
                                png.Writer(width=width,height=height,greyscale=False,alpha=channels==4,bitdepth=16).write(out,(row.tolist() for row in pixels))
                            os.replace(temporary,output)
                            return send_file(output,mimetype='image/png',conditional=True)
                    if ext in raw_formats:
                        import rawpy
                        try:
                            with rawpy.imread(str(p)) as raw:
                                if raw.sizes.width*raw.sizes.height>64_000_000:
                                    abort(413)
                                rgb=raw.postprocess(half_size=False,output_bps=16,use_camera_wb=True)
                            import png
                            with temporary.open('wb') as out:
                                png.Writer(width=rgb.shape[1],height=rgb.shape[0],greyscale=False,bitdepth=16).write(out,(row.reshape(-1).tolist() for row in rgb))
                        except rawpy.LibRawError:
                            abort(422)
                        os.replace(temporary,output)
                        return send_file(output,mimetype='image/png',conditional=True)
                    with warnings.catch_warnings():
                        warnings.simplefilter('error',Image.DecompressionBombWarning)
                        with Image.open(p) as original:
                            if original.width*original.height>64_000_000:
                                abort(413)
                            original.seek(0)
                            converted_image=ImageOps.exif_transpose(original)
                            if converted_image.mode in ('I;16','I;16B','I;16L','I'):
                                converted_image.save(temporary,format='PNG')
                            else:
                                converted_image.convert('RGBA').save(temporary,format='PNG',icc_profile=original.info.get('icc_profile'))
                    os.replace(temporary,output)
                except (Image.DecompressionBombWarning,Image.DecompressionBombError):
                    abort(413)
                except (OSError,ValueError):
                    abort(422)
                finally:
                    temporary.unlink(missing_ok=True)
        return send_file(output,mimetype='image/png',conditional=True)

    @app.post('/mkdir')
    def mkdir():
        p = target((request.get_json() or {}).get('path', ''))
        try:
            p.mkdir()
        except FileExistsError:
            abort(409)
        return jsonify(ok=True)

    @app.post('/move')
    @app.post('/rename')
    def rename():
        data = request.get_json() or {}
        src, dst = target(data.get('path','')), target(data.get('new',''))
        if src == root or dst == root or not src.exists() or dst.exists():
            abort(409)
        if not dst.parent.is_dir() or dst.is_relative_to(src):
            abort(409)
        # Windows rename refuses replacement, including racing destinations.
        with favorite_lock:
            values = favorites_read()
            old, new = src.relative_to(root).as_posix(), dst.relative_to(root).as_posix()
            src.rename(dst)
            updated = {new + path[len(old):] if path == old or path.startswith(old + '/') else path for path in values}
            try:
                favorites_write(updated)
                record_operation(old,new,dst,{x for x in values if x==old or x.startswith(old+'/')})
            except Exception:
                dst.rename(src)
                favorites_write(values)
                raise
        return jsonify(ok=True)

    @app.put('/upload')
    def upload():
        p = target(request.args.get('path',''))
        if p == root or not p.parent.is_dir():
            abort(400)
        # Existing files are never silently replaced. Changes become new versions.
        try:
            with p.open('xb') as out:
                try:
                    while chunk := request.stream.read(1024 * 1024):
                        out.write(chunk)
                except BaseException:
                    out.close()
                    p.unlink(missing_ok=True)
                    raise
        except FileExistsError:
            abort(409, 'Name already exists. Save under a new name.')
        return jsonify(ok=True)

    from tags import install as install_tags
    install_tags(app,target,metadata_dir,favorite_lock)
    from organize import install
    record_operation = install(app,root,target,metadata_dir,favorite_lock,favorites_read,favorites_write)
    from video_compat import install as install_video, VIDEO_EXTENSIONS
    install_video(app,target,metadata_dir)
    return app


def certificate(state, address):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    cert, key = state / 'server.crt', state / 'server.key'
    if cert.exists() and key.exists():
        current = x509.load_pem_x509_certificate(cert.read_bytes())
        if (ipaddress.ip_address(address) in current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
                and current.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc)):
            return cert, key
        raise RuntimeError('Certificate expired or hotspot IP changed. Rename private-state and restart.')
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Hotspot Files')])
    now = datetime.datetime.now(datetime.timezone.utc)
    signed = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(private.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), critical=False)
        .sign(private, hashes.SHA256()))
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert.write_bytes(signed.public_bytes(serialization.Encoding.PEM))
    return cert, key


def run_server():
    import getpass
    import ssl
    from cheroot.wsgi import Server
    from cheroot.ssl.builtin import BuiltinSSLAdapter
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--ip', required=True)
    parser.add_argument('--network', required=True)
    args = parser.parse_args()
    password = os.environ.pop('HOTSPOTFILES_SESSION_PASSWORD', None) or getpass.getpass('Set this session password (at least 12 characters): ')
    if len(password) < 12:
        raise SystemExit('Password too short.')
    state = (Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent) / 'private-state'
    state.mkdir(exist_ok=True)
    cert, key = certificate(state, args.ip)
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    print('Certificate SHA256:', x509.load_pem_x509_certificate(cert.read_bytes()).fingerprint(hashes.SHA256()).hex(':'))
    server = Server((args.ip, 8443), create_app(args.root, args.network, password), numthreads=24,
                    request_queue_size=128, timeout=30)
    adapter = BuiltinSSLAdapter(str(cert), str(key))
    adapter.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    adapter.context.minimum_version = ssl.TLSVersion.TLSv1_2
    adapter.context.load_cert_chain(str(cert), str(key))
    server.ssl_adapter = adapter
    print(f'Open https://{args.ip}:8443 on a hotspot device. Ctrl+C stops sharing.')
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()

if __name__ == '__main__':
    run_server()
