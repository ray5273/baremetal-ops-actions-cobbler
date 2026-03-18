"""WSGI proxy to cobblerd XML-RPC server on localhost:25151."""
import http.client


def application(environ, start_response):
    if environ["REQUEST_METHOD"] == "POST":
        try:
            content_length = int(environ.get("CONTENT_LENGTH", 0))
            request_body = environ["wsgi.input"].read(content_length)
            conn = http.client.HTTPConnection("127.0.0.1", 25151)
            conn.request(
                "POST", "/", body=request_body,
                headers={"Content-Type": "text/xml"},
            )
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            start_response("200 OK", [
                ("Content-Type", "text/xml"),
                ("Content-Length", str(len(body))),
            ])
            return [body]
        except Exception as e:
            error_msg = str(e).encode()
            start_response("500 Internal Server Error", [
                ("Content-Type", "text/plain"),
                ("Content-Length", str(len(error_msg))),
            ])
            return [error_msg]
    body = b"cobbler_api XML-RPC endpoint"
    start_response("200 OK", [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(len(body))),
    ])
    return [body]
