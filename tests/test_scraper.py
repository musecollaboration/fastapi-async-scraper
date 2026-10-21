"""Тесты модуля scraper.py — чистые функции и асинхронный слой."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
import httpx
from bs4 import BeautifulSoup

import scraper
from conftest import make_card, make_listing_html
from scraper import (
    CaptchaDetectedError,
    ScraperError,
    _build_headers,
    _clean_text,
    _looks_like_captcha,
    _make_sku,
    _next_page_url,
    _parse_breadcrumbs,
    _parse_card,
    _parse_listing,
    _validate_url,
)


# --- Хелперы ---------------------------------------------------------------

def _html(*cards, breadcrumbs=("Books",), next_href="page-2.html"):
    return make_listing_html(cards, breadcrumbs=breadcrumbs, next_href=next_href)


@contextmanager
def _zero_delays():
    """Обнуляем задержки и backoff для быстрых асинхронных тестов."""
    old_req = scraper.REQUEST_DELAY_SECONDS
    old_back = scraper.RETRY_BACKOFF_SECONDS
    scraper.REQUEST_DELAY_SECONDS = 0
    scraper.RETRY_BACKOFF_SECONDS = 0
    try:
        yield
    finally:
        scraper.REQUEST_DELAY_SECONDS = old_req
        scraper.RETRY_BACKOFF_SECONDS = old_back


# --- _clean_text -----------------------------------------------------------

class TestCleanText:
    def test_none(self):
        assert _clean_text(None) == ""

    def test_plain(self):
        assert _clean_text("  Hello   World  ") == "Hello World"

    def test_newlines(self):
        assert _clean_text("Hello\n  World\n\nFoo") == "Hello World Foo"

    def test_tabs(self):
        assert _clean_text("Hello\t\tWorld") == "Hello World"


# --- _validate_url ---------------------------------------------------------

class TestValidateUrl:
    def test_allowed_host(self):
        _validate_url("https://books.toscrape.com/catalogue/page-1.html")

    def test_www_host(self):
        _validate_url("https://www.books.toscrape.com/catalogue/page-1.html")

    def test_bad_scheme(self):
        with pytest.raises(ScraperError, match="начинаться с http"):
            _validate_url("ftp://books.toscrape.com/")

    def test_foreign_host(self):
        with pytest.raises(ScraperError, match="только с books.toscrape"):
            _validate_url("https://evil.com/page-1.html")


# --- _looks_like_captcha ---------------------------------------------------

class TestLooksLikeCaptcha:
    def test_marker_captcha(self):
        assert _looks_like_captcha("are you a captcha?")

    def test_marker_robot(self):
        assert _looks_like_captcha("Are You a Robot?")

    def test_case_insensitive(self):
        assert _looks_like_captcha("ACCESS DENIED")

    def test_no_marker(self):
        assert not _looks_like_captcha("All products — Fiction")

    def test_real_catalogue_not_captcha(self):
        html = _html(make_card("Test", "t_1.html", "t.jpg"))
        assert not _looks_like_captcha(html)


# --- _make_sku -------------------------------------------------------------

class TestMakeSku:
    def test_format(self):
        sku = _make_sku("https://books.toscrape.com/catalogue/x_1.html")
        assert sku.startswith("SKU-")
        assert len(sku) == 16

    def test_deterministic(self):
        url = "https://books.toscrape.com/catalogue/x_1.html"
        assert _make_sku(url) == _make_sku(url)

    def test_different_urls_different_sku(self):
        assert _make_sku("https://a.com/1.html") != _make_sku("https://a.com/2.html")


# --- _parse_breadcrumbs ----------------------------------------------------

class TestParseBreadcrumbs:
    def test_books_only(self):
        html = _html(breadcrumbs=("Books",))
        soup = BeautifulSoup(html, "html.parser")
        cat, sub = _parse_breadcrumbs(soup)
        assert cat == "Books"
        assert sub == "Books"

    def test_books_fiction(self):
        html = _html(breadcrumbs=("Books", "Fiction"))
        soup = BeautifulSoup(html, "html.parser")
        cat, sub = _parse_breadcrumbs(soup)
        assert cat == "Books"
        assert sub == "Fiction"

    def test_no_crumbs(self):
        soup = BeautifulSoup("<html><body></body></html>", "html.parser")
        cat, sub = _parse_breadcrumbs(soup)
        assert cat == "Books"
        assert sub == "Books"

    def test_all_products_filtered(self):
        """All Products исключается, остаётся пустой список -> дефолт."""
        html = """
        <ul class="breadcrumb">
          <li><a href="index.html">Home</a></li>
          <li><a href="all-products.html">All Products</a></li>
        </ul>
        """
        soup = BeautifulSoup(html, "html.parser")
        cat, sub = _parse_breadcrumbs(soup)
        assert cat == "Books"
        assert sub == "Books"


# --- _parse_card -----------------------------------------------------------

class TestParseCard:
    def test_full_card(self):
        card_html = make_card(
            "Test Book",
            "test_1000/index.html",
            "../media/cache/ab/cd.jpg",
            title="Test Book Full Title",
            short_name="Test Book ...",
        )
        soup = BeautifulSoup(card_html, "html.parser")
        card = soup.select_one("article")
        page_url = "https://books.toscrape.com/catalogue/page-1.html"
        p = _parse_card(card, page_url)
        assert p is not None
        assert p.name == "Test Book Full Title"
        assert p.product_url == "https://books.toscrape.com/catalogue/test_1000/index.html"
        assert p.image_urls == "https://books.toscrape.com/media/cache/ab/cd.jpg"
        assert p.sku == _make_sku(p.product_url)

    def test_missing_href(self):
        card_html = """
        <article class="product_pod">
          <h3><a>Broken</a></h3>
        </article>
        """
        soup = BeautifulSoup(card_html, "html.parser")
        assert _parse_card(soup.select_one("article"), "https://x.com/p.html") is None

    def test_no_title_attr_uses_text(self):
        card_html = """
        <article class="product_pod">
          <h3><a href="t_1.html">Title From Text</a></h3>
        </article>
        """
        soup = BeautifulSoup(card_html, "html.parser")
        card = soup.select_one("article")
        p = _parse_card(card, "https://books.toscrape.com/catalogue/page-1.html")
        assert p is not None
        assert p.name == "Title From Text"

    def test_no_image(self):
        card_html = """
        <article class="product_pod">
          <h3><a href="t_1.html" title="T">T</a></h3>
        </article>
        """
        soup = BeautifulSoup(card_html, "html.parser")
        p = _parse_card(soup.select_one("article"), "https://books.toscrape.com/catalogue/page-1.html")
        assert p is not None
        assert p.image_urls == ""


# --- _next_page_url --------------------------------------------------------

class TestNextPageUrl:
    def test_present(self):
        html = _html(next_href="page-2.html")
        soup = BeautifulSoup(html, "html.parser")
        url = _next_page_url(soup, "https://books.toscrape.com/catalogue/page-1.html")
        assert url == "https://books.toscrape.com/catalogue/page-2.html"

    def test_absent(self):
        html = _html(next_href=None)
        soup = BeautifulSoup(html, "html.parser")
        assert _next_page_url(soup, "https://books.toscrape.com/catalogue/page-1.html") is None


# --- _parse_listing --------------------------------------------------------

class TestParseListing:
    def test_parses_cards_and_categories(self):
        card = make_card("Book A", "a_1000/index.html", "a.jpg")
        card2 = make_card("Book B", "b_1000/index.html", "b.jpg", title="Book B Full")
        html = _html(card, card2, next_href=None)
        products, next_url = _parse_listing(
            html, "https://books.toscrape.com/catalogue/page-1.html")
        assert len(products) == 2
        assert products[0].category_lvl1 == "Books"
        assert products[1].subcategory_path == "Books"
        assert next_url is None
        assert products[0].name == "Book A"
        assert products[1].name == "Book B Full"

    def test_skips_broken_card(self):
        card = make_card("Good", "g_1000/index.html", "g.jpg")
        broken = '<article class="product_pod"><h3><a href="">No href</a></h3></article>'
        html = _html(card, broken, next_href=None)
        products, _ = _parse_listing(
            html, "https://books.toscrape.com/catalogue/page-1.html")
        assert len(products) == 1

    def test_empty_listing(self):
        html = _html()
        products, _ = _parse_listing(
            html, "https://books.toscrape.com/catalogue/page-1.html")
        assert products == []


# --- _build_headers --------------------------------------------------------

class TestBuildHeaders:
    def test_user_agent(self):
        h = _build_headers()
        assert "Mozilla" in h["User-Agent"]

    def test_accept_language(self):
        h = _build_headers()
        assert "en-US" in h["Accept-Language"]


# --- _fetch_html (async, httpx.MockTransport) ------------------------------

class TestFetchHtml:
    async def test_success(self):
        def handler(req):
            return httpx.Response(200, text="<!DOCTYPE html><body>OK</body>")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with _zero_delays():
            html = await scraper._fetch_html(client, "https://books.toscrape.com/x")
        assert "OK" in html

    async def test_retry_then_success(self):
        attempts = 0

        def handler(req):
            nonlocal attempts
            attempts += 1
            return httpx.Response(429) if attempts < 3 else httpx.Response(200, text="OK")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with _zero_delays():
            html = await scraper._fetch_html(client, "https://books.toscrape.com/x")
        assert html == "OK"
        assert attempts == 3

    async def test_max_retries_exhausted(self):
        attempts = 0

        def handler(req):
            nonlocal attempts
            attempts += 1
            return httpx.Response(500)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with _zero_delays():
            with pytest.raises(ScraperError, match="500"):
                await scraper._fetch_html(client, "https://books.toscrape.com/x")
        assert attempts == 3

    async def test_non_retryable_status(self):
        attempts = 0

        def handler(req):
            nonlocal attempts
            attempts += 1
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with _zero_delays():
            with pytest.raises(ScraperError, match="404"):
                await scraper._fetch_html(client, "https://books.toscrape.com/x")
        assert attempts == 1

    async def test_captcha_detected(self):
        def handler(req):
            return httpx.Response(200, text="<html><body>CAPTCHA detected</body></html>")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with _zero_delays():
            with pytest.raises(CaptchaDetectedError, match="антибот"):
                await scraper._fetch_html(client, "https://books.toscrape.com/x")

    async def test_network_error(self):
        def handler(req):
            raise httpx.ConnectError("boom", request=req)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with _zero_delays():
            with pytest.raises(ScraperError, match="3 попыток"):
                await scraper._fetch_html(client, "https://books.toscrape.com/x")


# --- fetch_category (async, monkeypatch _fetch_html) -----------------------

def _fetch_html_stub(urls: dict[str, str]):
    order: list[str] = []

    async def stub(client, url: str):
        order.append(url)
        if url not in urls:
            raise ScraperError(f"Неизвестный URL: {url}")
        return urls[url]

    stub._order = order
    return stub


class TestFetchCategory:
    async def test_single_page(self):
        html = _html(
            make_card("A", "a_1000/index.html", "a.jpg"),
            next_href=None,
        )
        stub = _fetch_html_stub({"https://books.toscrape.com/catalogue/page-1.html": html})
        with _zero_delays():
            mp = pytest.MonkeyPatch()
            mp.setattr(scraper, "_fetch_html", stub)
            products = await scraper.fetch_category(
                "https://books.toscrape.com/catalogue/page-1.html", max_pages=1)
        assert len(products) == 1
        assert products[0].name == "A"

    async def test_pagination(self):
        html1 = _html(
            make_card("A", "a_1000/index.html", "a.jpg"),
            next_href="page-2.html",
        )
        html2 = _html(
            make_card("B", "b_1000/index.html", "b.jpg", title="B Full"),
            next_href="page-3.html",
        )
        stub = _fetch_html_stub({
            "https://books.toscrape.com/catalogue/page-1.html": html1,
            "https://books.toscrape.com/catalogue/page-2.html": html2,
        })
        with _zero_delays():
            mp = pytest.MonkeyPatch()
            mp.setattr(scraper, "_fetch_html", stub)
            products = await scraper.fetch_category(
                "https://books.toscrape.com/catalogue/page-1.html", max_pages=2)
        assert len(products) == 2
        assert products[1].name == "B Full"

    async def test_dedup(self):
        html1 = _html(
            make_card("A", "a_1000/index.html", "a.jpg"),
            next_href="page-2.html",
        )
        html2 = _html(
            make_card("A", "a_1000/index.html", "a.jpg"),
            make_card("B", "b_1000/index.html", "b.jpg", title="B Full"),
            next_href=None,
        )
        stub = _fetch_html_stub({
            "https://books.toscrape.com/catalogue/page-1.html": html1,
            "https://books.toscrape.com/catalogue/page-2.html": html2,
        })
        with _zero_delays():
            mp = pytest.MonkeyPatch()
            mp.setattr(scraper, "_fetch_html", stub)
            products = await scraper.fetch_category(
                "https://books.toscrape.com/catalogue/page-1.html", max_pages=2)
        assert len(products) == 2

    async def test_max_pages_limit(self):
        calls = 0

        async def stub(client, url):
            nonlocal calls
            calls += 1
            return _html(
                make_card(f"P{calls}", f"p{calls}_1000/index.html", "i.jpg"),
                next_href="next.html",
            )

        with _zero_delays():
            mp = pytest.MonkeyPatch()
            mp.setattr(scraper, "_fetch_html", stub)
            products = await scraper.fetch_category(
                "https://books.toscrape.com/catalogue/page-1.html", max_pages=2)
        assert calls == 2
        assert len(products) == 2

    async def test_stops_on_no_next(self):
        async def stub(client, url):
            return _html(
                make_card("A", "a_1000/index.html", "a.jpg"),
                next_href=None,
            )

        with _zero_delays():
            mp = pytest.MonkeyPatch()
            mp.setattr(scraper, "_fetch_html", stub)
            products = await scraper.fetch_category(
                "https://books.toscrape.com/catalogue/page-1.html", max_pages=10)
        assert len(products) == 1

    async def test_max_pages_lt_1(self):
        with pytest.raises(ValueError, match=">= 1"):
            await scraper.fetch_category(max_pages=0)

    async def test_disallowed_host(self):
        with pytest.raises(ScraperError):
            await scraper.fetch_category(category_url="https://evil.com/x")

    async def test_empty_listing_raises(self):
        async def stub(client, url):
            return _html()

        with _zero_delays():
            mp = pytest.MonkeyPatch()
            mp.setattr(scraper, "_fetch_html", stub)
            with pytest.raises(ScraperError, match="не найдено ни одного"):
                await scraper.fetch_category(
                    "https://books.toscrape.com/catalogue/page-1.html", max_pages=1)
