"""Pydantic-модели, общие для парсера, FastAPI-слоя и экспорта в CSV."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- Константы PoC ---------------------------------------------------------

DEFAULT_CATEGORY_URL = "https://books.toscrape.com/catalogue/page-1.html"
DEFAULT_MAX_PAGES = 1
MAX_PAGES_LIMIT = 50

# Ограничение хоста защищает PoC от SSRF: парсим только целевой сайт.
ALLOWED_HOSTS = frozenset({"books.toscrape.com", "www.books.toscrape.com"})


class Product(BaseModel):
    """Нормализованная карточка товара."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    category_lvl1: str = Field(
        ...,
        description='Категория верхнего уровня, например "Books"',
        examples=["Books"],
    )
    subcategory_path: str = Field(
        ...,
        description='Путь подкатегории через " > ", например "Fiction > Fantasy"',
        examples=["Fiction > Fantasy"],
    )
    name: str = Field(
        ...,
        description="Название товара",
        examples=["A Light in the Attic"],
    )
    image_urls: str = Field(
        ...,
        description="Абсолютная ссылка на изображение товара",
        examples=[
            "https://books.toscrape.com/media/cache/fe/72/fe72f0532301ec28892ae79a629a293c.jpg"
        ],
    )
    product_url: str = Field(
        ...,
        description="Абсолютная ссылка на страницу товара",
        examples=[
            "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
        ],
    )
    sku: str = Field(
        ...,
        description=(
            "Артикул товара: UPC со страницы товара либо детерминированный "
            "суррогат для PoC"
        ),
        examples=["SKU-1F2E3D4C5B6A"],
    )


class ParseRequest(BaseModel):
    """Тело запроса ``POST /parse``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    category_url: str = Field(
        default=DEFAULT_CATEGORY_URL,
        description="URL страницы каталога для парсинга",
        examples=[DEFAULT_CATEGORY_URL],
    )
    max_pages: int = Field(
        default=DEFAULT_MAX_PAGES,
        ge=1,
        le=MAX_PAGES_LIMIT,
        description=(
            "Сколько страниц пагинации обойти. 1 — только стартовая страница "
            "(каждая следующая стоит ~1 секунду задержки)"
        ),
    )

    @field_validator("category_url")
    @classmethod
    def _validate_category_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("URL категории должен начинаться с http:// или https://")
        if parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError(
                "PoC-парсер работает только с books.toscrape.com, "
                f"получен хост: {parsed.hostname!r}"
            )
        return value


class ParseResponse(BaseModel):
    """Ответ ``POST /parse``."""

    status: Literal["success"] = Field(
        default="success",
        description="Статус выполнения запроса",
    )
    items_count: int = Field(
        ...,
        ge=0,
        description="Количество собранных товаров",
    )
    csv_file: str = Field(
        ...,
        description="Имя сохранённого CSV-файла (доступен через GET /download/{csv_file})",
        examples=["products_20261021_214500.csv"],
    )
