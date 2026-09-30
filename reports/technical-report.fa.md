# گزارش فنی تحویل

| فیلد | مقدار |
|---|---|
| پروژه | خط لوله OCR و تولید داده اسناد با دقت و قابلیت ردیابی بالا |
| نوع گزارش | تحویل فنی و مهندسی |
| زبان | فارسی |
| تاریخ جلالی | ۱۴۰۵-۰۷-۰۸ |
| تاریخ میلادی | ۲۰۲۶-۰۹-۳۰ |
| نسخه | برنامه پیاده‌سازی افزایشی ۰.۱.۰ |
| مخزن | `E:\OCR` |
| revision مخزن | `6e78341` |
| وضعیت تحویل | پیاده‌سازی افزایشی یکپارچه و سخت‌سازی ایمنی راستی‌آزمایی/خروجی push شد؛ اعتبارسنجی خارجی مدل‌ها و زیرساخت باقی مانده است |

## دامنه و معماری

مخزن یک ماژولارمونولیت API-first بر پایه Python 3.12+، FastAPI، Pydantic v2، PyMuPDF، Pillow، پورت‌های نوع‌دار OCR/چیدمان/دست‌خط/جدول، ذخیره‌سازی محلی تغییرناپذیر، خروجی قطعی داده و لاگ ساخت‌یافته است. در نسخه ۰.۱.۰ رابط کاربری مرورگری ارائه نشده و معماری اپراتور آینده جداگانه مستند شده است.

ساختار استاندارد `Document -> Page -> Block -> Line -> Word` است. متن خام و نرمال‌شده جدا نگهداری می‌شوند. مختصات فضای مختصات خود را ثبت می‌کنند و هر خط منشأ موتور/مدل/نسخه، مقیاس اطمینان، DPI، مقیاس ناحیه، نوع پیش‌پردازش، منشأ منبع، وضعیت راستی‌آزمایی، پرچم عدم‌قطعیت و تاریخچه تلاش‌ها را حفظ می‌کند.

## تغییرات پیاده‌سازی‌شده

- ورود منبع، امضای فایل، نام فایل، حجم، تعداد صفحات و checksum منبع را اعتبارسنجی می‌کند.
- متن داخلی قابل اتکای PDF پیش از OCR به‌صورت native استخراج می‌شود.
- صفحات ترکیبی PDF متن native را حفظ کرده و نواحی تصویر را به OCR می‌فرستند.
- نواحی نیازمند OCR از crop و پیش‌پردازش محدود، retry متن ریز، آداپترهای قابل تعویض و نگاشت برگشت‌پذیر هندسه پشتیبانی می‌کنند.
- راستی‌آزمایی همه تلاش‌ها را نگه می‌دارد، اختلاف، اطمینان کم، متن ریز و ناسازگاری مقیاس اطمینان را علامت می‌زند و نبود backend را fail-closed مدیریت می‌کند.
- راستی‌آزمایی اکنون کلید evidence برابر `(backend_family, backend, model, model_version)` دارد، پایداری یک هویت را از اجماع مستقل جدا می‌کند و بدون مستقل شمردن variantهای پیش‌پردازش، شمارش و reason code قطعی ثبت می‌کند.
- validatorهای خط، سلول جدول، block، صفحه و سند اجازه نمی‌دهند `needs_review=true` همراه `accepted` یا `verified` باقی بماند و وضعیت والد را از evidence فرزندان منتقل می‌کنند.
- نرمال‌سازی فارسی قابل تنظیم است و متن خام را تغییر نمی‌دهد.
- خروجی داده شامل JSON استاندارد، متن ساده، Markdown، تصویر صفحه، برش خطوط، برچسب‌ها و manifest قطعی است.
- قلاب‌های کیفیت CER، WER، اطمینان، اختلاف، precision/recall تشخیص خط بر پایه IoU، ترتیب خواندن، تطبیق دقیق متن فیلد/سلول، نرخ بازبینی و بازیابی متن ریز را پوشش می‌دهند.
- API شناسه درخواست، محدودیت آپلود، خطاهای احراز هویت نوع‌دار، خطای امن، health/readiness و احراز هویت اجباری در staging/production را فراهم می‌کند.
- سخت‌سازی امنیتی شامل traversal، تغییرناپذیری منبع، محدودیت منابع، ایمنی subprocess، حذف داده حساس از لاگ، بازبینی الگوهای راز و آزمون‌های امنیتی است.
- حاکمیت امنیتی شامل قرارداد نگهداری، حذف احراز هویت‌شده و امن، staging خصوصی خروجی، audit بازبینی، محدودیت پیکسل تصویر و لاگ محتوای redacted است.
- عملیات تولید شامل تنظیمات device/load مدل و concurrency، قرارداد lazy model/capability، متریک محدود، hook ردیابی، readiness مبتنی بر قابلیت، جداسازی خطای صفحه، checkpoint صفحات تکمیل‌شده، profiler DPI/منابع، volumeهای non-root و حذف وزن مدل از image است.
- آرتیفکت‌های استقرار شامل `.env.example`، `.dockerignore`، `Dockerfile`، `compose.yaml`، گردش‌کار CI، به‌روزرسانی OpenAPI، مستند استقرار و راهنمای عملیات هستند.
- Phase 13 یک ممیزی قطعی و غیرحساس انتهابه‌انتها با ۱۱ سناریوی نماینده، اعتبارسنجی schema استاندارد، بررسی منشأ خط/سلول، بازتولیدپذیری متن خام/نرمال‌شده، مسیر ترکیبی چاپی/دست‌خط، تشدید و نگاشت متن ریز، نگهداری candidateها، وضعیت عدم‌قطعیت، خروجی قطعی و اسکن ضدالگو/امنیت اضافه می‌کند. گزارش آن در `docs/final-audit.md` تولید شده است.
- منشأ مدل در ممیزی: موجودی قابلیت تولید، `tesseract/tesseract-lstm@external` را در دسترس ندانست، `heuristic-projection/pillow-projection@1` را در دسترس گزارش کرد و آداپترهای HTR/جدول را غیرفعال گزارش کرد؛ benchmark مصنوعی نسخه‌های `embedded-text@1`، `fixture@1` و `synthetic-primary` را ثبت کرد.

## برنامه پیاده‌سازی افزایشی

موارد زیر در همان ماژولارمونولیت پیاده‌سازی شده‌اند. در دسترس بودن آداپترها و دقت مدل‌ها به محیط وابسته است و این گزارش ادعای کیفیت مدل ارائه نمی‌دهد.

| کارگروه | وضعیت | شاهد |
|---|---|---|
| ۰۱ ایمنی راستی‌آزمایی و خروجی | IMPLEMENTED | شواهد خانواده مستقل backend، خروجی ایمن برای بازبینی و اصلاحات الحاقی |
| ۰۲ استخراج جدول | IMPLEMENTED | آداپتر اختیاری PP-Structure، نگاشت typed سلول و fallback OCR چاپی |
| ۰۳ OCR چاپی ثانویه | IMPLEMENTED | آداپتر lazy PaddleOCR با پشتیبانی از شکل‌های خروجی ۲.x و ۳.x |
| ۰۴ HTR دست‌خط | IMPLEMENTED | آداپتر Transformers فقط با مدل محلی و خطای صریح نبود قابلیت |
| ۰۵ پیش‌پردازش پیشرفته | IMPLEMENTED | انتخاب profile نام‌گذاری‌شده و variant متن ریز با منشأ کامل |
| ۰۶ پشتیبانی DOCX | IMPLEMENTED | پاراگراف و page break native با اعتبارسنجی signature و مسیر تصویر |
| ۰۷ پشتیبانی XLSX/XLS | IMPLEMENTED | سلول native، shared string، مختصات و reader اختیاری XLS قدیمی |
| ۰۸ پشتیبانی PPTX | IMPLEMENTED | متن native اسلاید، هندسه و مسیر تصویرهای جاسازی‌شده |
| ۰۹ هوش اسنادی | IMPLEMENTED | schemaهای typed فیلد/موجودیت با پیوند evidence به span و cell منبع |
| ۱۰ بازبینی و اصلاح | IMPLEMENTED | اصلاحات audit‌شده و الحاقی با متن خام تغییرناپذیر |
| ۱۱ اجرای benchmark واقعی | IMPLEMENTED | فرمان پیش‌بینی pipeline با کنترل ground truth خارجی |
| ۱۲ سخت‌سازی Docker و timeout | IMPLEMENTED | extraهای اختیاری، image با کاربر non-root و محدودیت timeout/منابع |
| ۱۳ backendهای تولید توزیع‌شده | IMPLEMENTED | metadata در PostgreSQL، artifact در S3، صف Redis با acknowledgement و entrypoint worker |
| ۱۴ قالب‌های متنی افزوده | IMPLEMENTED | readerهای native با signature برای TXT، CSV، JSON و HTML |

## فایل‌ها و مؤلفه‌های اصلی

- تنظیمات و استقرار: pyproject.toml، .env.example، Dockerfile، compose.yaml و README.md.
- ورود منبع: src/ocr_platform/ingestion/source.py، service.py، office_reader.py و text_reader.py.
- OCR و ساختار: src/ocr_platform/ocr/backends/paddle.py، tables/paddle.py، handwriting/transformers.py، pipeline.py و verification/engine.py.
- حاکمیت و هوش اسنادی: src/ocr_platform/governance/review.py، intelligence/models.py، intelligence/engine.py و dataset/exporter.py.
- آداپترهای توزیع‌شده: database/postgres.py، storage/s3.py، workers/redis_queue.py، workers/factory.py و worker.py.
- benchmark و آزمون‌ها: benchmarks/predict.py، benchmarks/run.py، tests/ingestion/test_office_and_text_formats.py، tests/ocr/test_optional_adapters.py، tests/intelligence/ و tests/storage/test_distributed_adapters.py.
- مستندات و state: docs/phase13-program.md، docs/openapi.yaml، project-state.json، release-manifest.json و گزارش‌های دوزبانه.

## تصمیم‌های معماری

- نصب پایه بدون بسته‌های سنگین مدل یا دانلود خودکار قابل استفاده باقی می‌ماند.
- اتصال‌های OCR، HTR، جدول، metadata، artifact و queue پشت پورت‌های typed و آداپترهای lazy قرار دارند.
- متن native و ساختار Office پیش از OCR تصویری استخراج می‌شوند و نواحی تصویری نیازمند OCR بعدی به‌صورت صریح حفظ می‌شوند.
- سیاست بازبینی و خروجی کل شیء را بررسی می‌کند؛ خروجی پیش‌فرض متن/Markdown/manifest ساختاری صفحه/crop، خط یا سلول نیازمند بازبینی و evidence مسدودکننده را حذف می‌کند و `all_with_status` وضعیت/بازبینی را صریح نگه می‌دارد، در حالی که JSON canonical کامل باقی می‌ماند.
- secretها از hash تنظیمات حذف شده‌اند و شناسه‌ها و نام artifactها محدود و قطعی هستند.
- انتخاب صف، metadata و object store از طریق تنظیمات محیطی صریح است و حالت پیش‌فرض همان ماژولارمونولیت محلی است.

## شواهد اعتبارسنجی فعلی

| بررسی | نتیجه |
|---|---|
| PYTHONPATH=src pytest -q | PASS — ۲۴۲ موفق؛ دو هشدار deprecation وابستگی |
| python -m compileall -q src tests | PASS |
| ruff check src tests scripts | PASS |
| python -m pip check | PASS |
| python -m build --no-isolation | PASS |
| docker compose config | PASS |
| docker compose --profile distributed config | PASS |
| اعتبارسنجی ساختاری OpenAPI | PASS |
| بازبینی الگوهای راز | PASS — الگوی کلید خصوصی یا token شناخته‌شده یافت نشد |
| smoke مدل واقعی و runtimeهای HTR/جدول | NOT_RUN — runtime، وزن مدل یا executable اختیاری در دسترس نبود |
| benchmark دقت با ground truth خارجی | NOT_RUN — corpus خارجی برچسب‌دار و مجاز در مخزن وجود ندارد |
| pip-audit | NOT_RUN — ابزار در دسترس نبود |
| بررسی static type | NOT_RUN — checker تنظیم‌شده در دسترس نبود |
| build و smoke اجرای Docker | NOT_RUN — Docker daemon در دسترس نبود |
| استقرار خارجی | NOT_PERFORMED — هدف و اعتبارنامه‌ای مجاز نشده است |

## شواهد Task 01: استقلال راستی‌آزمایی و ایمنی خروجی

| نیازمندی | نتیجه |
|---|---|
| سه variant پیش‌پردازش یک Tesseract برای متن کم‌اطمینان، اجماع مستقل ایجاد نمی‌کنند | PASS — آزمون قطعی؛ شمارش مستقل ۱ و وضعیت نیازمند بازبینی انسانی باقی می‌ماند |
| خانواده‌های مستقل backend می‌توانند اجماع تنظیم‌شده را تأمین کنند | PASS — آزمون regression خانواده backend |
| نسخه مدل در هویت evidence مشارکت دارد | PASS — آزمون regression هویت نسخه‌دار |
| وضعیت بازبینی نمی‌تواند همراه وضعیت accepted/verified برای خط یا سلول باقی بماند | PASS — آزمون مدل leaf و تجمیع والد |
| خروجی پیش‌فرض و `all_with_status` سیاست ایمن دارند | PASS — آزمون متن، Markdown، manifest ساختاری صفحه، label برش، سلول جدول و evidence canonical |
| ترتیب candidate، منشأ، history و reason code حفظ می‌شوند | PASS — مجموعه آزمون regression راستی‌آزمایی/خروجی |

این تغییر در commit `6e78341` ثبت و به `origin/main` push شد.

## وضعیت baseline دوازده‌مرحله‌ای

| مرحله | وضعیت | شواهد |
|---|---|---|
| ۰۱ تحلیل پروژه | PASS | brief، نیازمندی‌ها، ریسک‌ها و baseline یکپارچگی |
| ۰۲ معماری طراحی و UI | PASS | tokenهای طراحی و معماری سطح اپراتور/API |
| ۰۳ معماری frontend | PASS_NOT_APPLICABLE | نسخه ۰.۱.۰ API-first و بدون frontend مرورگری |
| ۰۴ معماری backend | PASS | pipeline ماژولار، پورت‌های نوع‌دار، خطاها و تنظیمات |
| ۰۵ معماری پایگاه داده | PASS | پورت‌های persistence/storage و آداپتر محلی مستندشده |
| ۰۶ یکپارچه‌سازی API | PASS | endpoint FastAPI، قرارداد OpenAPI و اتصال واقعی pipeline |
| ۰۷ احراز هویت و مجوز | PASS | کلید سرویس، مقایسه constant-time و آزمون‌های منفی |
| ۰۸ امنیت کاربرد | PASS | مدل تهدید، اصلاحات و آزمون‌های regression امنیتی |
| ۰۹ آزمون نرم‌افزار | PASS | ۲۱۴ آزمون و پوشش کل ۸۶٪ |
| ۱۰ QA و رفع اشکال | PASS | بدون نقص باز P0/P1؛ اصلاح retry و صفحات ترکیبی |
| ۱۱ استقرار و تولید | PASS | ساخت بسته، Compose، حاکمیت و تنظیمات اعتبارسنجی شد؛ daemon داکر در دسترس نبود |
| ۱۲ بازبینی نهایی | PASS | ردیابی نیازمندی، یکپارچگی، امنیت، مشاهده‌پذیری و انتشار نهایی |
| ممیزی یکپارچه‌سازی Phase 13 | PASS | ۱۱/۱۱ سناریو موفق؛ ۱۸ خط و ۴ سلول؛ بررسی منشأ، schema، مسیرهای ترکیبی، عدم‌قطعیت، متن ریز، خروجی قطعی و ضدالگو موفق |

## شواهد اعتبارسنجی baseline قبلی

| بررسی | نتیجه |
|---|---|
| `python -m pytest -q --cov=ocr_platform --cov-report=term-missing` | PASS — ۲۱۴ موفق؛ پوشش کل ۸۶٪؛ ۲ هشدار deprecation وابستگی |
| `ruff check src tests scripts` | PASS |
| `python -m compileall -q src tests scripts` | PASS |
| `python -m pip check` | PASS |
| `python -m build --no-isolation` | PASS — sdist و wheel ساخته و محتوای wheel بررسی شد |
| `docker compose config` | PASS — topology محلی production-like parse شد |
| parse قرارداد OpenAPI | PASS |
| اسکن الگوی راز | PASS — موردی یافت نشد |
| ممیزی انتهابه‌انتها و ضدالگو | PASS — ۱۱/۱۱ سناریو؛ منشأ، خروجی قطعی، تشدید متن ریز و مرز آداپترها بررسی شد |
| `pip-audit` | NOT_RUN — ابزار نصب نشده است |
| آزمون واقعی Tesseract/مدل‌های اختیاری | NOT_RUN — executable یا وزن مدل در دسترس نبود |
| ساخت/اجرای Docker | NOT_RUN — daemon داکر در دسترس نبود |
| استقرار خارجی | NOT_PERFORMED — هدف و اعتبارنامه‌ای مجاز نشده است |
| راستی‌آزمایی مستقل Codex | NOT_RUN — verifier در دسترس نبود |

## بازبینی امنیت و عملیات

در محدوده پیاده‌سازی‌شده، مشکل امنیتی شناخته‌شده Critical یا High باقی نمانده است. محیط staging/production در صورت غیرفعال بودن احراز هویت یا نبود کلید، fail-closed می‌شود. کلیدهای سرویس همچنان به چرخش در secret manager و rate limit در gateway نیاز دارند. آداپتر artifact محلی جایگزین storage پایدار تولید نیست. مجوز مدل‌ها، benchmark دقت، load test، بازیابی صف توزیع‌شده، اسکن advisories، آزمون بازیابی backup با زیرساخت واقعی و استقرار واقعی، پیش‌نیازهای صریح باقی‌مانده هستند.

## بازبینی یکپارچگی و regression

مخزن در ابتدا greenfield بود و منبع، route، API، migration، آزمون، integration، asset یا تنظیم استقرار قبلی نداشت. هیچ عنصر محافظت‌شده‌ای حذف نشد. منبع، متن خام، خروجی نرمال‌شده، رفتار native-first، پورت‌های آداپتر، تاریخچه راستی‌آزمایی، manifestهای خروجی و پرچم‌های بازبینی باقی مانده‌اند. هیچ آزمونی برای عبور مصنوعی از gate ضعیف نشده است.

## دستورات تحویل

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
ruff check src tests scripts
python -m compileall -q src tests scripts
docker compose config
uvicorn ocr_platform.api.app:app --host 127.0.0.1 --port 8000
```

از `.env.example` به‌عنوان الگوی امن استفاده کنید و اعتبارنامه‌های تولید را از secret manager تزریق کنید. پیش از پردازش اسناد واقعی، آداپترهای انتخابی OCR/چیدمان/HTR و وزن مدل‌ها را نصب و پیکربندی کنید.
