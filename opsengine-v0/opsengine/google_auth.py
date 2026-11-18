"""Google Cloud access tokens for Vertex AI, standard library only.

Two ways to get a token, tried in this order:
1. A service account key file: GOOGLE_APPLICATION_CREDENTIALS points at the JSON key Google gives you.
   We sign a short JWT with the key (RS256) and swap it at Google's token endpoint for an access token.
2. The metadata server, when OpsEngine runs on Google Cloud (Compute Engine, Cloud Run, GKE) with a
   service account attached. No key file needed.

Tokens are cached until five minutes before they expire. The key file's private key never leaves this
process and is never logged. Scope: cloud-platform (what Vertex AI requires)."""
import base64
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

_lock = threading.Lock()
_cache = {}


class AuthError(Exception):
    """Why no token could be had, in plain words, without any secret in the message."""


def _http(method, url, headers=None, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------- minimal DER / PKCS#8 parsing for an RSA private key ----------------
def _der(data, i):
    tag = data[i]
    length = data[i + 1]
    i += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[i:i + n], "big")
        i += n
    return tag, data[i:i + length], i + length


def _seq(data):
    out, i = [], 0
    while i < len(data):
        tag, val, i = _der(data, i)
        out.append((tag, val))
    return out


def rsa_private_key(pem):
    """(n, e, d) from a PEM "PRIVATE KEY" (PKCS#8) or "RSA PRIVATE KEY" (PKCS#1)."""
    lines = [l.strip() for l in pem.strip().splitlines() if l.strip() and not l.startswith("-----")]
    der = base64.b64decode("".join(lines))
    tag, body, _ = _der(der, 0)
    items = _seq(body)
    if len(items) == 3 and items[2][0] == 0x04:  # PKCS#8 wraps the PKCS#1 key in an OCTET STRING
        _, body, _ = _der(items[2][1], 0)
        items = _seq(body)
    ints = [int.from_bytes(v, "big") for t, v in items if t == 0x02]
    if len(ints) < 4:
        raise AuthError("the service account key isn't an RSA private key")
    return ints[1], ints[2], ints[3]


def rs256(message, key):
    """RSASSA-PKCS1-v1_5 signature with SHA-256."""
    n, e, d = key
    k = (n.bit_length() + 7) // 8
    t = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def signed_jwt(info, now=None):
    now = int(now or time.time())
    head = {"alg": "RS256", "typ": "JWT", "kid": info.get("private_key_id", "")}
    claims = {"iss": info["client_email"], "scope": SCOPE, "aud": info.get("token_uri", DEFAULT_TOKEN_URI),
              "iat": now, "exp": now + 3600}
    signing_input = _b64(json.dumps(head).encode()) + b"." + _b64(json.dumps(claims).encode())
    return (signing_input + b"." + _b64(rs256(signing_input, rsa_private_key(info["private_key"])))).decode()


# ---------------- tokens ----------------
def _from_key_file(path, http):
    try:
        info = json.loads(open(path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        raise AuthError("GOOGLE_APPLICATION_CREDENTIALS doesn't point at a readable service account key file")
    if info.get("type") != "service_account" or not info.get("private_key") or not info.get("client_email"):
        raise AuthError("the credentials file isn't a service account key (type service_account)")
    data = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": signed_jwt(info)}).encode()
    try:
        out = http("POST", info.get("token_uri", DEFAULT_TOKEN_URI),
                   {"Content-Type": "application/x-www-form-urlencoded"}, data)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AuthError(f"Google refused the service account sign-in ({type(exc).__name__})")
    return out["access_token"], int(out.get("expires_in", 3600))


def _from_metadata(http):
    try:
        out = http("GET", METADATA_URL, {"Metadata-Flavor": "Google"}, None)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise AuthError("no service account key file is set and this machine isn't on Google Cloud")
    return out["access_token"], int(out.get("expires_in", 3600))


def access_token(http=None):
    """A valid Google access token, cached. Raises AuthError (no secrets in the message)."""
    http = http or _http
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    key = path or "metadata"
    with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > time.time() + 300:
            return cached[0]
        token, ttl = _from_key_file(path, http) if path else _from_metadata(http)
        _cache[key] = (token, time.time() + ttl)
        return token


def clear_cache():
    with _lock:
        _cache.clear()
