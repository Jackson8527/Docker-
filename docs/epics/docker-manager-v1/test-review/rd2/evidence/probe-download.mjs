// Probes the C-17 preflight contract against the LIVE deployment (old frontend
// image, but the backend endpoints are the same code as in the working tree).
const URL_IMG =
  'http://127.0.0.1:8088/api/images/sha256:72ba65eb42c10344912a84ff42408db7d34f2feb642204570ab8fc5ffd29f1d3/save'
const URL_BAD = 'http://127.0.0.1:8088/api/images/sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff/save'

async function t(label, url, { cancel = true } = {}) {
  const t0 = Date.now()
  let res
  try {
    res = await fetch(url)
  } catch (e) {
    console.log(`${label}: fetch REJECTED after ${Date.now() - t0}ms -> ${e.constructor.name}: ${e.message}`)
    return
  }
  const tHeaders = Date.now() - t0
  console.log(`${label}: headers after ${tHeaders}ms, status=${res.status} ok=${res.ok} type=${res.headers.get('content-type')}`)
  if (!res.ok) {
    console.log(`${label}: body text = ${(await res.text()).slice(0, 120)}`)
    return
  }
  const t1 = Date.now()
  try {
    await res.body.cancel()
    console.log(`${label}: res.body.cancel() resolved after ${Date.now() - t1}ms (no throw)`)
  } catch (e) {
    console.log(`${label}: cancel() threw -> ${e.constructor.name}: ${e.message}`)
  }
}

console.log('--- A) real image export: does fetch resolve on HEADERS (before the tar finishes)? ---')
await t('live-200', URL_IMG)

console.log('\n--- B) nonexistent image: does the preflight see the 500? ---')
await t('live-500', URL_BAD)

console.log('\n--- C) 3 concurrent preflights, all cancelled: any leak/error? ---')
await Promise.all([t('c1', URL_IMG), t('c2', URL_IMG), t('c3', URL_IMG)])

console.log('\n--- D) preflight against a port where nothing listens (network-level reject) ---')
await t('dead-port', 'http://127.0.0.1:9/api/images/x/save')

console.log('\n--- E) does a preflight against the /api/ prefix WITHOUT a trailing slash get redirected (C-03 impact)? ---')
{
  const r = await fetch('http://127.0.0.1:8088/api/containers/', { redirect: 'manual' })
  console.log(`live container-api preflight (redirect:manual): status=${r.status} location=${r.headers.get('location')}`)
}
