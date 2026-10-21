"""Generate one local adapter's runtime inputs from its real Core registration.

No credentials are printed, and no Windows/system trust store is modified.
Run using the Node project's pinned Python environment.
"""
import argparse
import ipaddress
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)
    path.chmod(0o600)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--host-ip",required=True)
    parser.add_argument("--refresh-certs",action="store_true")
    args=parser.parse_args()
    host=ipaddress.IPv4Address(args.host_ip)
    if not host.is_private or host.is_loopback:
        raise ValueError("Dedicated private WSL host interface required")
    root=Path(__file__).resolve().parents[3]
    secrets=root/".local/briareus/secrets"
    setup=json.loads((secrets/"node-setup.json").read_text(encoding="utf-8"))
    if setup["endpoint"]!="https://127.0.0.2" or setup["runtime_uid"]!=2201 or setup["runtime_gid"]!=2201:
        raise ValueError("This local adapter requires its actual loopback/UID2201 registration")
    output=secrets/"node"
    output.mkdir(mode=0o700,exist_ok=True)
    marker=output/"installation.json"
    identity={"node_uuid":setup["node_record"]["id"],"registry_host":str(host)}
    if marker.exists():
        if json.loads(marker.read_text())!=identity:
            raise ValueError("Existing local installation differs; do not replace its identity")
    if not marker.exists() or args.refresh_certs:
        if not marker.exists() and list(output.iterdir()):
            raise ValueError("Refusing to overwrite unmarked local node credentials")
        key=(serialization.load_pem_private_key((output/"ca.key").read_bytes(),password=None)
            if marker.exists() else rsa.generate_private_key(public_exponent=65537,key_size=2048))
        name=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,"Briareus local node CA")])
        now=datetime.now(UTC)
        ca=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(
            x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365)).add_extension(
            x509.BasicConstraints(ca=True,path_length=0),True).add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False).add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False).add_extension(
            x509.KeyUsage(False,False,False,False,False,True,True,False,False),True).sign(key,hashes.SHA256())
        if not marker.exists():
            write_new(output/"ca.key",key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        (output/"ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        for service,names in {"node":[x509.IPAddress(ipaddress.ip_address("127.0.0.2"))],
            "registry":[x509.IPAddress(host),x509.IPAddress(ipaddress.ip_address("127.0.0.1")),x509.DNSName("localhost")]}.items():
            private=(serialization.load_pem_private_key((output/(service+".key")).read_bytes(),password=None)
                if marker.exists() else rsa.generate_private_key(public_exponent=65537,key_size=2048))
            subject=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,"Briareus local "+service)])
            cert=x509.CertificateBuilder().subject_name(subject).issuer_name(ca.subject).public_key(private.public_key()).serial_number(
                x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=90)).add_extension(
                x509.SubjectAlternativeName(names),False).add_extension(x509.BasicConstraints(ca=False,path_length=None),True).add_extension(
                x509.SubjectKeyIdentifier.from_public_key(private.public_key()),False).add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False).add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),False).sign(key,hashes.SHA256())
            if not marker.exists():
                write_new(output/(service+".key"),private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            (output/(service+".crt")).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        if not marker.exists():
            write_new(marker,json.dumps(identity).encode())
    values={"BRIAREUS_NODE_UUID":setup["node_record"]["id"],"BRIAREUS_NODE_RECORD":json.dumps(setup["node_record"],ensure_ascii=True),
        "BRIAREUS_CORE_VERIFY_KEY":setup["core_verify_key"],"BRIAREUS_GATEWAY_VERIFY_KEY":setup["gateway_verify_key"],
        "BRIAREUS_IMAGE_REGISTRIES":json.dumps([str(host)+":5500"]),"BRIAREUS_LOCAL_NODE_HOST_IP":str(host)}
    runtime=output/"runtime.env"
    if runtime.exists():
        print("Existing runtime inputs retained; trust stores unchanged.")
        return
    write_new(runtime,"".join(key+"="+json.dumps(value)+"\n" for key,value in values.items()).encode())
    print("Generated node TLS and runtime inputs; trust stores unchanged.")


if __name__=="__main__":
    main()
