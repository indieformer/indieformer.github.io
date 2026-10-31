/* site-chrome.js — single source of truth for the Indieformer site nav + footer.
   To add/remove a game or nav item, edit NAV_LINKS below. To change footer
   links, edit the FOOTER markup. Injected into [data-shared-nav] / [data-shared-footer]
   placeholders on every page that uses the shared chrome. Relies on each page's
   existing .site-nav / .site-footer CSS (unchanged). */
(function () {
  // ── the one place to edit the top nav ──
  var NAV_LINKS = [
    { href: '/how-we-make-a-game-popular/', label: 'The Approach' },
    { href: '/notes/', label: 'Notes' },
    // a group renders as a dropdown. Add a game here and nowhere else.
    { label: 'Games', children: [
      { href: '/scorchpot/',       label: 'Feed the Scorchpot' },
      { href: '/abelina/',         label: 'Abelina' },
      { href: '/slots-slaughter/', label: 'Slots & Slaughter' },
      { href: '/devilcoin/',       label: 'Devilcoin' }
    ] }
  ];

  var path = location.pathname;
  if (path.charAt(path.length - 1) !== '/') path += '/'; // normalise trailing slash

  function isCurrent(href) {
    return href !== '/' && (path === href || path.indexOf(href) === 0);
  }

  function esc(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

  function navHTML() {
    var links = NAV_LINKS.map(function (l) {
      if (!l.children) {
        return '<a href="' + l.href + '"' + (isCurrent(l.href) ? ' class="current"' : '') +
               '>' + esc(l.label) + '</a>';
      }
      var open = l.children.some(function (c) { return isCurrent(c.href); });
      var items = l.children.map(function (c) {
        return '<a role="menuitem" href="' + c.href + '"' +
               (isCurrent(c.href) ? ' class="current"' : '') + '>' + esc(c.label) + '</a>';
      }).join('');
      return '<span class="nav-group">' +
          '<button type="button" class="nav-trigger' + (open ? ' current' : '') +
            '" aria-expanded="false" aria-haspopup="true">' + esc(l.label) +
            '<svg viewBox="0 0 10 6" aria-hidden="true" width="10" height="6"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>' +
          '</button>' +
          '<span class="nav-menu" role="menu">' + items + '</span>' +
        '</span>';
    }).join('\n    ');
    return '' +
      '<a class="brand" href="/" aria-label="Indieformer home">\n' +
      '    <img src="/logo.png" alt="Indieformer" width="40" height="40">\n' +
      '  </a>\n' +
      '  <nav class="primary-nav" aria-label="Primary">\n    ' + links + '\n  </nav>';
  }

  /* The nav links themselves are styled by each page. The dropdown is new, so
     its CSS ships here rather than being copied into eighteen files. Colours
     fall back to literals for any page that does not define the tokens. */
  var NAV_CSS = '' +
    '.nav-group{position:relative;display:inline-flex}' +
    '.nav-trigger{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer;' +
      'display:inline-flex;align-items:center;gap:6px}' +
    '.nav-trigger svg{transition:transform .18s ease;opacity:.7}' +
    '.nav-group[data-open] .nav-trigger svg{transform:rotate(180deg)}' +
    '.nav-menu{position:absolute;top:calc(100% + 10px);left:50%;transform:translateX(-50%) translateY(-4px);' +
      'display:flex;flex-direction:column;min-width:190px;padding:7px;gap:2px;z-index:300;' +
      'background:var(--shadow-mid,#2F3040);border:1px solid var(--border-mid,rgba(255,255,255,.16));' +
      'border-radius:11px;box-shadow:0 18px 44px rgba(0,0,0,.5);' +
      'opacity:0;visibility:hidden;pointer-events:none;transition:opacity .16s ease,transform .16s ease}' +
    '.nav-group[data-open] .nav-menu{opacity:1;visibility:visible;pointer-events:auto;transform:translateX(-50%) translateY(0)}' +
    '.nav-menu a{display:block;padding:8px 11px;border-radius:7px;white-space:nowrap;text-decoration:none}' +
    '.nav-menu a:hover,.nav-menu a:focus-visible{background:var(--shadow-lite,#383A4D)}' +
    /* no hover on touch, so the click handler carries it there */
    '@media (hover:hover){.nav-group:hover .nav-menu{opacity:1;visibility:visible;pointer-events:auto;transform:translateX(-50%) translateY(0)}}' +
    '@media (max-width:640px){.nav-menu{left:0;transform:none;min-width:170px}' +
      '.nav-group[data-open] .nav-menu{transform:none}' +
      '@media (hover:hover){.nav-group:hover .nav-menu{transform:none}}}' +
    /* the gem turns to catch the light on hover; transform only, and it sits out
       entirely for anyone who asked for less motion */
    '@media (hover:hover) and (prefers-reduced-motion:no-preference){' +
      '.brand img{transition:transform .35s cubic-bezier(.2,.9,.3,1)}' +
      '.brand:hover img{transform:rotate(-8deg) scale(1.08)}}';

  function wireDropdowns(root) {
    var groups = [].slice.call(root.querySelectorAll('.nav-group'));
    function closeAll(except) {
      groups.forEach(function (g) {
        if (g === except) return;
        g.removeAttribute('data-open');
        g.querySelector('.nav-trigger').setAttribute('aria-expanded', 'false');
      });
    }
    groups.forEach(function (g) {
      var btn = g.querySelector('.nav-trigger');
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var open = g.hasAttribute('data-open');
        closeAll(g);
        if (open) { g.removeAttribute('data-open'); btn.setAttribute('aria-expanded', 'false'); }
        else { g.setAttribute('data-open', ''); btn.setAttribute('aria-expanded', 'true'); }
      });
    });
    document.addEventListener('click', function () { closeAll(null); });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var open = root.querySelector('.nav-group[data-open]');
      if (open) { closeAll(null); open.querySelector('.nav-trigger').focus(); }
    });
  }

  // ── footer markup (kept byte-identical to the original site-footer) ──
  var FOOTER_HTML = `
  <div class="footer-col brand-col">
    <img class="footer-logo" src="/logo-lockup.png" alt="Indieformer">
    <p>A small indie game publisher. Run by Josh &amp; Clem in Melbourne, Australia.</p>
  </div>
  <div class="footer-col">
    <p class="footer-label">Guides &amp; reads</p>
    <ul>
      <li><a href="https://indieformer.com/essay/">How to Really Make a Game</a></li>
      <li><a href="/press-kit-guide/">Press Kit Guide</a></li>
      <li><a href="/steam-marketing-guide/">Steam Marketing Guide</a></li>
    </ul>
  </div>
  <div class="footer-col">
    <p class="footer-label">Elsewhere</p>
    <ul>
<li><a href="https://indieformer.beehiiv.com">Newsletter archive</a></li>
    </ul>
  </div>
  <div class="footer-col">
    <p class="footer-label">Find us</p>
    <div class="social-icons">
      <a href="https://www.threads.com/@indieformer" target="_blank" rel="noopener" aria-label="Threads">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M17.79 11.4c-.09-.04-.18-.08-.27-.12-.16-2.93-1.76-4.6-4.44-4.62h-.04c-1.6 0-2.94.69-3.76 1.94l1.47.97c.61-.93 1.59-1.13 2.28-1.13h.03c.87.01 1.51.26 1.94.74.3.34.5.83.6 1.45-.74-.12-1.54-.16-2.39-.11-2.38.14-3.91 1.53-3.81 3.45.05.86.5 1.6 1.25 2.1.66.42 1.5.62 2.39.58 1.16-.05 2.06-.49 2.68-1.3.48-.62.77-1.41.91-2.39.55.34.96.78 1.19 1.31.39.91.42 2.4-.79 3.61-1.06 1.05-2.32 1.5-4.22 1.51-2.11-.02-3.7-.71-4.74-2.05-.97-1.25-1.48-3.05-1.5-5.35.02-2.31.53-4.11 1.5-5.36 1.04-1.34 2.63-2.03 4.74-2.05 2.13.02 3.75.71 4.81 2.06.52.66.93 1.49 1.18 2.46l1.71-.46c-.3-1.2-.79-2.21-1.44-3.04-1.39-1.74-3.39-2.62-5.95-2.64h-.02c-2.56.02-4.56.91-5.92 2.64-1.22 1.54-1.85 3.66-1.86 6.31v.01c.02 2.65.65 4.78 1.86 6.31 1.37 1.74 3.36 2.62 5.92 2.64h.02c2.27-.02 3.87-.62 5.2-1.96 1.73-1.75 1.68-3.94 1.11-5.29-.41-.96-1.19-1.75-2.24-2.3z"/></svg>
      </a>
      <a href="https://bsky.app/profile/indieformer.com" target="_blank" rel="noopener" aria-label="Bluesky">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M5.84 4.94c2.31 1.74 4.79 5.26 5.7 7.15.91-1.89 3.39-5.41 5.7-7.15 1.66-1.25 4.36-2.22 4.36 .89 0 .62-.36 5.22-.57 5.96-.73 2.59-3.37 3.25-5.71 2.85 4.1.7 5.15 3.04 2.89 5.39-4.3 4.46-6.18-1.12-6.66-2.55-.09-.26-.13-.38-.13-.28 0-.11-.04.02-.13.28-.48 1.43-2.36 7.01-6.66 2.55-2.26-2.34-1.22-4.69 2.89-5.39-2.34.4-4.99-.26-5.71-2.85-.21-.74-.57-5.34-.57-5.96 0-3.11 2.7-2.14 4.36-.89z"/></svg>
      </a>
      <a href="https://discord.gg/rztz9s2wb3" target="_blank" rel="noopener" aria-label="Discord">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M20.32 4.74A19.79 19.79 0 0 0 16.06 3a.07.07 0 0 0-.07.04 13.95 13.95 0 0 0-.61 1.27 18.31 18.31 0 0 0-5.48 0c-.16-.41-.4-.91-.62-1.27a.08.08 0 0 0-.08-.04A19.74 19.74 0 0 0 4.93 4.74a.07.07 0 0 0-.03.03A20.32 20.32 0 0 0 1.04 18.21a.08.08 0 0 0 .03.05 19.93 19.93 0 0 0 6.03 3.04.07.07 0 0 0 .08-.03c.46-.63.88-1.3 1.23-2a.07.07 0 0 0-.04-.1 13.07 13.07 0 0 1-1.88-.9.07.07 0 0 1 0-.13c.13-.1.25-.2.37-.3a.07.07 0 0 1 .07-.01c3.94 1.8 8.21 1.8 12.1 0a.07.07 0 0 1 .08.01c.12.1.24.2.37.3a.07.07 0 0 1 0 .13c-.6.35-1.23.65-1.88.9a.07.07 0 0 0-.04.1c.36.7.78 1.37 1.23 2a.07.07 0 0 0 .08.03 19.86 19.86 0 0 0 6.03-3.04.08.08 0 0 0 .03-.05 20.18 20.18 0 0 0-3.86-13.44.06.06 0 0 0-.03-.03zM8.52 15.27c-1.19 0-2.17-1.09-2.17-2.43 0-1.34.96-2.43 2.17-2.43 1.22 0 2.19 1.1 2.17 2.43 0 1.34-.96 2.43-2.17 2.43zm8.03 0c-1.19 0-2.17-1.09-2.17-2.43 0-1.34.96-2.43 2.17-2.43 1.22 0 2.19 1.1 2.17 2.43 0 1.34-.95 2.43-2.17 2.43z"/></svg>
      </a>
    </div>
  </div>

  <p class="footer-meta">© ${new Date().getFullYear()} Indieformer. · <a href="/privacy/">Privacy</a> · <a href="/terms/">Terms</a></p>`;

  function fill(sel, html) {
    var el = document.querySelector(sel);
    if (el) el.innerHTML = html;
  }
  var navEl = document.querySelector('[data-shared-nav]');
  if (navEl) {
    var st = document.createElement('style');
    st.textContent = NAV_CSS;
    document.head.appendChild(st);
    navEl.innerHTML = navHTML();
    wireDropdowns(navEl);
  }
  fill('[data-shared-footer]', FOOTER_HTML);
})();
