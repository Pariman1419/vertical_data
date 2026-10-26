"""HTTPS loopback-only spike launcher. No request/credential logging."""
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import getpass
import hashlib
import ipaddress
import json
import secrets
import ssl
import tempfile
import webbrowser
import os
from backend.spike.service import Service, APIError
from backend.spike.catalog_store import CatalogStore
from backend.spike.target_store import SQLiteTargetStore

ROOT = Path(__file__).resolve().parents[2]


def tls_context(passphrase, *, temp_dir=None):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "U-ETL local read-only spike")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .sign(key, hashes.SHA256()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Private key is encrypted on disk, temporary and outside the static root.
    if temp_dir is None:
        with tempfile.TemporaryDirectory(prefix="utl-etl-tls-") as directory_path:
            cert_path, key_path = Path(directory_path)/"cert.pem", Path(directory_path)/"key.pem"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.BestAvailableEncryption(passphrase.encode())))
            context.load_cert_chain(cert_path, key_path, password=passphrase)
    else:
        directory_path = Path(temp_dir)
        directory_path.mkdir(parents=True, exist_ok=True)
        cert_path, key_path = directory_path/"integration-cert.pem", directory_path/"integration-key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.BestAvailableEncryption(passphrase.encode())))
        context.load_cert_chain(cert_path, key_path, password=passphrase)
        cert_path.unlink(missing_ok=True)
        key_path.unlink(missing_ok=True)
    return context, cert.fingerprint(hashes.SHA256()).hex()


def handler_for(service, origin):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, status, data, cookie=None, mime="application/json; charset=utf-8"):
            payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            # The accepted app shell uses inline onclick/onsubmit attributes throughout its original UI.
            # Keep scripts same-origin and enable inline handlers only for this loopback-only local shell.
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
            if cookie: self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(payload)

        def guard_host(self):
            if self.headers.get("Host") != origin.split("//", 1)[1]:
                raise APIError(403, "Invalid local host")
            if self.client_address[0] != "127.0.0.1":
                raise APIError(403, "Local requests only")

        def token(self):
            cookie = SimpleCookie()
            try: cookie.load(self.headers.get("Cookie", ""))
            except Exception: raise APIError(401, "Application login required") from None
            return cookie["utl_session"].value if "utl_session" in cookie else ""

        def do_GET(self):
            try:
                self.guard_host()
                static_files = {"/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css",
                                "/ui-reference-theme.css": "ui-reference-theme.css",
                                "/assets/utac-logo-source.png": "assets/utac-logo-source.png",
                                "/app.js": "app.js", "/demo-sync.js": "demo-sync.js", "/sync-ui.js": "sync-ui.js",
                                "/dataset-workflow.js": "dataset-workflow.js",
                                "/prototype.js": "prototype.js", "/real-source-ui.js": "real-source-ui.js"}
                if self.path in static_files:
                    path = ROOT / static_files[self.path]
                    mime = "text/html; charset=utf-8" if path.suffix == ".html" else "text/javascript; charset=utf-8" if path.suffix == ".js" else "text/css; charset=utf-8" if path.suffix == ".css" else "image/png" if path.suffix == ".png" else "application/octet-stream"
                    return self.reply(200, path.read_bytes(), mime=mime)
                if self.path == "/api/session":
                    state = service.session(self.token())
                    return self.reply(200, {"csrf": state["csrf"], "discovery_scope": "all_granted_catalog", "profiles": service.profile_statuses(self.token())})
                if self.path == "/api/local-target/status":
                    return self.reply(200, service.local_target_status(self.token()))
                parsed = urlsplit(self.path)
                if parsed.path == "/api/local-target/preview":
                    query = parse_qs(parsed.query)
                    try:
                        profile_id = query["profile_id"][0]
                        schema = query["schema"][0]
                        object_name = query["object"][0]
                        limit_text = query.get("limit", ["100"])[0]
                        if not limit_text.isdigit(): raise ValueError
                        limit = int(limit_text)
                    except (KeyError, ValueError):
                        raise APIError(400, "Invalid preview request") from None
                    return self.reply(200, service.local_target_preview(
                        self.token(), profile_id, schema, object_name, limit))
                if parsed.path == "/api/catalog/cache":
                    query = parse_qs(parsed.query)
                    profile_id = query.get("profile_id", [None])[0]
                    return self.reply(200, service.catalog_cache(self.token(), profile_id))
                if parsed.path.startswith("/api/jobs/"):
                    return self.reply(200, service.job(self.token(), parsed.path.split("/")[-1]))
                raise APIError(404, "Not found")
            except APIError as exc: self.reply(exc.status, {"error": exc.message})
            except Exception: self.reply(500, {"error": "Local runtime error"})

        def do_POST(self):
            try:
                self.guard_host()
                if self.headers.get("Origin") != origin:
                    raise APIError(403, "Same-origin request required")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise APIError(415, "JSON required")
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 16384: raise APIError(413, "Request size invalid")
                data = json.loads(self.rfile.read(length))
                if self.path == "/api/login":
                    if not isinstance(data, dict) or set(data) != {"passphrase"}: raise APIError(400, "Invalid login request")
                    token, csrf = service.login(data["passphrase"])
                    return self.reply(200, {"csrf": csrf}, f"utl_session={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=1800")
                state = service.session(self.token())
                if not secrets.compare_digest(self.headers.get("X-CSRF", ""), state["csrf"]):
                    raise APIError(403, "CSRF validation failed")
                if self.path == "/api/logout":
                    service.logout(self.token())
                    return self.reply(200, {"credential_state": "credentials_required"}, "utl_session=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0")
                if self.path == "/api/profile/connect":
                    if not isinstance(data, dict) or set(data) != {"profile_id"}: raise APIError(400, "Invalid profile action")
                    return self.reply(200, service.connect_profile(self.token(), data["profile_id"]))
                if self.path == "/api/profile/disconnect":
                    if not isinstance(data, dict) or set(data) != {"profile_id"}: raise APIError(400, "Invalid profile action")
                    return self.reply(200, service.disconnect_profile(self.token(), data["profile_id"]))
                if self.path.startswith("/api/"):
                    return self.reply(202, service.submit(self.token(), self.path[5:], data))
                raise APIError(404, "Not found")
            except APIError as exc: self.reply(exc.status, {"error": exc.message})
            except (ValueError, TypeError, KeyError): self.reply(400, {"error": "Invalid request"})
            except Exception: self.reply(500, {"error": "Local runtime error"})
    return Handler


def main():
    password = getpass.getpass("Set local application passphrase (12+ characters, NOT your DB password): ")
    if len(password) < 12: raise SystemExit("Passphrase too short; no server started")
    context, fingerprint = tls_context(password)
    local_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    catalog_path = local_data / "UTAC" / "U-ETL Factory Data Bridge" / "oracle-catalog.sqlite3"
    target_path = local_data / "UTAC" / "U-ETL Factory Data Bridge" / "local-warehouse.sqlite3"
    service = Service(password, catalog_store=CatalogStore(catalog_path), target_store=SQLiteTargetStore(target_path))
    del password
    server = ThreadingHTTPServer(("127.0.0.1", 8443), handler_for(service, "https://localhost:8443"))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print("U-ETL Factory Data Bridge (same application UI, secure local mode): https://localhost:8443")
    print("Local self-signed certificate SHA256:", fingerprint)
    print("Verify this certificate on this machine only; no global certificate bypass. HTTP port 5173 remains Demo-only.")
    try:
        webbrowser.open_new_tab("https://localhost:8443/")
    except webbrowser.Error:
        print("Could not open a browser automatically; open https://localhost:8443/ manually.")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__": main()
