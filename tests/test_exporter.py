"""Тесты модуля exporter.py — выгрузка в CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from exporter import CSV_ENCODING, CSV_SEPARATOR, COLUMN_TITLES, export_to_csv
from schemas import Product


# ---------- Базовые проверки ------------------------------------------------

def test_creates_file(tmp_path: Path, sample_products: list[Product]):
    dst = tmp_path / "out.csv"
    path = export_to_csv(sample_products, dst)
    assert path.is_file()
    assert path == dst


def test_returns_path(tmp_path: Path, sample_products):
    path = export_to_csv(sample_products, tmp_path / "a.csv")
    assert isinstance(path, Path)


def test_creates_parent_dirs(tmp_path: Path, sample_products):
    nested = tmp_path / "a" / "b" / "c" / "out.csv"
    path = export_to_csv(sample_products, nested)
    assert path.is_file()


# ---------- Кодировка и разделитель -----------------------------------------

def test_bom_utf8_sig(tmp_path: Path, sample_products):
    path = export_to_csv(sample_products, tmp_path / "bom.csv")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM отсутствует"


def test_semicolon_separator(tmp_path: Path, sample_products):
    path = export_to_csv(sample_products, tmp_path / "sep.csv")
    raw = path.read_bytes().decode("utf-8-sig")
    lines = raw.strip().split("\n")
    # Заголовки и данные должны содержать ";"
    assert ";" in lines[0]
    assert ";" in lines[1]


def test_column_order(tmp_path: Path, sample_products):
    path = export_to_csv(sample_products, tmp_path / "cols.csv")
    raw = path.read_bytes().decode("utf-8-sig")
    header = raw.strip().split("\n")[0]
    expected = ";".join(COLUMN_TITLES.values())
    assert header == expected


# ---------- Содержимое CSV --------------------------------------------------

def test_roundtrip(sample_products, tmp_path: Path):
    """CSV читается обратно pandas с теми же значениями."""
    path = export_to_csv(sample_products, tmp_path / "rt.csv")
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    assert len(df) == 2
    assert df["Наименование"].iloc[0] == "A Light in the Attic"
    assert df["Категория"].iloc[1] == "Books"
    assert df["Подкатегория"].iloc[1] == "Fiction"


def test_empty_list(tmp_path: Path):
    path = export_to_csv([], tmp_path / "empty.csv")
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    assert len(df) == 0
    assert list(df.columns) == list(COLUMN_TITLES.values())


def test_russian_text_preserved(tmp_path: Path):
    ru = Product(
        category_lvl1="Книги",
        subcategory_path="Фантастика",
        name="Мастер и Маргарита",
        image_urls="https://example.com/m.jpg",
        product_url="https://example.com/m_1.html",
        sku="SKU-RU12345678",
    )
    path = export_to_csv([ru], tmp_path / "ru.csv")
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    assert df["Наименование"].iloc[0] == "Мастер и Маргарита"


def test_semicolon_in_field_quoted(tmp_path: Path):
    """Значение с «;» должно корректно кавычиться pandas."""
    p = Product(
        category_lvl1="Books",
        subcategory_path="A;B",
        name="Test",
        image_urls="https://x.com/i.jpg",
        product_url="https://x.com/t_1.html",
        sku="SKU-QQ11",
    )
    path = export_to_csv([p], tmp_path / "q.csv")
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    assert df["Подкатегория"].iloc[0] == "A;B"


# ---------- Константы -------------------------------------------------------

def test_encoding_constant():
    assert CSV_ENCODING == "utf-8-sig"


def test_separator_constant():
    assert CSV_SEPARATOR == ";"


def test_column_titles_keys_match_product():
    for key in COLUMN_TITLES:
        assert key in Product.model_fields
