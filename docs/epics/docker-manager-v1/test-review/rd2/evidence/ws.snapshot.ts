/**
 * Shared client side of the frozen websocket protocol (backend/app/routers/ws.py).
 *
 * Two rules live here because both `/ws/logs` and `/ws/exec` depend on them and
 * getting either wrong is silent - a wrong guess either renders a protocol
 * frame as log output or reconnects forever against a target that will never
 * answer.
 */

/**
 * Read a server-sent error frame, e.g. `{"error": "no such container: web"}`.
 *
 * `/ws/logs` and `/ws/exec` send exactly one such text frame before closing
 * when they cannot serve the request.
 *
 * The test is deliberately narrow: the WHOLE frame must parse as a JSON
 * *object* that carries a non-empty `error` string. Ordinary output is
 * therefore never misread as an error - a batched log frame (many lines joined
 * with `\n`) does not parse as JSON at all, and a log line that happens to be
 * JSON without an `error` key still goes to the log/terminal unchanged.
 *
 * @returns the reason to show the user, or `null` when the frame is data.
 */
export function parseServerErrorFrame(raw: string): string | null {
  const text = raw.trim()
  // Cheap reject before paying for JSON.parse on every log batch.
  if (!text.startsWith('{') || !text.endsWith('}')) return null

  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null

  const reason = (parsed as { error?: unknown }).error
  return typeof reason === 'string' && reason.trim() ? reason : null
}

/**
 * Should a closed socket be retried with backoff?
 *
 * `1000` (normal closure) means the backend finished on purpose: the log stream
 * ended because the container stopped, or it sent an error frame first.
 * Reconnecting would replay the same tail forever (or hammer a target that no
 * longer exists). `1008` (policy violation) is the cross-site-origin rejection
 * in `ws.py`, which a retry would hit identically.
 *
 * Everything else is treated as a dropped connection worth retrying - most
 * importantly `1006`, the code a browser reports when the transport dies
 * without a close handshake, plus `1001` (server going away) and `1011`.
 */
export function isRetryableClose(code: number): boolean {
  return code !== 1000 && code !== 1008
}

/**
 * Put a backend reason into words the user can act on.
 *
 * The important distinction is "the container does not exist" versus "the
 * connection failed": the first means retrying and editing the name are
 * pointless, the second is usually transient. `no container` is what
 * `/ws/logs` sends, `no such container: <name>` what `/ws/exec` sends.
 */
export function describeWsError(reason: string): string {
  if (/no such container|no container/i.test(reason)) {
    return `${reason} —— 容器可能已被删除或改名，请刷新列表后重试。`
  }
  return reason
}
