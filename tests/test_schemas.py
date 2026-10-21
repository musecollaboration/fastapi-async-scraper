"""Тесты Pydantic-моделей: Product, ParseRequest, ParseResponse."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas import (
    ALLOWED_HOSTS,
    DEFAULT_CATEGORY_URL,
    DEFAULT_MAX_PAGES,
    MAX_PAGES_LIMIT,
    ParseRequest,
    ParseResponse,
    Product,
)


# ---------- Product --------------------------------------------------------


class TestProduct:
    """Валидация карточки товара."""

    def _kw(self):
        return dict(
            category_lvl1="Books",
            subcategory_path="Fiction > Fantasy",
            name="Test Book",
            image_urls="https://example.com/img.jpg",
            product_url="https://example.com/catalogue/test_1/index.html",
            sku="SKU-ABC123",
        )

    def test_valid_product(self):
        p = Product(**self._kw())
        assert p.name == "Test Book"

    def test_strips_whitespace(self):
        kw = self._kw()
        kw["name"] = "  Trimmed  "
        p = Product(**kw)
        assert p.name == "Trimmed"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            Product(**self._kw(), extra_field="nope")

    def test_missing_field(self):
        kw = self._kw()
        kw.pop("category_lvl1")
        with pytest.raises(ValidationError, match="category_lvl1"):
            Product(**kw)

    def test_all_fields_present(self):
        p = Product(**self._kw())
        assert p.category_lvl1 == "Books"
        assert p.subcategory_path == "Fiction > Fantasy"
        assert p.image_urls == "https://example.com/img.jpg"
        assert p.product_url == "https://example.com/catalogue/test_1/index.html"
        assert p.sku == "SKU-ABC123"


# ---------- ParseRequest ---------------------------------------------------


class TestParseRequest:
    """Валидация тела запроса POST /parse."""

    def test_default_values(self):
        req = ParseRequest()
        assert req.category_url == DEFAULT_CATEGORY_URL
        assert req.max_pages == DEFAULT_MAX_PAGES

    def test_custom_values(self):
        req = ParseRequest(
            category_url="https://books.toscrape.com/catalogue/page-5.html",
            max_pages=10,
        )
        assert req.max_pages == 10

    @pytest.mark.parametrize("url", [
        "https://books.toscrape.com/catalogue/page-1.html",
        "http://books.toscrape.com/catalogue/page-1.html",
        "https://www.books.toscrape.com/catalogue/page-1.html",
    ])
    def test_allowed_hosts(self, url):
        ParseRequest(category_url=url)

    def test_reject_foreign_host(self):
        with pytest.raises(ValidationError, match="только с books.toscrape.com"):
            ParseRequest(category_url="https://evil.com/page-1.html")

    def test_reject_non_http_scheme(self):
        for url in ["ftp://books.toscrape.com/", "javascript:alert(1)", "books.toscrape.com/"]:
            with pytest.raises(ValidationError, match="начинаться с http"):
                ParseRequest(category_url=url)

    def test_max_pages_bounds(self):
        ParseRequest(max_pages=1)
        ParseRequest(max_pages=50)

    def test_max_pages_zero(self):
        with pytest.raises(ValidationError, match="1"):
            ParseRequest(max_pages=0)

    def test_max_pages_exceeds_limit(self):
        with pytest.raises(ValidationError, match="50"):
            ParseRequest(max_pages=51)

    def test_max_pages_negative(self):
        with pytest.raises(ValidationError):
            ParseRequest(max_pages=-5)

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            ParseRequest(extra="nope")


# ---------- ParseResponse --------------------------------------------------


class TestParseResponse:
    """Ответ POST /parse."""

    def test_valid(self):
        r = ParseResponse(status="success", items_count=20, csv_file="out.csv")
        assert r.status == "success"
        assert r.items_count == 20

    def test_default_status(self):
        r = ParseResponse(items_count=0, csv_file="empty.csv")
        assert r.status == "success"

    def test_status_literal(self):
        with pytest.raises(ValidationError, match="status"):
            ParseResponse(status="failed", items_count=0, csv_file="x.csv")

    def test_items_count_ge_zero(self):
        ParseResponse(status="success", items_count=0, csv_file="f.csv")
        with pytest.raises(ValidationError, match="0"):
            ParseResponse(status="success", items_count=-1, csv_file="f.csv")

    def test_extra_ignored(self):
        """ParseResponse по умолчанию игнорирует дополнительные поля (Pydantic v2)."""
        r = ParseResponse(status="success", items_count=1, csv_file="f.csv", extra="x")
        assert r.status == "success"
