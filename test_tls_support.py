import tempfile
import unittest
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from tls_support import prepare_apple_certificate


class TlsSupportTests(unittest.TestCase):
    def test_local_ca_chain_and_stable_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)
            public,fingerprint=prepare_apple_certificate(state)
            root=x509.load_pem_x509_certificate(public.read_bytes())
            server=x509.load_pem_x509_certificate((state/'server.crt').read_bytes())
            server.verify_directly_issued_by(root)
            self.assertTrue(root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
            self.assertFalse(server.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
            self.assertEqual(fingerprint,root.fingerprint(hashes.SHA256()).hex(':'))
            original=(state/'server.crt').read_bytes()
            prepare_apple_certificate(state)
            self.assertEqual((state/'server.crt').read_bytes(),original)

    def test_real_tls_parallel_requests_after_aborted_clients(self):
        import ssl,socket,threading,urllib.request
        from concurrent.futures import ThreadPoolExecutor
        from cheroot.wsgi import Server
        from cheroot.ssl.builtin import BuiltinSSLAdapter
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)
            public,_=prepare_apple_certificate(state)
            def application(environ,start_response):
                body=b'synthetic response'*2048
                start_response('200 OK',[('Content-Length',str(len(body)))])
                return [body]
            server=Server(('127.0.0.1',0),application,numthreads=24,request_queue_size=128,timeout=5)
            adapter=BuiltinSSLAdapter(str(state/'server.crt'),str(state/'server.key'))
            server.ssl_adapter=adapter
            server.prepare()
            port=server.socket.getsockname()[1]
            thread=threading.Thread(target=server.serve,daemon=True);thread.start()
            try:
                for _ in range(12):
                    socket.create_connection(('127.0.0.1',port),timeout=2).close()
                context=ssl.create_default_context(cafile=str(public))
                context.check_hostname=False  # Loopback fixture; production probes verify the IP SAN.
                def read(_):
                    with urllib.request.urlopen(f'https://127.0.0.1:{port}/',context=context,timeout=10) as response:
                        return len(response.read())
                with ThreadPoolExecutor(max_workers=16) as pool:
                    self.assertEqual(list(pool.map(read,range(48))),[len(b'synthetic response'*2048)]*48)
            finally:
                server.stop();thread.join(timeout=5)
