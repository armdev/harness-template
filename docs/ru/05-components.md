# 5. Компоненты

## 5.1 Карта репозитория

```
run.sh  help.sh               точки входа продукта
AGENTS.md  CLAUDE.md          точки входа для агентов
harness.yaml                  манифест (гайды + сенсоры)
harness.mk  compose.harness.yml   цели harness; контейнеры сенсоров
Makefile                      цели продукта (+ include harness.mk)
harness/                      сам harness
docker-compose.yml  .env.example  архитектура и конфигурация эталонной системы
services/  libs/common/       код приложения
db/migrations/                Flyway
contract/  eval/  tools/      спецификация, оценка поиска, образ тестовых инструментов
infra/prometheus/             конфигурация скрейпа, правила алертов
.claude/  .githooks/  .github/workflows/   интеграция с агентом, git и CI
docs/                         эта документация
```

## 5.2 Компоненты harness

| Компонент | Путь | Ответственность | Вход → выход |
|---|---|---|---|
| Манифест | `harness.yaml` | объявляет каждый гайд и сенсор как данные | — → читает раннер |
| Раннер | `harness/harness.py` | команды `run`, `selftest`, `coverage`, `stats`, `list`; запускает сенсоры, классифицирует результаты, пишет отчёт и журнал | манифест, env → `.harness/` |
| Образ раннера | `harness/Dockerfile` | закреплённые инструменты: ruff, semgrep, vulture, pip-audit, pytest, PyYAML, git | — → `air-harness-runner:<ver>` |
| Контейнеры сенсоров | `compose.harness.yml` | `harness` (плоскость static) и `harness-live` (плоскость live) из одного образа | репозиторий (ro) → `/out` |
| Цели make | `harness.mk` | точки входа стадий, перезапуск одного сенсора, selftest, coverage, stats, тесты harness | — |
| Сенсор топологии | `harness/sensors/topology_check.py` | проверяет `docker-compose.yml` на согласованность: T1–T9 | compose, файл алертов, пример env → замечания |
| Сенсор миграций | `harness/sensors/migrations_check.py` | правила истории Flyway M1–M5 | `db/migrations`, git → замечания |
| Сенсор ревью | `harness/sensors/review.py` | LLM применяет рубрику к диффу | дифф, рубрика, промпт → замечания (рекомендательно) |
| Правила semgrep | `harness/rules/semgrep/python.yml` | правила организации, сообщения которых говорят, что писать вместо | код → замечания |
| Белый список vulture | `harness/rules/vulture_whitelist.py` | имена, используемые фреймворком, которые выглядят мёртвыми | — |
| Засеянные дефекты | `harness/sensors/fixtures/` | доказывают, что сенсор срабатывает (`# expect: <rule>`) и молчит (`# expect: clean`) | — |
| Рубрика | `harness/review/RUBRIC.md` | R1–R9: одна рубрика для агента (вперёд) и ревьюера (назад) | — |
| Навыки | `harness/skills/*/SKILL.md` | процедуры: new-service, new-endpoint, db-migration, new-topic, harness-report, harness-steer | — |
| Промпты | `harness/prompts/` | системные промпты ревьюера и судьи; шаблоны для агента; промпты следующих шагов 01–08 | — |
| Stop-хук | `harness/hooks/agent-stop.sh` | не даёт агенту завершиться, пока статические сенсоры красные | JSON хука в stdin → код 0/2 |
| Тесты harness | `harness/tests/` | тесты раннера и сенсоров | — |
| Журнал изменений | `harness/CHANGELOG.md` | версии и ожидаемый эффект новых правил при первом запуске | — |

### Сенсоры

| id | Вид | Плоскость | Стадии | Блокирует | Команда |
|---|---|---|---|---|---|
| topology | computational | static | pre-commit, pipeline | да | `topology_check.py docker-compose.yml` |
| migrations | computational | static | pre-commit, pipeline | да | `migrations_check.py db/migrations` |
| ruff | computational | static | pre-commit, pipeline | да | `ruff check services libs contract eval` |
| semgrep-local | computational | static | pre-commit, pipeline | да | `semgrep scan --config harness/rules/semgrep` |
| review-agent | inferential | live | pre-commit | нет | `review.py` |
| unit | computational | host | integration, pipeline | да | `make test` |
| contract | computational | host | integration, pipeline | да | `make contract` |
| eval | computational | host | pipeline | да | `make eval` |
| prom-rules | computational | host | pipeline | да | `promtool check rules` |
| dead-code | computational | static | continuous | нет | `vulture … --min-confidence 80` |
| deps-audit | computational | live | continuous | нет | `harness/sensors/deps_audit.py` (pip-audit по каждому файлу requirements) |

### Гайды

`AGENTS.md`, шесть навыков, `RUBRIC.md`, сообщения правил semgrep, `harness/prompts/`, `contract/README.md`,
`eval/README.md` — 12 гайдов в манифесте; каждый связан хотя бы с одним сенсором, кроме двух процессных
навыков (`harness-report`, `harness-steer`), которые `harness-coverage` честно показывает как FF-ONLY.

## 5.3 Продуктовый интерфейс

| Компонент | Ответственность |
|---|---|
| `run.sh` | проверка окружения (docker, compose, make, свободные порты) → `make up[-observability]` → smoke-тест (создать → прочитать → найти) → опционально стадии harness → адреса → следующие шаги. Режимы `--check`, `--full`, `--llm`, `--urls`, `--down`, `--no-observability`. |
| `help.sh` | руководство в терминале: `run`, `commands`, `urls`, `harness`, `agent`, `prompts`, `config`, `troubleshoot`; `prompt <n>` выводит промпт; подставляет `{{task}}` и `{{report_md}}`. |
| `Makefile` | `up`, `up-observability`, `down`, `ps`, `logs`, `build`, `test`, `contract`, `eval`, `llm`, `clean`, `purge`, `help`. |

## 5.4 Компоненты эталонной системы

| Компонент | Путь | Ответственность |
|---|---|---|
| Общая библиотека | `libs/common/common/` | `service_auth` (подписывающий клиент Ed25519, верификатор, зависимость FastAPI), `telemetry` (`create_app`: JSON-логи, request id, `/healthz`, `/metrics`, HTTP-метрики), `keygen` (генерация идентичностей), `events` (`EventConsumer`: цикл Kafka-консьюмера — коммит после обработчика, пропуск некорректных событий, повтор при сбое) |
| gateway | `services/gateway/app.py` | публичные маршруты `/api/posts` (создание, список по автору), `/api/posts/{id}`, `/api/search`, `/api/notifications`; подписанное проксирование; `/` → `/docs` |
| content | `services/content/app.py` | `POST /posts`, `GET /posts/{id}`, `GET /posts?author=`; пишет в `content.posts`; публикует `content.post.created` |
| search | `services/search/app.py`, `indexer.py` | `GET /search` (фильтры по автору и тегу); `EventConsumer` с обработчиком, делающим upsert в `search.documents`; ранжирование полнотекстового поиска Postgres |
| notify | `services/notify/app.py`, `consumer.py` | `GET /outbox`; `EventConsumer` с обработчиком, записывающим одну строку `notify.outbox` на пост (идемпотентно) |
| Миграции | `db/migrations/V1..V7` | роли `content_svc`, `search_svc`, `notify_svc`; схемы `content`, `search`, `notify`; таблицы, индексы, теги, права |
| One-shot-сервисы | `docker-compose.yml` | `storage-init` (структура DATA_DIR), `service-keys` (идентичности), `migrate` (Flyway), `kafka-init` (топики) |
| Инфраструктура | `docker-compose.yml` | `postgres`, `kafka` (KRaft), `prometheus` (профиль), `ollama` (профиль) |
| Контрактные тесты | `contract/` | спецификация публичного API и границы аутентификации (32 теста) |
| Unit-тесты | `libs/common/tests/` | подпись, проверка, подмена идентичности, изменение тела, рассинхрон часов, идемпотентность keygen |
| Eval | `eval/` | корпус и запросы, `run_eval.py`, `baseline.json` |
| Образ tools | `tools/Dockerfile` | pytest, httpx, PyYAML, `libs/common` для контейнеров contract, unit и eval |
| Наблюдаемость | `infra/prometheus/` | задания скрейпа и алерты up / доля ошибок / задержка на сервис |

## 5.5 Интеграции

| Компонент | Путь | Ответственность |
|---|---|---|
| Claude Code | `CLAUDE.md`, `.claude/settings.json`, `.claude/skills/*` (симлинки) | импортирует AGENTS.md, открывает навыки, регистрирует Stop-хук, разрешает команды harness |
| git-хук | `.githooks/pre-commit` | `make harness-static` перед каждым коммитом |
| CI | `.github/workflows/harness.yml` | сборка раннера → тесты harness, coverage, selftest → статические сенсоры → `./run.sh --full`; отчёт в сводке джоба и как артефакт; ночью стадия continuous |

Далее: [Низкоуровневый дизайн](06-low-level-design.md)
