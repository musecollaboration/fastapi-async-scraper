# Books To Scrape Parser (PoC)

Реализация [технического задания](TASK.md) для асинхронного парсера каталога
[books.toscrape.com](https://books.toscrape.com/catalogue/page-1.html)
с REST-обёрткой на FastAPI и выгрузкой в CSV.

Архитектура написана так, будто на целевом сайте есть антибот-защита: реализованы
задержка между запросами, браузерные заголовки, ретраи с backoff и детектор капчи.
Все модули покрыты тестами на pytest (см. раздел [Тесты](#тесты)).

## Стек

* Python 3.10+
* FastAPI + Uvicorn
* httpx (async HTTP)
* BeautifulSoup4 (парсинг HTML)
* pandas (CSV-экспорт)
* Pydantic v2
* pytest + pytest-asyncio (тесты)

## Структура проекта

```
.
├── main.py           # FastAPI: GET / (UI), POST /parse, GET /download/{file}, GET /health
├── index.html        # минималистичный фронтенд: Tailwind CDN + vanilla JS
├── scraper.py        # fetch_category(): httpx + BeautifulSoup, ретраи, паузы, капча
├── schemas.py        # Pydantic-модели: Product, ParseRequest, ParseResponse
├── exporter.py       # export_to_csv(): pandas → utf-8-sig, разделитель ";"
├── requirements.txt
├── requirements-dev.txt  # зависимости для тестов (pytest, pytest-asyncio)
├── pytest.ini        # конфигурация pytest (asyncio_mode=auto)
├── tests/            # тесты: схемы, экспорт, парсер, API (101 тест)
├── exports/          # создаётся автоматически при первом экспорте
└── README.md
```

## Установка и запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn main:app --reload
```

Веб-интерфейс: <http://127.0.0.1:8000/> — форма с URL категории и количеством
страниц, лоадер, блок результата и ссылка «Скачать CSV».

Swagger UI: <http://127.0.0.1:8000/docs>

## Тесты

```bash
pip install -r requirements-dev.txt
python -m pytest
```

101 тест покрывает: валидацию Pydantic-моделей, формат CSV (кодировка, разделитель, заголовки), чистые функции парсера, ретраи с backoff, детектор капчи, пагинацию, дедупликацию и все эндпоинты FastAPI через TestClient.

## Эндпоинты

### `POST /parse`

Тело запроса (все поля опциональны):

```json
{
  "category_url": "https://books.toscrape.com/catalogue/page-1.html",
  "max_pages": 1
}
```

* `category_url` — стартовая страница каталога (по умолчанию страница 1 каталога
  `books.toscrape.com`; другие хосты отклоняются как SSRF-защита);
* `max_pages` — сколько страниц пагинации обойти, `1..50` (по умолчанию `1`).

Ответ:

```json
{
  "status": "success",
  "items_count": 20,
  "csv_file": "products_20261021_214500_123456.csv"
}
```

```bash
curl -X POST http://127.0.0.1:8000/parse \
  -H "Content-Type: application/json" \
  -d '{"category_url": "https://books.toscrape.com/catalogue/page-1.html", "max_pages": 2}'
```

Ошибки:

| Код | Причина |
|-----|---------|
| 422 | невалидное тело запроса (URL/диапазон `max_pages`) |
| 502 | сеть, HTTP-ошибка источника или антибот-заглушка |

### `GET /download/{csv_file}`

Отдаёт сохранённый CSV:

```bash
curl -OJ http://127.0.0.1:8000/download/products_20261021_214500_123456.csv
```

### `GET /health`

```json
{"status": "ok"}
```

## Как это работает

1. `fetch_category()` открывает `httpx.AsyncClient` с браузерными заголовками и
   таймаутом 20 с.
2. Перед каждым запросом — `asyncio.sleep(1)` (эмуляция «человеческого» темпа).
3. При `429/5xx` и сетевых сбоях — до 3 попыток с backoff `2 с × номер попытки`.
4. Если в HTML найден маркер капчи (`captcha`, `cf-challenge`, `are you a robot`,
   `unusual traffic`, `access denied`) — поднимается `CaptchaDetectedError`
   (наследник `ScraperError`), API отвечает `502`.
5. BeautifulSoup разбирает карточки `article.product_pod`: название — из `h3 a`
   (`title`), ссылки на картинку и товар — через `urljoin` к абсолютным.
6. Категории берутся из хлебных крошек страницы каталога:
   `Home > Books` → `category_lvl1="Books"`, `subcategory_path="Books"`;
   для страницы категории `Home > Books > Fiction` → `"Books"` / `"Fiction"`.
7. `sku` — детерминированный суррогат `SKU-<12 hex>` из `uuid.uuid5(NAMESPACE_URL, product_url)`.
   Настоящий UPC лежит на странице товара, но PoC не делает 20+ дополнительных
   запросов на страницу каталога.
8. Совпадения по `product_url` отбрасываются при обходе пагинации.

## Формат CSV

* кодировка `utf-8-sig`, разделитель `;` (открывается в Excel без пляски с кодировками);
* колонки: `Категория;Подкатегория;Наименование;Ссылка на фото;Ссылка на товар;Артикул`;
* при пустой выборке создаётся файл только с шапкой.

Пример:

```
Категория;Подкатегория;Наименование;Ссылка на фото;Ссылка на товар;Артикул
Books;Books;A Light in the Attic;https://books.toscrape.com/media/cache/fe/72/fe72f0532301ec28892ae79a629a293c.jpg;https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html;SKU-SKU-C752FCF23AFC
```

## Использование как библиотеки

```python
import asyncio

from exporter import export_to_csv
from scraper import fetch_category

products = asyncio.run(
    fetch_category("https://books.toscrape.com/catalogue/page-1.html", max_pages=2)
)
export_to_csv(products, "exports/books.csv")
print(len(products))
```

## Ограничения PoC

* Полный каталог — 1000 книг / 50 страниц: при `max_pages=50` обход займёт ~1 минуту
  только на паузах. Запускайте такие выгрузки в фоне.
* 5-звёздочный рейтинг, цена, наличие и описание не собираются — модель намеренно
  ограничена полями из ТЗ.
* UPC не настоящий: значения стабильны между запусками, но не равны UPC сайта.
* Нет прокси-ротации и решения капчи: детектор лишь сигнализирует о блокировке.
* CSV пишется в локальную папку `exports/`; для нескольких воркеров нужен общий
  volume или внешнее хранилище.
* Имя файла содержит UTC-метку времени (`products_YYYYmmdd_HHMMSS_ffffff.csv`).
