"""Search-engine policy for the app hosts.

The app itself (login, chat, settings, admin, …) must stay out of Google; only
the public demo page is meant to be found. Everything the app serves gets an
``X-Robots-Tag: noindex, nofollow`` header except the demo and its assets.

robots.txt deliberately allows crawling: a page blocked by robots.txt can't be
fetched, so Google would never see its noindex and could keep an old listing.
"""

_INDEXABLE_PREFIXES = ("/demo", "/static/", "/api/public/")
_DEMO_HOSTS = {"demo.orionforge.chat"}
_NOINDEX = (b"x-robots-tag", b"noindex, nofollow")


def _host(scope) -> str:
    for k, v in scope.get("headers") or ():
        if k == b"host":
            return v.decode("latin-1").split(":")[0].lower()
    return ""


def _indexable(host: str, path: str) -> bool:
    if host in _DEMO_HOSTS:
        return True
    return path == "/demo" or path.startswith(_INDEXABLE_PREFIXES) or path in ("/robots.txt", "/sitemap.xml")


def _origin(scope, host: str) -> str:
    scheme = "http" if host in ("localhost", "127.0.0.1") else "https"
    raw = next((v.decode("latin-1") for k, v in scope.get("headers") or () if k == b"host"), host)
    return f"{scheme}://{raw}"


def _robots(origin: str) -> bytes:
    return f"User-agent: *\nAllow: /\n\nSitemap: {origin}/sitemap.xml\n".encode()


def _sitemap(origin: str, host: str) -> bytes:
    loc = origin + ("/" if host in _DEMO_HOSTS else "/demo")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{loc}</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>\n"
    ).encode()


class SeoMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so streamed chat replies pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        host, path = _host(scope), scope.get("path", "")

        if path in ("/robots.txt", "/sitemap.xml") and scope.get("method") in ("GET", "HEAD"):
            origin = _origin(scope, host)
            body, ctype = ((_robots(origin), b"text/plain; charset=utf-8") if path == "/robots.txt"
                           else (_sitemap(origin, host), b"application/xml; charset=utf-8"))
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", ctype), (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"public, max-age=3600")]})
            await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})
            return

        if _indexable(host, path):
            return await self.app(scope, receive, send)

        async def send_noindex(message):
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"x-robots-tag"]
                message = {**message, "headers": headers + [_NOINDEX]}
            await send(message)

        return await self.app(scope, receive, send_noindex)
