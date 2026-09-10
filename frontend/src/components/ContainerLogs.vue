<template>
  <div class="log-wrap">
    <div class="log-bar">
      <div class="log-left">
        <el-select v-model="stream" size="small" style="width: 118px" @change="reconnect">
          <el-option label="stdout" value="stdout" />
          <el-option label="stderr" value="stderr" />
          <el-option label="全部" value="both" />
        </el-select>
        <el-select v-model="tail" size="small" style="width: 104px" @change="reconnect">
          <el-option label="最近 100 行" :value="100" />
          <el-option label="最近 500 行" :value="500" />
          <el-option label="最近 2000 行" :value="2000" />
        </el-select>
        <span class="log-state">
          <span class="log-dot" :class="{ 'is-live': status === 'connected' }"></span>
          {{ statusText }} · {{ lines.length }} 行
        </span>
      </div>
      <div class="log-right">
        <el-button size="small" :icon="VideoPause" @click="paused = !paused">
          {{ paused ? '继续' : '暂停' }}
        </el-button>
        <el-button size="small" :icon="Brush" @click="lines = []">清屏</el-button>
        <el-button size="small" :icon="Download" @click="download">下载</el-button>
        <el-button size="small" :icon="Refresh" @click="reconnect">重连</el-button>
      </div>
    </div>

    <div ref="bodyEl" class="log-body" @scroll="onScroll">
      <div v-if="!lines.length" class="log-empty">
        {{ status === 'connected' ? '等待日志输出…' : '暂无日志' }}
      </div>
      <div v-for="(line, i) in lines" :key="i" class="log-line">{{ line }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Refresh, Brush, Download, VideoPause } from '@element-plus/icons-vue'

const props = defineProps<{ name: string }>()

const MAX_LINES = 3000

const lines = ref<string[]>([])
const stream = ref('stdout')
const tail = ref(200)
const paused = ref(false)
const status = ref<'connecting' | 'connected' | 'closed'>('connecting')
const bodyEl = ref<HTMLDivElement>()

let ws: WebSocket | null = null
let disposed = false
let autoScroll = true

const statusText = computed(
  () => ({ connecting: '连接中', connected: '实时', closed: '已断开' })[status.value]
)

function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

async function append(chunk: string) {
  if (paused.value) return
  // A chunk may hold several lines; keep the trailing partial line intact.
  const parts = chunk.split('\n')
  for (const part of parts) {
    if (part === '') continue
    lines.value.push(part)
  }
  if (lines.value.length > MAX_LINES) {
    lines.value.splice(0, lines.value.length - MAX_LINES)
  }
  if (autoScroll) {
    await nextTick()
    const el = bodyEl.value
    if (el) el.scrollTop = el.scrollHeight
  }
}

function onScroll() {
  const el = bodyEl.value
  if (!el) return
  // Stop following once the user scrolls up; resume at the bottom.
  autoScroll = el.scrollHeight - el.scrollTop - el.clientHeight < 24
}

function connect() {
  status.value = 'connecting'
  ws = new WebSocket(
    wsUrl(`/ws/logs?filter=${encodeURIComponent(props.name)}&stream=${stream.value}&tail=${tail.value}`)
  )
  ws.onopen = () => {
    if (!disposed) status.value = 'connected'
  }
  ws.onmessage = (e) => {
    if (!disposed) append(e.data as string)
  }
  ws.onclose = () => {
    if (!disposed) status.value = 'closed'
  }
  ws.onerror = () => {
    if (!disposed) status.value = 'closed'
  }
}

function reconnect() {
  if (ws) {
    ws.onclose = null
    ws.close()
  }
  lines.value = []
  autoScroll = true
  connect()
}

function download() {
  const blob = new Blob([lines.value.join('\n')], { type: 'text/plain;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${props.name}.log`
  a.click()
  URL.revokeObjectURL(a.href)
}

onMounted(() => {
  disposed = false
  connect()
})

onUnmounted(() => {
  disposed = true
  if (ws) {
    ws.onclose = null
    ws.onmessage = null
    ws.close()
  }
})
</script>

<style scoped>
.log-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #0b1220;
}

.log-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 8px 12px;
  background: #111c2e;
  border-bottom: 1px solid #1e293b;
  flex: none;
}

.log-left,
.log-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.log-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #94a3b8;
}

.log-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f87171;
}
.log-dot.is-live {
  background: #4ade80;
}

.log-bar :deep(.el-button) {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
.log-bar :deep(.el-button:hover) {
  background: #334155;
  border-color: #475569;
  color: #f1f5f9;
}

.log-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 10px 12px;
  font-family: var(--dm-mono);
  font-size: 12px;
  line-height: 1.6;
  color: #cbd5e1;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-line {
  padding: 0 2px;
}
.log-line:hover {
  background: rgba(148, 163, 184, 0.08);
}

.log-empty {
  color: #475569;
  padding: 20px 4px;
}
</style>
