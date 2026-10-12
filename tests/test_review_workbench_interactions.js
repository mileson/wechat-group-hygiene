// Exercise the generated script with synthetic DOM/state only; no browser or packages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const page = fs.readFileSync(0, 'utf8');
const scripts = [...page.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(match => match[1]);
scripts.forEach(source => new vm.Script(source));
const source = scripts.find(script => script.includes('function selectSection('));
assert(source, 'Generated interaction script is required');
function fragment(start, end) {
  const offset = source.indexOf(start);
  const stop = source.indexOf(end, offset + start.length);
  assert(offset >= 0 && stop > offset, `Missing script boundaries: ${start}`);
  return source.slice(offset, stop);
}

class Element {
  constructor(tag = 'div', text = '') {
    this.tag = tag;
    this.textContent = text;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.classes = new Set();
    this.checked = false;
    this.hidden = false;
    this.classList = {
      add: (...values) => values.forEach(value => this.classes.add(value)),
      remove: (...values) => values.forEach(value => this.classes.delete(value)),
      toggle: (value, force) => {
        const add = force === undefined ? !this.classes.has(value) : force;
        if (add) this.classes.add(value); else this.classes.delete(value);
      },
    };
  }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get className() { return [...this.classes].join(' '); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  dispatchEvent(event) {
    event.target ||= this;
    this['on' + event.type]?.(event);
    (this.listeners[event.type] || []).forEach(callback => callback(event));
  }
  append(...nodes) { nodes.forEach(node => { node.parent = this; this.children.push(node); }); }
  prepend(node) { node.parent = this; this.children.unshift(node); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  remove() { this.parent.children = this.parent.children.filter(node => node !== this); }
  focus() { document.activeElement = this; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  matches(selector) { return selector.startsWith('.') ? this.classes.has(selector.slice(1)) : this.tag === selector; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  cloneNode(deep) {
    const clone = new Element(this.tag, this.textContent);
    clone.className = this.className;
    clone.dataset = { ...this.dataset };
    clone.checked = this.checked;
    if (deep) clone.append(...this.children.map(child => child.cloneNode(true)));
    return clone;
  }
}
class MockEvent {
  constructor(type, options = {}) { this.type = type; Object.assign(this, options); }
  preventDefault() { this.prevented = true; }
  stopPropagation() { this.stopped = true; }
}

const elements = new Map();
const document = {
  activeElement: null,
  listeners: {},
  getElementById: id => elements.get(id),
  createElement: tag => new Element(tag),
  createTextNode: text => new Element('#text', text),
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); },
};
function element(id, tag = 'div') { const node = new Element(tag); elements.set(id, node); return node; }
const review = element('review_queue');
const lowInvalid = element('confirmed_low_invalid');
const extra = element('special_keep');
const sections = [review, lowInvalid, extra];
const allCards = [];
function member(section, id, status) {
  const card = new Element('article');
  card.className = 'member'; card.dataset = { id, status, search: id };
  card.append(new Element('h3', id));
  const foot = new Element(); foot.className = 'card-foot';
  const label = new Element('label'); label.className = 'select-label';
  const pick = new Element('input'); pick.className = 'pick'; pick.dataset = { id, name: id, status };
  label.append(pick);
  const evidence = new Element('button'); evidence.className = 'evidence-button';
  foot.append(label, evidence); card.append(foot); section.append(card); allCards.push(card);
  return pick;
}
review.append(new Element('h2', 'review'));
lowInvalid.append(new Element('h2', 'low invalid'));
const a = member(review, 'a', 'confirmed_inactive');
const b = member(review, 'b', 'low_activity_needs_review');
const c = member(lowInvalid, 'c', 'confirmed_low_invalid');
const d = member(lowInvalid, 'd', 'confirmed_low_invalid');
const kept = member(extra, 'kept', 'special_keep');
allCards[1].classList.add('hidden');
const reviewButton = new Element('button'); reviewButton.dataset.section = 'review_queue';
const invalidButton = new Element('button'); invalidButton.dataset.section = 'confirmed_low_invalid';
document.querySelectorAll = selector => {
  if (selector === '.pick') return [a, b, c, d, kept];
  if (selector === '#dashboardView .member') return allCards;
  if (selector === '.section-select-all') return [reviewButton, invalidButton];
  if (selector === '#dashboardView .member-section') return sections;
  throw new Error('Unexpected selector: ' + selector);
};
element('goPurge', 'button');
element('purgeSelectAll', 'button');
['processedTotal', 'selectedTotal', 'actionTotal', 'protectedTotal', 'actionCount', 'protectedCount', 'purgeActionList', 'purgeProtectedList', 'purgeActionSection', 'purgeProtectedSection', 'purgeEmpty'].forEach(id => element(id));
const storage = new Map(); const writes = [];
const scope = page.match(/const key="(wechat-hygiene-review::[^"]+)"/)[1];
const processedKey = page.match(/const processedKey="([^"]+)"/)[1];
storage.set(scope, JSON.stringify({ a: true, b: false, kept: true, retired: true }));
storage.set(processedKey, JSON.stringify({ a: true, b: false, kept: true, retired: true }));
const context = vm.createContext({ document, Event: MockEvent, window: { getSelection: () => '' },
  localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => { storage.set(key, value); writes.push(key); } },
});
const run = code => vm.runInContext(code, context);

run(fragment('const key=', "document.querySelectorAll('#dashboardView .member').forEach(card=>"));
run(fragment('updateSelectionControls();\nfunction updateSectionSelectionControls()', 'function applyFilters()'));
assert.equal(reviewButton.textContent, '全选');
assert.equal(a.checked, true); assert.equal(b.checked, false);
reviewButton.dispatchEvent(new MockEvent('click'));
assert.equal(reviewButton.textContent, '取消全选');
assert.equal(b.checked, true, 'Filtered-out card is included in module-wide selection');
assert.equal(kept.checked, true); assert.equal(c.checked, false);
assert.equal(writes.length, 1, 'One write per selection batch');
reviewButton.dispatchEvent(new MockEvent('click'));
assert.equal(a.checked, false); assert.equal(b.checked, false);
assert.equal(JSON.parse(storage.get(scope)).retired, true);
assert.equal(JSON.parse(storage.get(scope)).b, false, 'Explicit deselection persists');
a.checked = true; a.dispatchEvent(new MockEvent('change'));
assert.equal(reviewButton.textContent, '全选');
b.checked = true; b.dispatchEvent(new MockEvent('change'));
assert.equal(reviewButton.textContent, '取消全选');
b.checked = false; b.dispatchEvent(new MockEvent('change'));
assert.equal(reviewButton.textContent, '全选');
invalidButton.dispatchEvent(new MockEvent('click'));
assert.equal(c.checked, true); assert.equal(d.checked, true);
invalidButton.dispatchEvent(new MockEvent('click'));
assert.equal(c.checked, false); assert.equal(d.checked, false); assert.equal(a.checked, true);

run(fragment('const processedKey=', 'function syncView()'));
b.checked = true;
run('renderPurgePage()');
const batch = elements.get('purgeSelectAll');
const total = elements.get('processedTotal');
const actionList = elements.get('purgeActionList');
const protectedList = elements.get('purgeProtectedList');
assert.equal(batch.textContent, '全选'); assert.equal(total.textContent, '1');
assert.equal(protectedList.children.length, 1);
assert(actionList.children.every(card => !card.classes.has('hidden')), 'All selected cards are visible on the review page regardless of the main filter');
assert.equal(protectedList.children[0].querySelector('.processed-label'), null);
let beforeWrites = writes.length;
batch.dispatchEvent(new MockEvent('click'));
assert.equal(batch.textContent, '取消全选'); assert.equal(total.textContent, '2');
assert.equal(writes.length, beforeWrites + 1);
assert(actionList.children.every(card => card.classes.has('processed')));
const box = actionList.children[1].querySelector('.processed-label').querySelector('input');
box.checked = false; box.dispatchEvent(new MockEvent('change'));
assert.equal(batch.textContent, '全选'); assert.equal(total.textContent, '1');
batch.dispatchEvent(new MockEvent('click'));
assert.equal(batch.textContent, '取消全选');
batch.dispatchEvent(new MockEvent('click'));
assert.equal(batch.textContent, '全选'); assert.equal(total.textContent, '0');
assert.equal(run('processed.kept'), true); assert.equal(run('processed.retired'), true);
batch.dispatchEvent(new MockEvent('click'));
actionList.children[0].querySelector('.remove-selected').dispatchEvent(new MockEvent('click'));
assert.equal(a.checked, false);
assert.equal(run('processed.a'), true, 'Removing from shortlist must retain previous processing mark');
a.checked = true; a.dispatchEvent(new MockEvent('change')); run('renderPurgePage()');
assert(actionList.children[0].classes.has('processed'), 'Reselection restores processing mark');
a.checked = false; b.checked = false; run('renderPurgePage()');
assert.equal(batch.disabled, true); beforeWrites = writes.length;
batch.dispatchEvent(new MockEvent('click')); assert.equal(writes.length, beforeWrites);

const search = element('search', 'input'); search.value = '';
const select = element('statusFilter', 'select'); select.value = 'all';
select.options = [...page.matchAll(/<option value='([^']+)'>([^<]+)<\/option>/g)].map(match => ({ value: match[1], textContent: match[2] }));
const control = element('statusFilterControl'); control.hidden = true;
const trigger = element('statusFilterTrigger', 'button');
const menu = element('statusFilterMenu'); menu.hidden = true;
const filterLabel = element('statusFilterLabel', 'span');
control.append(trigger, menu); element('resetFilters', 'button');
run(fragment('function applyFilters()', "const evidenceDialog=document.getElementById('evidenceDialog');"));
assert.equal(select.hidden, true); assert.equal(control.hidden, false);
assert.equal(filterLabel.textContent, '全部状态');
assert.equal(menu.children.length, select.options.length);
trigger.dispatchEvent(new MockEvent('click'));
assert.equal(trigger.attributes['aria-expanded'], 'true'); assert.equal(menu.hidden, false);
menu.children.find(option => option.dataset.value === 'candidates').dispatchEvent(new MockEvent('click'));
assert.equal(select.value, 'candidates'); assert.equal(filterLabel.textContent, '净化候选');
assert.equal(menu.hidden, true); assert.equal(document.activeElement, trigger);
assert(allCards[1].classes.has('hidden')); assert(allCards[4].classes.has('hidden'));
select.value = 'low_activity_needs_review'; select.dispatchEvent(new MockEvent('change'));
assert.equal(filterLabel.textContent, '人工复核');
search.value = 'b'; search.dispatchEvent(new MockEvent('input'));
assert.equal(allCards[1].classes.has('hidden'), false);
trigger.dispatchEvent(new MockEvent('keydown', { key: 'End' }));
assert.equal(document.activeElement, menu.children.at(-1));
menu.dispatchEvent(new MockEvent('keydown', { key: 'ArrowDown' }));
assert.equal(document.activeElement, menu.children[0]);
menu.dispatchEvent(new MockEvent('keydown', { key: 'Escape' }));
assert.equal(menu.hidden, true); assert.equal(document.activeElement, trigger);
trigger.dispatchEvent(new MockEvent('click'));
document.listeners.pointerdown.forEach(callback => callback({ target: search }));
assert.equal(menu.hidden, true);
trigger.dispatchEvent(new MockEvent('click'));
menu.dispatchEvent(new MockEvent('keydown', { key: 'Tab' })); assert.equal(menu.hidden, true);
elements.get('resetFilters').dispatchEvent(new MockEvent('click'));
assert.equal(select.value, 'all'); assert.equal(filterLabel.textContent, '全部状态'); assert.equal(search.value, '');
assert(allCards.every(card => !card.classes.has('hidden')));

// Invalid stored containers should not break either checkbox group.
for (const value of ['null', '[]', 'false', '"invalid"', '{']) {
  storage.set(scope, value); storage.set(processedKey, value);
  const isolated = vm.createContext({ document, localStorage: context.localStorage });
  vm.runInContext(fragment('const key=', 'const cardById='), isolated);
  assert.equal(vm.runInContext('typeof saved', isolated), 'object');
  vm.runInContext(fragment('const processedKey=', 'function saveProcessed()'), isolated);
  assert.equal(vm.runInContext('typeof processed', isolated), 'object');
}
console.log('PASS: generated scripts compile; selection/processing toggles, preserved local marks, protected isolation, dropdown filtering/reset/keyboard/outside close and invalid storage checks');
