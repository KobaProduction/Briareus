# Подключение MCP Briareus V1

Каждый MCP подключается отдельно. Названия и английские описания ниже можно
копировать в форму подключения своего MCP-клиента без изменений. Они не зависят
от расположения ноды или способа её развёртывания.

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
| Briareus V1 / Coolify | Manage applications, services, and deployments through Coolify. | [coolify.png](../assets/brand/services/coolify.png) |
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

## Первое подключение Serena

Используйте строку **Briareus V1 / Serena** из таблицы и адрес Serena из раздела
**«Подключение»**. Для работы с исходниками также подключите **Briareus V1 / Server**:
оба сервиса используют общее рабочее пространство.

После авторизации:

1. Вызовите `list_projects`, чтобы увидеть уже зарегистрированные проекты.
2. Если нужного проекта нет, подготовьте его папку через Server или доступные
   инструменты работы с репозиториями. Папка должна существовать внутри рабочего
   пространства Server.
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
