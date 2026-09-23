import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const app = fs.readFileSync(path.join(root, 'src/App.vue'), 'utf8')
const login = fs.readFileSync(path.join(root, 'src/views/LoginView.vue'), 'utf8')
const source = fs.readFileSync(path.join(root, 'src/version.ts'), 'utf8')

if (/v1\.0(?:\D|$)/.test(app)) throw new Error('App.vue must not hard-code v1.0')
for (const [name, view] of [['App.vue', app], ['LoginView.vue', login]]) {
  if (!view.includes('fetchAppVersion')) throw new Error(name + ' must use the shared runtime version helper')
  if (!view.includes('v{{ appVersion }}')) throw new Error(name + ' must render the runtime version when available')
}
if (!source.includes("api.get('/health')")) throw new Error('runtime version must come from GET /api/health')
if (!source.includes("return ''")) throw new Error('version fetch failures must degrade to an empty version')
if (/1\.3\.19|1\.0/.test(source)) throw new Error('version helper must not embed a product version')

console.log('app runtime version contract checks passed')
