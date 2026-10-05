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
const listEl  = document.getElementById('track-list');

const CH_IDS = ['msc', 'bin', 'vce', 'env'];

// Channel sliders & labels
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
            // Musik: full kedja med EQ och pan
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
            // Övriga: gain only — stereosfas bevaras (viktigt för bin)
            src.connect(gainNodes[ch]).connect(ctx.destination);
        }
    });

    applySettings();
}

// ── Settings (per användare × per spår, serverside) ───────────────────────────
const CH_DEFAULTS = { msc: 0.8, bin: 0.5, vce: 0.9, env: 0.4 };
let serverProfiles = {};

const profilesLoaded = fetch('api/load_profiles.php')
    .then(r => r.json())
    .then(data => { serverProfiles = data; })
    .catch(() => {});

function loadSettings(index) {
    const key = TRACKS[index]?.file ?? '';
    return serverProfiles[key] ?? {};
}

function saveSettings() {
    if (current < 0) return;
    const s = {
        balance: parseFloat(slBalance.value),
        bass:    parseFloat(slBass.value),
        treble:  parseFloat(slTreble.value),
    };
    CH_IDS.forEach(ch => s[ch] = parseFloat(sliders[ch].value));
    const key = TRACKS[current].file;
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

function initSettings() {
    setSliders({});
}

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

// Korrigerar drift mot msc-kanalen var ~250 ms (via timeupdate)
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

    setSliders(loadSettings(index));

    // Sätt src för alla kanaler, visa/dölj slider-rader
    CH_IDS.forEach(ch => {
        if (t[ch]) audios[ch].src = t[ch];
        else audios[ch].removeAttribute('src');
        if (rows[ch]) rows[ch].style.display = t[ch] ? '' : 'none';
    });

    titleEl.textContent   = t.title;
    artistEl.textContent  = t.artist || (t.album ? '♪ ' + t.album : '');
    seek.value = 0;
    timeCur.textContent = '0:00';
    timeDur.textContent = '0:00';

    document.querySelectorAll('.track-item').forEach((li, i) =>
        li.classList.toggle('active', i === index));

    if (autoplay) {
        initAudio();
        if (ctx.state === 'suspended') ctx.resume();
        playAll();
    }
    btnPlay.innerHTML = autoplay ? '&#9646;&#9646;' : '&#9654;';
}

function togglePlay() {
    if (!TRACKS.length) return;
    if (current < 0) { load(0, true); return; }
    initAudio();
    if (ctx.state === 'suspended') ctx.resume();
    if (audios.msc.paused) playAll(); else pauseAll();
}

btnPlay.addEventListener('click', togglePlay);
btnPrev.addEventListener('click', () => load(current - 1, !audios.msc.paused));
btnNext.addEventListener('click', () => load(current + 1, !audios.msc.paused));

// msc är master för UI-tillstånd
audios.msc.addEventListener('play',  () => { btnPlay.innerHTML = '&#9646;&#9646;'; });
audios.msc.addEventListener('pause', () => { btnPlay.innerHTML = '&#9654;'; });
audios.msc.addEventListener('ended', () => { pauseAll(); load(current + 1, true); });

audios.msc.addEventListener('timeupdate', () => {
    if (!audios.msc.duration) return;
    seek.value = (audios.msc.currentTime / audios.msc.duration) * 100;
    timeCur.textContent = fmt(audios.msc.currentTime);
    syncSecondary();
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

if (listEl) {
    listEl.addEventListener('click', e => {
        const li = e.target.closest('.track-item');
        if (li) load(parseInt(li.dataset.index), true);
    });
}

document.getElementById('btn-settings').addEventListener('click', () => {
    document.getElementById('settings-panel').classList.toggle('open');
});

// ── Play logging ──────────────────────────────────────────────────────────────
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
}

audios.msc.addEventListener('playing', () => {
    clearTimeout(logTimer);
    const file = TRACKS[current]?.file;
    if (!file || file === loggedTrack) return;
    logTimer = setTimeout(() => logPlay(file), 5000);
});
audios.msc.addEventListener('pause', () => clearTimeout(logTimer));
audios.msc.addEventListener('ended', () => { clearTimeout(logTimer); loggedTrack = null; });

// ── Init ──────────────────────────────────────────────────────────────────────
initSettings();
