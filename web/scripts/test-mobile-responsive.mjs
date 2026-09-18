import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')

const marker = '/* ===== 手机端适配（≤760px）'
const split = css.indexOf(marker)
if (split < 0) throw new Error('mobile media block missing from styles.css')
const base = css.slice(0, split)
const mobile = css.slice(split)

/* PC rules must stay untouched: fixed sidebar, 224px gutter, desktop paddings */
if (!/aside\s*{[^}]*width: 224px/.test(base)) throw new Error('desktop aside width 224px must be kept')
if (!/aside\s*{[^}]*position: fixed/.test(base)) throw new Error('desktop aside must stay fixed')
if (!base.includes('main { margin-left: 224px;')) throw new Error('desktop main margin-left 224px must be kept')
if (!base.includes('.content { padding: 22px 24px 40px; max-width: 1480px; }')) throw new Error('desktop content padding must be kept')
if (!base.includes('.shell { display: flex; min-height: 100vh; min-height: 100dvh; }')) throw new Error('shell needs the dvh upgrade over the vh fallback')

/* the mobile block must be media-query scoped and flip the shell */
if (!mobile.startsWith('/* ===== 手机端适配（≤760px）') || !mobile.includes('@media (max-width: 760px) {')) throw new Error('mobile rules must live inside @media (max-width: 760px)')
for (const token of [
  '.shell { display: block; }',
  'position: static',
  'main { margin-left: 0; }',
  '.step-nav { flex-direction: row; overflow-x: auto',
  '.step-nav .nav-desc { display: none; }',
  '.support-nav { display: flex; flex-direction: row',
  '.content { padding: 14px 14px 36px; }',
  '.uploads { grid-template-columns: 1fr',
  '.content .el-input, .content .el-select, .content .el-slider, .content .el-input-number { max-width: 100%; }',
  '.el-overlay-dialog .el-dialog { max-width: calc(100vw - 20px); }',
  '.el-message-box { max-width: calc(100vw - 32px); }',
  '.el-drawer { max-width: 100vw; }',
  '.hero-grid { grid-template-columns: 1fr 1fr',
  '.hero.idle { flex-direction: column',
]) {
  if (!mobile.includes(token)) throw new Error(`mobile contract missing: ${token}`)
}
if (/\b100vh\b/.test(mobile)) throw new Error('mobile block must not reintroduce fixed 100vh rules')

/* login page phone breakpoint from the branding special must survive */
if (!css.includes('@media (max-width: 480px)') || !css.includes('min-height: 100dvh')) throw new Error('login responsive rules must be kept')

/* STEP3 console must not force page-level overflow on 320px phones */
const review = fs.readFileSync(path.join(root, 'src/styles/pages/review.css'), 'utf8')
if (!/@media \(max-width: 480px\)[\s\S]*?\.review-console-main\s*{[^}]*min-width: 0/.test(review)) throw new Error('review console main needs a 480px min-width:0 escape')

console.log('mobile responsive + desktop guard contract checks passed')
