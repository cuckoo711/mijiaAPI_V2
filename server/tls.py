"""Self-signed TLS certificate management for local HTTPS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Iterable, Optional, Tuple

DEFAULT_CERT_NAME = "server.crt"
DEFAULT_KEY_NAME = "server.key"
DEFAULT_VALIDITY_DAYS = 3650
DEFAULT_HOSTS = ("localhost", "127.0.0.1", "::1")


def tls_dir(data_dir: Path) -> Path:
    """Return the directory that stores TLS material under ``data_dir``."""

    return Path(data_dir) / "tls"


def cert_paths(data_dir: Path) -> Tuple[Path, Path]:
    """Return ``(cert_path, key_path)`` for the local self-signed pair."""

    directory = tls_dir(data_dir)
    return directory / DEFAULT_CERT_NAME, directory / DEFAULT_KEY_NAME


def ensure_self_signed_cert(
    data_dir: Path,
    hosts: Optional[Iterable[str]] = None,
) -> Tuple[Path, Path]:
    """Generate a self-signed certificate when missing; return ``(cert, key)``.

    Existing files are kept so restarts reuse the same identity and clients
    that pinned the certificate do not break on every boot.
    """

    cert_path, key_path = cert_paths(data_dir)
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = tls_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mijia-api")])

    san_entries: list[x509.GeneralName] = []
    seen: set[str] = set()
    for raw in hosts if hosts is not None else DEFAULT_HOSTS:
        host = str(raw).strip()
        if not host or host in seen:
            continue
        seen.add(host)
        try:
            san_entries.append(x509.IPAddress(ip_address(host)))
        except ValueError:
            san_entries.append(x509.DNSName(host))

    if not san_entries:
        san_entries.append(x509.DNSName("localhost"))

    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=DEFAULT_VALIDITY_DAYS))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return cert_path, key_path
