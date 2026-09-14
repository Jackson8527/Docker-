import { parseServerErrorFrame, isRetryableClose, describeWsError } from './ws.ts'

const cases = [
  ['batch of lines', 'line one\nline two'],
  ['json log line, no error key', '{"level":"info","msg":"hello"}'],
  ['json log line WITH error key', '{"error":"connection reset by peer"}'],
  ['real error frame', '{"error": "no container"}'],
  ['error frame w/ padding', '\n {"error": "no such container: web"} \n'],
  ['array frame', '[1,2,3]'],
  ['empty error', '{"error": ""}'],
  ['null error', '{"error": null}'],
  ['non-string error', '{"error": 42}'],
  ['plain text', 'hello world'],
  ['json scalar', '42'],
  ['multi-line log ending with }', 'a\n{"x":1}'],
  ['error frame + more log', '{"error":"x"}\nmore log'],
]
for (const [name, raw] of cases) {
  console.log(name.padEnd(34), '->', JSON.stringify(parseServerErrorFrame(raw)))
}

console.log('--- isRetryableClose ---')
for (const code of [1000, 1001, 1005, 1006, 1008, 1011, 1015, 4000]) {
  console.log(String(code).padEnd(6), isRetryableClose(code))
}

console.log('--- describeWsError ---')
console.log(describeWsError('no container'))
console.log(describeWsError('no such container: web'))
console.log(describeWsError('boom'))
