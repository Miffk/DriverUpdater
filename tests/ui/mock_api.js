/* Подставной pywebview.api для просмотра интерфейса в обычном браузере (без Windows).
   Воспроизводит события, записанные из настоящего bridge.py: window.__FIXTURE__ = {events: [...]}. */
(function () {
  const F = window.__FIXTURE__ || { events: [] };
  const emit = (type, data) => window.__du && window.__du.onEvent({ type, data });
  const later = (ms, fn) => new Promise((r) => setTimeout(() => { fn(); r(); }, ms));
  const SPEED = window.__MOCK_SPEED__ || 1;
  let items = [];

  window.pywebview = {
    api: {
      get_info: async () => ({ version: '0.2.0', isAdmin: true, isWindows: true, demo: true, busy: false }),
      start: async () => {
        (async () => {
          for (const ev of F.events) {
            if (ev.type === 'items') items = ev.data.items;
            await later(ev.type === 'items' ? 900 * SPEED : 60 * SPEED, () => emit(ev.type, ev.data));
          }
        })();
        return true;
      },
      install: async (ids) => {
        const keys = [...new Set(items.filter((i) => ids.includes(i.id)).map((i) => i.offer.key))];
        (async () => {
          emit('install_started', { keys });
          for (const k of keys) {
            await later(300 * SPEED, () => emit('progress', { key: k, state: 'running', message: 'скачивание и установка' }));
            if (window.__MOCK_HOLD__ && k === keys[keys.length - 1]) return;
            await later(500 * SPEED, () => emit('progress', { key: k, state: k.endsWith('2') ? 'error' : 'ok',
              message: k.endsWith('2') ? 'ошибка 0x80070103' : 'установлен' }));
          }
          await later(200 * SPEED, () => emit('progress', { key: '', state: 'cleanup', message: '' }));
          await later(300 * SPEED, () => emit('install_done', { results: [], okCount: keys.length - 1, total: keys.length,
            cleanedBytes: 883023000, reboot: true }));
          emit('idle', { task: 'install' });
        })();
        return { ok: true, count: keys.length };
      },
      open_url: async () => true, reboot: async () => true, relaunch_as_admin: async () => false,
      check_update: async () => ({ available: true, version: '0.3.1', current: '0.3.0', canAutoUpdate: true,
        notes: '- Проверка драйверов на сайте NVIDIA\n- Кнопка «Перезапустить устройство»', page: 'https://github.com/' }),
      apply_update: async () => ({ ok: true }),
      repair: async (id) => { setTimeout(() => { emit('repair_done', { id, ok: false,
        message: 'Перезапуск не помог. Попробуйте вставить устройство в другой USB-разъём или перезагрузить компьютер.' });
        emit('idle', { task: 'repair' }); }, 600 * SPEED); return { ok: true }; },
      run_tool: async () => ({ ok: true }),
    },
  };
  window.dispatchEvent(new Event('pywebviewready'));
})();
