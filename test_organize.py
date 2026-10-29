import subprocess
import time
import unittest
from io import BytesIO
from PIL import Image
from test_app import SecurityTests


class OrganizeTests(unittest.TestCase):
    setUp = SecurityTests.setUp
    tearDown = SecurityTests.tearDown
    call = SecurityTests.call
    login = SecurityTests.login

    def test_library_duplicates_and_undo(self):
        self.login()
        (self.root/'folder').mkdir()
        (self.root/'a.txt').write_bytes(b'identical\x00content')
        (self.root/'folder'/'different-name.bin').write_bytes(b'identical\x00content')
        (self.root/'other.txt').write_bytes(b'different\x00content')
        (self.root/'.hotspot-private').mkdir()
        (self.root/'.hotspot-private'/'secret.txt').write_bytes(b'identical\x00content')
        rows=self.call('/library').json
        self.assertEqual(len(rows),3)
        self.assertTrue(any(x['name']=='folder/different-name.bin' for x in rows))
        self.assertEqual(self.call('/duplicates','POST',json={}).status_code,202)
        for _ in range(100):
            result=self.call('/duplicates').json
            if not result['running']:
                break
            time.sleep(.02)
        self.assertEqual(len(result['groups']),1)
        self.assertEqual(set(result['groups'][0]['paths']),{'a.txt','folder/different-name.bin'})
        self.call('/favorites','POST',json={'path':'a.txt','favorite':True})
        self.assertEqual(self.call('/move','POST',json={'path':'a.txt','new':'folder/a.txt'}).status_code,200)
        self.assertEqual(self.call('/delete','POST',json={'path':'folder/a.txt'}).status_code,200)
        history=self.call('/history').json
        self.assertEqual(len(history),2)
        self.assertEqual(self.call('/undo','POST',json={'id':history[1]['id']}).status_code,409)
        self.assertEqual(self.call('/undo','POST',json={'id':history[0]['id']}).status_code,200)
        self.assertEqual(self.call('/undo','POST',json={'id':history[1]['id']}).status_code,200)
        self.assertEqual((self.root/'a.txt').read_bytes(),b'identical\x00content')
        self.assertEqual(self.call('/favorites').json[0]['path'],'a.txt')
        self.assertEqual(self.call('/history').json,[])
        self.assertEqual(self.call('/history',ip='10.0.0.2').status_code,403)

    def test_undo_conflict_and_changed_file(self):
        self.login()
        (self.root/'a.txt').write_bytes(b'original')
        self.call('/rename','POST',json={'path':'a.txt','new':'b.txt'})
        row=self.call('/history').json[0]
        (self.root/'a.txt').write_bytes(b'new')
        self.assertEqual(self.call('/undo','POST',json={'id':row['id']}).status_code,409)
        (self.root/'a.txt').unlink()
        (self.root/'b.txt').write_bytes(b'changed length')
        self.assertEqual(self.call('/undo','POST',json={'id':row['id']}).status_code,409)
        self.assertEqual((self.root/'b.txt').read_bytes(),b'changed length')

    def test_similar_reencoded_image_and_persistent_results(self):
        import numpy as np
        from app import create_app
        self.login()
        rng=np.random.default_rng(42)
        pixels=rng.integers(0,256,(48,64,3),dtype=np.uint8)
        image=Image.fromarray(pixels).resize((640,480))
        image.save(self.root/'original.png')
        image.resize((320,240)).save(self.root/'reencoded.jpg',quality=90)
        Image.fromarray(rng.integers(0,256,(48,64,3),dtype=np.uint8)).resize((640,480)).save(self.root/'different.png')
        self.call('/duplicates','POST',json={'similar':True})
        for _ in range(150):
            result=self.call('/duplicates').json
            if not result['running']:
                break
            time.sleep(.02)
        groups=[g for g in result['groups'] if g.get('similar')]
        self.assertEqual(len(groups),1,result['phase'])
        self.assertEqual(set(groups[0]['paths']),{'original.png','reencoded.jpg'})
        self.app=create_app(self.root,'192.168.137.0/24','test-password-12345')
        self.client=self.app.test_client()
        self.login()
        self.assertEqual(self.call('/duplicates').json['groups'],result['groups'])
        self.call('/delete','POST',json={'path':'reencoded.jpg'})
        self.assertEqual(self.call('/duplicates').json['groups'],[])

    def test_hq_thumbnail_lossless_remux(self):
        import imageio_ffmpeg
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        self.login()
        source=self.root/'synthetic.mkv'
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=1920x1080:rate=2','-t','1.5',
                        '-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True)
        original=source.read_bytes()
        for _ in range(100):
            with self.call('/thumbnail?path=synthetic.mkv') as response:
                if response.status_code==200:
                    thumbnail=response.data
                    break
            time.sleep(.1)
        else:
            self.fail('thumbnail timed out')
        with Image.open(BytesIO(thumbnail)) as img:
            self.assertEqual(img.size,(1280,720))
            self.assertEqual(img.format,'PNG')
        self.assertEqual(self.call('/video-compatible?path=synthetic.mkv','POST',json={}).status_code,202)
        for _ in range(100):
            if self.call('/video-compatible?path=synthetic.mkv&status=1').status_code==200:
                break
            time.sleep(.1)
        else:
            self.fail('remux timed out')
        with self.call('/video-compatible?path=synthetic.mkv') as response:
            self.assertEqual(response.status_code,200)
            copy=self.root/'remux.mp4'
            copy.write_bytes(response.data)
        def pixels(path):
            data=subprocess.run([ffmpeg,'-v','error','-i',str(path),'-map','0:v:0','-f','framemd5','-'],capture_output=True,check=True).stdout
            return [line.split(b',')[-1].strip() for line in data.splitlines() if not line.startswith(b'#')]
        self.assertEqual(pixels(source),pixels(copy))
        self.assertEqual(source.read_bytes(),original)
        with self.call('/video-compatible?path=synthetic.mkv',headers={'Range':'bytes=0-15'}) as response:
            self.assertEqual(response.status_code,206)

    def test_similar_reencoded_video(self):
        import imageio_ffmpeg
        from similarity import fingerprint,similar
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        a,b,c=[self.root/name for name in ('a.mp4','b.mkv','c.mp4')]
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=10',
                        '-t','3','-c:v','libx264','-crf','18',str(a)],capture_output=True,check=True)
        subprocess.run([ffmpeg,'-v','error','-i',str(a),'-vf','scale=640:360','-c:v','libx264',
                        '-crf','30',str(b)],capture_output=True,check=True)
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc=size=320x180:rate=10',
                        '-t','3','-c:v','libx264','-pix_fmt','yuv420p',str(c)],capture_output=True,check=True)
        fa,fb,fc=map(fingerprint,(a,b,c))
        self.assertTrue(similar(fa,fb))
        self.assertFalse(similar(fa,fc))


if __name__=='__main__':
    unittest.main()
