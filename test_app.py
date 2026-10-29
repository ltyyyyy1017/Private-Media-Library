import tempfile
import unittest
from pathlib import Path
from app import create_app

class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = create_app(self.root, '192.168.137.0/24', 'test-password-12345')
        self.client = self.app.test_client()
        self.token = ''

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, path, method='GET', ip='192.168.137.2', **kw):
        headers = kw.pop('headers', {})
        headers.update(Origin='https://192.168.137.1:8443')
        if self.token:
            headers['X-CSRF-Token'] = self.token
        return self.client.open(path, method=method, base_url='https://192.168.137.1:8443',
            environ_overrides={'REMOTE_ADDR':ip}, headers=headers, **kw)

    def login(self):
        r = self.call('/login', 'POST', json={'password':'test-password-12345'})
        self.assertEqual(r.status_code, 200)
        self.token = r.json['csrf']

    def test_network_and_auth(self):
        self.assertEqual(self.call('/', ip='172.20.17.5').status_code, 403)
        self.assertEqual(self.call('/list').status_code, 401)
        self.assertEqual(self.call('/login','POST',json={'password':'bad'}).status_code,401)

    def test_files(self):
        self.login()
        self.assertEqual(self.call('/mkdir','POST',json={'path':'照片'}).status_code,200)
        self.assertEqual(self.call('/upload?path=a.txt','PUT',data=b'hello').status_code,200)
        with self.call('/file?path=a.txt') as response:
            self.assertEqual(response.data,b'hello')
        self.assertEqual(self.call('/upload?path=a.txt','PUT',data=b'overwrite').status_code,409)
        self.assertEqual(self.call('/rename','POST',json={'path':'a.txt','new':'b.txt'}).status_code,200)
        with self.call('/file?path=b.txt',headers={'Range':'bytes=1-3'}) as response:
            self.assertEqual(response.status_code,206)

    def test_traversal_and_active_content(self):
        self.login()
        for path in ('../secret','C:/Windows','x:stream','CON','a./b'):
            self.assertEqual(self.call('/mkdir','POST',json={'path':path}).status_code,400)
        self.call('/upload?path=evil.html','PUT',data=b'<script>alert(1)</script>')
        with self.call('/file?path=evil.html') as response:
            self.assertIn('attachment',response.headers['Content-Disposition'])

    def test_csrf(self):
        self.login()
        self.token = 'wrong'
        self.assertEqual(self.call('/mkdir','POST',json={'path':'bad'}).status_code,403)

    def test_image_formats(self):
        import io
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        self.login()
        first=Image.new('RGB',(16,12),'red')
        second=Image.new('RGB',(16,12),'blue')
        for name,fmt in [('animated.gif','GIF'),('animated.webp','WEBP'),('animated.apng','PNG')]:
            path=self.root/name
            first.save(path,format=fmt,save_all=True,append_images=[second],duration=200,loop=0)
            with self.call('/image?path='+name) as response:
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.data,path.read_bytes())
                with Image.open(io.BytesIO(response.data)) as im:
                    self.assertEqual(im.n_frames,2)
        for name,fmt in [('photo.tiff','TIFF'),('photo.heic','HEIF'),('photo.ico','ICO'),('photo.bmp','BMP'),('photo.tga','TGA')]:
            path=self.root/name
            first.resize((32,32)).save(path,format=fmt)
            original=path.read_bytes()
            with self.call('/image?path='+name+'&convert=1') as response:
                self.assertEqual(response.status_code,200,name)
                self.assertEqual(response.mimetype,'image/png')
                with Image.open(io.BytesIO(response.data)) as im:
                    self.assertEqual(im.size,(32,32))
            self.assertEqual(path.read_bytes(),original)
        (self.root/'bad.tiff').write_bytes(b'not an image')
        self.assertEqual(self.call('/image?path=bad.tiff').status_code,422)
        (self.root/'active.svg').write_text('<svg/>')
        self.assertEqual(self.call('/image?path=active.svg').status_code,404)
        self.assertEqual(self.call('/image?path=../outside.bmp').status_code,400)

    def test_recoverable_delete(self):
        self.login()
        self.call('/upload?path=keep.txt','PUT',data=b'recover me')
        self.call('/favorites','POST',json={'path':'keep.txt','favorite':True})
        self.assertEqual(self.call('/delete','POST',json={'path':'keep.txt'}).status_code,200)
        self.assertFalse((self.root/'keep.txt').exists())
        recovered=list((self.root/'.hotspot-trash').glob('*/keep.txt'))
        self.assertEqual(recovered[0].read_bytes(),b'recover me')
        self.assertEqual(self.call('/favorites').json,[])
        self.assertEqual(self.call('/delete','POST',json={'path':''}).status_code,400)
        self.assertEqual(self.call('/delete','POST',json={'path':'../outside'}).status_code,400)
        self.assertEqual(self.call('/list?path=.hotspot-trash').status_code,403)

    def test_remember_cookie(self):
        result=self.call('/login','POST',json={'password':'test-password-12345','remember':True})
        cookie=result.headers['Set-Cookie']
        for flag in ('Secure','HttpOnly','SameSite=Strict','Expires='):
            self.assertIn(flag,cookie)
        value=self.client.get_cookie('session',domain='192.168.137.1').value
        restarted=create_app(self.root,'192.168.137.0/24','test-password-12345').test_client()
        restarted.set_cookie('session',value,domain='192.168.137.1')
        self.assertEqual(restarted.get('/session',base_url='https://192.168.137.1:8443',environ_overrides={'REMOTE_ADDR':'192.168.137.2'}).status_code,200)
        changed=create_app(self.root,'192.168.137.0/24','changed-password-12345').test_client()
        changed.set_cookie('session',value,domain='192.168.137.1')
        self.assertEqual(changed.get('/session',base_url='https://192.168.137.1:8443',environ_overrides={'REMOTE_ADDR':'192.168.137.2'}).status_code,401)

    def test_full_resolution_raw_preview(self):
        import io,numpy as np,tifffile,png
        from PIL import Image
        self.login()
        tags=[(50706,'B',4,(1,4,0,0),False),(50707,'B',4,(1,1,0,0),False),(50708,'s',0,'Test Camera',False),(33421,'H',2,(2,2),False),(33422,'B',4,(0,1,1,2),False),(50710,'B',3,(0,1,2),False),(50711,'H',1,1,False),(50714,'H',1,0,False),(50717,'H',1,65535,False),(50721,'2i',9,(1,1,0,1,0,1,0,1,1,1,0,1,0,1,0,1,1,1),False),(50778,'H',1,21,False)]
        p=self.root/'sample.dng'
        tifffile.imwrite(p,np.full((64,64),10000,dtype=np.uint16),photometric=32803,metadata=None,extratags=tags)
        original=p.read_bytes()
        with self.call('/image?path=sample.dng') as response:
            self.assertEqual(response.status_code,200)
            width,height,rows,info=png.Reader(bytes=response.data).read()
            self.assertEqual((width,height,info['bitdepth']),(64,64,16))
        with self.call('/file?path=sample.dng&download=1') as response:
            self.assertEqual(response.data,original)
        Image.new('RGB',(4100,2),'red').save(self.root/'wide.tiff')
        with self.call('/image?path=wide.tiff') as response:
            with Image.open(io.BytesIO(response.data)) as image:
                self.assertEqual(image.size,(4100,2))
        import pillow_heif
        data=np.full((16,16,3),32768,dtype=np.uint16)
        pillow_heif.from_bytes('RGB;16',(16,16),data.tobytes()).save(self.root/'hdr.heic',quality=100,bit_depth=10)
        with self.call('/image?path=hdr.heic') as response:
            self.assertEqual(response.status_code,200)
            w,h,rows,info=png.Reader(bytes=response.data).read()
            self.assertEqual((w,h,info['bitdepth']),(16,16,16))

    def test_move_favorites(self):
        self.login()
        self.call('/mkdir','POST',json={'path':'books'})
        self.call('/upload?path=a.txt','PUT',data=b'original')
        self.assertEqual(self.call('/favorites','POST',json={'path':'a.txt','favorite':True}).status_code,200)
        self.assertEqual(self.call('/move','POST',json={'path':'a.txt','new':'books/a.txt'}).status_code,200)
        self.assertEqual(self.call('/favorites').json[0]['path'],'books/a.txt')
        self.assertEqual(self.call('/rename','POST',json={'path':'books','new':'novels'}).status_code,200)
        self.assertEqual(self.call('/favorites').json[0]['path'],'novels/a.txt')
        self.assertEqual(self.call('/move','POST',json={'path':'novels','new':'novels/child'}).status_code,409)
        self.assertEqual(self.call('/move','POST',json={'path':'novels/a.txt','new':'../escape'}).status_code,400)
        self.assertEqual(self.call('/file?path=.hotspot-favorites.json').status_code,403)
        self.assertEqual(self.call('/upload?path=.hotspot-favorites.json','PUT',data=b'bad').status_code,403)
        self.assertEqual(self.call('/upload?path=exists.txt','PUT',data=b'keep').status_code,200)
        self.assertEqual(self.call('/move','POST',json={'path':'novels/a.txt','new':'exists.txt'}).status_code,409)
        self.assertEqual((self.root/'exists.txt').read_bytes(),b'keep')

    def test_bruteforce(self):
        for _ in range(5):
            self.call('/login','POST',json={'password':'bad'})
        self.assertEqual(self.call('/login','POST',json={'password':'bad'}).status_code,429)

    def test_tls_server_prepare(self):
        import ssl
        from app import certificate
        from cheroot.wsgi import Server
        from cheroot.ssl.builtin import BuiltinSSLAdapter
        cert, key = certificate(self.root, '127.0.0.1')
        adapter = BuiltinSSLAdapter(str(cert),str(key))
        adapter.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        adapter.context.minimum_version = ssl.TLSVersion.TLSv1_2
        adapter.context.load_cert_chain(str(cert),str(key))
        server = Server(('127.0.0.1',0),self.app)
        server.ssl_adapter = adapter
        try:
            server.prepare()
            self.assertTrue(server.ready)
        finally:
            server.stop()

if __name__ == '__main__':
    unittest.main()
