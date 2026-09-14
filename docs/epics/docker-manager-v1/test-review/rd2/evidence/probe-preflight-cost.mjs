// How much server-side work does one preflight cost? Read exactly one chunk,
// report its size, then abort - i.e. what the browser's cancel() does, but
// with the byte count visible.
const URL_IMG =
  'http://127.0.0.1:8088/api/images/sha256:72ba65eb42c10344912a84ff42408db7d34f2feb642204570ab8fc5ffd29f1d3/save'

const ctrl = new AbortController()
const t0 = Date.now()
const res = await fetch(URL_IMG, { signal: ctrl.signal })
const reader = res.body.getReader()
const { value, done } = await reader.read()
console.log(`status=${res.status} content-type=${res.headers.get('content-type')}`)
console.log(`first chunk after ${Date.now() - t0}ms: ${done ? 'DONE' : value.byteLength + ' bytes'}`)

// Let the server keep streaming for 300ms and count what arrives, then abort.
let total = value ? value.byteLength : 0
const t1 = Date.now()
while (Date.now() - t1 < 300) {
  const r = await reader.read()
  if (r.done) break
  total += r.value.byteLength
}
console.log(`bytes received in ~300ms window: ${total} (${(total / 1024).toFixed(0)} KiB) - this is daemon work the download throws away`)
ctrl.abort()
try { await reader.closed } catch (e) { console.log(`aborted: ${e.constructor.name}`) }
console.log('preflight aborted cleanly')
