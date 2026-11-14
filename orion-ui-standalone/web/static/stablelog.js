/* Keep a polled message log readable.
 *
 *   patchLog(box, items, keyOf, html, emptyHtml)
 *
 * Instead of rebuilding the whole list (which throws away your place, your text selection
 * and makes the box jump), this patches only what changed: new messages are inserted,
 * gone ones removed, the rest are the same DOM nodes as before. Then:
 *   - if you were at the bottom (or it's the first fill), it follows the newest message;
 *   - otherwise the message you were reading stays exactly where it was on screen, even
 *     when older messages rolled off the top of the window;
 *   - while you're selecting text inside the box, nothing is touched (next poll will).
 * Returns true when the DOM was updated.
 */
(function () {
  window.patchLog = function (box, items, keyOf, html, emptyHtml) {
    const sel = window.getSelection && window.getSelection();
    if (sel && !sel.isCollapsed && sel.anchorNode && box.contains(sel.anchorNode)) return false;

    const first = !box._filled;
    const follow = first || box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    let anchor = null, offset = 0;
    if (!follow) {
      const top = box.getBoundingClientRect().top;
      for (const el of box.children) {
        const r = el.getBoundingClientRect();
        if (r.bottom > top) { anchor = el; offset = r.top - top; break; }
      }
    }

    if (!items.length) {
      box.innerHTML = emptyHtml || '';
      box._filled = true;
      return true;
    }
    const old = new Map();
    for (const el of box.children) if (el.dataset.key) old.set(el.dataset.key, el);
    const tpl = document.createElement('template');
    let cursor = box.firstChild;
    items.forEach(it => {
      const key = String(keyOf(it)), h = html(it);
      let el = old.get(key);
      if (el && el._html !== h) {       // its text changed (a relative clock, an edit): refresh the same node
        tpl.innerHTML = h;
        const fresh = tpl.content.firstElementChild;
        el.className = fresh.className;
        el.innerHTML = fresh.innerHTML;
        el._html = h;
      } else if (!el) {
        tpl.innerHTML = h;
        el = tpl.content.firstElementChild;
        el.dataset.key = key; el._html = h;
      }
      old.delete(key);
      if (el === cursor) cursor = cursor.nextSibling;
      else box.insertBefore(el, cursor);
    });
    while (cursor) { const next = cursor.nextSibling; cursor.remove(); cursor = next; }

    if (follow) box.scrollTop = box.scrollHeight;
    else if (anchor && anchor.isConnected) {
      box.scrollTop += (anchor.getBoundingClientRect().top - box.getBoundingClientRect().top) - offset;
    }
    box._filled = true;
    return true;
  };
})();
