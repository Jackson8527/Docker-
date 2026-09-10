<template>
  <div>
    <el-card class="log-card">
      <template #header>
        <div class="card-header">
          <span>实时日志：{{ name }}</span>
          <el-button size="small" type="warning" @click="reconnect">重连</el-button>
        </div>
      </template>
      <el-input
        type="textarea"
        :model-value="lines.join('\n')"
        :rows="12"
        readonly
        class="log-output"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{ name: string }>()
const lines = ref<string[]>([])
let ws: WebSocket | null = null
let alive = true

function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

function connect() {
  close()
  lines.value = []
  ws = new WebSocket(wsUrl(`/ws/logs?filter=${encodeURIComponent(props.name)}&stream=stdout&tail=200`))
  ws.onmessage = (e) => {
    if (!alive) return
    lines.value.push(e.data as string)
    if (lines.value.length > 500) lines.value.shift()
  }
}

function reconnect() {
  connect()
}

onMounted(() => {
  alive = true
  connect()
})
onUnmounted(() => {
  alive = false
  ws && ws.close()
})
</script>

<style scoped>
.log-output { font-family: monospace; font-size: 12px; }
</style>