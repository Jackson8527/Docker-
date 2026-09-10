import { ElMessage, ElMessageBox } from 'element-plus'

interface ApiErrorLike {
  response?: { data?: { detail?: unknown }; status?: number }
}

/**
 * Surface an API error.
 *
 * Pull failures carry a long, multi-line explanation (every registry that was
 * tried), which a toast would truncate - those open in a dialog instead.
 */
export function showApiError(err: unknown, title = '操作失败') {
  const e = err as ApiErrorLike
  const raw = e?.response?.data?.detail

  let detail: string
  if (typeof raw === 'string' && raw.trim()) {
    detail = raw
  } else if (raw != null) {
    detail = JSON.stringify(raw)
  } else {
    detail = err instanceof Error ? err.message : String(err)
  }

  if (detail.length > 140 || detail.includes('\n')) {
    ElMessageBox.alert(detail, title, {
      confirmButtonText: '知道了',
      customStyle: { maxWidth: '580px' },
    }).catch(() => {})
  } else {
    ElMessage.error(detail)
  }
}
