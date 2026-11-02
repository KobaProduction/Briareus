import { type ComputedRef, computed, ref, watch } from "vue";
import { readColumnLayout, writeColumnLayout } from "./column-layout-storage";
import type { DataTableColumn } from "./types";

interface ColumnLayoutController<Field extends string> {
  ordered: ComputedRef<DataTableColumn<Field>[]>;
  visible: ComputedRef<DataTableColumn<Field>[]>;
  hidden: ComputedRef<string[]>;
  toggle(id: string): void;
  move(id: string, direction: number): void;
  reset(): void;
}
/** Preferences contain column keys only; never table records or authority. */
export function useColumnLayout<Field extends string>(
  columns: () => DataTableColumn<Field>[],
  key: () => string,
): ColumnLayoutController<Field> {
  const order = ref<string[]>([]);
  const explicitHidden = ref<string[]>([]);
  const shown = ref<string[]>([]);
  const hidden = computed(() => [
    ...new Set([
      ...explicitHidden.value,
      ...columns()
        .filter((column) => column.defaultHidden && !shown.value.includes(column.key))
        .map((column) => column.key),
    ]),
  ]);
  watch(
    key,
    (value) => {
      const saved = readColumnLayout(value);
      order.value = saved?.order ?? [];
      explicitHidden.value = saved?.hidden ?? [];
      shown.value = saved?.shown ?? [];
    },
    { immediate: true },
  );
  const ordered = computed(() => {
    const ranks = new Map(order.value.map((id, index) => [id, index]));
    return [...columns()].sort((a, b) => (ranks.get(a.key) ?? 1000) - (ranks.get(b.key) ?? 1000));
  });
  const visible = computed(() => {
    const selected = ordered.value.filter((column) => !hidden.value.includes(column.key));
    return selected.length ? selected : ordered.value.slice(0, 1);
  });
  function save(): void {
    writeColumnLayout(key(), {
      order: order.value,
      hidden: explicitHidden.value,
      shown: shown.value,
    });
  }
  function toggle(id: string): void {
    if (hidden.value.includes(id)) {
      explicitHidden.value = explicitHidden.value.filter((key) => key !== id);
      shown.value = [...new Set([...shown.value, id])];
    } else if (visible.value.length > 1) {
      explicitHidden.value = [...explicitHidden.value, id];
      shown.value = shown.value.filter((key) => key !== id);
    }
    save();
  }
  function move(id: string, direction: number): void {
    const ids = ordered.value.map((column) => column.key);
    const index = ids.indexOf(id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= ids.length) return;
    const current = ids[index];
    const next = ids[target];
    if (current === undefined || next === undefined) return;
    [ids[index], ids[target]] = [next, current];
    order.value = ids;
    save();
  }
  function reset(): void {
    order.value = [];
    explicitHidden.value = [];
    shown.value = [];
    save();
  }
  return { ordered, visible, hidden, toggle, move, reset };
}
