"""Verified local health probes and an optional device-trusted local CA."""
import datetime
import http.client
import ipaddress
import ssl
from pathlib import Path


def check_service(base):
    state=Path(base)/'private-state'
    trust=state/'root-ca.crt'
    legacy=not trust.exists()
    if legacy:
        # The previous self-signed leaf is not an RFC-compliant CA. Pin its
        # exact public certificate instead of pretending that it is a CA.
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname=False
        context.verify_mode=ssl.CERT_NONE
    else:
        context=ssl.create_default_context(cafile=str(trust))
    connection=http.client.HTTPSConnection('192.168.137.1',8443,timeout=1,context=context)
    try:
        if legacy:
            import hashlib,hmac
            from cryptography import x509
            from cryptography.hazmat.primitives.serialization import Encoding
            expected=x509.load_pem_x509_certificate((state/'server.crt').read_bytes()).public_bytes(Encoding.DER)
            connection.connect()
            if not hmac.compare_digest(hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest(),hashlib.sha256(expected).digest()):
                raise ssl.SSLError('Local certificate pin mismatch')
        connection.request('HEAD','/')
        response=connection.getresponse()
        response.read()
        return response.status==200
    finally:
        connection.close()


def prepare_apple_certificate(state):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
    state=Path(state)
    state.mkdir(exist_ok=True)
    ca_file=state/'root-ca.crt'
    key_file=state/'root-ca.key'
    now=datetime.datetime.now(datetime.timezone.utc)
    if ca_file.exists() and key_file.exists():
        ca=x509.load_pem_x509_certificate(ca_file.read_bytes())
        ca_key=serialization.load_pem_private_key(key_file.read_bytes(),password=None)
    else:
        ca_key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Yingyu Private Hotspot CA')])
        ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5))
            .not_valid_after(now+datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=False,key_cert_sign=True,
                crl_sign=True,content_commitment=False,data_encipherment=False,key_agreement=False,
                encipher_only=False,decipher_only=False),critical=True).sign(ca_key,hashes.SHA256()))
        key_file.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    server_file=state/'server.crt'
    server_key=state/'server.key'
    if server_file.exists():
        current=x509.load_pem_x509_certificate(server_file.read_bytes())
        if current.issuer==ca.subject and current.not_valid_after_utc>now and server_key.exists():
            return ca_file,ca.fingerprint(hashes.SHA256()).hex(':')
        # Preserve the former public certificate. Private keys never leave private-state.
        (state/'previous-server.crt').write_bytes(server_file.read_bytes())
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Yingyu Hotspot Files')]))
        .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('192.168.137.1'))]),critical=False)
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,key_cert_sign=False,
            crl_sign=False,content_commitment=False,data_encipherment=False,key_agreement=False,
            encipher_only=False,decipher_only=False),critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
        .sign(ca_key,hashes.SHA256()))
    server_key.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    server_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    return ca_file,ca.fingerprint(hashes.SHA256()).hex(':')
