let token = ""

export function setCsrfToken(value: string): void {
  token = value
}

export function getCsrfToken(): string {
  return token
}
