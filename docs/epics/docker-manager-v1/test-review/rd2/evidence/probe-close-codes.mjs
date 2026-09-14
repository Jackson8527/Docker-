// Verifies that the 1005 close code seen in the live probe was CLIENT-initiated
// (my own close) rather than the backend's `ws.close()`, which Starlette
// defaults to code 1000. If a server-initiated close yields 1000, then
// isRetryableClose(1000) === false correctly stops the retry loop, and the
// "endless replay of the tail" worry is unfounded.
function probe(label, url, { autoClose = false } = {}) {
  return new Promise((res) => {
    const ws = new WebSocket(url)
    const t = setTimeout(() => {
      console.log(`${label}: timeout -> client closes NOW (this is where 1005 came from)`)
      try { ws.close() } catch {}
    }, 4000)
    ws.onclose = (ev) => {
      clearTimeout(t)
      console.log(`${label}: close code=${ev.code} wasClean=${ev.wasClean}`)
      res()
    }
    ws.onerror = () => {}
  })
}

// 1) Client-initiated close (reproduces 1005)
await probe('client-close', 'ws://127.0.0.1:8088/ws/logs?filter=dockermgr-frontend&stream=stdout&tail=3')

// 2) Server-initiated close after an error frame == the same code path
//    _close_ws() uses in the finally block.
await probe('server-close-after-error-frame', 'ws://127.0.0.1:8088/ws/logs?filter=nope-xyz&stream=stdout&tail=3')

// 3) Server-initiated close for /ws/exec
await probe('server-close-exec', 'ws://127.0.0.1:8088/ws/exec?container=nope-xyz')
