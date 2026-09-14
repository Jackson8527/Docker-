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
          <span v-if="truncated" class="log-truncated">· 已截断 {{ truncated }} 行</span>
        </span>
      </div>
      <div class="log-right">
        <el-button size="small" :icon="VideoPause" @click="paused = !paused">
          {{ paused ? '继续' : '暂停' }}
        </el-button>
        <el-button size="small" :icon="Brush" @click="clearScreen">清屏</el-button>
        <el-button size="small" :icon="Download" @click="download">下载</el-button>
        <el-button size="small" :icon="Refresh" @click="reconnect">重连</el-button>
        <el-button v-if="!userClosed" size="small" :icon="SwitchButton" @click="closeStream">
          断开
        </el-button>
      </div>
    </div>

    <div v-if="notice" class="log-notice">
      <el-alert
        :type="notice.type"
        :title="notice.title"
        :description="notice.detail"
        show-icon
        :closable="false"
      />
    </div>

    <div ref="bodyEl" class="log-body" @scroll="onScroll">
      <div v-if="!lines.length" class="log-empty">
        {{ status === 'connected' ? '等待日志输出…' : emptyText }}
      </div>
      <div v-for="(line, i) in lines" :key="i" class="log-line">{{ line }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Refresh, Brush, Download, VideoPause, SwitchButton } from '@element-plus/icons-vue'
import { describeWsError, isRetryableClose, parseServerErrorFrame } from '../utils/ws'

const props = defineProps<{ name: string }>()

// Lines kept in the DOM. Old ones are windowed out silently - the counter in
// the toolbar is the hint, and a marker line per flush would flood the view.
const MAX_LINES = 3000
// Lines buffered between two DOM flushes. The backend already coalesces its
// own output, so this only has to absorb a burst when the tab was throttled.
const MAX_BUFFER = 5000
// 100ms matches the backend's LOG_FLUSH_INTERVAL: faster flushes would just
// re-render without any new data.
const FLUSH_INTERVAL = 100

const RETRY_BASE = 1000
const RETRY_MAX = 30000

interface Notice {
  type: 'error' | 'warning' | 'info'
  title: string
  detail: string
}

const lines = ref<string[]>([])
const stream = ref('stdout')
const tail = ref(200)
const paused = ref(false)
const status = ref<'connecting' | 'connected' | 'closed'>('connecting')
const bodyEl = ref<HTMLDivElement>()
/** Lines dropped since the view was opened, shown next to the line count. */
const truncated = ref(0)
const notice = ref<Notice | null>(null)
/** Seconds until the next automatic attempt; 0 when none is pending. */
const retryIn = ref(0)
/** Set by the 「断开」button; suppresses automatic reconnects until 「重连」. */
const userClosed = ref(false)

let ws: WebSocket | null = null
let disposed = false
let autoScroll = true
let everConnected = false
/** Set when the server answered with an error frame instead of logs. */
let serverRefused = false
/** Non-reactive: the websocket callback must not trigger a render per line. */
let pending: string[] = []
let droppedSinceFlush = 0
let flushTimer: number | undefined
let tickTimer: number | undefined
let retryDelay = RETRY_BASE
let retryAt = 0

const statusText = computed(() => {
  if (userClosed.value) return '已断开（手动）'
  if (retryIn.value > 0) return `已断开 · ${retryIn.value}s 后重连`
  return { connecting: '连接中', connected: '实时', closed: '已断开' }[status.value]
})

const emptyText = computed(() => {
  if (userClosed.value) return '已手动断开连接'
  if (retryIn.value > 0) return '连接已断开，正在自动重连…'
  return '暂无日志'
})

function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

// ------------------------------------------------------------- rendering --

/**
 * Queue one line for the next flush.
 *
 * A frame from /ws/logs carries a whole batch of `\n`-separated lines (the
 * backend flushes every 100ms), so splitting is mandatory - and so is keeping
 * genuinely empty lines, otherwise blank lines in a batch shift the output.
 */
function pushLine(line: string) {
  pending.push(line)
  if (pending.length > MAX_BUFFER) {
    const overflow = pending.length - MAX_BUFFER
    pending.splice(0, overflow)
    droppedSinceFlush += overflow
    // Mark the gap where it happened; the toolbar counter alone is easy to miss.
    pending.push(`... 已截断，丢弃最旧的 ${overflow} 行 ...`)
  }
  scheduleFlush()
}

function scheduleFlush() {
  if (flushTimer !== undefined) return
  flushTimer = window.setTimeout(flush, FLUSH_INTERVAL)
}

/** Move the buffered lines into the DOM in one reactive write. */
function flush() {
  flushTimer = undefined
  if (disposed) return
  if (droppedSinceFlush) {
    truncated.value += droppedSinceFlush
    droppedSinceFlush = 0
  }
  if (!pending.length) return

  const batch = pending
  pending = []
  let next = lines.value.concat(batch)
  if (next.length > MAX_LINES) next = next.slice(next.length - MAX_LINES)
  lines.value = next

  if (autoScroll) scrollToBottom()
}

function scrollToBottom() {
  void nextTick().then(() => {
    const el = bodyEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function appendChunk(chunk: string) {
  if (paused.value || !chunk) return
  for (const line of chunk.split('\n')) pushLine(line)
}

function clearScreen() {
  lines.value = []
  pending = []
  truncated.value = 0
  droppedSinceFlush = 0
}

function onScroll() {
  const el = bodyEl.value
  if (!el) return
  // Stop following once the user scrolls up; resume at the bottom.
  autoScroll = el.scrollHeight - el.scrollTop - el.clientHeight < 24
}

// ------------------------------------------------------------ connection --

function connect() {
  status.value = 'connecting'
  notice.value = null
  serverRefused = false
  ws = new WebSocket(
    wsUrl(`/ws/logs?filter=${encodeURIComponent(props.name)}&stream=${stream.value}&tail=${tail.value}`)
  )
  ws.onopen = () => {
    if (disposed) return
    status.value = 'connected'
    everConnected = true
    // The socket reached the backend, so the target is up: start over at the
    // base delay. Without this a burst of failures pins the backoff at
    // RETRY_MAX forever - a healthy session that later drops would still make
    // the user wait 30s, and only the 「重连」button would bring it back to 1s.
    retryDelay = RETRY_BASE
  }
  ws.onmessage = (e) => {
    if (disposed) return
    const chunk = typeof e.data === 'string' ? e.data : ''
    const reason = parseServerErrorFrame(chunk)
    if (reason !== null) {
      // Protocol frame (`{"dockermgr":"error",...}`), not output: rendering it
      // as a log line (the old behaviour) left a bare `{"error":"no container"}`
      // in the view. The discriminant is checked in utils/ws.ts, so a JSON log
      // line carrying an `error` field still lands in the log below.
      serverRefused = true
      notice.value = { type: 'error', title: '无法获取日志', detail: describeWsError(reason) }
      return
    }
    appendChunk(chunk)
  }
  ws.onclose = (ev) => {
    if (disposed) return
    status.value = 'closed'
    if (!serverRefused && !isRetryableClose(ev.code)) {
      // A clean close the user has to act on (see utils/ws.ts): the log reader
      // ended because the container stopped/ exited, or the server rejected us.
      notice.value = {
        type: 'warning',
        title: '日志流已结束',
        detail: '容器可能已停止或退出。可点「重连」重新读取。',
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
  if (!isRetryableClose(code)) {
    // 1000/1008: retrying cannot help (see utils/ws.ts).
    if (!notice.value) {
      notice.value = {
        type: 'error',
        title: '连接已关闭',
        detail: `服务端结束了本次连接（code ${code}）。可点「重连」再试。`,
      }
    }
    return
  }

  if (!notice.value) {
    notice.value = {
      type: 'error',
      title: '连接已断开',
      detail: '与后端的连接中断，正在自动重连…',
    }
  }

  // Tell the user where the replayed tail begins, because a reconnect asks the
  // backend for the same `tail` again and may therefore repeat recent lines.
  // KNOWN TRADEOFF (N-06): the reconnect is a fresh `docker logs --tail=N`
  // (ws.py:103-109 has no `since`), so up to N lines the user already saw are
  // replayed - the notice is the only thing marking where the duplicate run
  // starts. Bounded by MAX_BUFFER / MAX_LINES, so it can flood the view but
  // never the memory. Shrinking `tail` for retries would hide the boundary too.
  if (everConnected) pushLine('... 连接已断开，正在重连（可能重复最近若干行）...')

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
  retryDelay = RETRY_BASE
  userClosed.value = false
  everConnected = false
  clearScreen()
  autoScroll = true
  connect()
}

/** Manual 「断开」: stop streaming and stay stopped. */
function closeStream() {
  userClosed.value = true
  stopRetry()
  dropSocket()
  status.value = 'closed'
  notice.value = null
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
  // Order matters: flag first so nothing late can re-arm a timer or socket.
  disposed = true
  stopRetry()
  if (flushTimer !== undefined) {
    window.clearTimeout(flushTimer)
    flushTimer = undefined
  }
  dropSocket()
  pending = []
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

.log-truncated {
  color: #fbbf24;
}

/* The drawer chrome is dark, so the stock light alert is re-tinted. */
.log-notice {
  flex: none;
  padding: 8px 12px 0;
}
.log-notice :deep(.el-alert) {
  align-items: flex-start;
  padding: 6px 10px;
  background: #1e293b;
  border: 1px solid #334155;
}
.log-notice :deep(.el-alert__title) {
  color: #e2e8f0;
  font-size: 12px;
}
.log-notice :deep(.el-alert__description) {
  color: #94a3b8;
  font-size: 12px;
  margin: 2px 0 0;
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
