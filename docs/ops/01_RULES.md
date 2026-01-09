# Rules (docs/ops)

## A) Release rules
- Каждая продуктовая задача = VERSION +1 + запись в README changelog.
- Merge только в main (через PR → main; если direct push принят — фиксировать факт и причины в README).
- DEV deploy auto на push main.
- DEV smoke warn-only (не валит деплой).
- PROD deploy manual only.
- Никаких долгих смоуков на обычных релизах.
- Любая задача = тесты + README update, если меняет user-flow.
- Источник правды = README Vision + docs/ops/01_RULES.md.

## B) LLM rules
- Никакого silent mock при LLM_REQUIRE_KEY=true.
- DEV acceptance всегда проверяет реальный LLM ping.
- LLM provider switch только через env DEV_LLM_* / PROD_LLM_*.

## C) Documents rules
- Платные документы не генерим до оплаты.
- Списание строго за успешный рендер (или debit->refund при fail).
- Документы/рендеры храним только в MinIO/S3, а в БД — ключи/мета.

## D) Payments rules
- Только int копейки, без float.
- Вебхуки идемпотентны (idempotency_key).
- Ledger должен быть правдой (audit).

## E) GitHub Actions rules
- Любой manual workflow обязан иметь `on: workflow_dispatch:`
- Acceptance команда:
  `gh workflow view <id|name> --yaml | find "workflow_dispatch"`

## F) Observability / logging rules (namespace)
- Trace events префиксы: auth.*, llm.*, brief.*, doc.*, payment.*
- Payload без секретов, текст только truncated+sha256+len.

## G) Repo hygiene (НОВОЕ правило)
- Запрещено коммитить zip/pdf/docx/рендеры/бинарники/outputs в git.
- Артефакты хранить в MinIO/S3, в git — только исходники и маленькие текстовые fixtures для тестов (json/yaml) до разумного размера.

## H) Forbidden moves
- Нельзя добавлять workflow, который валит DEV деплой по smoke.
- Нельзя включать silent mock на DEV при require-key.
- Нельзя менять user-flow без обновления README Vision.
- Нельзя генерить платные документы до оплаты.
