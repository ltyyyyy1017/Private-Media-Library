"""Lossless container compatibility. Never recompress a user's video/audio."""
import hashlib
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from flask import abort, jsonify, request, send_file

VIDEO_EXTENSIONS = {'.mp4','.webm','.mov','.m4v','.mkv','.avi','.ts','.mts','.m2ts','.mpeg','.mpg','.wmv','.flv','.3gp','.ogv','.vob','.m2v','.mxf'}


def install(app, target, metadata_dir):
    pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='lossless-remux')
    jobs = {}
    lock = threading.Lock()

    @app.route('/video-compatible',methods=['GET','POST'])
    def compatible():
        p=target(request.args.get('path',''))
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS:
            abort(404)
        s=p.stat()
        key=hashlib.sha256((str(p)+str(s.st_size)+str(s.st_mtime_ns)).encode()).hexdigest()
        cache=metadata_dir('.hotspot-video')
        output=cache/(key+'.mp4')
        with lock:
            if output.exists():
                if request.args.get('status') == '1':
                    return jsonify(ready=True)
                return send_file(output,mimetype='video/mp4',conditional=True)
            status=jobs.get(key)
            if request.method=='GET':
                if status=='failed':
                    return jsonify(error='无法无损封装为 MP4，请下载原文件使用本机播放器'),422
                return jsonify(pending=status=='pending'),202
            if status=='pending':
                return jsonify(pending=True),202
            if sum(v=='pending' for v in jobs.values())>=3:
                abort(429)
            jobs[key]='pending'

        def generate():
            import imageio_ffmpeg
            temporary=cache/(key+'.tmp.mp4')
            try:
                # Copy both streams. Unsupported codecs fail rather than silently losing quality/audio.
                command=[imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-protocol_whitelist','file',
                         '-i',str(p),'-map','0:v:0','-map','0:a:0?','-c','copy','-movflags','+faststart','-y',str(temporary)]
                result=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                      timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode or not temporary.exists() or p.stat().st_mtime_ns!=s.st_mtime_ns or p.stat().st_size!=s.st_size:
                    raise OSError('remux failed')
                os.replace(temporary,output)
                with lock:
                    jobs[key]='ready'
            except Exception:
                with lock:
                    jobs[key]='failed'
            finally:
                temporary.unlink(missing_ok=True)
        pool.submit(generate)
        return jsonify(pending=True),202
