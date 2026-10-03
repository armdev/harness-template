# air-harness documentation · документация

Static documentation of air-harness in two languages. The pages are plain Markdown with Mermaid diagrams and
render directly on GitHub. · Статическая документация air-harness на двух языках: обычный Markdown с диаграммами
Mermaid, отображается прямо на GitHub.

| # | English | Русский | What it answers · О чём |
|---|---|---|---|
| 1 | [What is a harness?](en/01-what-is-a-harness.md) | [Что такое harness?](ru/01-what-is-a-harness.md) | guides vs. sensors, why a product · гайды и сенсоры, почему продукт |
| 2 | [How to use](en/02-how-to-use.md) | [Как пользоваться](ru/02-how-to-use.md) | run.sh, the loop, stages, agents, LLM, troubleshooting · запуск, цикл, стадии, агенты, LLM, проблемы |
| 3 | [Use cases](en/03-use-cases.md) | [Сценарии использования](ru/03-use-cases.md) | eleven end-to-end scenarios · одиннадцать сквозных сценариев |
| 4 | [Implemented architecture](en/04-architecture.md) | [Реализованная архитектура](ru/04-architecture.md) | planes, stages, feedback loops, reference system, decisions · плоскости, стадии, контуры, эталонная система, решения |
| 5 | [Components](en/05-components.md) | [Компоненты](ru/05-components.md) | every component, its responsibility, inputs and outputs · каждый компонент, ответственность, входы и выходы |
| 6 | [Low-level design](en/06-low-level-design.md) | [Низкоуровневый дизайн](ru/06-low-level-design.md) | runner algorithms, file formats, rules, protocols, schema, sequences · алгоритмы, форматы, правила, протоколы, схема, последовательности |
| 7 | [Demo](en/07-demo.md) | [Демо](ru/07-demo.md) | walkthrough GIF and screenshots of a real run · GIF-обзор и скриншоты реального запуска |

![air-harness demo](assets/demo-en.gif)

**Quick start · Быстрый старт**

```bash
./run.sh          # run everything, print every URL · запустить всё и вывести все адреса
./help.sh         # the guide in your terminal · руководство в терминале
```

Related: [README](../README.md) · [AGENTS.md](../AGENTS.md) · [harness/HARNESS.md](../harness/HARNESS.md) (design
notes) · [harness/CHANGELOG.md](../harness/CHANGELOG.md).

The documentation describes the code at the time of writing; when they disagree, the code and `harness.yaml`
win — please fix the page. · Документация описывает код на момент написания; при расхождении правы код и
`harness.yaml` — исправьте страницу.
