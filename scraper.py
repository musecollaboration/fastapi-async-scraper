"""Асинхронный сбор карточек товаров с каталога books.toscrape.com.

Архитектура написана «как будто на сайте есть капча»:
* задержка между запросами (``asyncio.sleep``);
* реалистичные заголовки браузера;
* повторы с экспоненциальным backoff на 429/5xx и сетевые ошибки;
* детектор капчи/челленджа с выделенным исключением.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from schemas import (
    ALLOWED_HOSTS,
    DEFAULT_CATEGORY_URL,
    DEFAULT_MAX_PAGES,
    Product,
)

logger = logging.getLogger(__name__)

# --- Настройки обхода ------------------------------------------------------

REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CAPTCHA_MARKERS = (
    "captcha",
    "are you a robot",
    "cf-challenge",
    "access denied",
    "unusual traffic",
)


class ScraperError(RuntimeError):
    """Базовая ошибка сбора данных (сеть, HTTP-статус, разметка)."""


class CaptchaDetectedError(ScraperError):
    """Сайт вернул страницу-заглушку вместо каталога."""


# --- HTTP-слой -------------------------------------------------------------


def _build_headers() -> dict[str, str]:
    """Заголовки, имитирующие обычный браузер."""
    return {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Connection": "keep-alive",
    }


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ScraperError("URL категории должен начинаться с http:// или https://")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ScraperError(
            "PoC-парсер работает только с books.toscrape.com, "
            f"получен: {parsed.hostname!r}"
        )


def _looks_like_captcha(html: str) -> bool:
    """Грубая эвристика: ищем маркеры антибот-заглушки в HTML."""
    lowered = html.lower()
    return any(marker in lowered for marker in CAPTCHA_MARKERS)


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str:
    """GET с паузой, повторами и проверкой на капчу."""
    last_error: httpx.HTTPError | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Пауза перед каждым запросом — эмуляция «человеческого» темпа.
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code
            if status in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                delay = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "HTTP %s на %s (попытка %s/%s), повтор через %.1f с",
                    status,
                    url,
                    attempt,
                    MAX_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise ScraperError(f"HTTP {status} при запросе {url}") from exc
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                delay = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "Сетевая ошибка на %s (попытка %s/%s): %s; повтор через %.1f с",
                    url,
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise ScraperError(
                f"Не удалось загрузить {url} после {MAX_ATTEMPTS} попыток: {exc}"
            ) from exc

        html = response.text
        if _looks_like_captcha(html):
            raise CaptchaDetectedError(
                f"Вместо каталога получена антибот-заглушка: {url}. "
                "Нужна ротация прокси/ручное решение капчи."
            )
        return html

    # Сюда попадаем, только если цикл исчерпан по retry-ветке.
    raise ScraperError(f"Не удалось загрузить {url}: {last_error}")


# --- Парсинг разметки ------------------------------------------------------


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _parse_breadcrumbs(soup: BeautifulSoup) -> tuple[str, str]:
    """Возвращает (category_lvl1, subcategory_path) из хлебных крошек.

    Последний элемент крошек на сайте — ``<li class="active">Fiction</li>``
    без ссылки, поэтому берём текст ``<a>``, если он есть, иначе текст ``<li>``.
    """
    crumbs: list[str] = []
    for item in soup.select("ul.breadcrumb li"):
        link = item.find("a")
        text = _clean_text(link.get_text() if link is not None else item.get_text())
        if text and text.lower() not in {"home", "all products"}:
            crumbs.append(text)

    if not crumbs:
        # Для страницы «All products» категорий в крошках нет.
        return "Books", "Books"

    category_lvl1 = crumbs[0]
    remainder = crumbs[1:]
    subcategory_path = " > ".join(remainder) if remainder else category_lvl1
    return category_lvl1, subcategory_path


def _make_sku(product_url: str) -> str:
    """Детерминированный суррогат UPC.

    Настоящий UPC лежит на странице товара, поэтому в PoC мы не делаем
    дополнительных запросов: UUIDv5 от URL стабилен между запусками
    (в отличие от ``random``), что позволяет сравнивать выгрузки.
    """
    digest = uuid.uuid5(uuid.NAMESPACE_URL, product_url).hex[:12].upper()
    return f"SKU-{digest}"


def _parse_card(card: Tag, page_url: str) -> Product | None:
    """Преобразует ``<article class="product_pod">`` в ``Product``."""
    link = card.select_one("h3 a")
    if link is None or not link.get("href"):
        logger.warning("Карточка без ссылки на товар пропущена")
        return None

    product_url = urljoin(page_url, str(link["href"]))
    title_raw = link.get("title")
    name = _clean_text(title_raw if isinstance(title_raw, str) else None)
    name = name or _clean_text(link.get_text())

    image = card.select_one("img")
    image_src = str(image["src"]) if image is not None and image.get("src") else ""
    image_url = urljoin(page_url, image_src) if image_src else ""

    product = Product(
        category_lvl1="",  # заполняется в _parse_listing из крошек
        subcategory_path="",
        name=name,
        image_urls=image_url,
        product_url=product_url,
        sku=_make_sku(product_url),
    )
    return product


def _next_page_url(soup: BeautifulSoup, page_url: str) -> str | None:
    next_link = soup.select_one("ul.pager li.next a")
    if next_link is None or not next_link.get("href"):
        return None
    return urljoin(page_url, str(next_link["href"]))


def _parse_listing(html: str, page_url: str) -> tuple[list[Product], str | None]:
    """Парсит страницу каталога: список товаров + ссылка на следующую."""
    soup = BeautifulSoup(html, "html.parser")
    category_lvl1, subcategory_path = _parse_breadcrumbs(soup)

    products: list[Product] = []
    for card in soup.select("article.product_pod"):
        product = _parse_card(card, page_url)
        if product is None:
            continue
        products.append(
            product.model_copy(
                update={
                    "category_lvl1": category_lvl1,
                    "subcategory_path": subcategory_path,
                }
            )
        )

    return products, _next_page_url(soup, page_url)


# --- Публичный API ---------------------------------------------------------


async def fetch_category(
    category_url: str = DEFAULT_CATEGORY_URL,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list[Product]:
    """Собирает товары с каталога, обходя до ``max_pages`` страниц.

    :param category_url: стартовая страница каталога.
    :param max_pages: ограничение пагинации (1 — только стартовая страница).
    :return: список :class:`~schemas.Product` без дублей по ``product_url``.
    :raises ScraperError: сетевая/HTTP-ошибка или проблемы с разметкой.
    :raises CaptchaDetectedError: сайт вернул антибот-заглушку.
    """
    if max_pages < 1:
        raise ValueError("max_pages должен быть >= 1")
    _validate_url(category_url)

    products: list[Product] = []
    seen_urls: set[str] = set()
    page_url: str | None = category_url

    async with httpx.AsyncClient(
        headers=_build_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        for page_number in range(1, max_pages + 1):
            if page_url is None:
                break

            html = await _fetch_html(client, page_url)
            page_products, next_url = _parse_listing(html, page_url)

            fresh = [
                product
                for product in page_products
                if product.product_url not in seen_urls
            ]
            seen_urls.update(product.product_url for product in fresh)
            products.extend(fresh)

            logger.info(
                "Страница %s/%s (%s): найдено %s товаров, новых %s",
                page_number,
                max_pages,
                page_url,
                len(page_products),
                len(fresh),
            )
            page_url = next_url

    if not products:
        raise ScraperError(
            f"На странице {category_url} не найдено ни одного товара — "
            "изменилась разметка либо URL не является каталогом"
        )

    return products
