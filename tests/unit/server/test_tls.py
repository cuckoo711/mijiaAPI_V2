"""Self-signed TLS certificate generation."""

from __future__ import annotations

from pathlib import Path

from server.tls import cert_paths, ensure_self_signed_cert, tls_dir


def test_ensure_self_signed_cert_creates_pair(tmp_path: Path) -> None:
    cert_path, key_path = ensure_self_signed_cert(tmp_path)
    assert cert_path.is_file()
    assert key_path.is_file()
    assert cert_path == tmp_path / "tls" / "server.crt"
    assert key_path == tmp_path / "tls" / "server.key"
    assert tls_dir(tmp_path).is_dir()

    cert_pem = cert_path.read_bytes()
    key_pem = key_path.read_bytes()
    assert b"BEGIN CERTIFICATE" in cert_pem
    assert b"BEGIN RSA PRIVATE KEY" in key_pem or b"BEGIN PRIVATE KEY" in key_pem


def test_ensure_self_signed_cert_reuses_existing_pair(tmp_path: Path) -> None:
    first_cert, first_key = ensure_self_signed_cert(tmp_path)
    first_cert_bytes = first_cert.read_bytes()
    first_key_bytes = first_key.read_bytes()

    second_cert, second_key = ensure_self_signed_cert(tmp_path)
    assert second_cert == first_cert
    assert second_key == first_key
    assert second_cert.read_bytes() == first_cert_bytes
    assert second_key.read_bytes() == first_key_bytes


def test_ensure_self_signed_cert_includes_custom_hosts(tmp_path: Path) -> None:
    from cryptography import x509

    cert_path, _ = ensure_self_signed_cert(tmp_path, hosts=["localhost", "example.local", "10.0.0.5"])
    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    dns = san.value.get_values_for_type(x509.DNSName)
    ips = san.value.get_values_for_type(x509.IPAddress)
    assert "localhost" in dns
    assert "example.local" in dns
    assert any(str(ip) == "10.0.0.5" for ip in ips)


def test_cert_paths_match_layout(tmp_path: Path) -> None:
    cert_path, key_path = cert_paths(tmp_path)
    assert cert_path.name == "server.crt"
    assert key_path.name == "server.key"
    assert cert_path.parent == key_path.parent == tmp_path / "tls"
