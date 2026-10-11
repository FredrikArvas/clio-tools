/**
 * consent.js — Google Analytics consent mode och samtyckesbanner.
 *
 * Laddas av index.php i <head> (synkront, före gtag.js) så att consent-defaults gäller innan
 * Google-taggen startar. Ligger i en egen fil så att Content-Security-Policy kan förbjuda
 * inline-skript (script-src 'self' + googletagmanager.com).
 *
 * Exponerar globalt: gtag() (används även av player.js).
 */
window.dataLayer = window.dataLayer || [];
function gtag() { dataLayer.push(arguments); }

gtag('consent', 'default', {
    analytics_storage: 'denied',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
    wait_for_update: 500,
});
try {
    if (localStorage.getItem('clio_consent') === 'granted') {
        gtag('consent', 'update', { analytics_storage: 'granted' });
    }
} catch (_) { /* localStorage kan vara blockerat: då gäller 'denied' */ }

gtag('js', new Date());
gtag('config', 'G-MJR1MCM13R');

function clioConsent(granted) {
    try { localStorage.setItem('clio_consent', granted ? 'granted' : 'denied'); } catch (_) { /* se ovan */ }
    gtag('consent', 'update', { analytics_storage: granted ? 'granted' : 'denied' });
    document.getElementById('consent-banner').style.display = 'none';
}

// Bannern ligger efter <head> i DOM:en, så knapparna kopplas när sidan är inläst.
document.addEventListener('DOMContentLoaded', () => {
    const banner = document.getElementById('consent-banner');
    if (!banner) return;
    document.getElementById('consent-accept')?.addEventListener('click', () => clioConsent(true));
    document.getElementById('consent-deny')?.addEventListener('click', () => clioConsent(false));
    try {
        if (localStorage.getItem('clio_consent')) banner.style.display = 'none';
    } catch (_) { /* bannern visas */ }
});
