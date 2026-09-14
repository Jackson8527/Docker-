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
        <el-button v-if="!userClosed" size="small" :icon="SwitchButton" @click="closeStream">
          断开
        </el-button>
        <el-button size="small" :icon="Brush" @click="clearScreen">清屏</el-button>
      </div>
    </div>
    <div v-if="notice" class="term-notice">
      <el-alert
        :type="notice.type"
        :title="notice.title"
        :description="notice.detail"
        show-icon
        :closable="false"
      />
    </div>
    <div ref="hostEl" class="term-host"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Brush, SwitchButton } from '@element-plus/icons-vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { describeWsError, isRetryableClose, parseServerErrorFrame } from '../utils/ws'

const props = defineProps<{ cid: string }>()
defineEmits<{ (e: 'close'): void }>()

const RETRY_BASE = 1000
const RETRY_MAX = 30000
/** ~1 frame: PTY output is written to xterm once per frame at most. */
const WRITE_FLUSH_INTERVAL = 16

interface Notice {
  type: 'error' | 'warning' | 'info'
  title: string
  detail: string
}

const hostEl = ref<HTMLDivElement>()
const status = ref<'connecting' | 'connected' | 'closed'>('connecting')
const cols = ref(0)
const rows = ref(0)
const notice = ref<Notice | null>(null)
/** Seconds until the next automatic attempt; 0 when none is pending. */
const retryIn = ref(0)
/** Set by the 「断开」button; suppresses automatic reconnects until 「重连」. */
const userClosed = ref(false)

let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let ws: WebSocket | null = null
let observer: ResizeObserver | null = null
let disposed = false
let pending: string[] = []
/** Set when the server answered with an error frame instead of a session. */
let serverRefused = false
/** PTY bytes waiting for the next xterm write. */
let writeBuf = ''
let writeTimer: number | undefined
let tickTimer: number | undefined
let retryDelay = RETRY_BASE
let retryAt = 0

const statusText = computed(() => {
  if (userClosed.value) return '已断开（手动）'
  if (retryIn.value > 0) return `连接已断开 · ${retryIn.value}s 后重连`
  return { connecting: '连接中…', connected: '已连接', closed: '会话已结束' }[status.value]
})
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
  notice.value = null
  serverRefused = false

  ws = new WebSocket(wsUrl(`/ws/exec?container=${encodeURIComponent(props.cid)}`))

  ws.onopen = () => {
    if (disposed) return
    status.value = 'connected'
    // The socket reached the backend, so the target is up: restart the backoff
    // from the base delay. Without this, N failures pin the delay at RETRY_MAX
    // for the rest of the session - a later drop would cost the user 30s even
    // after hours of healthy streaming.
    retryDelay = RETRY_BASE
    flushPending()
    scheduleFit()
    term?.focus()
  }
  ws.onmessage = (e) => {
    if (disposed) return
    const chunk = typeof e.data === 'string' ? e.data : ''
    const reason = parseServerErrorFrame(chunk)
    if (reason !== null) {
      // Protocol frame (`{"dockermgr":"error",...}`), not PTY output: /ws/exec
      // answers an unknown container with a single error frame before closing.
      // Writing it to xterm would garble the screen instead of telling the user
      // what went wrong; the discriminant check lives in utils/ws.ts.
      serverRefused = true
      notice.value = { type: 'error', title: '无法打开终端', detail: describeWsError(reason) }
      return
    }
    queueWrite(chunk)
  }
  ws.onclose = (ev) => {
    if (disposed) return
    status.value = 'closed'
    // Never lose the tail of a session that just ended.
    flushWrite()
    if (!serverRefused) {
      if (isRetryableClose(ev.code)) {
        // Transport died (1006 and friends): reconnect, the session is gone but
        // there is nothing the user did wrong.
        notice.value = {
          type: 'error',
          title: '连接已断开',
          detail: '与容器的连接中断，正在自动重连…',
        }
      } else {
        // Clean close: the shell exited. Retrying would silently start a *new*
        // session, so this one is left to the user.
        queueWrite('\r\n\x1b[38;5;244m[会话已结束]\x1b[0m\r\n')
        notice.value = {
          type: 'warning',
          title: '会话已结束',
          detail: '容器内的 shell 已退出（或后端未能建立会话）。可点「重连」开启新会话。',
        }
      }
    }
    scheduleRetry(ev.code)
  }
  ws.onerror = () => {
    // A failing socket always reports through onclose too; that is where the
    // close code - and therefore the retry decision - is available.
  }
}

/** Queue the next attempt, doubling the delay up to RETRY_MAX. */
function scheduleRetry(code: number) {
  if (disposed || userClosed.value) return
  if (!isRetryableClose(code)) return

  retryAt = Date.now() + retryDelay
  retryIn.value = Math.ceil(retryDelay / 1000)
  retryDelay = Math.min(retryDelay * 2, RETRY_MAX)
  if (tickTimer === undefined) tickTimer = window.setInterval(tickRetry, 1000)
}

function tickRetry() {
  if (disposed || userClosed.value) {
    stopRetry()
    return
  }
  const left = retryAt - Date.now()
  if (left > 0) {
    retryIn.value = Math.ceil(left / 1000)
    return
  }
  stopRetry()
  connect()
}

function stopRetry() {
  if (tickTimer !== undefined) {
    window.clearInterval(tickTimer)
    tickTimer = undefined
  }
  retryIn.value = 0
  retryAt = 0
}

function dropSocket() {
  if (!ws) return
  // Detach first: a close handler here would schedule a retry we did not ask for.
  ws.onopen = null
  ws.onmessage = null
  ws.onclose = null
  ws.onerror = null
  ws.close()
  ws = null
}

/** Manual 「重连」: reset the backoff so the user does not wait out a 30s delay. */
function reconnect() {
  stopRetry()
  dropSocket()
  // Buffered output belongs to the session being dropped: discard it instead of
  // writing it, or it could land after term.reset() and survive the reset.
  discardWrite()
  retryDelay = RETRY_BASE
  userClosed.value = false
  if (term) {
    term.reset()
  }
  pending = []
  connect()
}

/** Manual 「断开」: stop the session and stay stopped. */
function closeStream() {
  userClosed.value = true
  stopRetry()
  flushWrite()
  dropSocket()
  status.value = 'closed'
  notice.value = null
}

// ---------------------------------------------------------------- output --

/**
 * Buffer PTY bytes and hand them to xterm at most once per frame.
 *
 * xterm queues internally, but calling write() for every websocket frame still
 * costs one parse entry per frame; a chatty command (`find /`, `tail -f`) can
 * push thousands. Coalescing also keeps escape sequences that arrive split
 * across frames in order - the buffer is a single string, so ordering cannot
 * be lost.
 */
function queueWrite(data: string) {
  if (disposed || !term || !data) return
  writeBuf += data
  if (writeTimer !== undefined) return
  writeTimer = window.setTimeout(flushWrite, WRITE_FLUSH_INTERVAL)
}

function flushWrite() {
  const data = writeBuf
  discardWrite()
  if (!disposed && term && data) term.write(data)
}

/** Drop buffered output without writing it (screen reset, teardown). */
function discardWrite() {
  if (writeTimer !== undefined) {
    window.clearTimeout(writeTimer)
    writeTimer = undefined
  }
  writeBuf = ''
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
  // Flag first, then tear down: nothing may re-arm a timer or a socket after this.
  disposed = true
  stopRetry()
  discardWrite()
  hostEl.value?.removeEventListener('contextmenu', onContextMenu, true)
  observer?.disconnect()
  observer = null
  dropSocket()
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

/* The terminal chrome is dark, so the stock light alert is re-tinted. */
.term-notice {
  flex: none;
  padding: 8px 12px 0;
}
.term-notice :deep(.el-alert) {
  align-items: flex-start;
  padding: 6px 10px;
  background: #1e293b;
  border: 1px solid #334155;
}
.term-notice :deep(.el-alert__title) {
  color: #e2e8f0;
  font-size: 12px;
}
.term-notice :deep(.el-alert__description) {
  color: #94a3b8;
  font-size: 12px;
  margin: 2px 0 0;
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
