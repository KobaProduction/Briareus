<script setup lang="ts">
import {ArrowRight,FolderKanban,Network,ShieldCheck,Users} from 'lucide-vue-next'
import BrandMark from '@/shared/ui/BrandMark.vue'
import {Button} from '@/shared/ui/button'
import {Badge} from '@/shared/ui/badge'
import {Card,CardHeader,CardTitle,CardDescription,CardContent} from '@/shared/ui/card'

const capabilities=[
  {icon:Users,title:'Команды и проекты',text:'Личные и командные проекты объединяют участников, подключения и рабочие данные.'},
  {icon:ShieldCheck,title:'Агенты и сеансы',text:'Согласование доступа, ограниченные по времени разрешения и история действий агентов.'},
  {icon:Network,title:'Инструменты MCP',text:'Файлы, терминал, Web, системы контроля версий, инфраструктура и анализ в одном пространстве.'},
]
const layers=[
  {title:'Core',text:'Учётные записи, команды, проекты и разрешения.'},
  {title:'Ноды',text:'Рабочие пространства проектов и независимо обновляемые MCP-сервисы.'},
  {title:'Control Panel',text:'Управление ресурсами, согласованиями и событиями в реальном времени.'},
]
</script>
<template>
  <div class="min-h-screen bg-background text-foreground">
    <a href="#main-content" class="sr-only rounded-md bg-primary p-3 text-primary-foreground focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50">К основному содержанию</a>
    <header class="border-b">
      <div class="mx-auto flex min-h-16 max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <a href="/" aria-label="Briareus — главная" class="flex items-center gap-2.5 text-sm font-semibold tracking-tight"><BrandMark/>BRIAREUS</a>
        <nav aria-label="Навигация" class="flex flex-wrap items-center gap-1">
          <Button as-child variant="ghost" size="sm"><a href="#platform">Платформа</a></Button>
          <Button as-child variant="ghost" size="sm"><a href="#architecture">Архитектура</a></Button>
          <Button as-child size="sm"><a href="/panel/">Открыть панель<ArrowRight class="size-4"/></a></Button>
        </nav>
      </div>
    </header>
    <main id="main-content" class="mx-auto max-w-6xl space-y-16 px-4 py-12 sm:px-6 sm:py-16">
      <section aria-labelledby="intro-title" class="grid items-center gap-8 lg:grid-cols-[1.4fr_1fr]">
        <div class="space-y-5">
          <Badge variant="outline">Платформа MCP и AI-агентов · прототип</Badge>
          <h1 id="intro-title" class="max-w-2xl text-3xl font-semibold tracking-tight sm:text-5xl">Инструменты и агенты в пространстве ваших проектов</h1>
          <p class="max-w-xl text-base leading-relaxed text-muted-foreground">Briareus объединяет команды, AI-агентов и MCP-инструменты. Управляйте проектами, согласовывайте доступ и следите за выполнением задач из одной панели.</p>
          <div class="flex flex-wrap gap-2">
            <Button as-child><a href="/panel/">Перейти в панель управления<ArrowRight class="size-4"/></a></Button>
            <Button as-child variant="outline"><a href="#platform">О проекте</a></Button>
          </div>
        </div>
        <Card>
          <CardHeader><FolderKanban class="mb-2 size-5 text-muted-foreground"/><CardTitle>Проект — общая точка работы</CardTitle><CardDescription>Команда, ресурсы и разрешения связаны с выбранным проектом.</CardDescription></CardHeader>
          <CardContent class="space-y-3 text-sm text-muted-foreground">
            <p>У каждого проекта свои файлы, подключения и рабочие сеансы.</p>
            <p>Агенты получают доступ к нужным инструментам через управляемые разрешения.</p>
          </CardContent>
        </Card>
      </section>
      <section id="platform" aria-labelledby="platform-title" class="scroll-mt-6 space-y-5">
        <div class="space-y-2"><h2 id="platform-title" class="text-2xl font-semibold tracking-tight">Что объединяет Briareus</h2><p class="text-sm text-muted-foreground">Работа нескольких агентов и инструментов в границах конкретного проекта.</p></div>
        <div class="grid gap-4 md:grid-cols-3">
          <Card v-for="item in capabilities" :key="item.title"><CardHeader><component :is="item.icon" class="mb-2 size-5 text-muted-foreground"/><CardTitle class="text-base">{{item.title}}</CardTitle></CardHeader><CardContent class="text-sm leading-relaxed text-muted-foreground">{{item.text}}</CardContent></Card>
        </div>
      </section>
      <section id="architecture" aria-labelledby="architecture-title" class="scroll-mt-6 space-y-5">
        <div class="space-y-2"><h2 id="architecture-title" class="text-2xl font-semibold tracking-tight">Устройство платформы</h2><p class="text-sm text-muted-foreground">Управление платформой и исполнение инструментов разделены.</p></div>
        <div class="grid gap-4 md:grid-cols-3"><Card v-for="layer in layers" :key="layer.title"><CardHeader><CardTitle class="text-base">{{layer.title}}</CardTitle></CardHeader><CardContent class="text-sm leading-relaxed text-muted-foreground">{{layer.text}}</CardContent></Card></div>
        <Card><CardHeader><CardTitle class="text-base">Открыть рабочее пространство</CardTitle><CardDescription>Войдите в панель, чтобы работать с доступными вам командами и проектами.</CardDescription></CardHeader><CardContent><Button as-child><a href="/panel/">Открыть Control Panel<ArrowRight class="size-4"/></a></Button></CardContent></Card>
      </section>
    </main>
    <footer class="border-t"><div class="mx-auto flex max-w-6xl flex-wrap justify-between gap-2 px-4 py-5 text-xs text-muted-foreground sm:px-6"><span>Briareus · платформа MCP и AI-агентов</span><span>Прототип в разработке</span></div></footer>
  </div>
</template>
