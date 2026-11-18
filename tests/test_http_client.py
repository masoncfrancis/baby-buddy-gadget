import unittest

import http_client


class FakeSocket:
    def __init__(self, incoming=b"", error=None):
        self.incoming = incoming
        self.error = error
        self.sent = bytearray()
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, address):
        self.address = address

    def send(self, data):
        self.sent.extend(data)
        return len(data)

    def recv(self, size):
        if self.error:
            raise self.error
        if not self.incoming:
            return b""
        chunk = self.incoming[:size]
        self.incoming = self.incoming[size:]
        return chunk

    def close(self):
        self.closed = True


class FakeSocketModule:
    SOCK_STREAM = 1

    def __init__(self, sock):
        self.sock = sock

    def getaddrinfo(self, host, port, family, socktype):
        return [(family, socktype, 0, "", (host, port))]

    def socket(self):
        return self.sock


class HttpClientTests(unittest.TestCase):
    def setUp(self):
        self.original_socket = http_client.socket

    def tearDown(self):
        http_client.socket = self.original_socket

    def test_url_parser_handles_host_port_query(self):
        self.assertEqual(
            http_client._parse_url("http://baby-buddy:8000/api/feedings/?x=1"),
            ("http", "baby-buddy", 8000, "/api/feedings/?x=1"),
        )

    def test_request_applies_timeout_and_reads_content_length(self):
        sock = FakeSocket(
            b"HTTP/1.0 201 Created\r\n"
            b"Content-Length: 2\r\n"
            b"X-Test: yes\r\n\r\n{}"
        )
        http_client.socket = FakeSocketModule(sock)

        response = http_client.post(
            "http://baby-buddy/api/feedings/",
            headers={"Content-Type": "application/json"},
            data="{}",
            timeout=6,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.text, "{}")
        self.assertEqual(response.headers["x-test"], "yes")
        self.assertEqual(sock.timeout, 6)
        self.assertIn(b"Content-Length: 2", sock.sent)
        response.close()
        self.assertTrue(sock.closed)

    def test_request_closes_socket_when_read_times_out(self):
        sock = FakeSocket(error=TimeoutError("read timed out"))
        http_client.socket = FakeSocketModule(sock)

        with self.assertRaises(TimeoutError):
            http_client.get("http://baby-buddy/api/", timeout=2)
        self.assertEqual(sock.timeout, 2)
        self.assertTrue(sock.closed)

    def test_chunked_response_decodes_body(self):
        self.assertEqual(
            http_client._decode_chunked(b"2\r\nOK\r\n0\r\n\r\n"), b"OK"
        )


if __name__ == "__main__":
    unittest.main()
