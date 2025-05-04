"""
A minimal drop-in replacement for the requests library,
using only the Python standard library.
Covers common use cases like GET, POST, PUT, DELETE, HEAD requests,
handling params, data, json, headers, timeouts, and basic response attributes.
"""

import http.client
import json as json_
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import gzip
import logging
from typing import Any, Dict, Generator, Mapping, Optional, Union

logger = logging.getLogger(__name__)

# --- Exceptions ---
class RequestException(IOError):
    """Base class for requests exceptions."""

    def __init__(self, *args, response=None, request=None, **kwargs):
        self.response = response
        self.request = request
        super().__init__(*args, **kwargs)


class HTTPError(RequestException):
    """An HTTP error occurred."""

    pass


class ConnectionError(RequestException):
    """A connection error occurred."""

    pass


class Timeout(RequestException):
    """The request timed out."""

    pass


# --- Response Object ---


class Response:
    """
    Mimics the requests.Response object.
    """

    def __init__(self):
        self.url: Optional[str] = None
        self.status_code: int = 0
        self.reason: Optional[str] = None
        self.headers: Mapping[str, str] = {}
        self._content: Optional[bytes] = None
        self._text: Optional[str] = None
        self.encoding: Optional[str] = None
        self.request: Optional[urllib.request.Request] = None
        self._content_consumed: bool = False
        self._stream: Optional[http.client.HTTPResponse] = None  # For streaming

    def _determine_encoding(self) -> Optional[str]:
        """Determine encoding from headers, default to utf-8."""
        content_type = self.headers.get("content-type")
        if content_type:
            parts = content_type.split("charset=")
            if len(parts) > 1:
                return parts[1].strip()
        return "utf-8"  # Default fallback

    @property
    def text(self) -> Optional[str]:
        """Return the content of the response in unicode."""
        if self._text is None:
            if self._content is None and self._stream:
                # Read stream if not already read
                self._content = self._stream.read()
                self._stream.close()
                self._content_consumed = True

            if self._content is not None:
                if self.encoding is None:
                    self.encoding = self._determine_encoding()
                try:
                    self._text = self._content.decode(
                        self.encoding or "utf-8", errors="replace"
                    )
                except (LookupError, TypeError):
                    # Fallback if encoding is invalid
                    self._text = self._content.decode("utf-8", errors="replace")
            else:
                self._text = ""  # No content means empty text
        return self._text

    @property
    def content(self) -> Optional[bytes]:
        """Return the content of the response in bytes."""
        if self._content is None and self._stream:
            # Read stream if not already read
            self._content = self._stream.read()
            self._stream.close()
            self._content_consumed = True
        return self._content

    def json(self, **kwargs) -> Any:
        """Return the json-encoded content of the response."""
        if self.text is None or not self.text.strip():
            # Handle empty response body
            raise json_.JSONDecodeError("Expecting value", "", 0)
        return json_.loads(self.text, **kwargs)

    def raise_for_status(self) -> None:
        """Raise an HTTPError for bad responses (4xx or 5xx)."""
        if 400 <= self.status_code < 600:
            reason = (
                self.reason or f"Client Error {self.status_code}"
                if 400 <= self.status_code < 500
                else f"Server Error {self.status_code}"
            )
            raise HTTPError(
                f"{self.status_code} {reason} for url: {self.url}", response=self
            )

    def iter_content(
        self, chunk_size: int = 1, decode_unicode: bool = False
    ) -> Generator[Union[bytes, str], None, None]:
        """Iterates over the response data.

        When stream=True is set on the request, this avoids reading the
        content at once into memory for large responses.

        :param chunk_size: Number of bytes it should read into memory.
        :param decode_unicode: If True, content will be decoded using the
                               best available encoding based on the response.
        """
        if self._content_consumed:
            # If content is already read (e.g., via .content or .text), iterate over it
            content_to_iterate = self._content if self._content is not None else b""
            for i in range(0, len(content_to_iterate), chunk_size):
                chunk = content_to_iterate[i : i + chunk_size]
                if decode_unicode:
                    if self.encoding is None:
                        self.encoding = self._determine_encoding()
                    yield chunk.decode(self.encoding or "utf-8", errors="replace")
                else:
                    yield chunk
            return

        if not self._stream:
            # If not streaming, behave like reading content and chunking
            content_to_iterate = self.content if self.content is not None else b""
            for i in range(0, len(content_to_iterate), chunk_size):
                chunk = content_to_iterate[i : i + chunk_size]
                if decode_unicode:
                    if self.encoding is None:
                        self.encoding = self._determine_encoding()
                    yield chunk.decode(self.encoding or "utf-8", errors="replace")
                else:
                    yield chunk
            return

        # Streaming case
        try:
            while True:
                chunk = self._stream.read(chunk_size)
                if not chunk:
                    break
                if decode_unicode:
                    if self.encoding is None:
                        self.encoding = self._determine_encoding()
                    yield chunk.decode(self.encoding or "utf-8", errors="replace")
                else:
                    yield chunk
        except Exception as e:
            # Handle potential errors during streaming read
            print(f"Error during streaming read: {e}")  # Or log properly
        finally:
            self._stream.close()
            self._content_consumed = True  # Mark as consumed after iteration

    def iter_lines(
        self,
        chunk_size: int = 512,
        decode_unicode: bool = False,
        delimiter: Optional[Union[str, bytes]] = None,
    ) -> Generator[Union[bytes, str], None, None]:
        """Iterates over the response data, one line at a time.

        When stream=True is set on the request, this avoids reading the
        content at once into memory for large responses.

        :param chunk_size: Number of bytes it should read into memory.
                           Influences buffering efficiency.
        :param decode_unicode: If True, content will be decoded using the
                               best available encoding based on the response.
        :param delimiter: Line separator. Defaults to ``\\n`` (newline).
                          Can be bytes or str (if decode_unicode=True).
        """
        if delimiter is None:
            delimiter = b"\n" if not decode_unicode else "\n"
        elif decode_unicode and isinstance(delimiter, bytes):
            raise ValueError("Delimiter must be str when decode_unicode=True")
        elif not decode_unicode and isinstance(delimiter, str):
            raise ValueError("Delimiter must be bytes when decode_unicode=False")

        buffer = b""
        for chunk in self.iter_content(chunk_size=chunk_size, decode_unicode=False):
            buffer += chunk
            while True:
                try:
                    # bytes.index raises ValueError if delimiter not found
                    line, buffer = buffer.split(delimiter, 1)
                    line += delimiter  # Add back the delimiter like requests does
                except ValueError:
                    # Delimiter not found in current buffer, need more data
                    break
                else:
                    if decode_unicode:
                        if self.encoding is None:
                            self.encoding = self._determine_encoding()
                        yield line.decode(self.encoding or "utf-8", errors="replace")
                    else:
                        yield line

        # Yield any remaining data after the loop finishes if buffer is not empty
        if buffer:
            if decode_unicode:
                if self.encoding is None:
                    self.encoding = self._determine_encoding()
                yield buffer.decode(self.encoding or "utf-8", errors="replace")
            else:
                yield buffer

    def close(self) -> None:
        """Release the connection."""
        if self._stream and not self._content_consumed:
            self._stream.close()
            self._content_consumed = True


# --- Request Functions ---


def request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Union[Dict[str, Any], str, bytes]] = None,
    json: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    allow_redirects: bool = True,
    stream: bool = False,
    **kwargs: Any,  # Allow other requests kwargs, though they might not be used
) -> Response:
    """
    Makes an HTTP request using the standard library.

    :param method: HTTP method (GET, POST, PUT, DELETE, HEAD, OPTIONS, PATCH).
    :param url: URL for the request.
    :param params: Dictionary of query parameters.
    :param data: Dictionary, bytes, or file-like object to send in the body (form-encoded).
    :param json: JSON serializable object to send in the body.
    :param headers: Dictionary of HTTP headers.
    :param timeout: Socket timeout in seconds.
    :param allow_redirects: Follow redirects.
    :param stream: If True, the response content will not be downloaded immediately.
    :return: Response object.
    """
    # Prepare URL with params
    if params:
        url_parts = list(urllib.parse.urlparse(url))
        query = dict(urllib.parse.parse_qsl(url_parts[4]))
        query.update(params)
        url_parts[4] = urllib.parse.urlencode(query)
        url = urllib.parse.urlunparse(url_parts)

    # Prepare headers
    req_headers = {}
    if headers:
        req_headers.update(headers)

    # Prepare data/body
    req_data = None
    if json is not None and data is not None:
        raise ValueError("Cannot provide both 'data' and 'json' parameters.")
    elif json is not None:
        req_data = json_.dumps(json).encode("utf-8")
        if "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"
    elif data is not None:
        if isinstance(data, dict):
            req_data = urllib.parse.urlencode(data).encode("utf-8")
            if "Content-Type" not in req_headers:
                req_headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif isinstance(data, str):
            req_data = data.encode("utf-8")
        elif isinstance(data, bytes):
            req_data = data
        # Note: File-like objects for 'data' are not handled here for simplicity

    # Create the request object
    req = urllib.request.Request(
        url, data=req_data, headers=req_headers, method=method.upper()
    )

    # Handle redirects (basic implementation)
    opener = urllib.request.build_opener()
    if not allow_redirects:
        # Prevent redirects by using a handler that raises errors on 3xx
        class NoRedirection(urllib.request.HTTPErrorProcessor):
            def http_response(self, request, response):
                return response

            https_response = http_response

        opener.add_handler(NoRedirection)

    # Create context to ignore SSL certificate verification if needed (like requests verify=False)
    # WARNING: Disabling SSL verification is insecure. Use with caution.
    # In a real scenario, prefer proper certificate handling.
    # For simplicity here, we mimic the common requests behavior.
    # If 'verify=False' is implicitly desired by not providing certs:
    ssl_context = ssl.create_default_context()
    if kwargs.get("verify") is False:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        opener.add_handler(urllib.request.HTTPSHandler(context=ssl_context))

    # Make the request
    resp = Response()
    resp.request = req
    resp.url = req.get_full_url()  # URL after potential param encoding

    http_response: Optional[http.client.HTTPResponse] = None
    try:
        http_response = opener.open(req, timeout=timeout)
        resp.status_code = http_response.status
        resp.reason = http_response.reason
        resp.headers = (
            http_response.headers
        )  # This is an HTTPMessage object, acts like a dict

        if stream:
            resp._stream = http_response
            # Don't read content yet
        else:
            raw_content = http_response.read()
            # --- Decompression Handling ---
            content_encoding = resp.headers.get("Content-Encoding")
            if content_encoding == "gzip":
                try:
                    resp._content = gzip.decompress(raw_content)
                    logger.debug(
                        "Decompressed gzipped response content."
                    )  # Add logger if available or use print
                except gzip.BadGzipFile:
                    logger.error(
                        "Failed to decompress gzip content, using raw content."
                    )  # Add logger
                    resp._content = raw_content  # Fallback to raw content on error
                except Exception as e:
                    logger.error(
                        f"Unexpected error during gzip decompression: {e}",
                        exc_info=True,
                    )  # Add logger
                    resp._content = raw_content  # Fallback
            else:
                # No compression or unsupported compression
                resp._content = raw_content
            # --- End Decompression ---
            resp._content_consumed = True
            http_response.close()  # Close after reading

    except urllib.error.HTTPError as e:
        # Handle HTTP errors (like 404, 500)
        # Try to read and decompress error body as well
        resp.status_code = e.code
        resp.reason = e.reason
        resp.headers = e.headers
        try:
            raw_error_content = e.read()
            # --- Decompression Handling for Error Body ---
            content_encoding = resp.headers.get("Content-Encoding")
            if content_encoding == "gzip":
                try:
                    resp._content = gzip.decompress(raw_error_content)
                    logger.debug(
                        "Decompressed gzipped error response content."
                    )  # Add logger
                except gzip.BadGzipFile:
                    logger.error(
                        "Failed to decompress gzipped error content, using raw content."
                    )  # Add logger
                    resp._content = raw_error_content  # Fallback
                except Exception as ex:
                    logger.error(
                        f"Unexpected error during gzip decompression of error body: {ex}",
                        exc_info=True,
                    )  # Add logger
                    resp._content = raw_error_content  # Fallback
            else:
                resp._content = raw_error_content
            # --- End Decompression ---
        except Exception as read_err:
            # Handle cases where reading the error body itself fails
            logger.error(
                f"Could not read error response body: {read_err}"
            )  # Add logger
            resp._content = None
        finally:
            resp._content_consumed = True
        # We don't raise here immediately, let the caller use raise_for_status
    except urllib.error.URLError as e:
        # Handle URL errors (connection refused, DNS errors, timeouts)
        if isinstance(e.reason, socket.timeout):
            raise Timeout(f"Request timed out: {e}", request=req) from e
        raise ConnectionError(f"Connection error: {e.reason}", request=req) from e
    except socket.timeout as e:
        raise Timeout(f"Request timed out: {e}", request=req) from e
    except Exception as e:
        # Catch other potential errors during the request
        raise RequestException(f"An unexpected error occurred: {e}", request=req) from e
    finally:
        # Ensure the opener is closed if it has a close method (it usually doesn't directly)
        # The underlying connection is managed by the http_response object
        if http_response and not stream and not resp._content_consumed:
            # Ensure closed if not streaming and not already closed after read
            try:
                http_response.close()
            except Exception:
                pass  # Ignore errors during close
        elif stream and not resp._stream:
            # If streaming was requested but failed before stream could be assigned
            if http_response:
                try:
                    http_response.close()
                except Exception:
                    pass

    return resp


# --- Convenience Methods ---


def get(url: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Response:
    """Sends a GET request."""
    return request("GET", url, params=params, **kwargs)


def post(
    url: str, data: Optional[Any] = None, json: Optional[Any] = None, **kwargs: Any
) -> Response:
    """Sends a POST request."""
    return request("POST", url, data=data, json=json, **kwargs)


def put(url: str, data: Optional[Any] = None, **kwargs: Any) -> Response:
    """Sends a PUT request."""
    # Note: requests' put often uses 'data', mirroring that here.
    return request("PUT", url, data=data, **kwargs)


def delete(url: str, **kwargs: Any) -> Response:
    """Sends a DELETE request."""
    return request("DELETE", url, **kwargs)


def head(url: str, **kwargs: Any) -> Response:
    """Sends a HEAD request."""
    # HEAD requests should not have a body read, even if sent by server
    kwargs["stream"] = True  # Effectively prevent reading body
    response = request("HEAD", url, **kwargs)
    # Ensure stream is closed immediately for HEAD
    if response._stream:
        response._stream.close()
        response._content_consumed = True
    return response


def options(url: str, **kwargs: Any) -> Response:
    """Sends an OPTIONS request."""
    return request("OPTIONS", url, **kwargs)


# --- Session Object (Placeholder) ---
# A full Session object implementation is complex (connection pooling, cookie persistence).
# This is a placeholder showing the structure.


class Session:
    """
    Placeholder for Session object.
    Does not implement connection pooling or cookie persistence yet.
    """

    def __init__(self):
        self.headers = {}
        self.params = {}
        # Add cookie handling, auth, etc. here in a full implementation

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        # Merge session headers/params with request-specific ones
        merged_headers = self.headers.copy()
        if "headers" in kwargs:
            merged_headers.update(kwargs["headers"])
        kwargs["headers"] = merged_headers

        merged_params = self.params.copy()
        if "params" in kwargs:
            merged_params.update(kwargs["params"])
        kwargs["params"] = merged_params

        # In a real session, would manage cookies and potentially connection pool
        return request(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> Response:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> Response:
        return self.request("OPTIONS", url, **kwargs)

    def close(self):
        """Close the session."""
        # In a real session, this would close pooled connections.
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# --- Expose top-level functions ---
# Mimic `import requests` usage
get = get
post = post
put = put
delete = delete
head = head
options = options
request = request
Response = Response
Session = Session
RequestException = RequestException
HTTPError = HTTPError
ConnectionError = ConnectionError
Timeout = Timeout
