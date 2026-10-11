<?php
/**
 * tests/theme_contrast_test.php — kontrollerar att varje tema i style.css uppfyller WCAG AA.
 *
 * Körs lokalt eller på servern:  php tests/theme_contrast_test.php
 * Läser style.css, plockar ut alla [data-theme="..."]-block och mäter kontrasten för de
 * färgpar som verkligen används i gränssnittet. Avslutskod 0 = alla teman klarar kraven.
 *
 * Misslyckade vägar testas också: en palett med för låg kontrast ska verkligen underkännas,
 * och ett tema som saknar en variabel ska rapporteras.
 */

const REQUIRED_VARIABLES = ['bg', 'surface', 'surface2', 'border', 'accent', 'accent2',
                            'text', 'muted', 'active-bg', 'on-accent'];
const MIN_TEXT_CONTRAST  = 4.5;   // WCAG AA, normal text
const MIN_GRAPHIC_CONTRAST = 3.0; // WCAG AA, grafiska komponenter

// [förgrund, bakgrund, minimikontrast, förklaring]
const COLOR_PAIRS = [
    ['text',      'bg',        MIN_TEXT_CONTRAST,    'brödtext mot bakgrund'],
    ['text',      'surface',   MIN_TEXT_CONTRAST,    'brödtext mot panel'],
    ['text',      'surface2',  MIN_TEXT_CONTRAST,    'text mot reglagepanel'],
    ['text',      'active-bg', MIN_TEXT_CONTRAST,    'aktuell rad/spår'],
    ['muted',     'bg',        MIN_TEXT_CONTRAST,    'dämpad text mot bakgrund'],
    ['muted',     'surface',   MIN_TEXT_CONTRAST,    'dämpad text mot panel'],
    ['muted',     'surface2',  MIN_TEXT_CONTRAST,    'dämpad text mot reglagepanel'],
    ['muted',     'active-bg', MIN_TEXT_CONTRAST,    'dämpad text mot aktivt spår'],
    ['accent',    'bg',        MIN_TEXT_CONTRAST,    'accent mot bakgrund'],
    ['accent',    'surface',   MIN_TEXT_CONTRAST,    'accent mot panel'],
    ['accent',    'surface2',  MIN_TEXT_CONTRAST,    'accent mot reglagepanel'],
    ['accent2',   'bg',        MIN_TEXT_CONTRAST,    'accent2 (flikar, albumnamn) mot bakgrund'],
    ['accent2',   'surface',   MIN_TEXT_CONTRAST,    'accent2 mot panel'],
    ['on-accent', 'accent',    MIN_TEXT_CONTRAST,    'text på fylld accent'],
    ['accent',    'surface2',  MIN_GRAPHIC_CONTRAST, 'play-ring mot knappyta'],
];

$pass = 0;
$fail = 0;

function check(string $description, bool $condition): void {
    global $pass, $fail;
    if ($condition) { $pass++; echo "  OK    $description\n"; return; }
    $fail++;
    echo "  FEL   $description\n";
}

function relative_luminance(string $hex): float {
    $channels = array_map(function (int $offset) use ($hex) {
        $value = hexdec(substr($hex, $offset, 2)) / 255;
        return $value <= 0.03928 ? $value / 12.92 : (($value + 0.055) / 1.055) ** 2.4;
    }, [1, 3, 5]);
    return 0.2126 * $channels[0] + 0.7152 * $channels[1] + 0.0722 * $channels[2];
}

function contrast_ratio(string $first, string $second): float {
    $a = relative_luminance($first);
    $b = relative_luminance($second);
    return (max($a, $b) + 0.05) / (min($a, $b) + 0.05);
}

/** @return array<string, array<string, string>> tema => variabel => hexvärde */
function parse_themes(string $css): array {
    $themes = [];
    preg_match_all('/\[data-theme="(\w+)"\]\s*\{([^}]*)\}/', $css, $blocks, PREG_SET_ORDER);
    foreach ($blocks as [, $theme, $body]) {
        preg_match_all('/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/', $body, $vars, PREG_SET_ORDER);
        foreach ($vars as [, $name, $hex]) {
            $themes[$theme][$name] = strtolower($hex);
        }
    }
    return $themes;
}

$css = file_get_contents(dirname(__DIR__) . '/style.css');
$themes = parse_themes($css);

echo "Teman\n";
check('minst fem teman hittades i style.css', count($themes) >= 5);

foreach ($themes as $theme => $vars) {
    echo "\nTema: $theme\n";
    $missing = array_diff(REQUIRED_VARIABLES, array_keys($vars));
    check("alla variabler finns ($theme)", $missing === []);
    if ($missing !== []) { echo "        saknas: " . implode(', ', $missing) . "\n"; continue; }

    foreach (COLOR_PAIRS as [$foreground, $background, $minimum, $label]) {
        $ratio = contrast_ratio($vars[$foreground], $vars[$background]);
        check(sprintf('%s: %s/%s %.1f (krav %.1f)', $label, $foreground, $background, $ratio, $minimum),
              $ratio >= $minimum);
    }
}

echo "\nMisslyckade vägar\n";
check('låg kontrast underkänns (#7a8299 mot #1e2a40 är under 4,5)',
      contrast_ratio('#7a8299', '#1e2a40') < MIN_TEXT_CONTRAST);
check('vit mot vit ger 1:1', abs(contrast_ratio('#ffffff', '#ffffff') - 1.0) < 0.001);
check('svart mot vit ger 21:1', abs(contrast_ratio('#000000', '#ffffff') - 21.0) < 0.01);
$broken = parse_themes('[data-theme="trasigt"] { --bg: #000000; }');
check('tema med saknade variabler upptäcks', array_diff(REQUIRED_VARIABLES, array_keys($broken['trasigt'])) !== []);

echo "\n$pass ok, $fail fel\n";
exit($fail === 0 ? 0 : 1);
