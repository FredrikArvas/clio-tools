// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * admin/upload.js — fliken "Ladda upp" i admin/index.php.
 *
 * Skickar valda eller släppta filer EN I TAGET till admin/upload.php (XMLHttpRequest för
 * progress per fil) med CSRF-token i X-CSRF-Token. Storlek och ändelse kontrolleras här för
 * snabb återkoppling; servern kontrollerar allt igen.
 *
 * CSP: laddas som fil (inga inline-skript). Konfigurationen läses ur JSON-blocket
 * #upload-config. Filnamn och serverns texter visas bara via textContent, aldrig innerHTML.
 */
(function () {
    'use strict';

    const configEl = document.getElementById('upload-config');
    const dropEl   = document.getElementById('upload-drop');
    const inputEl  = document.getElementById('upload-input');
    const listEl   = document.getElementById('upload-list');
    if (!configEl || !dropEl || !inputEl || !listEl) return;

    const CONFIG     = JSON.parse(configEl.textContent);
    const EXTENSIONS = CONFIG.extensions.map(ext => ext.toLowerCase());
    const pending    = [];
    let isSending    = false;

    function formatBytes(bytes) {
        if (bytes >= 1048576) return (bytes / 1048576).toFixed(1).replace('.', ',') + ' MB';
        if (bytes >= 1024)    return Math.round(bytes / 1024) + ' kB';
        return bytes + ' B';
    }

    function extensionOf(name) {
        const dot = name.lastIndexOf('.');
        return dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
    }

    /** Klientens snabbkontroll; '' = ok. */
    function precheck(file) {
        if (!EXTENSIONS.includes(extensionOf(file.name))) return 'Bara .' + EXTENSIONS.join(' och .') + ' kan laddas upp.';
        if (file.size <= 0) return 'Filen är tom.';
        if (file.size > CONFIG.maxBytes) return 'Filen är större än ' + formatBytes(CONFIG.maxBytes) + '.';
        return '';
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    /** Ny rad i resultatlistan. Returnerar {item, progress, status} för uppdateringar. */
    function addRow(file) {
        const item     = el('li', 'upload-item');
        const row      = el('div', 'row');
        row.append(el('span', 'name', file.name), el('span', 'size', formatBytes(file.size)));
        const progress = el('progress');
        progress.max   = 100;
        progress.value = 0;
        const status   = el('div', 'status', 'Väntar…');
        item.append(row, progress, status);
        listEl.append(item);
        return { item, progress, status };
    }

    function finishRow(row, isOk, message, warnings) {
        row.item.classList.add(isOk ? 'ok' : 'err');
        row.progress.remove();
        row.status.textContent = message;
        (warnings || []).forEach(text => row.item.append(el('div', 'warn', '⚠ ' + text)));
    }

    function parseResponse(xhr) {
        try {
            const data = JSON.parse(xhr.responseText);
            return (data && typeof data === 'object') ? data : null;
        } catch (e) {
            return null;
        }
    }

    function messageFor(xhr, data) {
        if (data && typeof data.message === 'string') return data.message;
        if (xhr.status === 413) return 'Filen är för stor för servern.';
        if (xhr.status === 0)   return 'Nätverksfel. Kontrollera anslutningen och försök igen.';
        return 'Uppladdningen misslyckades (HTTP ' + xhr.status + ').';
    }

    function send(file, row) {
        return new Promise(resolve => {
            const xhr  = new XMLHttpRequest();
            const form = new FormData();
            form.append('file', file, file.name);
            xhr.open('POST', CONFIG.endpoint);
            xhr.setRequestHeader('X-CSRF-Token', CONFIG.csrf);
            xhr.upload.addEventListener('progress', e => {
                if (!e.lengthComputable) return;
                row.progress.value = Math.round(e.loaded / e.total * 100);
                row.status.textContent = 'Laddar upp… ' + row.progress.value + ' %';
            });
            xhr.addEventListener('load', () => {
                const data = parseResponse(xhr);
                if (xhr.status === 200 && data && data.ok) {
                    finishRow(row, true, 'Klar: ' + data.filename + ' (' + formatBytes(data.bytes) + ')', data.warnings);
                } else {
                    finishRow(row, false, messageFor(xhr, data));
                }
                resolve();
            });
            xhr.addEventListener('error', () => { finishRow(row, false, messageFor(xhr, null)); resolve(); });
            xhr.addEventListener('abort', () => { finishRow(row, false, 'Avbruten.'); resolve(); });
            xhr.send(form);
        });
    }

    async function drain() {
        if (isSending) return;
        isSending = true;
        while (pending.length) {
            const { file, row } = pending.shift();
            row.status.textContent = 'Laddar upp…';
            await send(file, row);
        }
        isSending = false;
    }

    function enqueue(files) {
        Array.from(files).forEach(file => {
            const row   = addRow(file);
            const error = precheck(file);
            if (error) { finishRow(row, false, error); return; }
            pending.push({ file, row });
        });
        drain();
    }

    inputEl.addEventListener('change', () => {
        enqueue(inputEl.files);
        inputEl.value = '';
    });

    ['dragenter', 'dragover'].forEach(type => dropEl.addEventListener(type, e => {
        e.preventDefault();
        dropEl.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach(type => dropEl.addEventListener(type, () => dropEl.classList.remove('over')));
    dropEl.addEventListener('drop', e => {
        e.preventDefault();
        if (e.dataTransfer && e.dataTransfer.files.length) enqueue(e.dataTransfer.files);
    });
    // En fil som släpps utanför ytan ska inte öppnas i webbläsaren (och lämna admin-sidan).
    window.addEventListener('dragover', e => e.preventDefault());
    window.addEventListener('drop', e => e.preventDefault());
})();
