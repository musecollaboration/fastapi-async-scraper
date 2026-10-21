"""FastAPI-приложение: запуск парсинга каталога и выдача CSV."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
# Задел под статические ассеты: сейчас Tailwind подключён через CDN.
from fastapi.staticfiles import StaticFiles  # noqa: F401

from exporter import export_to_csv
from schemas import ParseRequest, ParseResponse
from scraper import ScraperError, fetch_category

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR / "exports"
INDEX_FILE = BASE_DIR / "index.html"

app = FastAPI(
    title="Books To Scrape Parser",
    description=(
        "PoC парсера каталога books.toscrape.com: сбор карточек товаров, "
        "выгрузка в CSV и скачивание файла."
    ),
    version="0.1.0",
)


def _build_filename() -> str:
    """Имя файла с UTC-меткой времени, чтобы выгрузки не перезаписывались."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"products_{stamp}.csv"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Отдаёт минималистичный веб-интерфейс парсера."""
    if not INDEX_FILE.is_file():
        raise HTTPException(status_code=500, detail="index.html не найден")
    return FileResponse(INDEX_FILE, media_type="text/html")


@app.get("/health", summary="Проверка живости сервиса")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/parse",
    response_model=ParseResponse,
    summary="Собрать каталог и сохранить CSV",
    responses={
        400: {"description": "Некорректный URL категории"},
        502: {"description": "Ошибка загрузки или капча на стороне сайта"},
    },
)
async def parse_category(payload: ParseRequest) -> ParseResponse:
    """Парсит каталог, сохраняет CSV и возвращает сводку."""
    logger.info(
        "Старт парсинга: url=%s, max_pages=%s",
        payload.category_url,
        payload.max_pages,
    )

    try:
        products = await fetch_category(
            payload.category_url,
            max_pages=payload.max_pages,
        )
    except ScraperError as exc:
        # Наружу — 502: проблема на стороне источника, а не клиента.
        logger.error("Парсинг не удался: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    filename = _build_filename()
    csv_path = await asyncio.to_thread(
        export_to_csv,
        products,
        EXPORT_DIR / filename,
    )
    logger.info("Сохранено %s товаров в %s", len(products), csv_path)

    return ParseResponse(
        status="success",
        items_count=len(products),
        csv_file=filename,
    )


@app.get(
    "/download/{filename}",
    response_class=FileResponse,
    summary="Скачать ранее сохранённый CSV",
    responses={404: {"description": "Файл не найден"}},
)
async def download_csv(filename: str) -> FileResponse:
    """Отдаёт CSV из каталога ``exports``."""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Некорректное имя файла")

    path = EXPORT_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")

    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        filename=safe_name,
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
