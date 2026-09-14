const wsUrl = (p) => `ws://127.0.0.1:8088${p}`
function probe(label, url) {
  return new Promise((res) => {
    const ws = new WebSocket(url)
    const frames = []
    const t = setTimeout(() => { try { ws.close() } catch {} ; res() }, 4000)
    ws.onmessage = (e) => { frames.push(typeof e.data === 'string' ? `TEXT(${e.data.length}):${e.data.slice(0,70).replace(/\n/g,'\\n')}` : `BIN(${e.data.byteLength})`) }
    ws.onerror = () => { console.log(`${label}: error`); }
    ws.onclose = (ev) => { clearTimeout(t); console.log(`${label}: close code=${ev.code} reason=${JSON.stringify(ev.reason)} frames=${frames.length}`); frames.slice(0,3).forEach(f=>console.log(`   ${f}`)); res() }
  })
}
await probe('ws/logs (running container)', wsUrl('/ws/logs?filter=dockermgr-frontend&stream=stdout&tail=3'))
await probe('ws/logs (nonexistent container -> error frame)', wsUrl('/ws/logs?filter=does-not-exist-xyz&stream=stdout&tail=3'))
await probe('ws/exec (nonexistent container -> error frame)', wsUrl('/ws/exec?container=does-not-exist-xyz'))
