/* Иконки интерфейса: линейные SVG 24×24, цвет берут из currentColor. */
(function () {
  const P = {
    // устройства
    gpu: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="9" cy="12" r="3"/><path d="M15 10h4M15 14h4M5 18v2M9 18v2"/>',
    net: '<path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 15.5a5 5 0 0 1 7 0"/><path d="M1.5 9a15 15 0 0 1 21 0"/><circle cx="12" cy="19" r="1.2" fill="currentColor"/>',
    bt: '<path d="M7 7l10 10-5 4V3l5 4L7 17"/>',
    audio: '<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>',
    chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    storage: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 14h18"/><circle cx="17" cy="17" r="1" fill="currentColor"/><path d="M7 17h5"/>',
    usb: '<path d="M12 3v14"/><path d="M9 6l3-3 3 3"/><path d="M12 13l-5-3V8"/><path d="M12 15l5-3v-2"/><rect x="5" y="6" width="4" height="2" rx=".5"/><circle cx="17" cy="9" r="1.2"/><circle cx="12" cy="19" r="2"/>',
    camera: '<path d="M4 7h3l2-3h6l2 3h3a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="4"/>',
    firmware: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M13 7l-4 6h4l-2 4"/>',
    finger: '<path d="M12 11v4a6 6 0 0 1-1 3"/><path d="M8 8.5A5 5 0 0 1 17 11v2"/><path d="M5 14v-3a7 7 0 0 1 12-4.9"/><path d="M16 17a10 10 0 0 1-1 4"/><path d="M8.5 20A9 9 0 0 0 9 16v-4a3 3 0 0 1 6 0"/>',
    input: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    battery: '<rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/><path d="M6 10v4M9 10v4"/>',
    sensor: '<circle cx="12" cy="12" r="2"/><path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.5 5.5a9 9 0 0 0 0 13M18.5 5.5a9 9 0 0 1 0 13"/>',
    printer: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/>',
    tpm: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><rect x="9" y="11" width="6" height="5" rx="1"/><path d="M10 11V9.5a2 2 0 0 1 4 0V11"/>',
    device: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9z"/>',
    // интерфейс
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 4v5h-5"/>',
    download: '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5"/><circle cx="12" cy="18" r=".8" fill="currentColor"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r=".8" fill="currentColor"/>',
    chevron: '<path d="M9 6l6 6-6 6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    log: '<path d="M4 5h16M4 10h16M4 15h10M4 20h7"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    pc: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M7 20h10M12 16v4"/>',
    cpu: '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 1.5v3M15 1.5v3M9 19.5v3M15 19.5v3M1.5 9h3M1.5 15h3M19.5 9h3M19.5 15h3"/><path d="M9 9h6v6H9z"/>',
    ram: '<rect x="2" y="7" width="20" height="10" rx="1.5"/><path d="M6 17v3M10 17v3M14 17v3M18 17v3M6 10v4M10 10v4M14 10v4M18 10v4"/>',
    board: '<rect x="3" y="3" width="18" height="18" rx="2"/><rect x="7" y="7" width="5" height="5" rx="1"/><path d="M15 7h2M15 10h2M7 16h10"/>',
    windows: '<path d="M3 5.5l7.5-1v7H3zM12 4.3L21 3v8.5h-9zM3 12.5h7.5v7L3 18.5zM12 12.5h9V21l-9-1.3z"/>',
    external: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    power: '<path d="M12 3v9"/><path d="M6.3 7a8 8 0 1 0 11.4 0"/>',
    sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 1.8 1.8.7-1.8.7L19 22l-.7-1.8-1.8-.7 1.8-.7z"/>',
  };

  const CLASS_ICONS = {
    Display: 'gpu', Net: 'net', Bluetooth: 'bt', MEDIA: 'audio', Media: 'audio', AudioEndpoint: 'audio',
    System: 'chip', HDC: 'storage', SCSIAdapter: 'storage', DiskDrive: 'storage', Volume: 'storage',
    CDROM: 'storage', USB: 'usb', UCM: 'usb', Camera: 'camera', Image: 'camera', Firmware: 'firmware',
    Biometric: 'finger', HIDClass: 'input', Keyboard: 'input', Mouse: 'input', Monitor: 'monitor',
    Battery: 'battery', Sensor: 'sensor', Printer: 'printer', PrintQueue: 'printer',
    SecurityDevices: 'tpm', Processor: 'cpu', Computer: 'pc', Extension: 'sparkle',
    SoftwareComponent: 'sparkle',
  };

  function svg(name, cls) {
    const body = P[name] || P.device;
    return '<svg class="ic' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
  }

  window.Icons = {
    svg,
    forClass: (cls) => CLASS_ICONS[cls] || 'device',
    hydrate(root) {
      (root || document).querySelectorAll('i[data-icon]').forEach((el) => {
        el.outerHTML = svg(el.getAttribute('data-icon'));
      });
    },
  };
})();
