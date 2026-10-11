<?php
/**
 * client_ip.php — vem är klienten egentligen, och kom begäran över HTTPS?
 *
 * Anropas av: auth.php (Secure-flaggan på sessionscookien), login_throttle.php (räknare per IP),
 * audit.php (IP i auditloggen).
 *
 * Säkerhetsantaganden:
 * - All publik trafik kommer via cloudflared-tunneln, som ansluter till nginx på loopback.
 *   REMOTE_ADDR är då alltid 127.0.0.1, och den riktiga klienten står i CF-Connecting-IP
 *   (Cloudflare skriver över värdet; klienten kan inte förfalska det genom tunneln).
 * - Proxy-headers litas BARA på när REMOTE_ADDR är loopback. Kommer begäran från något annat
 *   (t.ex. en Tailscale-peer direkt mot port 8091) ignoreras de, annars kunde vem som helst
 *   välja sin egen IP och kringgå spärren mot inloggningsförsök.
 */

function is_trusted_proxy(): bool {
    return in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true);
}

function client_ip(): string {
    $remote_address = $_SERVER['REMOTE_ADDR'] ?? '';
    if (!is_trusted_proxy()) return $remote_address;
    $forwarded = trim($_SERVER['HTTP_CF_CONNECTING_IP'] ?? '');
    return filter_var($forwarded, FILTER_VALIDATE_IP) ? $forwarded : $remote_address;
}

/** Cloudflare terminerar TLS; tunneln pratar HTTP med nginx. HTTPS avgörs därför av proxyns headers. */
function request_is_https(): bool {
    if (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') return true;
    if (!is_trusted_proxy()) return false;
    if (strtolower($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') return true;
    return str_contains($_SERVER['HTTP_CF_VISITOR'] ?? '', '"https"');
}
