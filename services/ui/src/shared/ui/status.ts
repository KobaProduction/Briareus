export type StatusTone = 'neutral' | 'info' | 'warning' | 'success' | 'danger'

export const statusToneClasses: Record<StatusTone, string> = {
 neutral: 'border-zinc-500/25 bg-zinc-500/10 text-muted-foreground',
 info: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300',
 warning: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
 success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
 danger: 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
}
