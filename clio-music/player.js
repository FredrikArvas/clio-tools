'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const audios = {
    msc: document.getElementById('audio-msc'),
    bin: document.getElementById('audio-bin'),
    vce: document.getElementById('audio-vce'),
    env: document.getElementById('audio-env'),
};
const btnPlay = document.getElementById('btn-play');
const btnPrev = document.getElementById('btn-prev');
const btnNext = document.getElementById('btn-next');
const seek    = document.getElementById('seek');
const timeCur = document.getElementById('time-cur');
const timeDur = document.getElementById('time-dur');
const titleEl = document.getElementById('track-title');
const artistEl= document.getElementById('track-artist');
const libListEl    = document.getElementById('track-list');
const btnLyrics    = document.getElementById('btn-lyrics');
const lyricsPanel  = document.getElementById('lyrics-panel');
const lyricsLinesEl = document.getElementById('lyrics-lines');

const CH_IDS = ['msc', 'bin', 'vce', 'env'];

const sliders = {};
const lbls    = {};
const rows    = {};
CH_IDS.forEach(ch => {
    sliders[ch] = document.getElementById('s-' + ch);
    lbls[ch]    = document.getElementById('lbl-' + ch);
    rows[ch]    = document.getElementById('row-' + ch);
});

const slBalance = document.getElementById('s-balance');
const slBass    = document.getElementById('s-bass');
const slTreble  = document.getElementById('s-treble');
const lblBal    = document.getElementById('lbl-balance');
const lblBass   = document.getElementById('lbl-bass');
const lblTreb   = document.getElementById('lbl-treble');

const btnRepeatOne = document.getElementById('btn-repeat-one');
const btnRepeatAll = document.getElementById('btn-repeat-all');
const btnShuffle   = document.getElementById('btn-shuffle');
const slSpeed      = document.getElementById('s-speed');
const lblSpeed     = document.getElementById('lbl-speed');

// ── Web Audio API ─────────────────────────────────────────────────────────────
let ctx;
const gainNodes = {};
let panNode, bassNode, trebleNode;

function initAudio() {
    if (ctx) return;
    ctx = new (window.AudioContext || window.webkitAudioContext)();

    CH_IDS.forEach(ch => {
        const src   = ctx.createMediaElementSource(audios[ch]);
        gainNodes[ch] = ctx.createGain();

        if (ch === 'msc') {
            panNode    = ctx.createStereoPanner();
            bassNode   = ctx.createBiquadFilter();
            bassNode.type            = 'lowshelf';
            bassNode.frequency.value = 200;
            trebleNode = ctx.createBiquadFilter();
            trebleNode.type            = 'highshelf';
            trebleNode.frequency.value = 4000;
            src.connect(gainNodes.msc)
               .connect(panNode)
               .connect(bassNode)
               .connect(trebleNode)
               .connect(ctx.destination);
        } else {
            src.connect(gainNodes[ch]).connect(ctx.destination);
        }
    });

    applySettings();
}

// ── Settings ──────────────────────────────────────────────────────────────────
const CH_DEFAULTS = { msc: 0.8, bin: 0.5, vce: 0.9, env: 0.4 };
let serverProfiles = {};

const profilesLoaded = fetch('api/load_profiles.php')
    .then(r => r.json())
    .then(data => { serverProfiles = data; loadGlobalSettings(); updateAllLikeButtons(); })
    .catch(() => {});

function loadSettings(index) {
    const key = TRACKS[index]?.file ?? '';
    return serverProfiles[key] ?? {};
}

function saveSettings() {
    if (current < 0) return;
    const key = TRACKS[current].file;
    const s = {
        ...(serverProfiles[key] ?? {}),
        balance: parseFloat(slBalance.value),
        bass:    parseFloat(slBass.value),
        treble:  parseFloat(slTreble.value),
    };
    CH_IDS.forEach(ch => s[ch] = parseFloat(sliders[ch].value));
    serverProfiles[key] = s;
    fetch('api/save_profile.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track: key, settings: s }),
    }).catch(() => {});
}

function applySettings() {
    if (!ctx) return;
    CH_IDS.forEach(ch => { gainNodes[ch].gain.value = parseFloat(sliders[ch].value); });
    panNode.pan.value     = parseFloat(slBalance.value);
    bassNode.gain.value   = parseFloat(slBass.value);
    trebleNode.gain.value = parseFloat(slTreble.value);
}

function setSliders(s) {
    CH_IDS.forEach(ch => { sliders[ch].value = s[ch] ?? CH_DEFAULTS[ch]; });
    slBalance.value = s.balance ?? 0;
    slBass.value    = s.bass    ?? 0;
    slTreble.value  = s.treble  ?? 0;
    updateLabels();
    if (ctx) applySettings();
}

function initSettings() { setSliders({}); }

function updateLabels() {
    CH_IDS.forEach(ch => {
        lbls[ch].textContent = Math.round(parseFloat(sliders[ch].value) * 100) + '%';
    });
    const bal = parseFloat(slBalance.value);
    lblBal.textContent  = bal === 0 ? 'C' : (bal > 0 ? 'H ' + Math.round(bal * 100) : 'V ' + Math.round(-bal * 100));
    lblBass.textContent = (parseFloat(slBass.value) >= 0 ? '+' : '') + parseFloat(slBass.value).toFixed(1) + ' dB';
    lblTreb.textContent = (parseFloat(slTreble.value) >= 0 ? '+' : '') + parseFloat(slTreble.value).toFixed(1) + ' dB';
}

[...CH_IDS.map(ch => sliders[ch]), slBalance, slBass, slTreble].forEach(el => {
    el.addEventListener('input',  () => { updateLabels(); if (ctx) applySettings(); });
    el.addEventListener('change', saveSettings);
});

// ── Uppspelningsläge & hastighet ──────────────────────────────────────────────
let playMode = 'none';

function updateModeButtons() {
    btnRepeatOne.classList.toggle('active', playMode === 'repeat-one');
    btnRepeatAll.classList.toggle('active', playMode === 'repeat-all');
    btnShuffle.classList.toggle('active',   playMode === 'shuffle');
}

function updateSpeedLabel() {
    const r = parseFloat(slSpeed.value);
    lblSpeed.textContent = r === 1 ? '1×' : r.toFixed(2).replace(/\.?0+$/, '') + '×';
}

function applyPlaybackRate() {
    const rate = parseFloat(slSpeed.value);
    CH_IDS.forEach(ch => { audios[ch].playbackRate = rate; });
}

function loadGlobalSettings() {
    const s = serverProfiles['_settings'] ?? {};
    playMode      = s.playMode ?? 'none';
    slSpeed.value = s.playbackRate ?? 1;

    // Restore queue
    if (Array.isArray(s.queue) && s.queue.length) {
        queue = s.queue
            .map(url => {
                const idx = TRACKS.findIndex(t => t.file === url);
                return idx >= 0 ? { idx, id: nextQueueId++ } : null;
            })
            .filter(Boolean);
        queueCursor = (typeof s.queueCursor === 'number' && s.queueCursor < queue.length)
            ? s.queueCursor : -1;
    }

    updateModeButtons();
    updateSpeedLabel();
    applyPlaybackRate();
    renderQueue();
    updateQueueBadge();
}

function saveGlobalSettings() {
    const s = {
        playMode,
        playbackRate: parseFloat(slSpeed.value),
        queue: queue.map(item => TRACKS[item.idx].file),
        queueCursor,
    };
    serverProfiles['_settings'] = s;
    fetch('api/save_profile.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track: '_settings', settings: s }),
    }).catch(() => {});
}

[
    [btnRepeatOne, 'repeat-one'],
    [btnRepeatAll, 'repeat-all'],
    [btnShuffle,   'shuffle'],
].forEach(([btn, mode]) => {
    btn.addEventListener('click', () => {
        playMode = (playMode === mode) ? 'none' : mode;
        updateModeButtons();
        saveGlobalSettings();
    });
});

slSpeed.addEventListener('input',  () => { updateSpeedLabel(); applyPlaybackRate(); });
slSpeed.addEventListener('change', saveGlobalSettings);

// ── Kö ────────────────────────────────────────────────────────────────────────
let queue       = [];  // [{idx: trackIndex, id: uniqueId}]
let queueCursor = -1;  // position in queue being played (-1 = playing from library)
let nextQueueId = 0;
let dragSrc     = null;

function escHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function updateQueueBadge() {
    const badge = document.getElementById('queue-badge');
    if (!badge) return;
    badge.textContent = queue.length;
    badge.style.display = queue.length ? '' : 'none';
}

function renderQueue() {
    const listEl  = document.getElementById('queue-list');
    const emptyEl = document.getElementById('queue-empty-msg');
    if (!listEl || !emptyEl) return;

    emptyEl.style.display = queue.length ? 'none' : '';
    listEl.innerHTML = '';

    queue.forEach((item, pos) => {
        const t  = TRACKS[item.idx];
        const li = document.createElement('li');
        li.className = 'queue-item' + (pos === queueCursor ? ' active' : '');
        li.dataset.queuePos = pos;
        li.draggable = true;

        const sub = t.album || t.artist;
        li.innerHTML =
            `<span class="drag-handle" title="Dra för att ändra ordning">&#8801;</span>` +
            `<span class="queue-num">${pos + 1}</span>` +
            `<div class="track-info">` +
            `<span class="t-title">${escHtml(t.title)}</span>` +
            (sub ? `<span class="t-artist">${escHtml(sub)}</span>` : '') +
            `</div>` +
            `<div class="queue-controls">` +
            `<button class="q-btn q-up" title="Flytta upp"${pos === 0 ? ' disabled' : ''}>&#8963;</button>` +
            `<button class="q-btn q-down" title="Flytta ned"${pos === queue.length - 1 ? ' disabled' : ''}>&#8964;</button>` +
            `<button class="q-btn q-remove" title="Ta bort">&#x2715;</button>` +
            `</div>`;

        li.addEventListener('click', e => {
            if (e.target.closest('.queue-controls') || e.target.closest('.drag-handle')) return;
            queueCursor = pos;
            load(item.idx, true);
        });

        li.querySelector('.q-up').addEventListener('click', e => {
            e.stopPropagation();
            if (pos === 0) return;
            [queue[pos - 1], queue[pos]] = [queue[pos], queue[pos - 1]];
            if (queueCursor === pos) queueCursor = pos - 1;
            else if (queueCursor === pos - 1) queueCursor = pos;
            renderQueue();
            saveGlobalSettings();
        });

        li.querySelector('.q-down').addEventListener('click', e => {
            e.stopPropagation();
            if (pos === queue.length - 1) return;
            [queue[pos], queue[pos + 1]] = [queue[pos + 1], queue[pos]];
            if (queueCursor === pos) queueCursor = pos + 1;
            else if (queueCursor === pos + 1) queueCursor = pos;
            renderQueue();
            saveGlobalSettings();
        });

        li.querySelector('.q-remove').addEventListener('click', e => {
            e.stopPropagation();
            queue.splice(pos, 1);
            if (queueCursor === pos) queueCursor = -1;
            else if (queueCursor > pos) queueCursor--;
            renderQueue();
            updateQueueBadge();
            saveGlobalSettings();
        });

        // Drag-and-drop
        li.addEventListener('dragstart', e => {
            dragSrc = li;
            e.dataTransfer.effectAllowed = 'move';
            setTimeout(() => li.classList.add('dragging'), 0);
        });
        li.addEventListener('dragend', () => {
            li.classList.remove('dragging');
            document.querySelectorAll('.queue-item').forEach(el => el.classList.remove('drag-over'));
        });
        li.addEventListener('dragover', e => {
            e.preventDefault();
            if (dragSrc !== li) li.classList.add('drag-over');
        });
        li.addEventListener('dragleave', () => li.classList.remove('drag-over'));
        li.addEventListener('drop', e => {
            e.preventDefault();
            li.classList.remove('drag-over');
            if (!dragSrc || dragSrc === li) return;
            const srcPos = parseInt(dragSrc.dataset.queuePos);
            const dstPos = parseInt(li.dataset.queuePos);
            const [moved] = queue.splice(srcPos, 1);
            queue.splice(dstPos, 0, moved);
            if (queueCursor === srcPos) {
                queueCursor = dstPos;
            } else if (srcPos < dstPos && queueCursor > srcPos && queueCursor <= dstPos) {
                queueCursor--;
            } else if (srcPos > dstPos && queueCursor >= dstPos && queueCursor < srcPos) {
                queueCursor++;
            }
            renderQueue();
            saveGlobalSettings();
        });

        listEl.appendChild(li);
    });
}

function addToQueue(trackIndex) {
    queue.push({ idx: trackIndex, id: nextQueueId++ });
    updateQueueBadge();
    renderQueue();
    saveGlobalSettings();
    // Flash the queue tab to signal something was added
    const qTab = document.getElementById('tab-queue');
    if (qTab) {
        qTab.classList.add('flash');
        setTimeout(() => qTab.classList.remove('flash'), 400);
    }
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(tab) {
    ['lib', 'queue', 'pl'].forEach(t => {
        document.getElementById('view-' + t).hidden = t !== tab;
        document.getElementById('tab-' + t).classList.toggle('active', t === tab);
    });
}
document.getElementById('tab-lib').addEventListener('click',   () => switchTab('lib'));
document.getElementById('tab-queue').addEventListener('click', () => switchTab('queue'));
document.getElementById('tab-pl').addEventListener('click',    () => switchTab('pl'));

// ── Kanalsynk ─────────────────────────────────────────────────────────────────
function playAll() {
    CH_IDS.forEach(ch => { if (audios[ch].src) audios[ch].play().catch(() => {}); });
}
function pauseAll() {
    CH_IDS.forEach(ch => audios[ch].pause());
}
function seekAll(time) {
    CH_IDS.forEach(ch => { if (audios[ch].src) audios[ch].currentTime = time; });
}

function syncSecondary() {
    if (!audios.msc.hasAttribute('src')) return;
    ['bin', 'vce', 'env'].forEach(ch => {
        if (!audios[ch].hasAttribute('src') || audios[ch].paused) return;
        if (Math.abs(audios[ch].currentTime - audios.msc.currentTime) > 0.3) {
            audios[ch].currentTime = audios.msc.currentTime;
        }
    });
}

// ── Playback ──────────────────────────────────────────────────────────────────
let current = -1;

function fmt(s) {
    s = Math.floor(s || 0);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

async function load(index, autoplay) {
    if (!TRACKS.length) return;
    if (current >= 0) saveSettings();
    await profilesLoaded;
    index   = ((index % TRACKS.length) + TRACKS.length) % TRACKS.length;
    current = index;
    const t = TRACKS[index];
    updateHeaderLike();

    setSliders(loadSettings(index));
    applyPlaybackRate();

    CH_IDS.forEach(ch => {
        if (t[ch]) audios[ch].src = t[ch];
        else audios[ch].removeAttribute('src');
        if (rows[ch]) rows[ch].style.display = t[ch] ? '' : 'none';
    });

    titleEl.textContent  = t.title;
    artistEl.textContent = t.artist || (t.album ? '♪ ' + t.album : '');
    loadLyrics(t.lyrics ?? null);
    seek.value = 0;
    timeCur.textContent = '0:00';
    timeDur.textContent = '0:00';

    // Highlight in library
    document.querySelectorAll('.track-item').forEach(li =>
        li.classList.toggle('active', parseInt(li.dataset.index) === index));

    // Highlight in queue
    renderQueue();

    if (autoplay) {
        initAudio();
        if (ctx.state === 'suspended') ctx.resume();
        playAll();
    }
    btnPlay.innerHTML = autoplay ? '&#9646;&#9646;' : '&#9654;';
}

// ── Navigation ────────────────────────────────────────────────────────────────

function advanceNext(autoplay, force = false) {
    if (queue.length > 0 && queueCursor >= 0) {
        const next = queueCursor + 1;
        if (next < queue.length) {
            queueCursor = next;
            load(queue[queueCursor].idx, autoplay);
        } else if (playMode === 'repeat-all' || force) {
            queueCursor = 0;
            load(queue[0].idx, autoplay);
        } else {
            pauseAll();
        }
    } else {
        if (playMode === 'repeat-all' || force) {
            queueCursor = -1;
            load((current + 1) % TRACKS.length, autoplay);
        } else {
            pauseAll();
        }
    }
}

function advancePrev() {
    const wasPlaying = !audios.msc.paused;
    if (queue.length > 0 && queueCursor > 0) {
        queueCursor--;
        load(queue[queueCursor].idx, wasPlaying);
    } else if (queue.length > 0 && queueCursor === 0) {
        load(queue[0].idx, wasPlaying);
    } else {
        queueCursor = -1;
        load(current - 1, wasPlaying);
    }
}

function togglePlay() {
    if (!TRACKS.length) return;
    if (current < 0) { load(0, true); return; }
    initAudio();
    if (ctx.state === 'suspended') ctx.resume();
    if (audios.msc.paused) playAll(); else pauseAll();
}

btnPlay.addEventListener('click', togglePlay);
btnPrev.addEventListener('click', () => {
    if (current >= 0 && !audios.msc.paused) gaEvent('music_skip', {
        track_title: TRACKS[current]?.title, skip_direction: 'prev',
        skip_at_sec: Math.round(audios.msc.currentTime),
    });
    advancePrev();
});
btnNext.addEventListener('click', () => {
    if (current >= 0 && !audios.msc.paused) gaEvent('music_skip', {
        track_title: TRACKS[current]?.title, skip_direction: 'next',
        skip_at_sec: Math.round(audios.msc.currentTime),
    });
    advanceNext(!audios.msc.paused, true);
});

audios.msc.addEventListener('play',  () => { btnPlay.innerHTML = '&#9646;&#9646;'; });
audios.msc.addEventListener('pause', () => { btnPlay.innerHTML = '&#9654;'; });
audios.msc.addEventListener('ended', () => {
    const t = TRACKS[current];
    if (t) gaEvent('music_complete', {
        track_title:  t.title,
        track_artist: t.artist || undefined,
        track_album:  t.album  || undefined,
    });
    if (playMode === 'repeat-one') {
        seekAll(0); playAll();
    } else if (playMode === 'shuffle') {
        if (queue.length > 0 && queueCursor >= 0) {
            queueCursor = Math.floor(Math.random() * queue.length);
            load(queue[queueCursor].idx, true);
        } else {
            load(Math.floor(Math.random() * TRACKS.length), true);
        }
    } else {
        advanceNext(true);
    }
});

audios.msc.addEventListener('timeupdate', () => {
    if (!audios.msc.duration) return;
    seek.value = (audios.msc.currentTime / audios.msc.duration) * 100;
    timeCur.textContent = fmt(audios.msc.currentTime);
    syncSecondary();
    if (!lyricsPanel.hidden) updateLyricsLine(audios.msc.currentTime);
});
audios.msc.addEventListener('loadedmetadata', () => {
    timeDur.textContent = fmt(audios.msc.duration);
});

let seeking = false;
seek.addEventListener('mousedown',  () => { seeking = true; });
seek.addEventListener('touchstart', () => { seeking = true; });
seek.addEventListener('input', () => {
    if (audios.msc.duration) timeCur.textContent = fmt(audios.msc.duration * seek.value / 100);
});
seek.addEventListener('change', () => {
    seeking = false;
    const t = audios.msc.duration * seek.value / 100;
    if (!isNaN(t)) seekAll(t);
});

// ── Bibliotek-interaktion ─────────────────────────────────────────────────────
if (libListEl) {
    libListEl.addEventListener('click', e => {
        const playAlbumBtn = e.target.closest('.btn-play-album');
        if (playAlbumBtn) { playAlbum(playAlbumBtn.dataset.album); return; }

        const albumHeader = e.target.closest('.album-header');
        if (albumHeader) { toggleAlbumSection(albumHeader.closest('.album-section')); return; }

        const likeBtn = e.target.closest('.btn-like');
        if (likeBtn) { toggleLike(parseInt(likeBtn.dataset.index)); return; }

        const addQueueBtn = e.target.closest('.btn-add-queue');
        if (addQueueBtn) { addToQueue(parseInt(addQueueBtn.dataset.index)); return; }

        const addPlBtn = e.target.closest('.btn-add-pl');
        if (addPlBtn) { showPlaylistDropdown(addPlBtn); return; }

        const li = e.target.closest('.track-item');
        if (li) {
            queueCursor = -1;
            load(parseInt(li.dataset.index), true);
        }
    });
}

document.getElementById('btn-settings').addEventListener('click', () => {
    document.getElementById('settings-panel').classList.toggle('open');
});

// ── Spelningslogg ─────────────────────────────────────────────────────────────
let loggedTrack = null;
let logTimer    = null;

function logPlay(file) {
    if (file === loggedTrack) return;
    loggedTrack = file;
    fetch('api/log_play.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track: file }),
    }).catch(() => {});
    const t = TRACKS[current];
    if (t) gaEvent('music_play', {
        track_title:  t.title,
        track_artist: t.artist || undefined,
        track_album:  t.album  || undefined,
    });
}

audios.msc.addEventListener('playing', () => {
    clearTimeout(logTimer);
    const file = TRACKS[current]?.file;
    if (!file || file === loggedTrack) return;
    logTimer = setTimeout(() => logPlay(file), 5000);
});
audios.msc.addEventListener('pause', () => clearTimeout(logTimer));
audios.msc.addEventListener('ended', () => { clearTimeout(logTimer); loggedTrack = null; });

// ── Album-sektioner ───────────────────────────────────────────────────────────
function toggleAlbumSection(section) {
    if (!section) return;
    const collapsed = section.classList.toggle('collapsed');
    const btn = section.querySelector('.album-toggle');
    if (btn) btn.textContent = collapsed ? '▸' : '▾';
    try {
        const key = 'clio_collapsed_albums';
        const saved = JSON.parse(localStorage.getItem(key) || '[]');
        const set = new Set(saved);
        if (collapsed) set.add(section.dataset.album); else set.delete(section.dataset.album);
        localStorage.setItem(key, JSON.stringify([...set]));
    } catch (_) {}
}

function playAlbum(albumName) {
    const esc = albumName.replace(/"/g, '\\"');
    const items = document.querySelectorAll(`.album-section[data-album="${esc}"] .track-item`);
    const indices = [...items].map(li => parseInt(li.dataset.index));
    if (!indices.length) return;
    queue = indices.map(idx => ({ idx, id: nextQueueId++ }));
    queueCursor = 0;
    renderQueue();
    updateQueueBadge();
    saveGlobalSettings();
    load(queue[0].idx, true);
    switchTab('queue');
}

// Återställ kollapsade album
(function () {
    try {
        const collapsed = JSON.parse(localStorage.getItem('clio_collapsed_albums') || '[]');
        collapsed.forEach(name => {
            const esc = name.replace(/"/g, '\\"');
            const sec = document.querySelector(`.album-section[data-album="${esc}"]`);
            if (!sec) return;
            sec.classList.add('collapsed');
            const btn = sec.querySelector('.album-toggle');
            if (btn) btn.textContent = '▸';
        });
    } catch (_) {}
})();

// ── Spellistor ────────────────────────────────────────────────────────────────
let playlists = {};
let plDropdownForIndex = -1;

fetch('api/load_playlists.php')
    .then(r => r.json())
    .then(data => { playlists = data || {}; renderPlaylists(); })
    .catch(() => {});

function renderPlaylists() {
    const listEl  = document.getElementById('pl-list');
    const emptyEl = document.getElementById('pl-empty-msg');
    if (!listEl) return;
    listEl.innerHTML = '';
    const names = Object.keys(playlists);
    if (emptyEl) emptyEl.style.display = names.length ? 'none' : '';
    names.forEach(name => {
        const count = (playlists[name] || []).length;
        const li    = document.createElement('li');
        li.className = 'pl-item';
        li.innerHTML =
            `<div class="pl-item-info">` +
            `<span class="pl-name">${escHtml(name)}</span>` +
            `<span class="pl-count">${count} spår</span>` +
            `</div>` +
            `<div class="pl-item-btns">` +
            `<button class="q-btn pl-play" title="Spela spellistan">▶</button>` +
            `<button class="q-btn q-remove pl-del" title="Ta bort">✕</button>` +
            `</div>`;
        li.querySelector('.pl-play').addEventListener('click', () => playPlaylist(name));
        li.querySelector('.pl-del').addEventListener('click',  () => deletePlaylist(name));
        listEl.appendChild(li);
    });
}

function savePlPlaylist(name, tracks) {
    playlists[name] = tracks;
    renderPlaylists();
    fetch('api/save_playlist.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, tracks }),
    }).catch(() => {});
}

function deletePlaylist(name) {
    if (!confirm(`Ta bort spellistan "${name}"?`)) return;
    delete playlists[name];
    renderPlaylists();
    fetch('api/save_playlist.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, delete: true }),
    }).catch(() => {});
}

function playPlaylist(name) {
    const urls    = playlists[name] || [];
    const indices = urls.map(url => TRACKS.findIndex(t => t.file === url)).filter(i => i >= 0);
    if (!indices.length) { alert('Spellistan är tom eller saknar tillgängliga spår.'); return; }
    queue = indices.map(idx => ({ idx, id: nextQueueId++ }));
    queueCursor = 0;
    renderQueue();
    updateQueueBadge();
    saveGlobalSettings();
    load(queue[0].idx, true);
    switchTab('queue');
}

function addToPlaylist(trackIndex, playlistName) {
    const url = TRACKS[trackIndex]?.file;
    if (!url) return;
    const existing = playlists[playlistName] || [];
    if (existing.includes(url)) return;
    savePlPlaylist(playlistName, [...existing, url]);
}

document.getElementById('btn-create-pl')?.addEventListener('click', () => {
    const input = document.getElementById('pl-new-name');
    const name  = input.value.trim();
    if (!name) return;
    if (!playlists[name]) savePlPlaylist(name, []);
    input.value = '';
});

document.getElementById('pl-new-name')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('btn-create-pl').click();
});

// ── Spellista-dropdown ────────────────────────────────────────────────────────
function showPlaylistDropdown(btn) {
    plDropdownForIndex = parseInt(btn.dataset.index);
    const dd = document.getElementById('pl-dropdown');
    if (!dd) return;
    updatePlDropdown();
    dd.hidden = false;
    const rect = btn.getBoundingClientRect();
    dd.style.top  = (rect.bottom + window.scrollY + 4) + 'px';
    dd.style.left = Math.max(8, Math.min(rect.left + window.scrollX, window.innerWidth - 176)) + 'px';
}

function updatePlDropdown() {
    const ul = document.getElementById('pl-dropdown-list');
    if (!ul) return;
    ul.innerHTML = '';
    Object.keys(playlists).forEach(name => {
        const li  = document.createElement('li');
        const btn = document.createElement('button');
        btn.className   = 'pl-drop-item';
        btn.textContent = name;
        btn.addEventListener('click', () => {
            addToPlaylist(plDropdownForIndex, name);
            document.getElementById('pl-dropdown').hidden = true;
        });
        li.appendChild(btn);
        ul.appendChild(li);
    });
    // "Ny spellista..." längst ned
    const li  = document.createElement('li');
    const btn = document.createElement('button');
    btn.className   = 'pl-drop-item pl-drop-new';
    btn.textContent = '+ Ny spellista…';
    btn.addEventListener('click', () => {
        document.getElementById('pl-dropdown').hidden = true;
        const name = prompt('Namn på ny spellista:');
        if (!name || !name.trim()) return;
        const n = name.trim();
        if (!playlists[n]) savePlPlaylist(n, []);
        addToPlaylist(plDropdownForIndex, n);
    });
    li.appendChild(btn);
    ul.appendChild(li);
}

document.addEventListener('click', e => {
    const dd = document.getElementById('pl-dropdown');
    if (!dd || dd.hidden) return;
    if (!dd.contains(e.target) && !e.target.closest('.btn-add-pl')) dd.hidden = true;
});

// ── Gilla ─────────────────────────────────────────────────────────────────────
let filterLiked = false;

function toggleLike(index) {
    const url = TRACKS[index]?.file;
    if (!url) return;
    const prof = { ...(serverProfiles[url] ?? {}) };
    prof.liked = !prof.liked;
    serverProfiles[url] = prof;
    fetch('api/save_profile.php', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track: url, settings: prof }),
    }).catch(() => {});
    updateLikeUI(index);
    if (filterLiked) applyLikedFilter();
}

function updateLikeUI(index) {
    const url   = TRACKS[index]?.file;
    const liked = serverProfiles[url]?.liked ?? false;
    document.querySelectorAll(`.btn-like[data-index="${index}"]`).forEach(btn => {
        btn.classList.toggle('liked', liked);
        btn.title = liked ? 'Ta bort gilla' : 'Gilla';
    });
    if (index === current) updateHeaderLike();
}

function updateHeaderLike() {
    const btn = document.getElementById('btn-like-header');
    if (!btn || current < 0) return;
    btn.hidden = false;
    const url   = TRACKS[current]?.file;
    const liked = serverProfiles[url]?.liked ?? false;
    btn.classList.toggle('liked', liked);
    btn.title = liked ? 'Ta bort gilla' : 'Gilla';
}

function updateAllLikeButtons() {
    TRACKS.forEach((_, i) => updateLikeUI(i));
}

function applyLikedFilter() {
    document.querySelectorAll('.track-item').forEach(li => {
        if (!filterLiked) { li.hidden = false; return; }
        const url = TRACKS[parseInt(li.dataset.index)]?.file;
        li.hidden = !(serverProfiles[url]?.liked ?? false);
    });
    document.querySelectorAll('.album-section').forEach(sec => {
        if (!filterLiked) { sec.hidden = false; return; }
        sec.hidden = ![...sec.querySelectorAll('.track-item')].some(li => !li.hidden);
    });
    const filterBtn = document.getElementById('btn-filter-liked');
    if (filterBtn) filterBtn.classList.toggle('active', filterLiked);
}

document.getElementById('btn-like-header')?.addEventListener('click', () => {
    if (current >= 0) toggleLike(current);
});

document.getElementById('btn-filter-liked')?.addEventListener('click', () => {
    filterLiked = !filterLiked;
    applyLikedFilter();
});

// ── Lyrics ────────────────────────────────────────────────────────────────────
let lyricsData      = [];
let lyricsActiveIdx = -1;
let lyricsVisible   = false;
try { lyricsVisible = localStorage.getItem('clio_lyrics_visible') === '1'; } catch (_) {}

function parseLRC(text) {
    const lines = [];
    for (const raw of text.split('\n')) {
        const m = raw.match(/^\[(\d+):(\d+(?:\.\d+)?)\](.*)/);
        if (!m) continue;
        const time = parseInt(m[1], 10) * 60 + parseFloat(m[2]);
        // Strip any remaining [tag] blocks (e.g. [end:mm:ss.xxx]) before text
        const lineText = m[3].replace(/\[[^\]]*\]/g, '').trim();
        lines.push({ time, text: lineText });
    }
    return lines.sort((a, b) => a.time - b.time);
}

function renderLyricsLines() {
    lyricsLinesEl.innerHTML = '';
    lyricsData.forEach((line, i) => {
        const li = document.createElement('li');
        li.textContent = line.text;
        li.dataset.idx = i;
        if (!line.text) li.className = 'lyric-spacer';
        lyricsLinesEl.appendChild(li);
    });
}

async function loadLyrics(url) {
    lyricsData      = [];
    lyricsActiveIdx = -1;
    lyricsLinesEl.innerHTML = '';
    if (!url) {
        btnLyrics.hidden = true;
        lyricsPanel.hidden = true;
        return;
    }
    try {
        const r = await fetch(url);
        if (!r.ok) throw new Error();
        lyricsData = parseLRC(await r.text());
    } catch (_) {
        btnLyrics.hidden = true;
        lyricsPanel.hidden = true;
        return;
    }
    renderLyricsLines();
    btnLyrics.hidden = false;
    lyricsPanel.hidden = !lyricsVisible;
    btnLyrics.classList.toggle('active', lyricsVisible);
}

function updateLyricsLine(currentTime) {
    if (!lyricsData.length) return;
    let idx = 0;
    for (let i = lyricsData.length - 1; i >= 0; i--) {
        if (currentTime >= lyricsData[i].time) { idx = i; break; }
    }
    if (idx === lyricsActiveIdx) return;
    lyricsActiveIdx = idx;
    const items = lyricsLinesEl.querySelectorAll('li');
    items.forEach((el, i) => el.classList.toggle('active', i === idx));
    const activeEl = items[idx];
    if (activeEl) activeEl.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

btnLyrics.addEventListener('click', () => {
    lyricsVisible = !lyricsVisible;
    lyricsPanel.hidden = !lyricsVisible;
    btnLyrics.classList.toggle('active', lyricsVisible);
    try { localStorage.setItem('clio_lyrics_visible', lyricsVisible ? '1' : '0'); } catch (_) {}
});

// ── Google Analytics ──────────────────────────────────────────────────────────
function gaEvent(name, params) {
    if (typeof gtag !== 'function') return;
    gtag('event', name, { user_type: CM_USER_TYPE, ...params });
}

if (typeof gtag === 'function') {
    gtag('set', { user_properties: { user_type: CM_USER_TYPE } });
}

// ── Init ──────────────────────────────────────────────────────────────────────
initSettings();
updateModeButtons();
updateSpeedLabel();
updateQueueBadge();
