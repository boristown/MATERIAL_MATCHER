(function () {
  var ua = navigator.userAgent || '';
  var browser = '';
  var version = 0;
  var minimum = 0;
  var match;

  match = /Firefox\/(\d+)/.exec(ua);
  if (match) {
    browser = 'firefox';
    version = parseInt(match[1], 10) || 0;
    minimum = 52;
  } else {
    match = /(?:Chrome|Chromium)\/(\d+)/.exec(ua);
    if (match && !/(?:Edg|Edge|OPR)\//.test(ua)) {
      browser = 'chrome';
      version = parseInt(match[1], 10) || 0;
      minimum = 49;
    }
  }

  function block(reasonBrowser, reasonVersion) {
    var path = window.location.pathname || '';
    window.__MM_BROWSER_UNSUPPORTED__ = true;
    if (path.indexOf('/unsupported-browser.html') !== -1) return;

    var target = '/unsupported-browser.html';
    var query = [];
    if (reasonBrowser) query.push('browser=' + encodeURIComponent(reasonBrowser));
    if (reasonVersion) query.push('version=' + encodeURIComponent(String(reasonVersion)));
    if (query.length) target += '?' + query.join('&');
    window.location.replace(target);
  }

  if (browser && version < minimum) {
    block(browser, version);
    return;
  }

  /*
   * XP baseline: the production build ships an ESM track and a legacy
   * SystemJS/nomodule track (chrome >= 49 / firefox >= 52 ESR). Legacy
   * engines execute the nomodule track, so ES module support is NOT
   * required. Instead require the ES2015 runtime baseline that both
   * tracks depend on (Promise + Proxy + Symbol, covered by core-js
   * polyfills on the ESM track and natively on the XP browsers).
   */
  if (typeof Promise === 'undefined' || typeof Proxy === 'undefined' || typeof Symbol === 'undefined') {
    block('', 0);
  }
})();
