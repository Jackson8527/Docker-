<template>
  <div class="term-wrap">
    <div class="term-bar">
      <div class="term-state">
        <span class="term-dot" :class="statusClass"></span>
        <span class="term-state-text">{{ statusText }}</span>
        <span v-if="cols && rows" class="term-size">{{ cols }} × {{ rows }}</span>
      </div>
      <div class="term-actions">
        <span class="term-tip">选中文本 Ctrl+C 复制 · Ctrl+V / 右键 粘贴</span>
        <el-button size="small" :icon="Refresh" @click="reconnect">重连</el-button>
        <el-button size="small" :icon="Brush" @click="clearScreen">清屏</el-button>
      </div>
    </div>
    <div ref="hostEl" class="term-host"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Brush } from '@element-plus/icons-vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

const props = defineProps<{ cid: string }>()
defineEmits<{ (e: 'close'): void }>()

const hostEl = ref<HTMLDivElement>()
const status = ref<'connecting' | 'connected' | 'closed'>('connecting')
const cols = ref(0)
const rows = ref(0)

let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let ws: WebSocket | null = null
let observer: ResizeObserver | null = null
let disposed = false
let pending: string[] = []

const statusText = computed(
  () => ({ connecting: '连接中…', connected: '已连接', closed: '会话已结束' })[status.value]
)
const statusClass = computed(() => `is-${status.value}`)

function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

/** Send a JSON control frame; queue input until the socket is open. */
function send(payload: Record<string, unknown>, queueIfClosed = false) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload))
  } else if (queueIfClosed && payload.type === 'input') {
    pending.push(String(payload.data ?? ''))
  }
}

function flushPending() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  for (const data of pending) ws.send(JSON.stringify({ type: 'input', data }))
  pending = []
}

/**
 * Fit the terminal to its container.
 *
 * A drawer animates open, so at mount time the host element can still be
 * 0x0; fitting then yields nonsense cols/rows and xterm renders garbled.
 * We therefore refuse to fit while the box has no size - the ResizeObserver
 * calls us again as soon as the drawer has settled.
 */
function fit() {
  if (disposed || !fitAddon || !term || !hostEl.value) return
  const { clientWidth, clientHeight } = hostEl.value
  if (clientWidth <= 0 || clientHeight <= 0) return
  try {
    fitAddon.fit()
  } catch {
    return
  }
  cols.value = term.cols
  rows.value = term.rows
  send({ type: 'resize', cols: term.cols, rows: term.rows })
}

function scheduleFit() {
  // Two frames: the first lets the drawer's transition start, the second
  // runs after the layout it produced has been applied.
  requestAnimationFrame(() => requestAnimationFrame(fit))
}

function clearScreen() {
  term?.clear()
}

// ------------------------------------------------------------- clipboard --
//
// xterm copies only through the browser's native `copy` event, and its default
// key handling sends Ctrl+C to the PTY as \x03. So selecting text and pressing
// Ctrl+C used to interrupt the running command instead of copying it, and
// paste relied on a native event that does not reliably arrive. Wire both up
// explicitly instead.

async function copySelection() {
  const text = term?.getSelection() ?? ''
  if (!text) return

  try {
    await navigator.clipboard.writeText(text)
    ElMessage({ message: '已复制', type: 'success', duration: 1200 })
    return
  } catch {
    // Clipboard API unavailable (permission denied or non-secure context).
  }

  // Legacy fallback: a throwaway textarea plus execCommand.
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.top = '-1000px'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
    ElMessage({ message: '已复制', type: 'success', duration: 1200 })
  } catch {
    ElMessage.warning('复制失败，请手动选中后使用浏览器复制')
  } finally {
    document.body.removeChild(ta)
  }
}

async function pasteFromClipboard() {
  term?.focus()
  try {
    const text = await navigator.clipboard.readText()
    // term.paste() applies bracketed-paste mode and normalises line endings.
    if (text) term?.paste(text)
  } catch {
    ElMessage.warning('浏览器未允许读取剪贴板，请在地址栏放开权限后重试')
  }
}

/** Right-click pastes, matching Windows Terminal / PuTTY habits. */
function onContextMenu(ev: MouseEvent) {
  ev.preventDefault()
  ev.stopPropagation()
  pasteFromClipboard()
}

function onCustomKey(ev: KeyboardEvent): boolean {
  if (ev.type !== 'keydown') return true

  // Leave Alt/Ctrl+Alt combinations to the shell.
  if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return true

  const key = ev.key.toLowerCase()

  if (key === 'c') {
    if (term?.hasSelection()) {
      // Copy, and swallow the key so the shell does not also receive \x03.
      // Returning false also lets the browser raise its native copy event,
      // which writes the same text - so this still works if the async
      // clipboard API is blocked.
      copySelection()
      return false
    }
    // No selection: plain Ctrl+C keeps its SIGINT meaning, while an explicit
    // Ctrl+Shift+C should send nothing at all.
    return !ev.shiftKey
  }

  if (key === 'v') {
    // xterm consumes Ctrl+V by default, which suppresses the browser's native
    // paste event - that is exactly why paste did not work at all. Returning
    // false lets the event through; xterm's own textarea listener then pastes
    // it, with no clipboard permission needed.
    //
    // Do NOT paste here as well: doing so sends the text twice (the native
    // event fires once we stop consuming the key).
    return false
  }

  return true
}

function connect() {
  status.value = 'connecting'
  cols.value = 0
  rows.value = 0

  ws = new WebSocket(wsUrl(`/ws/exec?container=${encodeURIComponent(props.cid)}`))

  ws.onopen = () => {
    if (disposed) return
    status.value = 'connected'
    flushPending()
    scheduleFit()
    term?.focus()
  }
  ws.onmessage = (e) => {
    if (!disposed && term) term.write(e.data as string)
  }
  ws.onclose = () => {
    if (disposed) return
    status.value = 'closed'
    term?.write('\r\n\x1b[38;5;244m[会话已结束]\x1b[0m\r\n')
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
  if (term) {
    term.reset()
  }
  pending = []
  connect()
}

onMounted(async () => {
  disposed = false
  await nextTick()
  if (!hostEl.value) return

  term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: '"JetBrains Mono", "Cascadia Mono", Consolas, "Courier New", monospace',
    scrollback: 5000,
    allowProposedApi: true,
    theme: {
      background: '#0b1220',
      foreground: '#e2e8f0',
      cursor: '#60a5fa',
      cursorAccent: '#0b1220',
      selectionBackground: '#334155',
      black: '#1e293b',
      red: '#f87171',
      green: '#4ade80',
      yellow: '#fbbf24',
      blue: '#60a5fa',
      magenta: '#c084fc',
      cyan: '#22d3ee',
      white: '#e2e8f0',
    },
  })
  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.open(hostEl.value)

  term.onData((data) => send({ type: 'input', data }, true))
  term.attachCustomKeyEventHandler(onCustomKey)
  hostEl.value.addEventListener('contextmenu', onContextMenu, true)

  // The single source of truth for sizing: fires when the drawer opens,
  // finishes its transition, or the window is resized.
  observer = new ResizeObserver(() => fit())
  observer.observe(hostEl.value)

  connect()
  scheduleFit()
})

onUnmounted(() => {
  disposed = true
  hostEl.value?.removeEventListener('contextmenu', onContextMenu, true)
  observer?.disconnect()
  observer = null
  if (ws) {
    ws.onclose = null
    ws.onmessage = null
    ws.close()
  }
  term?.dispose()
  term = null
  fitAddon = null
})
</script>

<style scoped>
.term-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #0b1220;
}

.term-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #111c2e;
  border-bottom: 1px solid #1e293b;
  flex: none;
}

.term-state {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #94a3b8;
}

.term-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #fbbf24;
}
.term-dot.is-connected {
  background: #4ade80;
}
.term-dot.is-closed {
  background: #f87171;
}

.term-size {
  padding: 1px 6px;
  border-radius: 4px;
  background: #1e293b;
  color: #64748b;
  font-family: monospace;
}

.term-tip {
  font-size: 11px;
  color: #64748b;
  margin-right: 4px;
}

.term-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.term-actions :deep(.el-button) {
  background: #1e293b;
  border-color: #334155;
  color: #cbd5e1;
}
.term-actions :deep(.el-button:hover) {
  background: #334155;
  border-color: #475569;
  color: #f1f5f9;
}

/* min-height:0 is required or xterm overflows instead of scrolling. */
.term-host {
  flex: 1 1 auto;
  min-height: 0;
  padding: 6px 0 6px 8px;
  overflow: hidden;
}
</style>
