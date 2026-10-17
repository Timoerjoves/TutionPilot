"""Ed25519 digital signatures (RFC 8032), standard library only.

Follows the reference algorithm in RFC 8032 sections 5.1 and 6 (IETF Trust, Simplified BSD License for code
components) and is checked against the RFC's test vectors and against the browser's WebCrypto Ed25519
(tests/test_signing.py).

Fine for a sandbox demo. Not hardened: plain Python integers are not constant-time, so do not use this
for real keys; production would use a vetted library or a hardware key (see the security self-assessment).
"""
import hashlib
import os

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493  # order of the base point
D = -121665 * pow(121666, -1, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _sha512(b):
    return hashlib.sha512(b).digest()


def _add(p1, p2):  # extended twisted Edwards coordinates (X, Y, Z, T)
    a = (p1[1] - p1[0]) * (p2[1] - p2[0]) % P
    b = (p1[1] + p1[0]) * (p2[1] + p2[0]) % P
    c = 2 * p1[3] * p2[3] * D % P
    d = 2 * p1[2] * p2[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(p1, p2):
    return (p1[0] * p2[2] - p2[0] * p1[2]) % P == 0 and (p1[1] * p2[2] - p2[1] * p1[2]) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, -1, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * pow(5, -1, P) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _compress(pt):
    zinv = pow(pt[2], -1, P)
    x, y = pt[0] * zinv % P, pt[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(b):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(secret):
    if len(secret) != 32:
        raise ValueError("Ed25519 secret key must be 32 bytes")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def new_secret():
    return os.urandom(32)


def public_key(secret):
    a, _ = _expand(secret)
    return _compress(_mul(a, G))


def sign(secret, message):
    a, prefix = _expand(secret)
    pub = _compress(_mul(a, G))
    r = int.from_bytes(_sha512(prefix + message), "little") % L
    big_r = _compress(_mul(r, G))
    h = int.from_bytes(_sha512(big_r + pub + message), "little") % L
    return big_r + int.to_bytes((r + h * a) % L, 32, "little")


def verify(public, message, signature):
    """True only for a valid signature by this public key over exactly these bytes."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a_pt = _decompress(public)
    r_pt = _decompress(signature[:32])
    if a_pt is None or r_pt is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    h = int.from_bytes(_sha512(signature[:32] + public + message), "little") % L
    return _equal(_mul(s, G), _add(r_pt, _mul(h, a_pt)))
