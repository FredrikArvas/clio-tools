// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

'use strict';

// Temaval. Laddas synkront i <head> så att rätt tema sätts innan sidan målas (ingen blinkning).
// Ett tema är bara data-theme på <html>; färgerna bor i style.css. Valet sparas i localStorage.
(function () {
    const STORAGE_KEY   = 'clio_theme';
    const DEFAULT_THEME = 'natt';
    const THEMES = [
        { id: 'natt',     name: 'Mörk natt',     desc: 'Djup och fokuserad' },
        { id: 'morgon',   name: 'Ljus morgon',   desc: 'Ljus och dämpad' },
        { id: 'skymning', name: 'Varm skymning', desc: 'Ombonad och varm' },
        { id: 'skog',     name: 'Djup skog',     desc: 'Jordnära och lugn' },
        { id: 'lavendel', name: 'Lavendel',      desc: 'Mjuk och drömsk' },
        { id: 'kontrast', name: 'Hög kontrast',  desc: 'Skarp och tydlig' },
    ];
    const THEME_IDS = THEMES.map(t => t.id);

    function loadTheme() {
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            return THEME_IDS.includes(saved) ? saved : DEFAULT_THEME;
        } catch (err) {
            console.warn('Kunde inte läsa temaval:', err);
            return DEFAULT_THEME;
        }
    }

    function saveTheme(id) {
        try {
            localStorage.setItem(STORAGE_KEY, id);
        } catch (err) {
            console.warn('Kunde inte spara temaval:', err);
        }
    }

    function applyTheme(id) {
        document.documentElement.dataset.theme = id;
    }

    function buildTile(theme, isCurrent) {
        const tile = document.createElement('button');
        tile.type = 'button';
        tile.className = 'theme-tile';
        tile.dataset.theme = theme.id;   // tilen får temats egna färger via style.css
        tile.setAttribute('aria-pressed', String(isCurrent));
        tile.innerHTML = '<span class="theme-dots" aria-hidden="true"><span></span><span></span><span></span></span>'
            + '<span class="theme-name"></span><span class="theme-desc"></span>';
        tile.querySelector('.theme-name').textContent = theme.name;
        tile.querySelector('.theme-desc').textContent = theme.desc;
        return tile;
    }

    function initPicker() {
        const button = document.getElementById('btn-theme');
        const panel  = document.getElementById('theme-panel');
        if (!button || !panel) return;

        const tilesEl = panel.querySelector('.theme-tiles');
        const current = document.documentElement.dataset.theme;
        THEMES.forEach(t => tilesEl.appendChild(buildTile(t, t.id === current)));

        const setOpen = open => {
            panel.hidden = !open;
            button.setAttribute('aria-expanded', String(open));
        };
        button.addEventListener('click', () => setOpen(panel.hidden));
        tilesEl.addEventListener('click', e => {
            const tile = e.target.closest('.theme-tile');
            if (!tile) return;
            applyTheme(tile.dataset.theme);
            saveTheme(tile.dataset.theme);
            tilesEl.querySelectorAll('.theme-tile').forEach(el =>
                el.setAttribute('aria-pressed', String(el === tile)));
        });
        document.addEventListener('click', e => {
            if (!panel.hidden && !panel.contains(e.target) && !button.contains(e.target)) setOpen(false);
        });
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && !panel.hidden) { setOpen(false); button.focus(); }
        });
    }

    applyTheme(loadTheme());
    document.addEventListener('DOMContentLoaded', initPicker);
})();
