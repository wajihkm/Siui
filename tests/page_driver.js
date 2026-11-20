// The page test's hands and eyes, added to the board's page by the test's own server (never part of the plugin).
// It walks the board as a person would: every world, every stage, the panels, the dialogs, the search, the exports.
// After each step it notes what a hostile value managed to bring alive, and leaves the notes in a hidden <pre> for the
// test to read from the page's final markup.
(async () => {
  const sleep = ms => new Promise(done => setTimeout(done, ms));
  const out = { done: false, steps: 0, live: [], links: [], pwn: 0, asked: false, control: false, controlFired: false, tiles: 0, stops: 0, good: 0, style: '', error: '', pageError: '' };
  const pre = document.createElement('pre');
  pre.id = 'hostile-result'; pre.hidden = true;
  document.body.appendChild(pre);
  const RUNS = /^\s*(javascript|vbscript|x|data:text\/html)\s*:/i;
  const note = where => {
    out.steps += 1;
    document.querySelectorAll('[data-pwn]').forEach(el => {
      const key = `<${el.tagName.toLowerCase()} data-pwn="${el.getAttribute('data-pwn')}"> at ${where}`;
      if (out.live.length < 60 && !out.live.some(one => one.split(' at ')[0] === key.split(' at ')[0])) out.live.push(key);
    });
    document.querySelectorAll('[href], [src], [action], [formaction]').forEach(el => {
      ['href', 'src', 'action', 'formaction', 'xlink:href'].forEach(name => {
        const value = el.getAttribute(name) || '';
        if (RUNS.test(value)) { const key = `<${el.tagName.toLowerCase()} ${name}="${value.slice(0, 50)}"> at ${where}`; if (out.links.length < 30 && !out.links.includes(key)) out.links.push(key); }
      });
    });
    document.querySelectorAll('*').forEach(el => {
      for (const a of Array.from(el.attributes)) if (/^on/i.test(a.name) && /__pwn/.test(a.value)) { const key = `<${el.tagName.toLowerCase()} ${a.name}> at ${where}`; if (out.live.length < 60 && !out.live.includes(key)) out.live.push(key); }
    });
    out.pwn = window.__pwn || 0;
    out.good = document.querySelectorAll('[fill="#12ab34"]').length || out.good;
    out.style = document.documentElement.style.cssText.slice(0, 600);
    pre.textContent = JSON.stringify(out);
  };
  const click = el => el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  const closeDialogs = () => document.querySelectorAll('dialog[open]').forEach(d => { try { d.close('cancel'); } catch (e) { /* not open */ } });
  /** Clicks up to `max` of what matches, one at a time, looking after each. */
  const each = async (selector, where, max, after) => {
    const count = Math.min(document.querySelectorAll(selector).length, max);
    for (let i = 0; i < count; i += 1) {
      const el = document.querySelectorAll(selector)[i];
      if (!el) break;
      click(el); await sleep(70); note(`${where} ${selector} ${i}`);
      if (after) await after(i);
      closeDialogs();
    }
    return count;
  };
  const openDetails = async where => { document.querySelectorAll('details:not([open])').forEach(d => { d.open = true; }); await sleep(40); note(`${where} details`); };
  try {
    // The control: the same payload written the unsafe way must be seen, or the test proves nothing.
    const control = document.createElement('div');
    control.hidden = true;
    control.innerHTML = '<img src="x:" onerror="window.__pwn=(window.__pwn||0)+1" data-pwn="control">';
    document.body.appendChild(control);
    await sleep(400);
    out.control = document.querySelectorAll('[data-pwn="control"]').length === 1;
    out.controlFired = (window.__pwn || 0) > 0;
    control.remove(); window.__pwn = 0;

    for (let i = 0; i < 40 && !document.querySelector('#roadmap svg, #map svg, #card *'); i += 1) await sleep(100);
    await sleep(300);
    note('load');
    await openDetails('load');

    const PANEL = ['[data-jump]', '[data-go]', '[data-expand]', 'button[data-output]', '[data-move-event]', 'button[data-move-decision]', '[data-return]',
      'button[data-forget]', 'button[data-again]', 'button[data-queue]', 'button[data-start]', '[data-start]', '[data-hide]', '[data-delete-pack]', '[data-abandon]',
      '[data-apply]', '[data-fork]', 'button[data-road]', '.otherroad', '[data-goto]', '[data-checkpoint]', '[data-done]', '[data-reopen]', 'a[data-path]', '.gnode[data-path]', '.more-text .more'];
    const tiles = '#roadmap .tile[data-run], #roadmap .sidequests[data-run]';
    out.tiles = await each(tiles, 'world', 30, async () => {
      await openDetails('world');
      const stops = await each('#map .stop', 'stage', 8, async () => { await openDetails('stage'); await each('[data-jump]', 'stage', 2); });
      out.stops += stops;
      for (const selector of PANEL) await each(selector, 'panel', 2);
    });

    // A save point: a name, then the server's question about new files, whose names are the project's own.
    const save = document.querySelector('[data-checkpoint]');
    if (save) {
      click(save); await sleep(80); note('save point name');
      const ok = document.querySelector('#ask[open] [value=ok]');
      if (ok) { ok.click(); await sleep(250); note('save point new files'); out.asked = !!document.querySelector('#ask[open] [data-alt]:not([hidden])'); }
      closeDialogs();
    }

    // The card, the Now panel, the dialogs, the menus.
    for (const selector of ['#nowtoggle', '#nowhandle', '#agent', '#infoBtn', '[data-new]', '#readyBtn', '#card [data-showcard]', '#card .more', '#exportMenu > summary', '#schemeBtn', '#autoBtn', '#chatFirstBtn']) await each(selector, 'chrome', 2);
    await openDetails('chrome');
    const dialog = document.getElementById('newworld');
    if (dialog && dialog.showModal) { try { click(document.querySelector('[data-new]')); await sleep(80); note('new world'); dialog.querySelectorAll('input[type=radio]').forEach(r => click(r)); await sleep(60); note('new world choices'); } catch (e) { /* no such button on this state */ } closeDialogs(); }

    // The search: letters every payload holds.
    const box = document.getElementById('searchBox');
    if (box) for (const q of ['img', 'onerror', 'a', 'x:']) { box.value = q; box.dispatchEvent(new Event('input', { bubbles: true })); await sleep(80); note(`search ${q}`); await each('#searchResults .r', 'search', 3); }

    // The exports: the test's server keeps what the page sends.
    await each('[data-export]', 'export', 3, async () => { await sleep(500); note('export toast'); });
    await sleep(600);
    note('end');
  } catch (e) {
    out.error = String((e && e.stack) || e).slice(0, 600);
  }
  const live = document.getElementById('live');
  out.pageError = live && /could not be drawn|page error|error/i.test(live.textContent || '') ? (live.textContent || '').slice(0, 200) : '';
  out.done = true;
  note('done');
})();
