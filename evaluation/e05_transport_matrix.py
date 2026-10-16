"""Bounded, private E05 one-variable experiment. Never used as a product transport.

Local TLS echo first; --live sends only the two frozen public-source requests.
No redirects, proxy environment, auth bypass, retries or response body logging.
"""

import argparse
import hashlib
import http.client
import json
import os
import platform
import random
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import h2.config
import h2.connection
import h2.events
import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from proofops.adapters.local.http_diagnostics import RESPONSE_HEADERS, safe_header
from proofops.domain.provenance import canonical_hash

CASES = dict(
    H0=("stdlib", False, False, 4, {}),
    H1=("stdlib", False, False, 4, {"Accept": "application/json"}),
    H2=("stdlib", False, False, 4, {"User-Agent": "ProofOps-X7-diagnostic/1"}),
    H3=("httpx", False, False, 4, {}),
    H4=("httpx", True, False, 4, {}),
    H5=("httpx", False, True, 4, {}),
    H6=("stdlib", False, False, 1, {}),
)
RESERVE = Decimal(".007")  # 32768 input at highest .125 + 4096*.5, VAT1.10
CAP = Decimal(".5")
MAX_ATTEMPTS = 28


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def frozen_bodies(root):
    base = root / "outputs/agent-results/R108-redesign/lab"
    paths = [
        base
        / "perf/I6/C-trial/lgchem/extraction-receipts"
        / "43c73a08-0a0d-5274-b449-8c26e6629f75/request.json",
        base
        / "fix/F1/lg-measured/lgchem/tagging-receipts"
        / "98097783-6bf5-4d99-949a-fa956ad0a4c4/elements"
        / "76e70d7a-4602-563f-8165-c7f2bba8341e/request.json",
    ]
    bodies = []
    for i, path in enumerate(paths):
        saved = json.loads(path.read_text())
        system = saved["system_prompt"] if i == 0 else saved["wire_system"]
        user = saved["user_json"] if i == 0 else saved["wire_user_json"]
        max_tokens = saved["max_tokens"] if i == 0 else saved["request"]["max_tokens"]
        body = dict(
            model="gpt-6-luna",
            messages=[dict(role="system", content=system), dict(role="user", content=user)],
            max_completion_tokens=max_tokens,
            temperature=0,
            stream=False,
            reasoning_effort="none",
            store=False,
            service_tier="default",
            response_format=dict(type="json_object"),
            top_p=1,
        )
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        assert len(raw) <= 16384 and 0 < max_tokens <= 4096
        bodies.append(raw)
    # Exact F1 request remains unchanged; don't shrink the output or paraphrase its input.
    assert len(bodies[1]) == 14046
    assert canonical_hash(json.loads(bodies[1])) == (
        "16111bb567d255c673b13075a78af981b5ca6e70ab34f50379594f5613f9c685"
    )
    assert canonical_hash(json.loads(bodies[0])) == (
        "d27aa2a7b6be5c48d55672bb5df1d6abafd1611381096d0ac65e667a7586af9d"
    )
    return bodies


@contextmanager
def local_echo(*, response_status=200):
    """TLS1.2+ echo negotiates h1/h2; records only header names/settings and hashes."""
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256())
        )
        cert_path, key_path = directory / "cert.pem", directory / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)
        server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_tls.minimum_version = ssl.TLSVersion.TLSv1_2
        server_tls.load_cert_chain(cert_path, key_path)
        server_tls.set_alpn_protocols(["h2", "http/1.1"])

        class Echo(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def payload(self, raw, headers):
                return json.dumps(
                    dict(
                        wire_sha256=digest(raw),
                        request_bytes=len(raw),
                        header_names=sorted(headers),
                        header_settings={
                            n: headers[n]
                            for n in ("accept", "user-agent", "content-type", "accept-encoding")
                            if n in headers
                        },
                        authorization_sha256=digest(headers.get("authorization", "").encode()),
                        connection_id=self.connection_id,
                    )
                ).encode()

            def handle(self):
                self.connection_id = str(uuid4())
                if self.connection.selected_alpn_protocol() != "h2":
                    return super().handle()
                connection = h2.connection.H2Connection(
                    config=h2.config.H2Configuration(client_side=False, header_encoding="utf-8")
                )
                connection.initiate_connection()
                self.connection.sendall(connection.data_to_send())
                requests = {}
                while raw := self.connection.recv(65536):
                    for event in connection.receive_data(raw):
                        if isinstance(event, h2.events.RequestReceived):
                            requests[event.stream_id] = [dict(event.headers), bytearray()]
                        elif isinstance(event, h2.events.DataReceived):
                            requests[event.stream_id][1].extend(event.data)
                            connection.acknowledge_received_data(
                                event.flow_controlled_length, event.stream_id
                            )
                        elif isinstance(event, h2.events.StreamEnded):
                            headers, body = requests.pop(event.stream_id)
                            result = self.payload(
                                body, {n: v for n, v in headers.items() if not n.startswith(":")}
                            )
                            connection.send_headers(
                                event.stream_id,
                                [
                                    (":status", "200"),
                                    ("content-type", "application/json"),
                                    ("content-length", str(len(result))),
                                ],
                            )
                            connection.send_data(event.stream_id, result, end_stream=True)
                    self.connection.sendall(connection.data_to_send())

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                result = (
                    self.payload(raw, {n.lower(): v for n, v in self.headers.items()})
                    if response_status == 200
                    else b""
                )
                self.send_response(response_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(result)))
                self.send_header("CF-Ray", "local-echo-test")
                self.end_headers()
                self.wfile.write(result)

        server = ThreadingHTTPServer(("localhost", 0), Echo)
        server.socket = server_tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        context = ssl.create_default_context(cafile=str(cert_path))
        try:
            yield f"https://localhost:{server.server_port}/v1/chat/completions", context
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class Matrix:
    def __init__(
        self, output, bodies, *, live=False, key="local-echo-sentinel", url=None, verify=True
    ):
        self.output, self.bodies, self.live, self.key = output, bodies, live, key
        self.url = "https://api.openai.com/v1/chat/completions" if live else url
        self.verify = verify
        self.lock = threading.Lock()
        self.starts, self.next_start, self.denials, self.stopped = [], 0.0, 0, False
        self.reserved, self.calls = Decimal(0), []

    def client(self, http2=False):
        client = httpx.Client(
            http2=http2,
            verify=self.verify,
            trust_env=False,
            follow_redirects=False,
            timeout=45,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )
        client.headers.clear()
        return client

    def invoke(self, case, body_index, repeat, pool=None):
        engine, reuse, http2, rps, extra = CASES[case]
        body = self.bodies[body_index]
        reservation_id = str(uuid4())
        with self.lock:
            while time.monotonic() < self.next_start:
                time.sleep(min(0.02, self.next_start - time.monotonic()))
            if self.stopped or len(self.starts) >= MAX_ATTEMPTS or self.reserved + RESERVE > CAP:
                return
            started = time.monotonic()
            self.next_start = started + 1 / rps
            self.starts.append(started)
            self.reserved += RESERVE
            recent = dict(
                recent_requests_1s=sum(t > started - 1 for t in self.starts),
                recent_requests_60s=sum(t > started - 60 for t in self.starts),
            )
            record = dict(
                case=case,
                body_index=body_index,
                repeat=repeat,
                reservation_id=reservation_id,
                request_bytes=len(body),
                wire_sha256=digest(body),
                started_at=datetime.now(UTC).isoformat(),
                started_monotonic=started,
                engine=engine,
                rps=rps,
                workers=8,
                exposure_usd=str(RESERVE) if self.live else "0",
                accounting="pending" if self.live else "local_echo",
                **recent,
            )
            private_write(self.output / f"{reservation_id}.reservation.json", record)
        headers = {
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
            **extra,
        }
        # request ids differ legitimately across attempts, not part of the variable comparison.
        if self.live:
            headers["X-Client-Request-Id"] = reservation_id
        response, raw, client = None, None, None
        trace = {}

        def httpx_trace(name, info):
            if name.endswith("connect_tcp.started") or name.endswith("start_tls.started"):
                trace[name] = time.monotonic()
            elif name.endswith("connect_tcp.complete") or name.endswith("start_tls.complete"):
                trace[name] = time.monotonic()
            elif name.endswith("receive_response_headers.complete"):
                record["ttfb_ms"] = round((time.monotonic() - started) * 1000, 2)

        try:
            if engine == "stdlib":
                from urllib.parse import urlsplit

                target = urlsplit(self.url)
                context = self.verify if isinstance(self.verify, ssl.SSLContext) else None
                if context is not None:
                    context.set_alpn_protocols(["http/1.1"])
                client = http.client.HTTPSConnection(
                    target.hostname, target.port, timeout=45, context=context
                )
                connect_start = time.monotonic()
                client.connect()
                record["connect_tls_ms"] = round((time.monotonic() - connect_start) * 1000, 2)
                client.request("POST", target.path, body=body, headers=headers)
                response = client.getresponse()
                record["ttfb_ms"] = round((time.monotonic() - started) * 1000, 2)
                record.update(
                    http_status=response.status,
                    http_version={10: "HTTP/1.0", 11: "HTTP/1.1"}.get(response.version),
                    headers={
                        n: v
                        for n in RESPONSE_HEADERS
                        if (v := safe_header(response.getheader(n), self.key))
                    },
                )
                raw = response.read(1048577)
                record.update(
                    connection_new=True, connection_reused=False, connection_id=str(uuid4())
                )
            else:
                client = pool if reuse else self.client(http2)
                with client.stream(
                    "POST",
                    self.url,
                    content=body,
                    headers=headers,
                    extensions={"trace": httpx_trace},
                ) as response:
                    record.update(
                        http_status=response.status_code,
                        http_version=response.http_version,
                        headers={
                            n: v
                            for n in RESPONSE_HEADERS
                            if (v := safe_header(response.headers.get(n), self.key))
                        },
                    )
                    stream = response.extensions.get("network_stream")
                    record["connection_id"] = digest(str(id(stream)).encode())
                    raw = bytearray()
                    for chunk in response.iter_raw():
                        raw.extend(chunk[: 1048577 - len(raw)])
                        if len(raw) > 1048576:
                            break
                record["connection_new"] = any(n.endswith("connect_tcp.complete") for n in trace)
                record["connection_reused"] = not record["connection_new"]
                for stage, output in (("connect_tcp", "connect_ms"), ("start_tls", "tls_ms")):
                    a = next((v for n, v in trace.items() if n.endswith(stage + ".started")), None)
                    b = next((v for n, v in trace.items() if n.endswith(stage + ".complete")), None)
                    record[output] = round((b - a) * 1000, 2) if a and b else None
            record.update(
                response_body_bytes_read=len(raw),
                response_body_sha256=digest(raw),
                response_body_truncated=len(raw) > 1048576,
                request_header_names=sorted(headers),
                request_header_settings={k: v for k, v in extra.items()},
            )
            data = json.loads(raw) if len(raw) <= 1048576 and raw.startswith(b"{") else {}
            if not self.live:
                record["echo"] = data
                record.update(exposure_usd="0", accounting="local_echo")
            elif record["http_status"] == 200:
                usage = data.get("usage") or {}
                incoming, outgoing = usage.get("prompt_tokens"), usage.get("completion_tokens")
                if not (
                    type(incoming) is int
                    and type(outgoing) is int
                    and 0 <= incoming <= 32768
                    and 0 <= outgoing <= json.loads(body)["max_completion_tokens"]
                ):
                    raise ValueError("INVALID_USAGE")
                bound = (
                    (Decimal(incoming) * Decimal(".125") + Decimal(outgoing) * Decimal(".5"))
                    / 1000000
                    * Decimal("1.10")
                )
                assert bound <= RESERVE
                record.update(
                    exposure_usd=str(bound),
                    accounting="settled_upper_bound",
                    input_tokens=incoming,
                    output_tokens=outgoing,
                )
            with self.lock:
                self.denials = self.denials + 1 if record["http_status"] == 403 else 0
                error = data.get("error") or {}
                # A known access/policy rejection stops the matrix immediately.
                if (
                    self.denials >= 3
                    or record["http_status"] in (401, 429)
                    or (
                        isinstance(error, dict)
                        and error.get("code")
                        in {
                            "permission_denied",
                            "unsupported_country_region_territory",
                            "insufficient_quota",
                            "policy_violation",
                            "access_denied",
                        }
                    )
                    or (
                        record["http_status"] == 403
                        and isinstance(error, dict)
                        and error.get("type") == "invalid_request_error"
                    )
                ):
                    self.stopped = True
        except Exception as error:
            record["exception_type"] = type(error).__name__
            if self.live:
                with self.lock:
                    self.stopped = True  # no unbounded/uncertain follow-up
        finally:
            if client is not None and not reuse:
                client.close()
            record.update(
                finished_at=datetime.now(UTC).isoformat(),
                finished_monotonic=time.monotonic(),
                total_ms=round((time.monotonic() - started) * 1000, 2),
            )
            private_write(self.output / f"{reservation_id}.result.json", record)
            with self.lock:
                self.calls.append(record)

    def run(self):
        assert RESERVE * MAX_ATTEMPTS <= CAP
        private_write(
            self.output / "plan.json",
            dict(
                cap_usd=str(CAP),
                maximum_attempts=28,
                maximum_exposure_usd=str(RESERVE * 28),
                seed=105,
                runtime=dict(
                    python=platform.python_version(),
                    platform=platform.system(),
                    architecture=platform.machine(),
                    httpx=httpx.__version__,
                    h2=h2.__version__,
                ),
                live=self.live,
                body_hashes=[digest(b) for b in self.bodies],
                cases=CASES,
                retries=0,
                region="local-egress-not-c8g",
                price_source="https://developers.openai.com/api/docs/models/gpt-6-luna",
            ),
        )
        order = list(CASES)
        random.Random(105).shuffle(order)
        # Reversed second round produces A/B then B/A adjacent arm ordering.
        # Keep H4's bounded pool over both rounds, with no concurrent socket use.
        pool = self.client()
        try:
            for repeat, round_order in enumerate((order, list(reversed(order)))):
                for case in round_order:
                    with ThreadPoolExecutor(8) as executor:
                        list(
                            executor.map(
                                lambda i: self.invoke(
                                    case, i, repeat, pool if case == "H4" else None
                                ),
                                range(2),
                            )
                        )
                    if self.stopped:
                        break
                if self.stopped:
                    break
        finally:
            pool.close()
        result = dict(
            live=self.live,
            calls=self.calls,
            attempts=len(self.calls),
            exposure_usd=str(sum((Decimal(c["exposure_usd"]) for c in self.calls), Decimal(0))),
            stopped=self.stopped,
            root_cause="not_established",
        )
        private_write(self.output / "results.json", result)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    bodies = frozen_bodies(args.root)
    if args.live:
        key = next(
            line.split("=", 1)[1].strip().strip("\"'")
            for line in (args.root / ".env.openai.local").read_text().splitlines()
            if line.startswith("OPENAI_API_KEY=")
        )
        result = Matrix(args.output, bodies, live=True, key=key).run()
    else:
        with local_echo() as (url, context):
            result = Matrix(args.output, bodies, url=url, verify=context).run()
    print(json.dumps({k: v for k, v in result.items() if k != "calls"}))


if __name__ == "__main__":
    main()
