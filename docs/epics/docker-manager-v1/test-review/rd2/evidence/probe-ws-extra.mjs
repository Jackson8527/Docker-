import { isRetryableClose, parseServerErrorFrame } from './ws.ts'
console.log('isRetryableClose(1005) =', isRetryableClose(1005), '(a bare client-side close)')
console.log('isRetryableClose(1000) =', isRetryableClose(1000))
console.log('isRetryableClose(1006) =', isRetryableClose(1006))
console.log('--- adversarial parse cases: real-world JSON logging ---')
for (const c of [
  '{"error":"boom","msg":"db down"}',
  '{"level":"error","error":"ECONNREFUSED","msg":"upstream"}',
  '{"time":"2026-09-11T00:00:00Z","error":"x"}',
  '{"error":{"code":500}}',
  '  {"error":"x"}  ',
  '{"error":"x"} trailing',
]) console.log(' ', JSON.stringify(c).padEnd(58), '->', JSON.stringify(parseServerErrorFrame(c)))
