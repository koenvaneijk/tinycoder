import unittest
from unittest.mock import patch, MagicMock, call
import http.client
import socket
import ssl
import gzip
import json as json_

# Assuming tinycoder is importable (e.g., added to PYTHONPATH or installed)
import tinycoder.requests as requests


class MockHTTPResponse:
    def __init__(
        self, status=200, reason="OK", headers=None, body=b"", url="http://test.com"
    ):
        self.status = status
        self.reason = reason
        self.headers = http.client.HTTPMessage()
        if headers:
            for k, v in headers.items():
                self.headers.add_header(k, v)
        self._body = body
        self._read_calls = 0
        self.url = url  # Add url attribute

    def read(self, amt=None):
        self._read_calls += 1
        if self._read_calls > 1 and amt is None:  # Simulate reading till EOF
            return b""
        if amt is None:
            return self._body
        else:
            # Simulate reading in chunks (basic)
            start = (self._read_calls - 1) * amt
            end = start + amt
            return self._body[start:end]

    def getheaders(self):
        # http.client.HTTPResponse.headers is the HTTPMessage object itself
        return self.headers.items()

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Helper to create a gzipped body
def create_gzip_body(data_bytes):
    return gzip.compress(data_bytes)


class TestRequests(unittest.TestCase):

    def setUp(self):
        # Ensure each test starts clean
        pass

    @patch("urllib.request.OpenerDirector.open")
    def test_get_success(self, mock_open):
        """Test a successful GET request."""
        expected_content = b'{"message": "success"}'
        mock_resp = MockHTTPResponse(
            status=200,
            reason="OK",
            headers={"Content-Type": "application/json"},
            body=expected_content,
        )
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/data")

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]
        self.assertEqual(req.get_full_url(), "http://test.com/data")
        self.assertEqual(req.method, "GET")
        self.assertIsNone(req.data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.url, "http://test.com/data")
        self.assertEqual(response.content, expected_content)
        self.assertEqual(response.text, '{"message": "success"}')
        self.assertEqual(response.json(), {"message": "success"})
        self.assertEqual(response.headers["Content-Type"], "application/json")
        response.raise_for_status()  # Should not raise

    @patch("urllib.request.OpenerDirector.open")
    def test_get_with_params(self, mock_open):
        """Test a GET request with query parameters."""
        mock_resp = MockHTTPResponse(status=200, body=b"Params received")
        mock_open.return_value = mock_resp

        response = requests.get(
            "http://test.com/search", params={"q": "test", "limit": 10}
        )

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]
        # Check if params are correctly encoded in the URL
        self.assertTrue(
            req.get_full_url() == "http://test.com/search?q=test&limit=10"
            or req.get_full_url()
            == "http://test.com/search?limit=10&q=test"  # Order independent
        )
        self.assertEqual(req.method, "GET")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Params received")

    @patch("urllib.request.OpenerDirector.open")
    def test_post_with_data(self, mock_open):
        """Test a POST request with form data."""
        mock_resp = MockHTTPResponse(status=201, reason="Created", body=b"Data posted")
        mock_open.return_value = mock_resp

        data = {"key": "value", "another": 123}
        response = requests.post("http://test.com/resource", data=data)

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]
        self.assertEqual(req.get_full_url(), "http://test.com/resource")
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.data, b"key=value&another=123")
        self.assertEqual(
            req.headers["Content-type"], "application/x-www-form-urlencoded"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.reason, "Created")
        self.assertEqual(response.content, b"Data posted")

    @patch("urllib.request.OpenerDirector.open")
    def test_post_with_json(self, mock_open):
        """Test a POST request with JSON data."""
        mock_resp = MockHTTPResponse(
            status=200,
            body=b'{"result": "ok"}',
            headers={"Content-Type": "application/json"},
        )
        mock_open.return_value = mock_resp

        payload = {"name": "test", "items": [1, 2, 3]}
        response = requests.post("http://test.com/api", json=payload)

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]
        self.assertEqual(req.get_full_url(), "http://test.com/api")
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.data, json_.dumps(payload).encode("utf-8"))
        self.assertEqual(req.headers["Content-type"], "application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"result": "ok"})

    @patch("urllib.request.OpenerDirector.open")
    def test_put_request(self, mock_open):
        """Test a PUT request."""
        mock_resp = MockHTTPResponse(status=200, body=b"Resource updated")
        mock_open.return_value = mock_resp

        data = b"raw data"
        response = requests.put("http://test.com/resource/1", data=data)

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]
        self.assertEqual(req.get_full_url(), "http://test.com/resource/1")
        self.assertEqual(req.method, "PUT")
        self.assertEqual(req.data, data)
        # Default content-type not set by default for raw bytes/str unless specified

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Resource updated")

    @patch("urllib.request.OpenerDirector.open")
    def test_options_request(self, mock_open):
        """Test an OPTIONS request."""
        mock_resp = MockHTTPResponse(
            status=200, headers={"Allow": "GET, POST, HEAD, OPTIONS"}
        )
        mock_open.return_value = mock_resp

        response = requests.options("http://test.com/resource")

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]
        self.assertEqual(req.get_full_url(), "http://test.com/resource")
        self.assertEqual(req.method, "OPTIONS")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Allow"], "GET, POST, HEAD, OPTIONS")

    @patch("urllib.request.OpenerDirector.open")
    def test_timeout(self, mock_open):
        """Test request timeout."""
        # Simulate timeout by raising socket.timeout from opener.open
        mock_open.side_effect = socket.timeout("Request timed out")

        with self.assertRaises(requests.Timeout) as cm:
            requests.get("http://test.com/slow", timeout=0.1)
        self.assertTrue("Request timed out" in str(cm.exception))

    @patch("urllib.request.OpenerDirector.open")
    def test_connection_error(self, mock_open):
        """Test connection error."""
        # Simulate connection error by raising URLError
        mock_open.side_effect = requests.urllib.error.URLError("Connection refused")

        with self.assertRaises(requests.ConnectionError) as cm:
            requests.get("http://nonexistent.domain/data")
        self.assertTrue("Connection error: Connection refused" in str(cm.exception))

    @patch("urllib.request.build_opener")
    def test_no_redirects(self, mock_build_opener):
        """Test allow_redirects=False."""
        # Mock the opener and its open method
        mock_opener = MagicMock()
        mock_resp = MockHTTPResponse(
            status=302, reason="Found", headers={"Location": "/new/location"}
        )
        mock_opener.open.return_value = mock_resp
        mock_build_opener.return_value = mock_opener

        response = requests.get("http://test.com/redirect", allow_redirects=False)

        mock_build_opener.assert_called_once()
        # Check if NoRedirection handler was added (difficult to assert directly, check behavior)
        # We expect the 302 response directly
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/new/location")

        # Verify the opener was used
        mock_opener.open.assert_called_once()

    @patch("urllib.request.OpenerDirector.open")
    def test_gzip_decompression(self, mock_open):
        """Test automatic gzip decompression."""
        original_content = b'{"data": "this was compressed"}'
        gzipped_content = create_gzip_body(original_content)
        mock_resp = MockHTTPResponse(
            status=200,
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            body=gzipped_content,
        )
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/gzipped")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Encoding"], "gzip")
        self.assertEqual(response.content, original_content)  # Should be decompressed
        self.assertEqual(response.text, original_content.decode("utf-8"))
        self.assertEqual(response.json(), {"data": "this was compressed"})

    @patch("urllib.request.OpenerDirector.open")
    def test_bad_gzip_decompression(self, mock_open):
        """Test handling of bad gzip data."""
        bad_gzipped_content = b"this is not gzip data"
        mock_resp = MockHTTPResponse(
            status=200, headers={"Content-Encoding": "gzip"}, body=bad_gzipped_content
        )
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/badgzip")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Encoding"], "gzip")
        # Should fallback to raw content on decompression error
        self.assertEqual(response.content, bad_gzipped_content)

    @patch("urllib.request.OpenerDirector.open")
    def test_stream_iter_content_bytes(self, mock_open):
        """Test iter_content with stream=True (bytes)."""
        content = b"chunk1chunk2chunk3"
        mock_resp = MockHTTPResponse(status=200, body=content)
        # Need to mock read to simulate streaming chunk reads
        mock_resp.read = MagicMock(
            side_effect=[content[0:6], content[6:12], content[12:18], b""]
        )
        mock_resp.close = MagicMock()
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/stream", stream=True)

        self.assertFalse(response._content_consumed)  # Not consumed yet
        self.assertIsNotNone(response._stream)

        chunks = list(response.iter_content(chunk_size=6))

        self.assertEqual(chunks, [b"chunk1", b"chunk2", b"chunk3"])
        self.assertTrue(response._content_consumed)  # Consumed after iteration
        mock_resp.close.assert_called_once()  # Stream should be closed after iteration

    @patch("urllib.request.OpenerDirector.open")
    def test_stream_iter_content_unicode(self, mock_open):
        """Test iter_content with stream=True (unicode)."""
        content = "line1\nline2".encode("utf-8")
        mock_resp = MockHTTPResponse(
            status=200,
            body=content,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        mock_resp.read = MagicMock(side_effect=[content[0:6], content[6:], b""])
        mock_resp.close = MagicMock()
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/stream_text", stream=True)

        chunks = list(response.iter_content(chunk_size=6, decode_unicode=True))

        self.assertEqual(chunks, ["line1\n", "line2"])
        self.assertEqual(response.encoding, "utf-8")
        self.assertTrue(response._content_consumed)
        mock_resp.close.assert_called_once()

    @patch("urllib.request.OpenerDirector.open")
    def test_stream_iter_lines(self, mock_open):
        """Test iter_lines with stream=True."""
        content = b"line1\nline2\nline3 incomplete"
        mock_resp = MockHTTPResponse(status=200, body=content)
        # Simulate reading chunks that might split lines
        mock_resp.read = MagicMock(
            side_effect=[content[0:8], content[8:15], content[15:], b""]
        )
        mock_resp.close = MagicMock()
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/stream_lines", stream=True)

        lines = list(response.iter_lines())

        self.assertEqual(lines, [b"line1\n", b"line2\n", b"line3 incomplete"])
        self.assertTrue(response._content_consumed)
        mock_resp.close.assert_called_once()

    @patch("urllib.request.OpenerDirector.open")
    def test_iter_content_after_read(self, mock_open):
        """Test iter_content after response.content was already accessed."""
        content = b"already read data"
        mock_resp = MockHTTPResponse(status=200, body=content)
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/already_read")

        # Access content first
        self.assertEqual(response.content, content)
        self.assertTrue(response._content_consumed)

        # Now iterate
        chunks = list(response.iter_content(chunk_size=5))
        self.assertEqual(chunks, [b"alrea", b"dy re", b"ad da", b"ta"])

    @patch("urllib.request.OpenerDirector.open")
    def test_empty_json_response(self, mock_open):
        """Test calling .json() on an empty response body."""
        mock_resp = MockHTTPResponse(
            status=200, body=b"", headers={"Content-Type": "application/json"}
        )
        mock_open.return_value = mock_resp

        response = requests.get("http://test.com/empty")

        self.assertEqual(response.content, b"")
        self.assertEqual(response.text, "")
        with self.assertRaises(json_.JSONDecodeError):
            response.json()

    @patch("urllib.request.OpenerDirector.open")
    def test_session_header_merging(self, mock_open):
        """Test that session headers are merged with request headers."""
        mock_resp = MockHTTPResponse(status=200)
        mock_open.return_value = mock_resp

        with requests.Session() as session:
            session.headers.update(
                {"X-Session-Header": "SessionValue", "User-Agent": "SessionAgent"}
            )
            response = session.get(
                "http://test.com/session",
                headers={
                    "X-Request-Header": "RequestValue",
                    "User-Agent": "RequestAgent",
                },
            )

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]

        # Request-specific header takes precedence
        self.assertEqual(req.headers["User-agent"], "RequestAgent")
        self.assertEqual(req.headers["X-session-header"], "SessionValue")
        self.assertEqual(req.headers["X-request-header"], "RequestValue")

    @patch("urllib.request.OpenerDirector.open")
    def test_session_param_merging(self, mock_open):
        """Test that session params are merged with request params."""
        mock_resp = MockHTTPResponse(status=200)
        mock_open.return_value = mock_resp

        with requests.Session() as session:
            session.params.update({"sess_param": "s_val", "common": "s_common"})
            response = session.get(
                "http://test.com/session_params",
                params={"req_param": "r_val", "common": "r_common"},
            )

        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        req = args[0]
        final_url = req.get_full_url()

        # Check that all params are present, request takes precedence for common
        self.assertIn("sess_param=s_val", final_url)
        self.assertIn("req_param=r_val", final_url)
        self.assertIn("common=r_common", final_url)
        self.assertNotIn("common=s_common", final_url)


if __name__ == "__main__":
    unittest.main()
