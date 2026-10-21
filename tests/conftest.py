"""Общие фикстуры: строители HTML в разметке books.toscrape.com."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from schemas import Product

# --- Шаблоны разметки (точная структура books.toscrape.com) -----------------

_CARD = """\
<article class="product_pod">
  <div class="image_container">
    <a href="{href}"><img src="{img}" class="thumbnail" alt="{name}"></a>
  </div>
  <p class="star-rating {rating}"><span class="icon-star"></span></p>
  <h3><a href="{href}" title="{title}">{short_name}</a></h3>
  <div class="product_price">
    <p class="price_color">{price}</p>
  </div>
</article>
"""


def make_card(name: str, href: str, img: str,
              *, title: str | None = None, short_name: str | None = None,
              rating: str = "Three", price: str = "£51.77") -> str:
    """Одна карточка ``article.product_pod`` как на books.toscrape.com."""
    return _CARD.format(
        href=href,
        img=img,
        name=name,
        title=title if title is not None else name,
        short_name=short_name if short_name is not None else f"{name[:10]} ...",
        rating=rating,
        price=price,
    )


def make_listing_html(cards: Sequence[str],
                      breadcrumbs: Sequence[str] = ("Books",),
                      next_href: str | None = "page-2.html") -> str:
    """Полная HTML-страница каталога с ``cards`` и хлебными крошками."""
    crumbs: list[str] = ["<li><a href=\"index.html\">Home</a></li>"]
    for item in breadcrumbs:
        crumbs.append(f'<li class="active">{item}</li>')
    crumbs_html = "<ul class=\"breadcrumb\">" + "".join(crumbs) + "</ul>"

    pager = '<ul class="pager">'
    pager += '<li class="current"><span>Page 1 of 50</span></li>'
    if next_href:
        pager += f'<li class="next"><a href="{next_href}">next</a></li>'
    pager += "</ul>"

    return f"""\
<!DOCTYPE html>
<html>
<head><title>Books</title></head>
<body>
{crumbs_html}
{"".join(cards)}
{pager}
</body>
</html>
"""


# --- Фикстуры продуктов ----------------------------------------------------

@pytest.fixture()
def sample_products() -> list[Product]:
    """Реалистичный список товаров для тестов экспорта и API."""
    return [
        Product(
            category_lvl1="Books",
            subcategory_path="Books",
            name="A Light in the Attic",
            image_urls="https://books.toscrape.com/media/cache/fe/72/fe72f0532301ec28892ae79a629a293c.jpg",
            product_url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
            sku="SKU-C752FCF23AFC",
        ),
        Product(
            category_lvl1="Books",
            subcategory_path="Fiction",
            name="Tipping the Velvet",
            image_urls="https://books.toscrape.com/media/cache/2b/80/2b8004260513034b00b235d5c0a99560.jpg",
            product_url="https://books.toscrape.com/catalogue/tipping-the-velvet_969/index.html",
            sku="SKU-A1B2C3D4E5F6",
        ),
    ]


@pytest.fixture()
def tmp_export_dir(tmp_path: Path) -> Path:
    """Временная директория для тестов экспорта/загрузки файлов."""
    d = tmp_path / "exports"
    d.mkdir()
    return d
