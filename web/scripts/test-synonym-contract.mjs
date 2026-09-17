import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), 'utf8')
const exists = (...parts) => fs.existsSync(path.join(root, ...parts))

const view = read('src/views/DataView.vue')
const app = read('src/App.vue')
const system = read('src/views/SystemView.vue')
const css = read('src/styles/pages/data.css')
const html = read('index.html')
const favicon = read('public', 'favicon.svg')

const requiredView = [
  '<h2>同义词配置</h2>',
  '当前同义词配置',
  '保存修改',
  '+ 添加一条',
  '搜索同义词（原始写法或统一写法）',
  '查看历史',
  '有未保存的修改',
  '已保存为第',
  '匹配设置',
  '区分大小写',
  '保存后将形成新的同义词版本，历史任务不会受到影响',
  'base_version_no',
  'DICTIONARY_VERSION_CONFLICT',
  'syn-grid__head',
  'syn-grid__row',
  '原始写法',
  '统一写法',
  '删除',
  '同义词版本历史',
  'created_by',
]
for (const token of requiredView) {
  if (!view.includes(token)) throw new Error(`Synonym view contract missing: ${token}`)
}

const bannedView = ['创建新版本', '业务字典', '数据字典', '字典管理', 'dictionaryDialogVisible', 'mapping-editor']
for (const token of bannedView) {
  if (view.includes(token)) throw new Error(`Synonym view must not contain: ${token}`)
}

if (!app.includes("['同义词配置', '/data']")) throw new Error('Side menu must show 同义词配置')
for (const token of ['业务字典', '数据字典', '字典管理']) {
  if (app.includes(token)) throw new Error(`Side menu must not contain ${token}`)
  if (system.includes(token)) throw new Error(`System page must not contain ${token}`)
}

if (!html.includes('rel="icon"') || !html.includes('favicon.svg')) throw new Error('index.html must reference favicon.svg')
if (!html.includes('<title>物料集团码智能匹配平台</title>')) throw new Error('index.html title must be the product name')
for (const token of ['dev', 'vite', 'test', 'localhost']) {
  const title = html.match(/<title>([^<]*)<\/title>/)?.[1] ?? ''
  if (title.toLowerCase().includes(token)) throw new Error(`Title must not contain technical word: ${token}`)
}
if (!favicon.includes('#BF2D2B') || !favicon.includes('#1C2B7E')) throw new Error('favicon must reuse the 小罡 AI brand mark')
if (!favicon.includes('aria-label="小罡 AI"')) throw new Error('favicon must carry the brand label')
if (exists('public', 'favicon.png') || exists('public', 'logo.png')) throw new Error('binary favicon assets are not allowed by repository policy')

const requiredCss = [
  'position: sticky',
  'grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1fr) 72px',
  '.syn-grid__head',
  '.syn-grid__row',
  '.syn-actions',
  '.syn-arrow',
]
for (const token of requiredCss) {
  if (!css.includes(token)) throw new Error(`Synonym CSS contract missing: ${token}`)
}

if (!view.includes('el-input v-model="row.source"') || !view.includes('el-input v-model="row.target"')) {
  throw new Error('Mapping rows must be inline-editable on the main page (no modal editor)')
}

console.log('STEP synonym-ux + favicon contract checks passed')
