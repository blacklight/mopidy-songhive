import logging
from urllib.parse import urlencode

import requests
from mopidy import httpclient

import mopidy_songhive

logger = logging.getLogger(__name__)


class SonghiveHttpError(Exception):
    """Raised when the Songhive API returns an error response."""

    def __init__(self, status_code, message="", url=None):
        self.status_code = status_code
        self.url = url
        super().__init__(
            f"Songhive API error {status_code}: {message} ({url})"
        )


class SonghiveHttpClient:
    """Thin ``requests`` wrapper for the Songhive REST API.

    Handles the base URL, optional bearer authentication, the Mopidy
    user-agent/proxy settings, and transparent pagination of list endpoints.
    """

    PAGE_SIZE = 100
    MAX_RETRIES = 3

    def __init__(self, base_url, token=None, proxy=None):
        self.base_url = base_url.rstrip("/")
        self.token = token or None

        user_agent = httpclient.format_user_agent(
            "/".join(
                (
                    mopidy_songhive.Extension.dist_name,
                    mopidy_songhive.__version__,
                )
            )
        )

        self.session = requests.Session()
        self.session.headers.update({"user-agent": user_agent})
        if self.token:
            self.session.headers.update(
                {"Authorization": f"Bearer {self.token}"}
            )

        if proxy:
            http_proxy = httpclient.format_proxy(proxy)
            self.session.proxies.update(
                {"http": http_proxy, "https": http_proxy}
            )

    @property
    def authenticated(self):
        return self.token is not None

    def url(self, path, params=None):
        """Build an absolute API URL for ``path`` with optional query params."""
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        return url

    def _request(self, method, path, params=None, json=None, raw=False):
        url = self.url(path, params)
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.request(
                    method, url, json=json, timeout=30
                )
            except requests.RequestException as exc:
                last_error = exc
                logger.info(
                    "Songhive %s %s failed on try %d: %s",
                    method,
                    url,
                    attempt,
                    exc,
                )
                continue

            if response.status_code == 204:
                return response if raw else None

            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text
                raise SonghiveHttpError(response.status_code, detail, url)

            if raw:
                return response
            try:
                return response.json()
            except ValueError:
                return response.text

        raise SonghiveHttpError(0, str(last_error), url)

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def get_page(self, path, params=None):
        """GET a list endpoint and return ``(items, total_or_none)``."""
        response = self._request("GET", path, params=params, raw=True)
        try:
            items = response.json()
        except ValueError:
            items = []
        total = response.headers.get("X-Total-Count")
        try:
            total = int(total) if total is not None else None
        except ValueError:
            total = None
        if not isinstance(items, list):
            items = []
        return items, total

    def get_all(self, path, params=None, max_items=None):
        """Fetch all pages of a paginated list endpoint."""
        params = dict(params or {})
        params.setdefault("limit", self.PAGE_SIZE)
        offset = int(params.pop("offset", 0) or 0)
        items = []
        while True:
            params["offset"] = offset
            page, total = self.get_page(path, params)
            items.extend(page)
            offset += len(page)
            if (
                not page
                or len(page) < params["limit"]
                or (total is not None and len(items) >= total)
                or (max_items is not None and len(items) >= max_items)
            ):
                break
        if max_items is not None:
            items = items[:max_items]
        return items

    def post(self, path, payload=None, params=None):
        return self._request("POST", path, params=params, json=payload or {})

    def patch(self, path, payload=None, params=None):
        return self._request("PATCH", path, params=params, json=payload or {})

    def delete(self, path, params=None):
        try:
            self._request("DELETE", path, params=params)
            return True
        except SonghiveHttpError as exc:
            logger.info("Songhive DELETE %s failed: %s", path, exc)
            return False

    def head_ok(self, url):
        """Return True when a HEAD request against ``url`` succeeds."""
        try:
            response = self.session.head(url, timeout=10)
            return response.status_code < 400
        except requests.RequestException:
            return False
