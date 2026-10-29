"""Local perceptual candidates using MIT-licensed benhoyt/dhash. No AI."""
import io
import re
import subprocess
from PIL import Image, ImageOps, ImageStat
import dhash
from video_compat import VIDEO_EXTENSIONS

IMAGE_EXTENSIONS={'.jpg','.jpeg','.png','.webp','.heic','.heif','.avif','.bmp','.tif','.tiff','.gif'}


def fingerprint(path):
    def image_hash(image):
        image=ImageOps.exif_transpose(image).convert('RGB')
        # Blank frames and flat graphics give misleadingly identical hashes.
        if max(ImageStat.Stat(image.resize((32,32))).stddev)<5:
            raise ValueError('uninformative image')
        return [dhash.dhash_int(image),image.width/image.height]
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        import pillow_heif
        pillow_heif.register_heif_opener()
        with Image.open(path) as image:
            if image.width*image.height>64_000_000:
                raise ValueError('large image')
            value,ratio=image_hash(image)
        return dict(type='image',hashes=[value],ratio=ratio,duration=0)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    import imageio_ffmpeg
    exe=imageio_ffmpeg.get_ffmpeg_exe()
    def run(args):
        return subprocess.run([exe,'-nostdin','-protocol_whitelist','file',*args],capture_output=True,
                              timeout=35,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    probe=run(['-i',str(path)])
    match=re.search(rb'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',probe.stderr)
    if not match:
        raise ValueError('duration unknown')
    h,m,s=map(float,match.groups())
    duration=h*3600+m*60+s
    hashes=[]
    for fraction in (.1,.3,.5,.7,.9):
        frame=run(['-v','error','-ss',str(duration*fraction),'-i',str(path),'-frames:v','1',
                   '-vf','scale=256:-1','-f','image2pipe','-vcodec','png','-'])
        if frame.returncode:
            raise ValueError('frame decode failed')
        with Image.open(io.BytesIO(frame.stdout)) as image:
            value,ratio=image_hash(image)
            hashes.append(value)
    return dict(type='video',hashes=hashes,ratio=ratio,duration=duration)


def similar(a,b):
    if a['type']!=b['type'] or abs(a['ratio']/b['ratio']-1)>.03:
        return False
    if a['type']=='video' and abs(a['duration']-b['duration'])>max(.5,min(a['duration'],b['duration'])*.02):
        return False
    distances=[(x^y).bit_count() for x,y in zip(a['hashes'],b['hashes'])]
    return sum(x<=6 for x in distances)>=(4 if a['type']=='video' else 1)


def find_candidates(files,target,cache,progress):
    values=[]
    skipped=0
    for index,f in enumerate(files):
        progress(index,len(files))
        try:
            p=target(f['name'])
            s=p.stat()
            key=f['name']
            signature=[s.st_size,s.st_mtime_ns,s.st_ino]
            record=cache.get(key)
            if not record or record['signature']!=signature:
                record=dict(signature=signature,value=fingerprint(p))
                if [p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ino]!=signature:
                    raise ValueError('changed')
                cache[key]=record
            if record['value']:
                values.append((key,record['value']))
        except Exception:
            skipped+=1
    # Compare to group representative to avoid transitive similarity chains.
    groups=[]
    used=set()
    for i,(path,value) in enumerate(values):
        if path in used:
            continue
        matches=[other for other,candidate in values[i+1:] if other not in used and similar(value,candidate)]
        if matches:
            paths=[path,*matches]
            used.update(paths)
            groups.append(dict(paths=paths,size=0,similar=True,media=value['type']))
    return groups,skipped
