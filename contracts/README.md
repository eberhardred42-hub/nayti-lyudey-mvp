# Contracts v1 (эталоны)

Эта папка содержит **JSON-эталоны** (reference examples) для контрактов v1.
Они не исполняются кодом напрямую, но используются как:

- ориентир структуры артефактов (что где лежит, какие поля ожидаем)
- быстрый чек при отладке (сравнение фактических артефактов с эталоном)
- словарь `kind` (минимально поддерживаемые типы артефактов)

## Два слоя: `user_result` и `trace`

В v1 мы разделяем артефакты на два слоя:

- `user_result` — то, что можно показывать пользователю и/или использовать как "building blocks" результата
- `trace` — технический след построения (вход ML/LLM, запросы/ответы, качество, манифест)

Эталон объединённого пакета: [contracts/hiring_pack.v1.json](hiring_pack.v1.json)

## Minimum kinds (утверждённый набор)

### User-facing

- `free_report_json`
- `free_report_md`

### Building blocks

- `role_snapshot_json`
- `sourcing_pack_json`
- `screening_script_json`
- `budget_reality_check_json`
- `scorecard_json` (сразу с anchors 1–5)

### Trace

- `ml_job_input`
- `llm_request`
- `llm_response`
- `quality_report`
- `manifest`

## Backward compatibility (Stage 7.3)

Если встречаются legacy-kinds из старых стадий, v1 сохраняет обратную совместимость через поле:

- `meta.legacy_kind`

Допустимые значения legacy (если они попадаются):

- `tasks_summary`
- `screening_questions`
- `sourcing_pack`

Пример: артефакт `sourcing_pack_json` может иметь `meta.legacy_kind = "sourcing_pack"`.

## Эталоны (файлы)

- [contracts/vacancy_profile.v1.json](vacancy_profile.v1.json)
- [contracts/free_report_json.v1.json](free_report_json.v1.json)
- [contracts/role_snapshot_json.v1.json](role_snapshot_json.v1.json)
- [contracts/sourcing_pack_json.v1.json](sourcing_pack_json.v1.json)
- [contracts/screening_script_json.v1.json](screening_script_json.v1.json)
- [contracts/budget_reality_check_json.v1.json](budget_reality_check_json.v1.json)
- [contracts/scorecard_json.v1.json](scorecard_json.v1.json)
- [contracts/quality_report.v1.json](quality_report.v1.json)
- [contracts/manifest.v1.json](manifest.v1.json)
- [contracts/hiring_pack.v1.json](hiring_pack.v1.json)

## Как использовать для отладки (curl)

Пример: получить `free_report_json` из backend и сравнить с эталоном.

1) Создать сессию:

```bash
curl -s -X POST http://localhost:8000/sessions \
  -H 'Content-Type: application/json' \
  -d '{"profession_query":"Senior Python Developer"}'
```

2) Пройти короткий флоу (минимально):

```bash
# старт
curl -s -X POST http://localhost:8000/chat/message \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<session_id>","type":"start","text":null}'

# выбрать "Есть текст вакансии"
curl -s -X POST http://localhost:8000/chat/message \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<session_id>","type":"reply","text":"Есть текст вакансии"}'

# отправить текст вакансии
curl -s -X POST http://localhost:8000/chat/message \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<session_id>","type":"reply","text":"..."}'
```

3) Забрать отчёт:

```bash
curl -s 'http://localhost:8000/report/free?session_id=<session_id>' | python3 -m json.tool
```

Сравнение делается вручную: по ключам и типам полей (headline/sections/status/min-max и т.д.).

Примечание: `free_report_md` — это markdown-строка; она не имеет отдельного `.v1.json` эталона, но присутствует как `kind` в манифесте и в объединённом `hiring_pack`.
