import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const guardPath = fileURLToPath(new URL('../public/browser-check.js', import.meta.url))
const pagePath = fileURLToPath(new URL('../public/unsupported-browser.html', import.meta.url))
const guardSource = readFileSync(guardPath, 'utf8')
const pageSource = readFileSync(pagePath, 'utf8')

function runGuard(userAgent, supportsModule = true) {
  let redirectedTo = ''
  const scriptElement = supportsModule ? { noModule: false } : {}
  const context = {
    navigator: { userAgent },
    document: { createElement: () => scriptElement },
    window: {
      location: {
        pathname: '/',
        replace: target => { redirectedTo = target },
      },
    },
    encodeURIComponent,
    parseInt,
  }
  vm.runInNewContext(guardSource, context, { filename: 'browser-check.js' })
  return redirectedTo
}

assert.match(runGuard('Mozilla/5.0 Firefox/47.0'), /browser=firefox&version=47/)
assert.match(runGuard('Mozilla/5.0 Firefox/78.0'), /browser=firefox&version=78/)
assert.equal(runGuard('Mozilla/5.0 Firefox/79.0'), '')

assert.match(runGuard('Mozilla/5.0 Chrome/49.0.2623.112 Safari/537.36'), /browser=chrome&version=49/)
assert.match(runGuard('Mozilla/5.0 Chrome/86.0.4240.198 Safari/537.36'), /browser=chrome&version=86/)
assert.equal(runGuard('Mozilla/5.0 Chrome/87.0.4280.88 Safari/537.36'), '')

assert.equal(runGuard('Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'), '')
assert.equal(runGuard('Unknown Modern Browser', true), '')
assert.equal(runGuard('Unknown Ancient Browser', false), '/unsupported-browser.html')

assert.match(pageSource, /浏览器版本过低/)
assert.match(pageSource, /Firefox &ge;79/)
assert.match(pageSource, /Chrome &ge;87/)

console.log('browser compatibility guard tests passed')
