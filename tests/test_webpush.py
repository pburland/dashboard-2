"""Web push encryption round trip: decrypt the way a browser does (RFC 8291)."""
import base64
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.integrations import webpush as wp


def _hkdf(salt, ikm, info, n):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]


def test_encrypt_round_trip():
    ua = ec.generate_private_key(ec.SECP256R1())
    ua_pub = wp._pub_bytes(ua.public_key())
    auth = os.urandom(16)
    blob = wp.encrypt(b'{"title":"Easy run"}', wp.b64u(ua_pub), wp.b64u(auth))
    salt, rs, idlen = blob[:16], struct.unpack("!I", blob[16:20])[0], blob[20]
    as_pub = blob[21:21 + idlen]
    assert rs == 4096 and idlen == 65
    shared = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, blob[21 + idlen:], None)
    assert plain == b'{"title":"Easy run"}\x02'


def test_vapid_header_is_a_valid_es256_jwt():
    import json
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = wp.b64u(wp._pub_bytes(priv.public_key()))
    h = wp.vapid_auth(priv, pub, "https://web.push.apple.com/abc", "https://example.up.railway.app")
    token = h.split("t=")[1].split(",")[0]
    head, claims, sig = token.split(".")
    assert json.loads(wp.unb64u(claims))["aud"] == "https://web.push.apple.com"
    raw = wp.unb64u(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    priv.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))   # raises if bad
    assert h.endswith(f"k={pub}")
