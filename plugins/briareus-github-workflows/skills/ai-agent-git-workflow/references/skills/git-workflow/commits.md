# Коммиты

Формируй логические коммиты по завершённым изменениям, а не по каждой попытке.
Просмотри фактический staged diff; убедись, что в нём нет чужих, случайных
или несвязанных файлов. Сообщение описывает полезный смысл изменения,
а не служит отчётом о процессе.

Если проект не установил иной формат, используй Conventional Commits:

```text
<type>[optional scope]: <short imperative summary>

<body explaining meaningful changes and why, when needed>

[optional footer]
```

- Заголовок — конкретный, на английском, в повелительном наклонении,
  обычно до 50–72 символов; без точки, заглушек `update`, `fix` или `wip`.
- Тип выбирай по главному эффекту: `feat`, `fix`, `refactor`, `perf`,
  `test`, `docs`, `style`, `build`, `ci`, `chore`, `revert`.
  В монорепозитории `scope` обязателен и указывает сервис или компонент;
  в обычном репозитории он необязателен, если местные правила не строже.
- Тело нужно, когда заголовка недостаточно для понимания значимых
  изменений, причин, контрактов или ограничений. Для тривиального diff
  достаточно заголовка. Не перечисляй построчно файлы и операции.
- При наличии тела отделяй его пустой строкой; footer используй для
  ссылок на Issue, breaking changes и других необходимых метаданных.
- Несовместимость отмечай `!` и `BREAKING CHANGE:` с объяснением
  последствия и требуемой миграции.

Примеры:

```text
docs(git): define issue and pull request lifecycle

Keep task state in Issues and prefer local validation before publication.
Clarify branch cleanup and separate reviewer ownership.
```

```text
docs: fix broken skill link
```
