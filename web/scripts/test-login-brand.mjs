import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const view = fs.readFileSync(path.join(root, 'src/views/LoginView.vue'), 'utf8')
const css = fs.readFileSync(path.join(root, 'src/styles.css'), 'utf8')
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8')

/* product naming: the platform name replaces the old engine wording */
if (view.includes('物料集团码匹配引擎')) throw new Error('Login page must not show “物料集团码匹配引擎”')
if (!view.includes('物料集团码') || !view.includes('智能匹配平台')) throw new Error('Login page must show the product name 物料集团码智能匹配平台')
if (html.includes('匹配引擎')) throw new Error('index.html title must stay 物料集团码智能匹配平台')
if (!view.includes('使用分配的本地账号登录')) throw new Error('Login subtitle must stay business-friendly')

/* 小罡 AI brand block above the form, reusing the existing favicon asset */
if (!view.includes('/favicon.svg')) throw new Error('Login must reuse the existing 小罡 AI brand asset')
if (!view.includes('小罡 AI')) throw new Error('Login must show the 小罡 AI brand name')

/* version comes from the shared backend-version helper, never hard-coded */
if (!view.includes('fetchAppVersion')) throw new Error('Login footer must read the shared runtime version')
if (/v1\.0[^-9.]/.test(view)) throw new Error('Login must not hard-code v1.0')

/* mobile-first layout: dvh with vh fallback, scrollable, safe areas, no fixed 420px card */
if (!css.includes('min-height: 100vh')) throw new Error('Login needs a vh fallback before dvh')
if (!css.includes('min-height: 100dvh')) throw new Error('Login must use 100dvh so soft keyboards keep the page usable')
if (!css.includes('overflow-y: auto')) throw new Error('Login must stay scrollable on short screens')
if (!css.includes('env(safe-area-inset-top)') || !css.includes('env(safe-area-inset-bottom)')) throw new Error('Login must respect notched-device safe areas')
if (css.includes('width: 420px')) throw new Error('Login card must not use a fixed 420px width (320px overflow)')
if (!/\.login-stage\s*{[^}]*margin:\s*auto/.test(css)) throw new Error('Login card must centre via margin:auto so tall content never clips')
if (!css.includes('max-width: 440px')) throw new Error('Login column must cap desktop width (420–480px)')
if (!css.includes('clamp(28px, 4.6vw, 36px)')) throw new Error('Title must use responsive clamp() sizing (28px phone → 36px desktop)')
if (!css.includes('@media (max-width: 480px)')) throw new Error('Login needs a dedicated phone breakpoint')
if (!/\.login \.card \.el-input__inner { font-size: 16px/.test(css)) throw new Error('Inputs must be >=16px to stop iOS auto-zoom')
if (!css.includes('min-height: 50px')) throw new Error('Inputs need ~48-52px touch height')
if (!/\.login \.card \.el-button--primary { width: 100%; height: 50px/.test(css)) throw new Error('Login button needs ~48-52px primary action height')

/* viewport meta stays device-width for responsive rendering */
if (!html.includes('width=device-width')) throw new Error('index.html must keep the responsive viewport meta')

/* authentication logic must not have been touched by the restyle */
for (const token of ["api.post('/auth/login'", "api.post('/auth/change-password'", 'must_change_password', 'consumeAuthReturnTo', 'consumeAuthExpiredNotice']) {
  if (!view.includes(token)) throw new Error(`Login auth contract missing: ${token}`)
}

console.log('login brand + mobile responsive contract checks passed')
