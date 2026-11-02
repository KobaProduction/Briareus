<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from "vue";
import { useI18n } from "vue-i18n";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import {
  finishPasswordSetup,
  preparePasswordSetup,
  recoverPasswordSetup,
} from "../api/password-setup";
import type { PasswordPolicy } from "../model/password-setup";

const formId = useId();
const _props = defineProps<{ mode: "invitation" | "recovery" }>();
const emit = defineEmits<{ back: [] }>();
const { locale } = useI18n();
const link = ref(""),
  password = ref(""),
  confirmation = ref(""),
  email = ref("");
const prepared = ref(false),
  busy = ref(false),
  done = ref(false),
  notice = ref("");
const policy = ref<PasswordPolicy>({});
const passwordRules = computed(() =>
  [
    `Длина: ${policy.value.length_min ?? 1}–${policy.value.length_max ?? 256} символов.`,
    ...(
      [
        ["include_lower_case", "строчных букв"],
        ["include_upper_case", "заглавных букв"],
        ["include_digits", "цифр"],
        ["include_special", "специальных символов"],
      ] as const
    )
      .filter(([key]) => (policy.value[key] ?? 0) > 0)
      .map(([key, label]) => `Не менее ${policy.value[key]} ${label}.`),
  ].join(" "),
);
let controller: AbortController | null = null;
function setupFailure(error: unknown): string {
  const code = error instanceof Error ? error.message : "";
  const messages: Record<string, string> = {
    RAUTHY_INVITATION_MAIL_UNCONFIGURED:
      "Отправка почты не настроена. Администратору необходимо настроить SMTP Rauthy.",
    SETUP_CODE_INVALID_OR_EXPIRED:
      "Ссылка или код недействительны, истекли либо уже привязаны к другому сеансу.",
    SETUP_PROVIDER_REJECTED:
      "Провайдер отклонил пароль или требует MFA. Проверьте правила пароля и подготовьте ссылку заново.",
    SETUP_OUTCOME_UNCONFIRMED:
      "Результат не подтверждён. Сначала попробуйте войти с новым паролем.",
  };
  return locale.value === "ru"
    ? messages[code] || "Провайдер недоступен. Повторите попытку после восстановления связи."
    : code || "Provider unavailable";
}
async function run(action: "prepare" | "finish" | "recovery") {
  if (busy.value) return;
  busy.value = true;
  notice.value = "";
  const request = new AbortController();
  controller = request;
  const timer = setTimeout(() => request.abort(), 65000);
  try {
    if (action === "prepare") {
      policy.value = await preparePasswordSetup(link.value, request.signal);
      prepared.value = true;
    } else if (action === "finish") {
      await finishPasswordSetup(password.value, request.signal);
      password.value = "";
      confirmation.value = "";
      link.value = "";
      done.value = true;
    } else {
      await recoverPasswordSetup(email.value, request.signal);
      notice.value =
        locale.value === "ru"
          ? "Запрос принят. Если учётная запись существует, провайдер обработает восстановление. Доставка письма не подтверждена."
          : "Request accepted. The provider processes recovery if the account exists. Email delivery is unconfirmed.";
    }
  } catch (error) {
    notice.value = setupFailure(error);
    if (action === "finish") prepared.value = false;
  } finally {
    clearTimeout(timer);
    busy.value = false;
    controller = null;
  }
}
onBeforeUnmount(() => {
  controller?.abort();
  password.value = "";
  confirmation.value = "";
  link.value = "";
});
</script>
<template>
  <section class="space-y-5 rounded-2xl border border-border bg-card p-7">
    <h1 class="text-xl font-semibold">
      {{ mode === "invitation" ? "Регистрация по приглашению" : "Восстановление доступа" }}
    </h1>
    <p v-if="done" role="status" class="text-sm">
      Пароль принят провайдером. Теперь войдите с email и новым паролем.
    </p>
    <template v-else>
      <form
        v-if="mode === 'recovery' && !prepared"
        class="space-y-3"
        @submit.prevent="run('recovery')"
      >
        <label class="block text-sm" :for="`${formId}-email`"
          >Электронная почта<Input
            :id="`${formId}-email`"
            v-model="email"
            type="email"
            autocomplete="email"
            required
            :disabled="busy"
          /></label
        >
        <Button :disabled="busy || !email" class="w-full">Запросить восстановление</Button>
      </form>
      <form v-if="!prepared" class="space-y-3" @submit.prevent="run('prepare')">
        <p class="text-sm text-muted-foreground">
          Скопируйте ссылку из письма, не открывая её, или вставьте код в формате ID:код. Установка
          пароля проходит здесь.
        </p>
        <label class="block text-sm" :for="`${formId}-link`"
          >Ссылка или код из письма<Input
            :id="`${formId}-link`"
            v-model="link"
            autocomplete="off"
            required
            :disabled="busy"
            maxlength="1024"
          /></label
        >
        <Button variant="outline" :disabled="busy || !link" class="w-full">Продолжить</Button>
      </form>
      <form v-else class="space-y-3" @submit.prevent="run('finish')">
        <p class="text-sm text-muted-foreground">{{ passwordRules }}</p>
        <label class="block text-sm" :for="`${formId}-password`"
          >Новый пароль<Input
            :id="`${formId}-password`"
            v-model="password"
            type="password"
            autocomplete="new-password"
            required
            maxlength="256"
            :disabled="busy"
          /></label
        >
        <label class="block text-sm" :for="`${formId}-confirmation`"
          >Повторите пароль<Input
            :id="`${formId}-confirmation`"
            v-model="confirmation"
            type="password"
            autocomplete="new-password"
            required
            maxlength="256"
            :disabled="busy"
          /></label
        >
        <Button :disabled="busy || !password || password !== confirmation" class="w-full"
          >Сохранить пароль</Button
        >
      </form>
    </template>
    <p v-if="notice" role="status" class="text-sm text-muted-foreground">{{ notice }}</p>
    <Button variant="ghost" :disabled="busy" @click="emit('back')">Вернуться ко входу</Button>
  </section>
</template>
