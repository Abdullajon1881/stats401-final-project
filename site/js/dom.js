/* Safe DOM construction.
 *
 * Every label this interface shows can originate in OpenStreetMap: station
 * names, entrance names, bazaar names, district labels. OSM is world-editable,
 * so those strings are untrusted input and must never be concatenated into
 * markup. The previous implementation built tooltip and detail markup as HTML
 * strings and assigned them with innerHTML, which would execute anything a
 * mapper typed into a name tag.
 *
 * Nothing in this module ever sets innerHTML. Text reaches the document only
 * through textContent, so a hostile name renders as the literal characters a
 * mapper typed and nothing else.
 */

/** Create an element. `text` is always assigned as text, never parsed. */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'text') {
      node.textContent = String(value);
    } else if (key === 'class') {
      node.className = value;
    } else if (key === 'dataset') {
      Object.assign(node.dataset, value);
    } else if (key === 'style') {
      Object.assign(node.style, value);
    } else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) {
      node.setAttribute(key, '');
    } else {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Replace an element's children with the given nodes. */
export function replace(host, children) {
  host.replaceChildren(...[].concat(children).filter(Boolean));
}

/** A key/value row, as used in tooltips. */
export function kv(key, value, valueClass) {
  return el('span', { class: 'tip-row' }, [
    el('span', { class: 'k', text: key }),
    el('span', { class: valueClass ? `v ${valueClass}` : 'v', text: value }),
  ]);
}

/** A labelled cell, as used in the district detail grid. */
export function cell(key, value, valueClass) {
  return el('div', { class: 'dd-cell' }, [
    el('div', { class: 'dd-k', text: key }),
    el('div', { class: valueClass ? `dd-v ${valueClass}` : 'dd-v', text: value }),
  ]);
}

/**
 * A display label for a feature whose name comes from OSM.
 * Missing and blank names fall back rather than rendering "null".
 */
export function safeName(value, fallback) {
  const text = value === null || value === undefined ? '' : String(value).trim();
  return text.length > 0 && text !== 'null' && text !== 'undefined' ? text : fallback;
}
