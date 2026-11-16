# Подключение MCP Briareus V1

Каждый MCP подключается отдельно. Названия и английские описания ниже можно
копировать в форму подключения своего MCP-клиента без изменений. Они не зависят
от расположения ноды или способа её развёртывания.


## Что фактически настраивается сейчас

- **Карточка подключения в ChatGPT:** оператор задаёт имя, описание, адрес MCP,
  способ авторизации и изображение. Таблица ниже — рекомендуемые значения
  этих полей; это не автоматически доставляемые сервером навыки.
- **MCP server metadata:** общий конструктор
  `shared/hand_runtime/src/briareus_hand_runtime/runtime_common.py`
  сейчас создаёт `FastMCP(name, middleware=...)`, не задавая явно
  `instructions` и `version`. Gateway также создаёт свою FastMCP-фасадную
  поверхность без этих полей. Следовательно, общие инструкции Briareus
  пока не поставляются в MCP metadata из этих точек.
- **Инструменты:** объявления в `services/hands/**` задают названия,
  docstring-описания, схемы параметров и аннотации. Например, описание
  GitHub checkout сейчас допускает `projects/example/repo`; одной правки
  текста недостаточно без [проверки канонического пути в реализации](operations/git-and-worktrees.md).
- **Версии:** `version = "1.0.0"` в сервисных `pyproject.toml` — версия
  Python-пакета, не гарантированная версия MCP `serverInfo` и не версия
  устанавливаемого ChatGPT-плагина. Нужна отдельная политика версионирования.
- **Skills:** в исходниках Briareus V1 сейчас нет пакета `skills/*/SKILL.md`
  или `plugin.json`. Просто добавить `SKILL.md` на MCP-сервере недостаточно
  для автоматического появления навыка в подключении ChatGPT.

## Как связать MCP и навыки (план, не реализован)

1. Серверные ограничения (например, канонический checkout) реализовать и
   протестировать в обработчиках GitHub/GitLab/Server. Они действуют даже
   при игнорировании агентом текста инструкций.
2. В `build_private_mcp` и Gateway согласованно задавать краткие MCP
   `instructions` и явную версию; проверить, что они доходят до ChatGPT,
   а не теряются на фасаде или прокси.
3. Уточнить `description` каждого инструмента и его ограничения, прежде
   всего `github_checkout_repository` и `workspace_create`. Описания
   должны совпадать с реально реализованной валидацией.
4. Для повторяемых сценариев создать отдельные `skills/<name>/SKILL.md`:
   например, `checkout-and-review`, `safe-implementation`,
   `review-and-publish`. Навыки описывают порядок вызовов и критерии
   завершения; сами по себе не являются MCP policy enforcement.
5. Упаковать MCP и навыки как ChatGPT Plugin с `plugin.json`,
   `skills/` и `mcp.json` либо привязать уже зарегистрированные MCP
   через OpenAI-расширение и `.app.json`. Установить тестовый плагин,
   обновить его после изменения метаданных, проверить и позитивную,
   и негативную активацию навыков. Отдельно проверить, что сервер
   действительно отклоняет недопустимый путь.

См. официальные руководства:
[Build an MCP server](https://developers.openai.com/plugins/build/mcp-server),
[Build skills](https://developers.openai.com/plugins/build/skills),
[Package your plugin](https://developers.openai.com/plugins/build/plugins).

## Где взять картинки

Готовые картинки находятся в [assets/brand/services](../assets/brand/services).
В таблице у каждого MCP есть ссылка на его PNG. Откройте ссылку и скачайте
исходный файл: на GitHub используйте **Download raw file**. Затем загрузите этот
PNG в поле логотипа при добавлении MCP. Не используйте скриншот или исходник из
`sources/`: PNG уже содержит нужную рамку, прозрачность и укладывается в 10 000 байт.
SVG рядом с PNG предназначен для использования там, где поддерживается вектор.

## Названия, описания и логотипы

| Название | Description (English) | Картинка PNG |
| --- | --- | --- |
| Briareus V1 / Playwright | Automate browser interactions, navigate pages, inspect content, and capture screenshots with Playwright. | [playwright.png](../assets/brand/services/playwright.png) |
| Briareus V1 / Server | Work with workspace files, execute terminal commands, and manage background jobs. | [server.png](../assets/brand/services/server.png) |
| Briareus V1 / GitHub | Work with GitHub repositories, branches, commits, issues, and pull requests. | [github.png](../assets/brand/services/github.png) |
| Briareus V1 / GitLab | Work with GitLab projects, repositories, merge requests, and pipelines. | [gitlab.png](../assets/brand/services/gitlab.png) |
| Briareus V1 / SigNoz | Inspect application logs, traces, and metrics through SigNoz. | [signoz.png](../assets/brand/services/signoz.png) |
| Briareus V1 / Coolify | Inspect Coolify applications and redacted runtime logs, confirm scoped variable reads, and request authorized deployment or restart actions. | [coolify.png](../assets/brand/services/coolify.png) |
| Briareus V1 / Serena | Navigate and refactor code with semantic tools across projects in the shared Server workspace. | [serena.png](../assets/brand/services/serena.png) |
| Briareus V1 / radare2 | Inspect executable files, machine instructions, and program structure with radare2 tools in the shared Server workspace. | [radare2.png](../assets/brand/services/radare2.png) |
| Briareus V1 / Analyzer-R | Inspect program modules, machine instructions, control flow, and dependencies through a unified analysis interface. | [analysis-r.png](../assets/brand/services/analysis-r.png) |
| Briareus V1 / Ghidra | Inspect programs, generate C pseudocode, and manage program analysis projects with Ghidra. | [ghidra.png](../assets/brand/services/ghidra.png) |
| Briareus V1 / Analyzer G | Inspect program modules, generate C pseudocode, and recover behavior contracts through a unified analysis interface. | [analysis-g.png](../assets/brand/services/analysis-g.png) |

Описания анализаторов используют [словарь AI Agent Workflow](https://github.com/ArthurKoba/ai-agent-workflow/blob/main/prompts/projects/reverse-analysis.md#8-required-terminology):
program analysis, machine instructions, C pseudocode, behavior contracts.
Названия операций и идентификаторы инструментов при этом сохраняются точно.

**SigNoz** — название подключения наблюдаемости. **Analyzer-R** и **Analyzer G** —
отдельные подключения с унифицированным интерфейсом анализа; **radare2** и
**Ghidra** предоставляют инструменты соответствующих движков напрямую. Выбирайте
нужные подключения по задаче. Телеметрия фронтенда не является отдельным MCP.

## Порядок подключения

1. Войдите в свою панель Briareus и откройте раздел **«Подключение»**.
2. Найдите нужный доступный MCP и скопируйте его адрес из панели. Используйте
   полный адрес выбранного MCP, а не адрес главной страницы панели. Адрес
   индивидуален для вашей ноды, поэтому в этой инструкции он не задан.
3. В своём MCP-клиенте добавьте удалённое подключение. Укажите название и
   английское описание из таблицы, загрузите соответствующий PNG и вставьте
   скопированный адрес. Если клиент предлагает выбор авторизации, используйте OAuth.
4. Запустите подключение и войдите через предложенный сервер авторизации.
   У вашей учётной записи должен быть назначен доступ к выбранной ноде.
   Пароли и служебные токены в название, описание или адрес MCP не добавляются.
5. После возврата в клиент дождитесь получения списка инструментов. Проверьте
   подключение безопасным чтением: списком проектов, вкладок или другим доступным
   инструментом просмотра. Сам факт успешного входа ещё не подтверждает загрузку
   инструментов.
6. Повторите эти действия для остальных нужных MCP. Наличие сервиса в таблице
   не означает, что он включён на каждой ноде: доступность проверяется в панели.

Если клиент требует Client ID или не завершает OAuth, передайте администратору
точный текст ошибки. Регистрация OAuth-клиентов на сервере авторизации — настройка
оператора; пользовательский логотип или описание её не заменяют. Настройки
провайдера описаны в [документации OIDC](oidc.md).

## Serena (дополнительный, сейчас выключенный Hand)

Serena сейчас намеренно остановлена. Этот раздел оставлен как описание будущего
разрешённого подключения, **не как инструкция перезапускать сервис**. Если оператор
разрешит его использование, применяйте следующие правила.


Используйте строку **Briareus V1 / Serena** из таблицы и адрес Serena из раздела
**«Подключение»**. Для работы с исходниками также подключите **Briareus V1 / Server**:
оба сервиса используют общее рабочее пространство.

После авторизации:

Языковые серверы заранее устанавливает оператор через отдельный административный
терминал Server. Агентам общий каталог toolchains доступен для чтения и запуска,
без установки или обновления пакетов. При ошибке отсутствующих инструментов
передайте запрос оператору; [порядок подготовки](../services/hands/serena/README.md#operator-owned-tools)
описан отдельно. Для JavaScript-инструментов используется Bun.

1. Вызовите `list_projects`, чтобы увидеть уже зарегистрированные проекты.
2. Если проект не зарегистрирован, используйте **существующую** папку
   `/workspace/projects/<repository-name>` либо уже созданный Git worktree.
   Не создавайте отдельный клон или каталог по имени агента/задачи.
   Порядок проверки и переиспользования каталогов описан в
   [руководстве V1 по Git/worktree](operations/git-and-worktrees.md).
3. Вызовите `register_project`, передав `project_id` и `folder`. `folder` — путь
   существующей папки относительно рабочего пространства Server; `project_id` —
   стабильное имя проекта из строчных латинских букв, цифр, `_` и `-`, начинающееся
   с буквы и длиной до 63 символов.
4. В вызовах инструментов Serena указывайте этот `project_id`. Для разных проектов
   используются отдельные процессы и настройки; можно работать с несколькими
   проектами в одном MCP-подключении.

`stop_project` останавливает процесс проекта, сохраняя регистрацию и файлы.
`unregister_project` снимает регистрацию, сохраняя исходники. Первый вызов
инструментов проекта может занять больше времени из-за запуска языкового сервера.
