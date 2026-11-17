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
        const total = 870 * 1048576;
        (async () => {
          emit('install_started', { keys });
          keys.forEach((k) => emit('progress', { key: k, state: 'waiting', message: 'в очереди' }));
          for (const k of keys) {
            const last = k === keys[keys.length - 1];
            for (let p = 0; p <= 100; p += 20) {
              if (window.__MOCK_HOLD__ && last && p > 40) return; // «заморозить» посреди скачивания
              await later(80 * SPEED, () => emit('progress', { key: k, state: 'running', stage: 'download', percent: p,
                message: 'Скачивание · ' + p + '% · ' + Math.round(870 * p / 100) + ' МБ из 870 МБ', done: total * p / 100, total }));
            }
            await later(150 * SPEED, () => emit('progress', { key: k, state: 'running', stage: 'verify', message: 'Проверка цифровой подписи' }));
            await later(150 * SPEED, () => emit('progress', { key: k, state: 'running', stage: 'install', message: 'Установка драйвера' }));
            await later(300 * SPEED, () => emit('progress', { key: k, state: k.endsWith('2') ? 'error' : 'ok',
              message: k.endsWith('2') ? 'ошибка 0x80070103' : 'установлен' }));
          }
          await later(200 * SPEED, () => emit('progress', { key: '', state: 'cleanup', stage: 'cleanup', message: '' }));
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
