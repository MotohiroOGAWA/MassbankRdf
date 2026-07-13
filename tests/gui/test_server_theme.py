from __future__ import annotations

import unittest

from starlette.requests import Request

from massbank_rdf.gui.server import _light_theme_redirect_url


def make_request(
    path: str = "/kg/input/",
    *,
    method: str = "GET",
    query: str = "",
    accept: str = "text/html",
) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [(b"accept", accept.encode())],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
    )


class TestServerTheme(unittest.TestCase):
    def test_html_page_without_theme_redirects_to_light(self) -> None:
        url = _light_theme_redirect_url(make_request(query="tab=kg"))

        self.assertEqual(
            url,
            "http://testserver/kg/input/?tab=kg&__theme=light",
        )

    def test_dark_theme_request_is_replaced_with_light(self) -> None:
        url = _light_theme_redirect_url(make_request(query="__theme=dark"))

        self.assertEqual(
            url,
            "http://testserver/kg/input/?__theme=light",
        )

    def test_light_theme_request_does_not_redirect(self) -> None:
        url = _light_theme_redirect_url(make_request(query="__theme=light"))

        self.assertIsNone(url)

    def test_non_html_request_does_not_redirect(self) -> None:
        url = _light_theme_redirect_url(
            make_request(path="/kg/input/config", accept="application/json")
        )

        self.assertIsNone(url)


if __name__ == "__main__":
    unittest.main()
