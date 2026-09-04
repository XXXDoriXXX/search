# Швидка перевірка за 2 хвилини

```bash
git clone -b claude/product-data-parser-g61ar7 https://github.com/XXXDoriXXX/search.git && cd search
pip install -r requirements.txt

# 1. Офлайн-демо з пастками (копії помилки, сусідня модель, конфлікт гарантії). Працює без мережі та ключів.
python3 fixtures/demo/build.py
python3 -m pte "Шуруповерт Bosch GSR 12V-35 FC Professional solo" --offline --fixtures fixtures/demo/index.json --trace --json out.json

# 2. Тести та метрики прийняття
python3 -m pytest -q
python3 eval/run_eval.py

# 3. Live: реальний веб (DuckDuckGo + Wikidata працюють без ключів)
python3 -m pte "Bosch GSR 12V-35 FC" --tier-a bosch-professional.com --tier-b icecat.biz --trace --json live.json

# 4. Live з Google (serper.dev) і Brave, плюс LLM-екстрактор для сторінок виробника
export SERPER_API_KEY=... BRAVE_API_KEY=... ANTHROPIC_API_KEY=...
python3 -m pte "Makita DGA504Z" --tier-a makita.de makita.com --mode deep --json live.json

# 5. Порівняння з Perplexity на тому самому golden set
export PERPLEXITY_API_KEY=...
python3 eval/baselines/perplexity.py
python3 eval/run_eval.py --live --baseline eval/baselines/out/perplexity.jsonl
```

Готовий результат кроку 1 лежить у `examples/demo-run.json` (повний JSON з доказами) та `examples/demo-run.txt` (консольний підсумок і trace).
