<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>交互终端：{{ cid }}</span>
          <el-button size="small" type="danger" @click="close">关闭</el-button>
        </div>
      </template>
      <div ref="terminalEl" class="terminal"></div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

const props = defineProps<{ cid: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const terminalEl = ref<HTMLDivElement>()
let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let ws: WebSocket | null = null
let alive = true

function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

onMounted(() => {
  if (!terminalEl.value) return
  alive = true
  term = new Terminal({ cursorBlink: true })
  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.open(terminalEl.value)
  fitAddon.fit()

  ws = new WebSocket(wsUrl(`/ws/exec?container=${encodeURIComponent(props.cid)}`))
  term.onData((data) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(data)
  })
  ws.onmessage = (e) => {
    if (alive && term) term.write(e.data as string)
  }
  ws.onclose = () => {
    if (alive && term) term.write('\r\n\x1b[31m[会话已结束]\x1b[0m')
  }
})

function close() {
  alive = false
  ws && ws.close()
  emit('close')
}

onUnmounted(() => {
  alive = false
  ws && ws.close()
  term && term.dispose()
})
</script>

<style scoped>
.terminal {
  width: 100%;
  height: 400px;
  background: #000;
  padding: 8px;
}
</style>