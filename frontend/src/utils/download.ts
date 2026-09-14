import { showApiError } from './error'

/**
 * How long the preflight waits for response headers.
 *
 * Matches the axios default in api/index.ts (30s) rather than inventing a
 * second timeout for the user to learn; the preflight only needs the status
 * line, but a daemon busy exporting something else can take a while to answer.
 * Without it a wedged backend left the button spinning forever, because such a
 * `fetch` neither resolves nor rejects.
 */
const PREFLIGHT_TIMEOUT = 30000

/**
 * Preflight a streaming download, then let the browser perform the real
 * transfer through a plain `<a href>`.
 *
 * Why the preflight: a bare `<a href>` has no failure channel at all. When the
 * backend answered 500 (path does not exist, image gone, daemon error) the
 * browser navigated to the JSON error page while the UI still announced
 * "已开始下载/已开始导出" - a fake success. `fetch()` first makes the status
 * code observable.
 *
 * Why the download itself stays a direct link: the response is a streamed
 * tar (see spec.md D6). Reading it through fetch/blob would pull the whole
 * archive into memory, which is exactly what the streaming design avoids. The
 * link hands the transfer to the browser's own download manager.
 *
 * COST: the preflight makes the backend start a second, short-lived export.
 * `docker get_archive` / `images.save()` begin producing the tar as soon as
 * they are called, and we cancel that response body the moment its headers
 * arrive - so every download now pays one aborted export on the server. That
 * daemon-side work is unavoidable if the user is to see failures at all; the
 * body is cancelled immediately so nothing of it is buffered in the browser.
 *
 * KNOWN LIMIT: the preflight only reads the status line. The failures it exists
 * for (path does not exist, image already removed) are raised by docker-py
 * before the streamed response is constructed, so those are caught - but a
 * daemon that fails *after* answering 200 (I/O error while packing a large
 * layer, disk full) still reaches the browser as a truncated tar while the UI
 * says "已开始下载/已开始导出". Draining one chunk here would close that gap,
 * at the cost of the streaming design this path is built around; the response
 * is `Transfer-Encoding: chunked`, so `Content-Length` cannot be used for an
 * integrity check either.
 *
 * @returns `true` when the download was handed to the browser, `false` when
 *          the preflight failed - in which case the error has already been
 *          surfaced through `showApiError`.
 */
export async function startDownload(url: string, filename: string): Promise<boolean> {
  // The abort is what makes the wait finite; `timedOut` is set right before it
  // so the failure can be explained instead of surfacing a bare DOMException.
  const ctrl = new AbortController()
  let timedOut = false
  const timer = window.setTimeout(() => {
    timedOut = true
    ctrl.abort()
  }, PREFLIGHT_TIMEOUT)

  let res: Response
  try {
    res = await fetch(url, { signal: ctrl.signal })
  } catch (err) {
    // fetch only rejects on network-level failures (DNS, offline, CORS) - or on
    // our own abort, whose DOMException message is not fit to show a user.
    showApiError(
      timedOut
        ? new Error(
            `预检超过 ${PREFLIGHT_TIMEOUT / 1000} 秒仍未收到响应，已取消本次下载。` +
              '请确认后端与 Docker daemon 是否正常后重试。'
          )
        : err,
      '下载失败'
    )
    return false
  } finally {
    // Headers arrived (or the abort fired): the timer must not outlive this
    // call, where a late abort would kill the streaming error-body read below.
    window.clearTimeout(timer)
  }

  if (!res.ok) {
    const detail = await readErrorDetail(res)
    showApiError({ response: { data: { detail }, status: res.status } }, '下载失败')
    return false
  }

  // Release the preflight body before it starts streaming for real. `cancel()`
  // also aborts the underlying request, so the server stops writing the tar.
  try {
    await res.body?.cancel()
  } catch {
    // Already closed/aborted - there is nothing left to release.
  }

  const a = document.createElement('a')
  a.href = url
  a.download = filename
  // Firefox ignores a click on a detached anchor, so mount it first.
  document.body.appendChild(a)
  a.click()
  a.remove()
  return true
}

/** Pull FastAPI's `{"detail": ...}` out of an error response, whatever its shape. */
async function readErrorDetail(res: Response): Promise<string> {
  try {
    const text = await res.text()
    try {
      const body = JSON.parse(text) as { detail?: unknown } | null
      if (body && typeof body === 'object' && body.detail != null) {
        return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      }
    } catch {
      // Not JSON (nginx error page, empty body, ...): fall through to the text.
    }
    return text.trim() || `${res.status} ${res.statusText}`
  } catch {
    return `${res.status} ${res.statusText}`
  }
}
