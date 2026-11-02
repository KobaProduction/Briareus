import { HAND_EFFECT_ACTIONS, type HandEffectScope } from "@/shared/lib/hand-effect-scope";
export interface PermissionGroup {
  id: string;
  title: string;
  actions: string[];
  operations: string[];
  tools: string[];
  system: boolean;
}
const moduleTitles: Record<string, string> = {
  files: "Файлы",
  terminal: "Терминал",
  web: "Браузер",
  reverse: "Анализ",
  svc: "Системы контроля версий",
  infrastructure: "Инфраструктура",
  integrations: "Подключения",
  variables: "Переменные",
  agents: "Агенты",
  project: "Система",
};
const actionTitles: Record<string, string> = {
  read: "Чтение",
  write: "Запись",
  execute: "Выполнение",
  access: "Доступ",
  import: "Импорт",
  manage: "Управление",
  use: "Использование",
};
function operationModules(operation: string, effects: readonly HandEffectScope[]): string[] {
  if (effects.length) return [...new Set(effects.map((scope) => scope.hand))];
  const candidates = Object.entries(HAND_EFFECT_ACTIONS)
    .filter(([, actions]) => (actions as readonly string[]).includes(operation))
    .map(([hand]) => hand);
  return [
    candidates.length === 1 ? (candidates[0] ?? operation) : (operation.split(".")[0] ?? operation),
  ];
}
function createGroup(id: string, operation: string): PermissionGroup {
  return {
    id,
    title: moduleTitles[id] || id,
    actions: [],
    operations: [],
    tools: [],
    system: operation === "project.metadata.read",
  };
}
function addOperation(
  group: PermissionGroup,
  operation: string,
  effects: readonly HandEffectScope[],
): void {
  const action = actionTitles[operation.split(".").at(-1) ?? ""] || operation;
  if (!group.actions.includes(action)) group.actions.push(action);
  if (!group.operations.includes(operation)) group.operations.push(operation);
  for (const scope of effects) {
    if (scope.hand === group.id && !group.tools.includes(scope.tool)) group.tools.push(scope.tool);
  }
}
/** Formats current owner evidence. Does not infer grants from a module name. */
export function presentPermissions(
  operations: readonly string[],
  scopes: readonly HandEffectScope[],
): PermissionGroup[] {
  const groups = new Map<string, PermissionGroup>();
  for (const operation of operations) {
    const effects = scopes.filter((scope) => scope.action === operation);
    for (const id of operationModules(operation, effects)) {
      const group = groups.get(id) ?? createGroup(id, operation);
      addOperation(group, operation, effects);
      groups.set(id, group);
    }
  }
  return [...groups.values()];
}
export function shortIdentifier(id: string): string {
  return id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id;
}
