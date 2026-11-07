export function supportedLocale(value: unknown): "ru" | "en" | null {
  if (typeof value !== "string" || !value) return null
  try {
    const language = new Intl.Locale(value.replaceAll("_", "-")).language
    return language === "ru" || language === "en" ? language : null
  } catch {
    return null
  }
}

export function browserLocale(): "ru" | "en" {
  const languages = typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language]
  for (const language of languages) {
    const supported = supportedLocale(language)
    if (supported) return supported
  }
  return "en"
}
