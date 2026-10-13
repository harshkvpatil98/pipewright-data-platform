"""`scripts/check-oidc.py` against a provider on this machine (A6, W7).

The script exists to be pointed at a real identity provider, which this
machine does not have. This runs it against a small one served locally, so
the script itself is known to work: it reports a good setup as good, a wrong
client secret as wrong, and completes a sign-in from a pasted address.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check-oidc.py"
CLIENT_ID = "pipewright"
SECRET = "right-secret"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _load_script():
    spec = importlib.util.spec_from_file_location("check_oidc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def provider() -> Iterator[dict]:
    issued: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            base = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/.well-known/openid-configuration":
                self._json(200, {
                    "issuer": base, "authorization_endpoint": f"{base}/authorize",
                    "token_endpoint": f"{base}/token", "jwks_uri": f"{base}/jwks",
                    "code_challenge_methods_supported": ["S256"],
                    "id_token_signing_alg_values_supported": ["RS256"],
                })
            elif self.path == "/jwks":
                jwk = RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
                self._json(200, {"keys": [{**jwk, "kid": "k1", "alg": "RS256"}]})
            else:
                self._json(404, {})

        def do_POST(self) -> None:
            base = f"http://127.0.0.1:{self.server.server_port}"
            form = {key: values[0] for key, values in parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
            if form.get("client_secret") != SECRET:
                self._json(401, {"error": "invalid_client"})
            elif form.get("code") not in issued:
                self._json(400, {"error": "invalid_grant"})
            else:
                now = int(time.time())
                token = jwt.encode(
                    {"iss": base, "aud": CLIENT_ID, "sub": "u1", "iat": now, "exp": now + 300,
                     "nonce": issued[form["code"]], "email": "ann@example.com", "groups": ["data-admins"]},
                    KEY, algorithm="RS256", headers={"kid": "k1"},
                )
                self._json(200, {"id_token": token})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"issuer": f"http://127.0.0.1:{server.server_port}", "issued": issued}
    server.shutdown()


def _configure(monkeypatch, issuer: str, secret: str) -> None:
    from api_gateway.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_issuer", issuer)
    monkeypatch.setattr(settings, "oidc_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "oidc_client_secret", secret)
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://app.example.com/api/v1/auth/sso/callback")
    monkeypatch.setattr(settings, "oidc_group_role_map", '{"data-admins": "admin"}')


def test_a_good_setup_passes(provider, monkeypatch, capsys) -> None:
    _configure(monkeypatch, provider["issuer"], SECRET)
    monkeypatch.setattr("sys.argv", ["check-oidc.py"])
    assert _load_script().main() == 0
    output = capsys.readouterr().out
    assert "Client id and secret accepted" in output
    assert "Every check passed" in output


def test_a_wrong_secret_is_named(provider, monkeypatch, capsys) -> None:
    _configure(monkeypatch, provider["issuer"], "wrong-secret")
    monkeypatch.setattr("sys.argv", ["check-oidc.py"])
    assert _load_script().main() == 1
    assert "check OIDC_CLIENT_ID and OIDC_CLIENT_SECRET" in capsys.readouterr().out


def test_a_real_sign_in_completes_from_the_pasted_address(provider, monkeypatch, capsys) -> None:
    _configure(monkeypatch, provider["issuer"], SECRET)
    monkeypatch.setattr("sys.argv", ["check-oidc.py", "--sign-in"])

    def browser(_prompt: str) -> str:
        # What a person does: open the printed address, sign in, and paste
        # where the provider sent them back to.
        printed = capsys.readouterr().out
        address = next(line.strip() for line in printed.splitlines() if "/authorize?" in line)
        query = parse_qs(urlparse(address).query)
        provider["issued"]["the-code"] = query["nonce"][0]
        return f"https://app.example.com/api/v1/auth/sso/callback?code=the-code&state={query['state'][0]}"

    monkeypatch.setattr("builtins.input", browser)
    assert _load_script().main() == 0
    output = capsys.readouterr().out
    assert "ID token verified" in output
    assert "role admin" in output
