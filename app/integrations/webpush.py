"""Web Push (RFC 8030) with message encryption (RFC 8291, aes128gcm) and
VAPID (RFC 8292), written on the `cryptography` library.

The server's VAPID key pair is created on first use and kept in the
integrations table, so there's nothing to configure.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_SIZE = 4096


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _pub_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ── keys ─────────────────────────────────────────────────────────────────
def keys(conn) -> tuple[ec.EllipticCurvePrivateKey, str]:
    """(private key, public key as base64url) for VAPID; created once."""
    r = conn.execute("select access_token, extra from integrations where provider = 'vapid'").fetchone()
    if r and r["access_token"]:
        priv = ec.derive_private_key(int.from_bytes(unb64u(r["access_token"]), "big"), ec.SECP256R1())
        return priv, r["extra"]["public_key"]
    priv = ec.generate_private_key(ec.SECP256R1())
    d = priv.private_numbers().private_value.to_bytes(32, "big")
    pub = b64u(_pub_bytes(priv.public_key()))
    conn.execute("""insert into integrations (provider, access_token, extra) values ('vapid', %s, %s::jsonb)
                    on conflict (provider) do nothing""", (b64u(d), json.dumps({"public_key": pub})))
    conn.commit()
    return keys(conn)


def vapid_auth(priv: ec.EllipticCurvePrivateKey, public_key: str, endpoint: str, contact: str) -> str:
    u = urlparse(endpoint)
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                              "sub": contact}).encode())
    der = priv.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{claims}.{sig}, k={public_key}"


# ── encryption (RFC 8291) ────────────────────────────────────────────────
def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    ua_pub_bytes = unb64u(p256dh)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_bytes)
    as_priv = server_key or ec.generate_private_key(ec.SECP256R1())
    as_pub_bytes = _pub_bytes(as_priv.public_key())
    shared = as_priv.exchange(ec.ECDH(), ua_pub)
    ikm = _hkdf(unb64u(auth), shared, b"WebPush: info\x00" + ua_pub_bytes + as_pub_bytes, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)       # \x02: last (only) record
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_pub_bytes)) + as_pub_bytes + body


class Gone(Exception):
    """The subscription no longer exists (phone uninstalled, permission revoked)."""


def send(conn, subscription: dict, message: dict, contact: str, ttl: int = 12 * 3600) -> int:
    priv, pub = keys(conn)
    endpoint = subscription["endpoint"]
    data = encrypt(json.dumps(message).encode(), subscription["keys"]["p256dh"], subscription["keys"]["auth"])
    r = httpx.post(endpoint, content=data, timeout=20, headers={
        "Authorization": vapid_auth(priv, pub, endpoint, contact), "TTL": str(ttl),
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "Urgency": "normal"})
    if r.status_code in (404, 410):
        raise Gone(r.status_code)
    if r.status_code >= 400:
        raise RuntimeError(f"push service said {r.status_code}: {r.text[:200]}")
    return r.status_code
