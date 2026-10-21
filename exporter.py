"""Сохранение собранных товаров в CSV-файл."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from schemas import Product

# Порядок ключей задаёт порядок колонок в CSV.
COLUMN_TITLES: dict[str, str] = {
    "category_lvl1": "Категория",
    "subcategory_path": "Подкатегория",
    "name": "Наименование",
    "image_urls": "Ссылка на фото",
    "product_url": "Ссылка на товар",
    "sku": "Артикул",
}

CSV_SEPARATOR = ";"
CSV_ENCODING = "utf-8-sig"


def export_to_csv(
    products: list[Product],
    filename: str | Path = "products.csv",
) -> Path:
    """Выгружает товары в CSV (``utf-8-sig``, разделитель ``;``).

    :param products: список товаров; пустой список даст файл только с шапкой.
    :param filename: путь к файлу (родительские каталоги создаются автоматически).
    :return: фактический путь к сохранённому файлу.
    """
    rows = [product.model_dump() for product in products]
    frame = pd.DataFrame(rows, columns=list(COLUMN_TITLES))
    frame = frame.rename(columns=COLUMN_TITLES)

    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        sep=CSV_SEPARATOR,
        encoding=CSV_ENCODING,
        index=False,
    )
    return path
