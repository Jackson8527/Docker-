// Executable transcription of the retry state machine in
// frontend/src/components/ContainerLogs.vue (lines 70-71, 93-105, 197-328)
// and ContainerTerminal.vue (lines 43-44, 64-77, 294-363).
// Only the retry bookkeeping is transcribed; Vue/WS/DOM are stubbed.
// Every assignment below is copied verbatim from the component source.

const RETRY_BASE = 1000
const RETRY_MAX = 30000

let now = 0
const timers = new Map() // interval id -> fn
let nextTimerId = 1

function setTimeoutStub(fn) { return 0 } // not needed (flush timer only)
function setIntervalStub(fn) { const id = nextTimerId++; timers.set(id, fn); return id }
function clearIntervalStub(id) { timers.delete(id) }
function fireOneSecond() { for (const fn of [...timers.values()]) fn(); now += 1000 }

class Sim {
  constructor(label) {
    this.label = label
    this.disposed = false
    this.userClosed = false
    this.retryDelay = RETRY_BASE     // line 104/76
    this.retryAt = 0                  // line 105/77
    this.tickTimer = undefined        // line 103/75
    this.retryIn = 0
    this.everConnected = false
    this.connects = 0
  }
  connect() {                        // lines 197-240 / 231-292
    this.connects++
    this.retryIn = 0
  }
  scheduleRetry(code, retryable = true) {   // lines 243-273 / 295-303
    if (this.disposed || this.userClosed) return
    if (!retryable) return
    this.retryAt = now + this.retryDelay                       // 269 / 299
    this.retryIn = Math.ceil(this.retryDelay / 1000)           // 270 / 300
    this.retryDelay = Math.min(this.retryDelay * 2, RETRY_MAX) // 271 / 301
    if (this.tickTimer === undefined) this.tickTimer = setIntervalStub(() => this.tickRetry()) // 272 / 302
  }
  tickRetry() {                      // 275-287 / 305-317
    if (this.disposed || this.userClosed) { this.stopRetry(); return }
    const left = this.retryAt - now
    if (left > 0) { this.retryIn = Math.ceil(left / 1000); return }
    this.stopRetry()
    this.connect()
  }
  stopRetry() {                      // 289-296 / 319-326
    if (this.tickTimer !== undefined) { clearIntervalStub(this.tickTimer); this.tickTimer = undefined }
    this.retryIn = 0
    this.retryAt = 0
  }
  reconnect() {                      // 310-319 / 340-353
    this.stopRetry()
    this.retryDelay = RETRY_BASE                              // 313 / 346
    this.userClosed = false
    this.everConnected = false
    this.connect()
  }
  closeStream() {                    // 322-328 / 356-363
    this.userClosed = true
    this.stopRetry()
  }
}

function advanceUntilConnect(sim, maxSeconds = 120) {
  let t = 0
  while (t < maxSeconds) {
    fireOneSecond()
    t++
    if (sim.tickTimer === undefined && sim.retryIn === 0) return t
  }
  return -1
}

console.log('=== S1: repeated transport failures (1006) — does the delay cap at 30s? ===')
{
  const s = new Sim('logs')
  for (let i = 1; i <= 6; i++) {
    s.scheduleRetry(1006)
    const shown = s.retryIn
    const waited = advanceUntilConnect(s)
    console.log(`  drop #${i}: next retry shown = ${shown}s, actual wait = ${waited}s`)
  }
}

console.log('\n=== S2: successful connection, then a later drop — does the delay reset? ===')
{
  const s = new Sim('logs')
  for (let i = 1; i <= 6; i++) { s.scheduleRetry(1006); advanceUntilConnect(s) }
  console.log(`  retryDelay after 6 failures (capped) = ${s.retryDelay / 1000}s`)
  s.everConnected = true            // ws.onopen fired (line 207/242)
  now += 3600_000                   // one hour of healthy streaming
  s.scheduleRetry(1006)
  console.log(`  next drop after 1h healthy: shown = ${s.retryIn}s  (expected 1s if backoff resets on success)`)
}

console.log('\n=== S3: manual 「重连」 resets the backoff (documented path) ===')
{
  const s = new Sim('logs')
  for (let i = 1; i <= 6; i++) { s.scheduleRetry(1006); advanceUntilConnect(s) }
  s.reconnect()
  s.scheduleRetry(1006)
  console.log(`  after manual reconnect: shown = ${s.retryIn}s`)
}

console.log('\n=== S4: 「断开」 (userClosed) and unmount really stop retries ===')
{
  const s = new Sim('logs')
  s.scheduleRetry(1006)
  s.closeStream()
  fireOneSecond(); fireOneSecond(); fireOneSecond()
  console.log(`  after 断开: tickTimer=${s.tickTimer} retryIn=${s.retryIn} connects=${s.connects}`)

  const s2 = new Sim('logs')
  s2.scheduleRetry(1006)
  s2.disposed = true                // onUnmounted (line 346) then stopRetry (347)
  s2.stopRetry()
  fireOneSecond(); fireOneSecond()
  console.log(`  after unmount: tickTimer=${s2.tickTimer} retryIn=${s2.retryIn} connects=${s2.connects}`)
}

console.log('\n=== S5: pending ticks left in the interval after a successful reconnect (S1 loop) ===')
{
  const s = new Sim('logs')
  s.scheduleRetry(1006)
  fireOneSecond()                   // t=1s: tickRetry -> stopRetry + connect
  console.log(`  after 1 tick: connects=${s.connects} tickTimer=${s.tickTimer} liveIntervals=${timers.size}`)
}
