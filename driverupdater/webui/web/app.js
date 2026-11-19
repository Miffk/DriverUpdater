/* DriverUpdater — логика интерфейса.
   Данные приходят из Python (bridge.py): вызовы pywebview.api.* и события window.__du.onEvent. */
(function () {
  'use strict';

  const GROUPS = [
    { key: 'required', title: 'Необходимо', hint: 'без них устройства не работают или работают плохо', stat: 'установить или исправить' },
    { key: 'recommended', title: 'Рекомендуется', hint: 'устройство работает, но обновление заметно полезно', stat: 'полезные обновления' },
    { key: 'optional', title: 'Необязательно', hint: 'по желанию — польза небольшая', stat: 'можно пропустить' },
    { key: 'not_needed', title: 'В порядке', hint: 'ничего делать не нужно', stat: 'устройств без проблем' },
  ];
  const GROUP_BY_KEY = Object.fromEntries(GROUPS.map((g) => [g.key, g]));

  const S = {
    info: null, system: null, deviceCount: 0, items: [], byId: new Map(),
    searched: false, busy: true, selected: new Set(), open: new Set(),
    filter: 'all', query: '', installing: false, install: null, collapsed: new Set(), update: null,
  };

  // ───────── утилиты ─────────
  const $ = (id) => document.getElementById(id);
  const api = () => (window.pywebview && window.pywebview.api) || null;

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v; // только для собственных SVG-иконок
      else if (k === 'style') el.style.cssText = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const icon = (name, cls) => {
    const t = document.createElement('template');
    t.innerHTML = Icons.svg(name, cls);
    return t.content.firstChild;
  };

  function plural(n, one, few, many) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }
  function fmtSize(n) {
    if (!n) return '';
    const u = ['Б', 'КБ', 'МБ', 'ГБ'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n.toFixed(0) : n.toFixed(n < 10 ? 1 : 0)) + ' ' + u[i];
  }
  const fmtDate = (d) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d.split('-').reverse().join('.') : d || '');
  const verDate = (v, d) => [v, d ? 'от ' + fmtDate(d) : ''].filter(Boolean).join(' ');

  function toast(text, kind) {
    for (const el of $('toasts').children) {
      if (el.dataset.text === text && !el.classList.contains('out')) return; // такое сообщение уже на экране
    }
    const colors = { error: 'var(--red)', ok: 'var(--green)', warn: 'var(--amber)' };
    const el = h('div', { class: 'toast', style: '--c:' + (colors[kind] || 'var(--accent)') },
      icon(kind === 'error' ? 'alert' : kind === 'ok' ? 'check' : 'info'), h('div', {}, text));
    el.dataset.text = text;
    $('toasts').append(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 300); }, 6000);
  }

  function log(line) {
    const pre = $('log');
    pre.textContent += line + '\n';
    if (pre.textContent.length > 200000) pre.textContent = pre.textContent.slice(-150000);
    pre.scrollTop = pre.scrollHeight;
  }

  function setStatus(text, mode) {
    $('statusText').textContent = text;
    $('status').className = 'status' + (mode ? ' ' + mode : '');
  }

  // ───────── шапка и кольцо ─────────
  function counts() {
    const c = { required: 0, recommended: 0, optional: 0, not_needed: 0 };
    for (const it of S.items) {
      if (it.necessity !== 'not_needed' && it.action === 'none') c.not_needed++;
      else c[it.necessity]++;
    }
    return c;
  }

  function renderHero() {
    const ring = $('ring');
    if (!S.searched) {
      ring.dataset.state = 'loading';
      $('ringNumber').textContent = S.deviceCount || '—';
      $('ringCaption').textContent = S.deviceCount ? plural(S.deviceCount, 'устройство', 'устройства', 'устройств') : 'проверка';
      $('ringValue').style.strokeDashoffset = '';
      $('headline').textContent = S.system
        ? 'Ищу подходящие драйверы для ' + S.deviceCount + ' ' + plural(S.deviceCount, 'устройства', 'устройств', 'устройств') + '…'
        : 'Определяю оборудование…';
      return;
    }
    const c = counts();
    const total = c.required + c.recommended + c.optional + c.not_needed || 1;
    const issues = c.required + c.recommended;
    const pct = Math.round(100 * (total - issues) / total);
    ring.dataset.state = c.required ? 'bad' : c.recommended ? 'warn' : 'good';
    $('ringNumber').textContent = pct + '%';
    $('ringCaption').textContent = 'в порядке';
    requestAnimationFrame(() => { $('ringValue').style.strokeDashoffset = String(326.7 * (1 - pct / 100)); });

    let text;
    const repairs = S.items.filter((it) => it.action === 'repair').length;
    const installs = c.required - repairs;
    if (c.required) {
      const parts = [];
      if (installs) parts.push('нужно установить ' + installs + ' ' + plural(installs, 'драйвер', 'драйвера', 'драйверов'));
      if (repairs) parts.push(repairs + ' ' + plural(repairs, 'устройство работает', 'устройства работают', 'устройств работают') + ' с ошибкой');
      text = parts.join(', ');
      text = text.charAt(0).toUpperCase() + text.slice(1);
    }
    else if (c.recommended) text = 'Всё работает, но есть ' + c.recommended + ' ' + plural(c.recommended, 'полезное обновление', 'полезных обновления', 'полезных обновлений');
    else if (c.optional) text = 'Всё в порядке. Есть ' + c.optional + ' ' + plural(c.optional, 'необязательное обновление', 'необязательных обновления', 'необязательных обновлений');
    else text = 'Все драйверы в порядке — устанавливать ничего не нужно';
    $('headline').textContent = text;
  }

  // ───────── карточки компьютера ─────────
  function renderSystem() {
    const box = $('system');
    box.replaceChildren();
    const s = S.system;
    if (!s) {
      for (let i = 0; i < 6; i++) box.append(h('div', { class: 'skeleton short' }));
      return;
    }
    const d = s.display || {};
    const specs = [
      ['pc', 'Компьютер', d.computer],
      ['cpu', 'Процессор', d.cpu],
      ['gpu', Number(d.gpuCount) > 1 ? 'Видеокарты' : 'Видеокарта', d.gpus],
      ['ram', 'Оперативная память', d.ram],
      ['board', 'Материнская плата', d.board],
      ['windows', 'Windows', d.os],
    ];
    specs.forEach(([ic, k, v], i) => {
      box.append(h('div', { class: 'spec', style: 'animation-delay:' + i * 40 + 'ms', title: v || '' },
        h('div', { class: 'tile' }, icon(ic)),
        h('div', {}, h('div', { class: 'k' }, k), h('div', { class: 'v' }, v || '—'))));
    });
  }

  // ───────── сводка ─────────
  function renderSummary() {
    const box = $('summary');
    box.replaceChildren();
    const c = counts();
    GROUPS.forEach((g, i) => {
      const n = S.searched ? c[g.key] : '—';
      box.append(h('button', {
        class: 'stat c-' + g.key + (S.filter === g.key ? ' active' : ''),
        style: 'animation-delay:' + i * 50 + 'ms',
        disabled: !S.searched,
        title: S.filter === g.key ? 'Показать все' : 'Показать только «' + g.title + '»',
        onclick: () => { S.filter = S.filter === g.key ? 'all' : g.key; renderSummary(); renderList(); },
      }, h('div', { class: 'n' }, n), h('div', { class: 't' }, g.title), h('div', { class: 'd' }, g.stat)));
    });
  }

  // ───────── список ─────────
  function visibleItems() {
    const q = S.query.trim().toLowerCase();
    return S.items.filter((it) => {
      const grp = groupOf(it);
      if (S.filter !== 'all' && grp !== S.filter) return false;
      const hay = [it.name, it.clsTitle, it.hwid, it.vendor, it.offer && it.offer.title].join(' ').toLowerCase();
      if (q && !hay.includes(q)) return false;
      return true;
    });
  }
  const groupOf = (it) => (it.action === 'none' ? 'not_needed' : it.necessity);

  function renderList() {
    const list = $('list');
    list.replaceChildren();
    if (!S.searched) {
      list.append(h('div', { class: 'group' },
        h('div', { class: 'group-head' }, h('h3', {}, 'Поиск драйверов'),
          h('span', { class: 'hint' }, 'Windows Update и каталог Microsoft — это может занять пару минут'))),
        h('div', { class: 'cards' }, [0, 1, 2, 3].map((i) => h('div', { class: 'skeleton', style: 'animation-delay:' + i * 120 + 'ms' }))));
      return;
    }
    const items = visibleItems();
    const c = counts();
    if (!items.length) {
      const allGood = !c.required && !c.recommended && !c.optional && !S.query;
      list.append(h('div', { class: 'empty' },
        h('div', { class: 'big' }, icon(allGood ? 'check' : 'search')),
        h('h3', {}, allGood ? 'Все драйверы в порядке' : 'Ничего не найдено'),
        h('div', {}, allGood ? 'Для всех устройств установлены подходящие драйверы. Можно проверить снова позже.'
          : 'Попробуйте написать название по-другому.')));
      return;
    }
    let delay = 0;
    for (const g of GROUPS) {
      const gi = items.filter((it) => groupOf(it) === g.key);
      if (!gi.length) continue;
      const selectable = gi.filter((it) => it.installable && !it.firmware);
      const allOn = selectable.length && selectable.every((it) => S.selected.has(it.id));
      const folded = S.collapsed.has(g.key) && !S.query;
      list.append(h('section', { class: 'group c-' + g.key + (folded ? ' folded' : '') },
        h('div', { class: 'group-head' },
          h('button', {
            class: 'fold', title: folded ? 'Показать' : 'Свернуть', 'aria-expanded': String(!folded),
            onclick: () => { if (S.collapsed.has(g.key)) S.collapsed.delete(g.key); else S.collapsed.add(g.key); renderList(); },
          }, icon('chevron'), h('span', { class: 'dot' }), h('h3', {}, g.title), h('span', { class: 'count' }, gi.length)),
          h('span', { class: 'hint' }, g.hint),
          selectable.length > 1 ? h('button', {
            class: 'link',
            onclick: () => { selectable.forEach((it) => (allOn ? S.selected.delete(it.id) : S.selected.add(it.id))); renderList(); updateSelection(); },
          }, allOn ? 'Снять все' : 'Выбрать все') : null),
        folded ? null : h('div', { class: 'cards' }, gi.map((it) => deviceCard(it, g.key, Math.min(delay++ * 25, 400))))));
    }
  }

  function deviceCard(it, grp, delay) {
    const isOpen = S.open.has(it.id);
    const sel = S.selected.has(it.id);
    const cur = it.current;

    const sub = h('div', { class: 'sub' },
      it.vendor ? h('span', { class: 'vendor' }, it.vendor) : null,
      it.vendor ? h('span', {}, '·') : null,
      h('span', {}, it.clsTitle),
      h('span', {}, '·'),
      h('span', {}, cur ? verDate(cur.version, '') : 'нет драйвера'));
    if (it.offer) sub.append(h('span', { class: 'arrow' }, '→'), h('span', { class: 'new' }, it.offer.version || fmtDate(it.offer.date) || 'новая версия'));
    else if (it.action !== 'none') sub.append(h('span', { class: 'arrow' }, '→'), h('span', {}, it.action === 'repair' ? 'нужен перезапуск' : 'у Microsoft нет — см. сайт производителя'));

    const meta = h('div', { class: 'meta' });
    if (it.problem && ![22, 24, 45].includes(it.problem)) meta.append(h('span', { class: 'chip warn' }, icon('alert'), 'ошибка, код ' + it.problem));
    if (it.firmware && it.offer) meta.append(h('span', { class: 'chip warn' }, icon('firmware'), 'прошивка'));
    if (it.offer) {
      meta.append(h('span', { class: 'chip' }, it.offer.source));
      if (it.offer.size) meta.append(h('span', { class: 'chip' }, fmtSize(it.offer.size)));
      if (it.offer.reboot) meta.append(h('span', { class: 'chip note' }, icon('power'), 'перезагрузка'));
    }

    let ctl;
    if (it.installable) {
      const input = h('input', { type: 'checkbox', 'aria-label': 'Установить ' + it.name });
      input.checked = sel;
      input.disabled = S.busy;
      input.addEventListener('change', () => toggleItem(it, input));
      ctl = h('label', { class: 'switch-row', onclick: (e) => e.stopPropagation(), title: sel ? 'Будет установлен' : 'Не устанавливать' },
        input, h('span', { class: 'switch' }));
    } else if (it.repairable && it.action === 'repair') {
      ctl = h('button', { class: 'btn btn-sm btn-primary', onclick: (e) => { e.stopPropagation(); doRepair(it); } }, icon('refresh'), 'Исправить');
    } else if (it.action !== 'none' && it.tool) {
      ctl = h('button', { class: 'btn btn-sm', onclick: (e) => { e.stopPropagation(); askTool(it); } }, icon('download'), 'Программа ' + it.vendor);
    } else if (it.action !== 'none' && (it.site || it.searchUrl)) {
      ctl = h('button', { class: 'btn btn-sm', onclick: (e) => { e.stopPropagation(); openUrl(it.site ? it.site.url : it.searchUrl); } },
        icon('external'), it.site ? 'Сайт ' + it.site.name : 'Найти');
    }

    const facts = h('dl', { class: 'facts' });
    const fact = (k, v) => v && facts.append(h('dt', {}, k), h('dd', {}, v));
    fact('Тип устройства', it.clsTitle);
    fact('Производитель', it.vendor);
    fact('Модель', it.model && it.model !== it.name ? it.model : '');
    fact('Установлен драйвер', cur ? [verDate(cur.version, cur.date), cur.provider ? '(от ' + cur.provider + ')' : ''].join(' ') : 'нет');
    if (it.offer) {
      fact('Будет установлено', it.offer.title);
      fact('Источник', it.offer.source + (it.offer.size ? ' · ' + fmtSize(it.offer.size) : ''));
    }
    if (it.winName && it.winName !== it.name) fact('Название в Windows', it.winName);
    fact('Код устройства', it.hwid);

    const actions = h('div', { class: 'actions' });
    if (it.repairable) {
      actions.append(h('button', { class: 'btn btn-sm' + (it.action === 'repair' ? ' btn-primary' : ''), onclick: () => doRepair(it) },
        icon('refresh'), 'Перезапустить устройство'));
    }
    if (it.tool) {
      actions.append(h('button', { class: 'btn btn-sm', onclick: () => askTool(it) }, icon('download'),
        'Проверить программой ' + it.vendor));
    }
    if (it.site && (it.action !== 'none' || it.cls === 'Display')) {
      actions.append(h('button', { class: 'btn btn-sm', onclick: () => openUrl(it.site.url) }, icon('external'),
        'Сайт ' + it.site.name + ' с драйверами'));
    }
    if (it.searchUrl && it.action !== 'none' && !it.offer) {
      actions.append(h('button', { class: 'btn btn-sm btn-ghost', onclick: () => openUrl(it.searchUrl) }, icon('search'),
        it.site ? 'Найти этот драйвер на сайте ' + it.site.name : 'Найти драйвер в интернете'));
    }

    const card = h('article', {
      class: 'dev c-' + grp + (isOpen ? ' open' : '') + (sel ? ' selected' : ''),
      style: 'animation-delay:' + delay + 'ms',
    },
    h('div', {
      class: 'dev-row', tabindex: '0', role: 'button', 'aria-expanded': String(isOpen),
      onclick: () => toggleOpen(it.id, card),
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleOpen(it.id, card); } },
    },
    h('div', { class: 'tile' }, icon(Icons.forClass(it.cls))),
    h('div', { style: 'min-width:0' }, h('div', { class: 'name', title: it.name }, it.name), sub),
    meta,
    h('div', { class: 'ctl' }, ctl || ''),
    icon('chevron', 'chev')),
    h('div', { class: 'dev-more' }, h('div', {},
      h('div', { class: 'why' },
        h('div', { class: 'label' }, icon('info'), 'Почему — ' + (GROUP_BY_KEY[grp] || {}).title),
        h('p', {}, it.reason), facts, actions.childNodes.length ? actions : null))));
    return card;
  }

  function toggleOpen(id, card) {
    if (S.open.has(id)) S.open.delete(id); else S.open.add(id);
    card.classList.toggle('open', S.open.has(id));
    card.querySelector('.dev-row').setAttribute('aria-expanded', String(S.open.has(id)));
  }

  function toggleItem(it, input) {
    if (input.checked && it.firmware) {
      input.checked = false;
      modal({
        tone: 'required', iconName: 'firmware', title: 'Обновить прошивку?',
        body: [h('p', {}, 'Это обновление прошивки (BIOS/UEFI или контроллера) для «' + it.name + '».'),
          h('p', {}, 'Если во время прошивки пропадёт питание, компьютер может перестать включаться. ' +
            'Ставьте её, только если знаете, зачем она нужна. Ноутбук держите на зарядке.')],
        actions: [{ text: 'Отмена' }, {
          text: 'Всё равно установить', kind: 'danger',
          run: () => { S.selected.add(it.id); renderList(); updateSelection(); },
        }],
      });
      return;
    }
    if (input.checked) S.selected.add(it.id); else S.selected.delete(it.id);
    input.closest('.dev').classList.toggle('selected', input.checked);
    updateSelection();
  }

  function selectedItems() {
    return S.items.filter((it) => S.selected.has(it.id) && it.installable);
  }

  function updateSelection() {
    const sel = selectedItems();
    const uniq = new Map(sel.map((it) => [it.offer.key, it]));
    const size = [...uniq.values()].reduce((s, it) => s + (it.offer.size || 0), 0);
    const n = uniq.size;
    $('btnInstallText').textContent = n ? 'Установить (' + n + ')' : 'Установить';
    $('btnInstall').disabled = S.busy || !n;
    $('btnRefresh').disabled = S.busy;
    $('dock').hidden = S.busy || !n || !S.searched;
    $('dockCount').textContent = n;
    $('dockText').textContent = plural(n, 'драйвер выбран', 'драйвера выбрано', 'драйверов выбрано') + (size ? ' · примерно ' + fmtSize(size) : '');
  }

  function renderAll() { renderHero(); renderSystem(); renderSummary(); renderList(); updateSelection(); }

  // ───────── диалоги ─────────
  function modal({ tone, iconName, title, body, actions }) {
    const ov = $('modal');
    const mi = $('modalIcon');
    mi.className = 'modal-icon' + (tone ? ' c-' + tone : '');
    mi.replaceChildren(icon(iconName || 'info'));
    $('modalTitle').textContent = title;
    $('modalBody').replaceChildren(...[].concat(body || []));
    const box = $('modalActions');
    box.replaceChildren();
    (actions || [{ text: 'Понятно', kind: 'primary' }]).forEach((a) => {
      const b = h('button', { class: 'btn ' + (a.kind === 'primary' ? 'btn-primary' : a.kind === 'danger' ? 'btn-danger' : '') },
        a.icon ? icon(a.icon) : null, a.text);
      b.addEventListener('click', () => { if (!a.keep) closeModal(); if (a.run) a.run(); });
      box.append(b);
    });
    ov.hidden = false;
    const last = box.lastElementChild;
    if (last) last.focus();
  }
  const closeModal = () => { $('modal').hidden = true; };

  function openUrl(url) { const a = api(); if (a) a.open_url(url); }

  // ───────── действия ─────────
  function start() {
    const a = api();
    if (!a) return;
    S.searched = false;
    S.busy = true;
    S.filter = 'all';
    renderAll();
    a.start(false).then((ok) => { if (!ok) toast('Подождите — предыдущая операция ещё идёт.', 'warn'); });
  }

  function askInstall() {
    const sel = selectedItems();
    const uniq = [...new Map(sel.map((it) => [it.offer.key, it])).values()];
    if (!uniq.length) return;
    const size = uniq.reduce((s, it) => s + (it.offer.size || 0), 0);
    const restore = $('optRestore').checked;
    modal({
      tone: 'optional', iconName: 'download',
      title: 'Установить ' + uniq.length + ' ' + plural(uniq.length, 'драйвер', 'драйвера', 'драйверов') + '?',
      body: [
        h('ul', {}, uniq.map((it) => h('li', {}, icon(Icons.forClass(it.cls)),
          h('div', {}, it.name, h('small', {}, it.offer.title)), h('span', { class: 'sz' }, fmtSize(it.offer.size))))),
        h('p', {}, (size ? 'Будет скачано примерно ' + fmtSize(size) + '. ' : '') +
          (restore ? 'Перед установкой создадим точку восстановления Windows. ' : '') +
          'После установки все скачанные файлы будут удалены.'),
      ],
      actions: [{ text: 'Отмена' }, { text: 'Установить', kind: 'primary', icon: 'download', run: () => doInstall(sel, restore) }],
    });
  }

  function doInstall(sel, restore) {
    api().install(sel.map((it) => it.id), restore).then((res) => {
      if (res && res.ok) return;
      const err = res && res.error;
      if (err === 'admin') {
        needAdmin();
      } else {
        toast(err || 'Не удалось начать установку', 'error');
      }
    });
  }

  function needAdmin() {
    modal({
      tone: 'recommended', iconName: 'shield', title: 'Нужны права администратора',
      body: h('p', {}, 'Windows разрешает менять драйверы и устройства только с правами администратора. Перезапустить программу с ними?'),
      actions: [{ text: 'Отмена' }, { text: 'Перезапустить', kind: 'primary', run: () => api().relaunch_as_admin() }],
    });
  }

  function doRepair(it) {
    modal({
      tone: 'recommended', iconName: 'refresh', title: 'Перезапустить устройство?',
      body: [h('p', {}, '«' + it.name + '» будет на пару секунд отключено и включено снова — как если бы вы вынули его и вставили обратно.'),
        h('p', {}, 'Если это клавиатура или мышь, они могут ненадолго перестать отвечать.')],
      actions: [{ text: 'Отмена' }, {
        text: 'Перезапустить', kind: 'primary', icon: 'refresh',
        run: () => api().repair(it.id).then((res) => {
          if (res && res.ok) { S.busy = true; updateSelection(); setStatus('Перезапускаю устройство…'); return; }
          if (res && res.error === 'admin') needAdmin(); else toast((res && res.error) || 'Не получилось', 'error');
        }),
      }],
    });
  }

  function askTool(it) {
    modal({
      tone: 'optional', iconName: 'download', title: it.toolTitle,
      body: [h('p', {}, 'У ' + it.vendor + ' есть своя официальная бесплатная программа, которая сама находит и ставит самые свежие драйверы для их устройств.'),
        h('p', {}, 'Мы скачаем её с официального сайта ' + it.vendor + ', проверим подпись и запустим. Дальше следуйте подсказкам программы. Когда закроете её, установочный файл будет удалён.')],
      actions: [{ text: 'Отмена' }, {
        text: 'Скачать и запустить', kind: 'primary', icon: 'download',
        run: () => api().run_tool(it.tool).then((res) => {
          if (res && res.ok) { S.busy = true; updateSelection(); return; }
          toast((res && res.error) || 'Не получилось', 'error');
        }),
      }],
    });
  }

  async function checkUpdate() {
    const a = api();
    if (!a || !a.check_update) return;
    const u = await a.check_update();
    if (!u || !u.available) return;
    S.update = u;
    $('updateText').textContent = 'Вышла новая версия программы — ' + u.version + ' (у вас ' + u.current + ')';
    $('updateBar').hidden = false;
  }

  function showNotes() {
    const u = S.update;
    modal({
      tone: 'optional', iconName: 'sparkle', title: 'Что нового в версии ' + u.version,
      body: h('div', { class: 'notes' }, ...(u.notes || 'Описание изменений есть на странице релиза.').split(/\r?\n/)
        .filter((l) => l.trim()).map((l) => h('p', {}, l.replace(/^[-*#\s]+/, '')))),
      actions: [{ text: 'Закрыть' }, { text: 'Обновить', kind: 'primary', icon: 'download', run: applyUpdate }],
    });
  }

  function setUpdateBusy(busy, text) {
    $('updateApply').disabled = busy;
    $('updateNotes').disabled = busy;
    if (text) $('updateText').textContent = text;
  }

  function applyUpdate() {
    if ($('updateApply').disabled) return;
    setUpdateBusy(true, 'Скачиваю новую версию…');
    api().apply_update().then((res) => {
      if (res && res.manual) { setUpdateBusy(false); toast('Открыл страницу загрузки новой версии в браузере.', 'ok'); return; }
      if (res && res.ok) return; // дальше — события update_progress / update_ready / update_failed
      setUpdateBusy(false, 'Вышла новая версия программы — ' + S.update.version + ' (у вас ' + S.update.current + ')');
      toast((res && res.error) || 'Не удалось начать обновление', 'error');
    }).catch((e) => {
      setUpdateBusy(false);
      toast('Не удалось начать обновление: ' + e, 'error');
    });
  }

  // ───────── экран установки ─────────
  // Этапы установки одного драйвера: название и доля общего пути (для общего процента).
  const STAGES = {
    waiting: { label: 'В очереди', from: 0, to: 0 },
    download: { label: 'Скачивание', from: 0, to: 0.6 },
    verify: { label: 'Проверка подписи', from: 0.6, to: 0.65 },
    extract: { label: 'Распаковка', from: 0.65, to: 0.7 },
    install: { label: 'Установка', from: 0.7, to: 0.95 },
    check: { label: 'Проверка', from: 0.95, to: 0.99 },
  };

  function fmtElapsed(ms) {
    const s = Math.floor(ms / 1000);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  function showInstaller(keys) {
    const byKey = new Map();
    S.items.forEach((it) => { if (it.offer && !byKey.has(it.offer.key)) byKey.set(it.offer.key, it); });
    S.install = { keys, states: {}, frac: {}, current: null, stageAt: Date.now(), timer: null };
    $('installTitle').textContent = 'Установка драйверов';
    $('installStep').textContent = 'Подготовка…';
    $('installPct').textContent = '0%';
    $('installSub').textContent = '0 из ' + keys.length + ' ' + plural(keys.length, 'драйвера', 'драйверов', 'драйверов');
    $('installSpinner').classList.remove('done');
    $('installSpinner').replaceChildren();
    $('installBar').style.width = '2%';
    $('installList').replaceChildren(...keys.map((k) => {
      const it = byKey.get(k);
      return h('li', { 'data-key': k, 'data-state': 'waiting' },
        h('span', { class: 'st' }, icon('download')),
        h('div', { class: 'body' },
          h('div', { class: 'row1' }, h('span', { class: 'nm' }, it ? it.name : k), h('span', { class: 'stage' }, 'В очереди')),
          h('div', { class: 'msg' }, it ? it.offer.title : ''),
          h('div', { class: 'mini' }, h('span', {}))));
    }));
    $('installFoot').replaceChildren(h('span', { class: 'warn' }, icon('alert'), 'Не выключайте компьютер до окончания установки'));
    $('installer').hidden = false;
    $('installCard').classList.add('running'); // блик на полосе — только пока идёт установка
    S.install.timer = setInterval(tickInstall, 1000);
  }

  // Раз в секунду: показываем, сколько длится текущий этап (установка NVIDIA идёт минутами).
  function tickInstall() {
    const I = S.install;
    if (!I || !I.current) return;
    const li = $('installList').querySelector('li[data-key="' + CSS.escape(I.current) + '"]');
    if (!li || li.dataset.state !== 'running') return;
    const stage = li.dataset.stage;
    if (stage === 'download' && li.dataset.pct) return; // у скачивания есть свой процент
    const label = (STAGES[stage] || {}).label || 'Работаю';
    li.querySelector('.stage').textContent = label + ' · ' + fmtElapsed(Date.now() - I.stageAt);
  }

  function updateOverall() {
    const I = S.install;
    const total = I.keys.length || 1;
    const sum = I.keys.reduce((acc, k) => acc + (I.states[k] ? 1 : (I.frac[k] || 0)), 0);
    const pct = Math.min(99, Math.round(100 * sum / total));
    $('installPct').textContent = pct + '%';
    $('installBar').style.width = Math.max(2, pct) + '%';
    const done = Object.keys(I.states).length;
    $('installSub').textContent = 'Готово ' + done + ' из ' + total + ' ' + plural(total, 'драйвера', 'драйверов', 'драйверов');
  }

  function onProgress(d) {
    const I = S.install;
    if (!I) return;
    if (d.state === 'cleanup') {
      $('installStep').textContent = 'Удаляю скачанные установочные файлы…';
      return;
    }
    const li = $('installList').querySelector('li[data-key="' + CSS.escape(d.key) + '"]');
    if (!li) return;
    const name = li.querySelector('.nm').textContent;
    const st = li.querySelector('.st');
    const bar = li.querySelector('.mini > span');
    li.dataset.state = d.state;

    if (d.state === 'ok' || d.state === 'error') {
      I.states[d.key] = d.state;
      li.querySelector('.stage').textContent = d.state === 'ok' ? 'Готово' : 'Ошибка';
      li.querySelector('.msg').textContent = d.message;
      bar.style.width = '100%';
      st.replaceChildren(icon(d.state === 'ok' ? 'check' : 'x'));
      updateOverall();
      return;
    }
    if (d.state === 'waiting') return;

    // running
    const stage = d.stage || 'install';
    if (li.dataset.stage !== stage || I.current !== d.key) I.stageAt = Date.now();
    I.current = d.key;
    li.dataset.stage = stage;
    st.replaceChildren();
    const info = STAGES[stage] || STAGES.install;
    const pct = typeof d.percent === 'number' ? Math.max(0, Math.min(100, d.percent)) : null;
    if (pct !== null) li.dataset.pct = String(pct); else delete li.dataset.pct;
    li.classList.toggle('indeterminate', pct === null);
    bar.style.width = pct !== null ? pct + '%' : '';

    // текст этапа: «Скачивание · 45%» или «Установка · 0:12»
    let label = info.label;
    if (pct !== null) label += ' · ' + Math.round(pct) + '%';
    else label += ' · ' + fmtElapsed(Date.now() - I.stageAt);
    li.querySelector('.stage').textContent = label;
    let msg = d.message;
    if (stage === 'download' && d.total) {
      // скорость и оставшееся время по последним замерам
      const now = Date.now();
      const sp = I.speed && I.speed.key === d.key ? I.speed : (I.speed = { key: d.key, t: now, done: d.done || 0, bps: 0 });
      const dt = (now - sp.t) / 1000;
      if (dt >= 0.5) {
        const inst = ((d.done || 0) - sp.done) / dt;
        sp.bps = sp.bps ? sp.bps * 0.7 + inst * 0.3 : inst;
        sp.t = now; sp.done = d.done || 0;
      }
      msg = fmtSize(d.done || 0) + ' из ' + fmtSize(d.total);
      if (sp.bps > 0) {
        const left = Math.max(0, (d.total - (d.done || 0)) / sp.bps);
        msg += ' · ' + fmtSize(sp.bps) + '/с · осталось ~' + (left >= 60 ? Math.ceil(left / 60) + ' мин' : Math.ceil(left) + ' с');
      }
    }
    li.querySelector('.msg').textContent = msg;
    $('installStep').textContent = name + ' — ' + info.label.toLowerCase() + (pct !== null ? ' ' + Math.round(pct) + '%' : '');

    I.frac[d.key] = info.from + (info.to - info.from) * ((pct ?? 0) / 100);
    updateOverall();
  }

  function stopInstallAnimations() {
    if (S.install && S.install.timer) clearInterval(S.install.timer);
    $('installCard').classList.remove('running');
  }

  function onInstallDone(d) {
    stopInstallAnimations();
    $('installPct').textContent = '100%';
    $('installSub').textContent = '';
    $('installSpinner').classList.add('done');
    $('installSpinner').replaceChildren(icon(d.okCount ? 'check' : 'x'));
    $('installBar').style.width = '100%';
    $('installTitle').textContent = d.okCount === d.total ? 'Готово!' : 'Установка завершена';
    $('installStep').textContent = 'Успешно: ' + d.okCount + ' из ' + d.total +
      (d.cleanedBytes ? ' · удалено установочных файлов: ' + fmtSize(d.cleanedBytes) : ' · установочные файлы удалены');
    const foot = $('installFoot');
    const finish = () => { $('installer').hidden = true; S.selected.clear(); start(); };
    if (d.reboot) {
      foot.replaceChildren(
        h('span', { class: 'warn' }, icon('power'), 'Чтобы драйверы заработали, нужна перезагрузка'),
        h('div', { style: 'display:flex;gap:8px' },
          h('button', { class: 'btn', onclick: finish }, 'Позже'),
          h('button', { class: 'btn btn-primary', onclick: () => { api().reboot(); toast('Компьютер перезагрузится через 10 секунд', 'warn'); } },
            icon('power'), 'Перезагрузить')));
    } else {
      foot.replaceChildren(h('span', {}, ''), h('button', { class: 'btn btn-primary', onclick: finish }, icon('check'), 'Готово'));
    }
    S.install = null;
  }

  // ───────── события из Python ─────────
  const handlers = {
    phase: (d) => setStatus(d.text),
    system: (d) => { S.system = d.system; S.deviceCount = d.count; renderHero(); renderSystem(); },
    items: (d) => {
      S.items = d.items;
      S.byId = new Map(d.items.map((it) => [it.id, it]));
      S.selected = new Set(d.items.filter((it) => it.selected).map((it) => it.id));
      S.open.clear();
      S.searched = true;
    },
    log: (d) => log(d.text),
    error: (d) => {
      setStatus('Ошибка: ' + d.message, 'error');
      toast(d.message, 'error');
      if (S.install || !$('installer').hidden) {
        stopInstallAnimations();
        $('installStep').textContent = 'Ошибка: ' + d.message;
        $('installFoot').replaceChildren(h('span', {}, ''), h('button', { class: 'btn', onclick: () => { $('installer').hidden = true; start(); } }, 'Закрыть'));
        S.install = null;
      }
      if (!S.searched && S.system) { S.searched = true; }
    },
    idle: (d) => {
      S.busy = false;
      if (d.task === 'start' && !$('status').classList.contains('error')) {
        setStatus('Проверка завершена · ' + new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }), 'idle');
      }
      renderAll();
    },
    install_started: (d) => { S.busy = true; updateSelection(); showInstaller(d.keys); },
    progress: onProgress,
    install_done: onInstallDone,
    install_aborted: (d) => {
      stopInstallAnimations();
      $('installer').hidden = true;
      S.install = null;
      modal({ tone: 'required', iconName: 'alert', title: 'Установка не начата', body: h('p', {}, d.message) });
    },
    repair_done: (d) => {
      modal({
        tone: d.ok ? 'not_needed' : 'recommended', iconName: d.ok ? 'check' : 'alert',
        title: d.ok ? 'Готово' : 'Не помогло', body: h('p', {}, d.message),
        actions: [{ text: 'Проверить снова', kind: 'primary', run: () => setTimeout(start, 50) }],
      });
    },
    tool_done: (d) => {
      toast(d.message, d.ok ? 'ok' : 'error');
      if (d.ok) setTimeout(start, 500);
    },
    update_progress: (d) => {
      const size = d.total ? fmtSize(d.done) + ' из ' + fmtSize(d.total) : fmtSize(d.done);
      setUpdateBusy(true, 'Скачиваю новую версию' + (d.percent != null ? ' · ' + d.percent + '%' : '') + ' · ' + size);
    },
    update_ready: (d) => {
      setUpdateBusy(true, 'Версия ' + d.version + ' готова. Перезапускаю программу…');
    },
    update_failed: (d) => {
      setUpdateBusy(false, 'Вышла новая версия программы — ' + S.update.version + ' (у вас ' + S.update.current + ')');
      modal({
        tone: 'required', iconName: 'alert', title: 'Не удалось обновить программу',
        body: [h('p', {}, 'Причина: ' + d.message), h('p', {}, 'Можно скачать новую версию вручную со страницы релиза.')],
        actions: [{ text: 'Закрыть' }, { text: 'Открыть страницу', kind: 'primary', icon: 'external', run: () => openUrl(d.page) }],
      });
    },
    close_blocked: () => toast('Идёт установка драйверов — дождитесь её окончания.', 'warn'),
  };

  window.__du = {
    onEvent(ev) {
      const fn = handlers[ev.type];
      if (fn) {
        try { fn(ev.data || {}); } catch (e) { console.error(e); }
      }
    },
  };

  // ───────── запуск ─────────
  function bindUi() {
    Icons.hydrate();
    // Окно свёрнуто или закрыто другими окнами — ставим все анимации на паузу.
    const syncPaused = () => document.documentElement.classList.toggle('paused', document.hidden);
    document.addEventListener('visibilitychange', syncPaused);
    syncPaused();
    $('btnRefresh').addEventListener('click', start);
    $('btnInstall').addEventListener('click', askInstall);
    $('dockInstall').addEventListener('click', askInstall);
    $('dockClear').addEventListener('click', () => { S.selected.clear(); renderList(); updateSelection(); });
    $('updateApply').addEventListener('click', applyUpdate);
    $('updateNotes').addEventListener('click', showNotes);
    $('btnLog').addEventListener('click', () => $('drawer').classList.add('open'));
    $('drawerClose').addEventListener('click', () => $('drawer').classList.remove('open'));
    let t;
    $('search').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { S.query = e.target.value; renderList(); }, 120); });
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (!$('modal').hidden) closeModal();
      else $('drawer').classList.remove('open');
    });
    $('modal').addEventListener('click', (e) => { if (e.target === $('modal')) closeModal(); });
    renderAll();
  }

  async function init() {
    const a = api();
    S.info = await a.get_info();
    $('version').textContent = 'версия ' + S.info.version;
    $('demoBadge').hidden = !S.info.demo;
    if (!S.info.isWindows && !S.info.demo) setStatus('Программа работает только в Windows', 'error');
    start();
    checkUpdate().catch(() => {});
  }

  bindUi();
  if (api() && api().get_info) init();
  else window.addEventListener('pywebviewready', init, { once: true });
})();
