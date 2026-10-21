"""Тесты FastAPI-приложения: main.py — эндпоинты и веб-интерфейс."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from exporter import CSV_ENCODING, CSV_SEPARATOR
from schemas import Product
from scraper import CaptchaDetectedError

client = TestClient(main.app)


# ---------- GET / -----------------------------------------------------------

class TestIndex:
    def _get_index(self):
        return client.get("/")

    def test_serves_html(self):
        r = self._get_index()
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Парсер каталога" in r.text

    def test_has_form(self):
        r = self._get_index()
        assert 'id="parse-form"' in r.text

    def test_has_category_url_input(self):
        r = self._get_index()
        assert 'id="category-url"' in r.text

    def test_has_max_pages_input(self):
        r = self._get_index()
        assert 'id="max-pages"' in r.text

    def test_has_spinner(self):
        r = self._get_index()
        assert 'id="spinner"' in r.text

    def test_has_result_and_error_blocks(self):
        r = self._get_index()
        assert 'id="result"' in r.text
        assert 'id="error"' in r.text

    def test_index_missing_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "INDEX_FILE", tmp_path / "nope.html")
        r = client.get("/")
        assert r.status_code == 500


# ---------- GET /health -----------------------------------------------------

class TestHealth:
    def test_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------- GET /docs -------------------------------------------------------

class TestDocs:
    def test_swagger_available(self):
        r = client.get("/docs")
        assert r.status_code == 200


# ---------- POST /parse -----------------------------------------------------

class TestParse:
    def test_success(self, tmp_export_dir, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_DIR", tmp_export_dir)
        fake = [
            Product(
                category_lvl1="Books",
                subcategory_path="Fiction",
                name="Test",
                image_urls="https://x.com/i.jpg",
                product_url="https://x.com/t_1.html",
                sku="SKU-TT",
            ),
        ]

        async def stub(*args, **kwargs):
            return fake

        monkeypatch.setattr(main, "fetch_category", stub)
        r = client.post("/parse", json={"category_url": "https://books.toscrape.com/catalogue/page-1.html", "max_pages": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["items_count"] == 1
        assert data["csv_file"] is not None
        csv_path = tmp_export_dir / data["csv_file"]
        assert csv_path.is_file()

    def test_default_body(self, tmp_export_dir, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_DIR", tmp_export_dir)

        async def stub(*args, **kwargs):
            return []

        monkeypatch.setattr(main, "fetch_category", stub)
        r = client.post("/parse", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_bad_host_422(self):
        r = client.post("/parse", json={"category_url": "https://evil.com/x"})
        assert r.status_code == 422

    def test_max_pages_0_422(self):
        r = client.post("/parse", json={"max_pages": 0})
        assert r.status_code == 422

    def test_max_pages_51_422(self):
        r = client.post("/parse", json={"max_pages": 51})
        assert r.status_code == 422

    def test_scraper_error_502(self, monkeypatch):
        async def stub(*args, **kwargs):
            raise main.ScraperError("Сайт недоступен")

        monkeypatch.setattr(main, "fetch_category", stub)
        r = client.post("/parse", json={})
        assert r.status_code == 502
        assert "Сайт недоступен" in r.json()["detail"]

    def test_captcha_error_502(self, monkeypatch):
        async def stub(*args, **kwargs):
            raise CaptchaDetectedError("Защита")

        monkeypatch.setattr(main, "fetch_category", stub)
        r = client.post("/parse", json={})
        assert r.status_code == 502
        assert "Защита" in r.json()["detail"]


# ---------- GET /download/{filename} ----------------------------------------

class TestDownload:
    def _write_csv(self, tmp_export_dir, name="test.csv", content="Категория;Наименование\nA;B"):
        """Помещает CSV-файл в EXPORT_DIR и возвращаем путь."""
        path = tmp_export_dir / name
        path.write_bytes(content.encode(CSV_ENCODING))
        return path

    def test_serves_csv(self, tmp_export_dir, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_DIR", tmp_export_dir)
        self._write_csv(tmp_export_dir)
        r = client.get("/download/test.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert r.headers["content-disposition"].startswith("attachment")

    def test_bom_preserved(self, tmp_export_dir, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_DIR", tmp_export_dir)
        bom = "Категория;Наименование\nA;B".encode("utf-8")
        csv_bytes = b"\xef\xbb\xbf" + bom
        (tmp_export_dir / "bom.csv").write_bytes(csv_bytes)
        r = client.get("/download/bom.csv")
        assert r.status_code == 200
        assert r.read() == csv_bytes

    def test_not_found(self, tmp_export_dir, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_DIR", tmp_export_dir)
        r = client.get("/download/missing.csv")
        assert r.status_code == 404

    def test_non_csv_extension(self, tmp_export_dir, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_DIR", tmp_export_dir)
        (tmp_export_dir / "notes.txt").write_text("data")
        r = client.get("/download/notes.txt")
        assert r.status_code == 400

    def test_path_traversal_blocked(self, tmp_export_dir, monkeypatch):
        monkeypatch.setattr(main, "EXPORT_DIR", tmp_export_dir)
        # Путь с попыткой выхода за пределы EXPORT_DIR
        r = client.get("/download/..%2f..%2fetc%2fpasswd")
        # Результат: либо 400 (защита сработала), либо 404 (файл не найден)
        # Но точно НЕ 200 и НЕ утечка системного файла
        assert r.status_code != 200
        assert "root:" not in r.text
