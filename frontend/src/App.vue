<template>
  <div class="dm-shell">
    <aside class="dm-sidebar">
      <div class="dm-brand">
        <span class="dm-brand-mark">🐳</span>
        <span class="dm-brand-text">
          Docker Manager
          <span class="dm-brand-sub">容器管理平台</span>
        </span>
      </div>

      <nav class="dm-nav">
        <router-link
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          class="dm-nav-item"
          :class="{ 'is-active': isActive(item.path) }"
        >
          <span class="dm-nav-icon"><component :is="item.icon" /></span>
          <span>{{ item.title }}</span>
        </router-link>
      </nav>

      <div class="dm-sidebar-foot">v1 · 本地部署 · 127.0.0.1</div>
    </aside>

    <div class="dm-main">
      <header class="dm-header">
        <div>
          <h1 class="dm-header-title">{{ current?.meta?.title || 'Docker 管理平台' }}</h1>
          <div class="dm-header-desc">{{ current?.meta?.desc || '管理本机容器运行时' }}</div>
        </div>
        <div class="dm-header-right">
          <span class="dm-health">
            <span class="dm-health-dot" :class="healthClass"></span>
            {{ healthText }}
          </span>
          <el-button :icon="Refresh" @click="reload">刷新</el-button>
        </div>
      </header>

      <main class="dm-content">
        <router-view v-slot="{ Component }">
          <component :is="Component" :key="`${route.fullPath}#${reloadKey}`" />
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh, Box, Picture, Connection, Coin } from '@element-plus/icons-vue'
import http from './api'

const route = useRoute()

const nav = [
  { path: '/containers', title: '容器', icon: Box },
  { path: '/images', title: '镜像', icon: Picture },
  { path: '/networks', title: '网络', icon: Connection },
  { path: '/volumes', title: '卷', icon: Coin },
]

const current = computed(() => route.matched[route.matched.length - 1])
const isActive = (path: string) => route.path.startsWith(path)

const health = ref<'ok' | 'bad' | 'unknown'>('unknown')
const healthClass = computed(() =>
  health.value === 'ok' ? 'is-ok' : health.value === 'bad' ? 'is-bad' : ''
)
const healthText = computed(
  () => ({ ok: '服务正常', bad: '服务异常', unknown: '检测中…' })[health.value]
)

let timer: number | undefined

async function checkHealth() {
  try {
    const r = await http.get('/health', { timeout: 5000 })
    health.value = r.data?.status === 'ok' ? 'ok' : 'bad'
  } catch {
    health.value = 'bad'
  }
}

/** Bumping this remounts the routed view, which refetches its data. */
const reloadKey = ref(0)
function reload() {
  reloadKey.value++
  checkHealth()
}

onMounted(() => {
  checkHealth()
  timer = window.setInterval(checkHealth, 15000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>
