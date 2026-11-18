"""Small bounded HTTP/1.0 client for MicroPython and host-side tests.

Socket connect/read operations use per-socket timeouts. DNS lookup uses
getaddrinfo and cannot be bounded portably on the RP2 MicroPython port; use a
stable LAN IPv4 address in BABY_BUDDY_BASE_URL to avoid that dependency.
"""

try:
    import usocket as socket
except ImportError:
    import socket


MAX_RESPONSE_BYTES = 32768


class Response:
    def __init__(self, status_code, headers, body, sock):
        self.status_code = status_code
        self.headers = headers
        self.text = body.decode("utf-8")
        self._sock = sock

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None


def _parse_url(url):
    scheme_end = url.find("://")
    if scheme_end < 0:
        raise ValueError("URL must include http:// or https://")
    scheme = url[:scheme_end].lower()
    if scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS URLs are supported")

    remainder = url[scheme_end + 3 :]
    slash = remainder.find("/")
    query = remainder.find("?")
    separators = [pos for pos in (slash, query) if pos >= 0]
    split_at = min(separators) if separators else len(remainder)
    authority = remainder[:split_at]
    target = remainder[split_at:] if split_at < len(remainder) else "/"
    if target.startswith("?"):
        target = "/" + target
    if not authority or "@" in authority:
        raise ValueError("URL must include a host and must not include credentials")

    if ":" in authority:
        host, port_text = authority.rsplit(":", 1)
        port = int(port_text)
    else:
        host = authority
        port = 443 if scheme == "https" else 80
    if not host or not (1 <= port <= 65535):
        raise ValueError("Invalid URL host or port")
    return scheme, host, port, target


def _send_all(sock, data):
    offset = 0
    while offset < len(data):
        sent = sock.send(data[offset:])
        if sent is None or sent <= 0:
            raise OSError("socket send failed")
        offset += sent


def _decode_chunked(body):
    decoded = bytearray()
    offset = 0
    while True:
        line_end = body.find(b"\r\n", offset)
        if line_end < 0:
            raise ValueError("Malformed chunked response")
        size_text = body[offset:line_end].split(b";", 1)[0]
        size = int(size_text, 16)
        offset = line_end + 2
        if size == 0:
            return bytes(decoded)
        end = offset + size
        if end + 2 > len(body) or body[end : end + 2] != b"\r\n":
            raise ValueError("Incomplete chunked response")
        decoded.extend(body[offset:end])
        offset = end + 2


def _parse_response(raw):
    split_at = raw.find(b"\r\n\r\n")
    if split_at < 0:
        raise ValueError("Malformed HTTP response headers")

    lines = raw[:split_at].split(b"\r\n")
    status_parts = lines[0].split(None, 2)
    if len(status_parts) < 2:
        raise ValueError("Malformed HTTP status line")
    status_code = int(status_parts[1])

    headers = {}
    for line in lines[1:]:
        if b":" in line:
            name, value = line.split(b":", 1)
            headers[name.decode("ascii").strip().lower()] = (
                value.decode("ascii").strip()
            )

    body = bytes(raw[split_at + 4 :])
    if headers.get("transfer-encoding", "").lower() == "chunked":
        body = _decode_chunked(body)
    elif "content-length" in headers:
        body = body[: int(headers["content-length"])]
    return status_code, headers, body


def request(method, url, headers=None, body=None, timeout=5):
    """Send one HTTP request; raise on timeout, malformed response, or I/O error."""
    scheme, host, port, target = _parse_url(url)
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket()
    try:
        sock.settimeout(timeout)
        sock.connect(addr)
        if scheme == "https":
            try:
                import ussl
            except ImportError:
                import ssl as ussl
            sock = ussl.wrap_socket(sock, server_hostname=host)

        request_headers = {}
        for key, value in (headers or {}).items():
            key = str(key)
            value = str(value)
            request_headers[key] = value
        default_port = 443 if scheme == "https" else 80
        request_headers.setdefault(
            "Host", host if port == default_port else "%s:%d" % (host, port)
        )
        request_headers.setdefault("Connection", "close")
        request_headers.setdefault("Accept-Encoding", "identity")
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        if body_bytes is not None:
            request_headers.setdefault("Content-Length", str(len(body_bytes)))

        lines = ["%s %s HTTP/1.0" % (method, target)]
        for key, value in request_headers.items():
            if "\r" in key or "\n" in key or "\r" in value or "\n" in value:
                raise ValueError("Invalid HTTP header")
            lines.append("%s: %s" % (key, value))
        payload = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
        if body_bytes is not None:
            payload += body_bytes
        _send_all(sock, payload)

        received = bytearray()
        while len(received) <= MAX_RESPONSE_BYTES:
            chunk = sock.recv(512)
            if not chunk:
                break
            received.extend(chunk)
            split_at = received.find(b"\r\n\r\n")
            if split_at >= 0:
                header_lines = received[:split_at].split(b"\r\n")
                content_length = None
                chunked = False
                for line in header_lines[1:]:
                    name, separator, value = line.partition(b":")
                    if not separator:
                        continue
                    if name.lower() == b"content-length":
                        content_length = int(value.strip())
                    elif name.lower() == b"transfer-encoding":
                        chunked = b"chunked" in value.lower()
                body_length = len(received) - split_at - 4
                if content_length is not None and content_length > MAX_RESPONSE_BYTES:
                    raise ValueError("HTTP response exceeded size limit")
                if method.upper() == "HEAD":
                    break
                if content_length is not None and body_length >= content_length:
                    break
                if content_length is None and not chunked:
                    # No length means response is delimited by connection close.
                    continue
        if len(received) > MAX_RESPONSE_BYTES:
            raise ValueError("HTTP response exceeded size limit")
        status, response_headers, response_body = _parse_response(received)
        return Response(status, response_headers, response_body, sock)
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


def get(url, headers=None, timeout=5):
    return request("GET", url, headers=headers, timeout=timeout)


def post(url, headers=None, data=None, timeout=6):
    return request("POST", url, headers=headers, body=data, timeout=timeout)
