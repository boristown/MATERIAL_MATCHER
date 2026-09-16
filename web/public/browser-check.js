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
    minimum = 79;
  } else {
    match = /(?:Chrome|Chromium)\/(\d+)/.exec(ua);
    if (match && !/(?:Edg|Edge|OPR)\//.test(ua)) {
      browser = 'chrome';
      version = parseInt(match[1], 10) || 0;
      minimum = 87;
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
   * The main application is an ES module application. Browsers without
   * `nomodule` support are too old to execute the production bundle safely.
   * Known Firefox/Chrome versions are handled above so the upgrade page can
   * show the exact product-specific minimum version.
   */
  if (!('noModule' in document.createElement('script'))) {
    block('', 0);
  }
})();
