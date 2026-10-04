import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const guardPath = fileURLToPath(new URL('../public/browser-check.js', import.meta.url))
const pagePath = fileURLToPath(new URL('../public/unsupported-browser.html', import.meta.url))
const guardSource = readFileSync(guardPath, 'utf8')
const pageSource = readFileSync(pagePath, 'utf8')

// XP baseline: legacy SystemJS/nomodule track allows chrome>=49 / firefox>=52,
// capability gate = Promise + Proxy + Symbol present.
function runGuard(userAgent, supportsEs2015Baseline = true) {
  let redirectedTo = ''
  const context = {
    navigator: { userAgent },
    document: { createElement: () => ({}) },
    window: {
      location: {
        pathname: '/',
        replace: target => { redirectedTo = target },
      },
    },
    encodeURIComponent,
    parseInt,
  }
  if (supportsEs2015Baseline) {
    context.Promise = function Promise() {}
    context.Proxy = function Proxy() {}
    context.Symbol = function Symbol() {}
  } else {
    context.Promise = undefined
    context.Proxy = undefined
    context.Symbol = undefined
  }
  vm.runInNewContext(guardSource, context, { filename: 'browser-check.js' })
  return redirectedTo
}

assert.match(runGuard('Mozilla/5.0 Firefox/47.0'), /browser=firefox&version=47/)
assert.equal(runGuard('Mozilla/5.0 Firefox/52.0'), '')
assert.equal(runGuard('Mozilla/5.0 Firefox/120.0'), '')

assert.match(runGuard('Mozilla/5.0 Chrome/48.0.2564.116 Safari/537.36'), /browser=chrome&version=48/)
assert.equal(runGuard('Mozilla/5.0 Chrome/49.0.2623.112 Safari/537.36'), '')
assert.equal(runGuard('Mozilla/5.0 Chrome/87.0.4280.88 Safari/537.36'), '')

assert.equal(runGuard('Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'), '')
assert.equal(runGuard('Unknown Modern Browser', true), '')
assert.equal(runGuard('Unknown Ancient Browser', false), '/unsupported-browser.html')
assert.equal(runGuard('Mozilla/5.0 (Windows NT 5.1; rv:52.0) Gecko/20100101 Firefox/52.0'), '')

assert.match(pageSource, /浏览器版本过低/)
assert.match(pageSource, /Firefox &ge;52/)
assert.match(pageSource, /Chrome &ge;49/)

console.log('browser compatibility guard tests passed')
