'use strict';
// md2docx.js — Markdown → Word (.docx)
// Användning: node md2docx.js input.md [output.docx] [--profile capgemini|aiab]
//
// Kör från clio-docx-katalogen (node_modules ligger där).

const {
  Document, Packer, Paragraph, TextRun, HeadingLevel,
  Table, TableRow, TableCell, WidthType, BorderStyle,
  AlignmentType, ShadingType, TableLayoutType, VerticalAlign,
  convertInchesToTwip,
} = require('docx');
const fs   = require('fs');
const path = require('path');

// ── PROFILER ────────────────────────────────────────────────────────────────
const PROFILES = {

  capgemini: {
    // Capgemini "New CG Template_2025 / Larissa"
    // Källa: Capgemini_word_template_simple.docx → word/theme/theme1.xml + styles.xml
    font:           'Ubuntu',
    fontHeading:    'Ubuntu Medium',
    fontMono:       'Courier New',
    bodySize:       21,   // 10.5pt
    codeSize:       19,   // 9.5pt
    h1Size:         32,   // 16pt  — H1 color: Capgemini blue
    h2Size:         24,   // 12pt  — H2 color: light blue
    h3Size:         22,   // 11pt  — H3 color: teal
    h4Size:         21,   // 10.5pt
    colorH1:        '0058AB',
    colorH2:        '1DB8F2',
    colorH3:        '00828E',
    colorH4:        '0D1329',
    colorBody:      '000000',
    colorMuted:     '404040',
    bqBg:           'E0F4F3',   // ljus teal
    bqBorder:       '00828E',   // teal
    tableHeaderBg:  '121A38',   // navy
    tableHeaderTxt: 'FFFFFF',
    tableAltBg:     'D6EAF8',   // ljusblå
    codeBg:         'F5F5F5',
    codeTxt:        '333333',
  },

  neutral: {
    // Neutral — generisk profil utan företagsbranding (Arial, grå/svart)
    font:           'Arial',
    fontHeading:    'Arial',
    fontMono:       'Courier New',
    bodySize:       22,   // 11pt
    codeSize:       20,   // 10pt
    h1Size:         32,   // 16pt
    h2Size:         26,   // 13pt
    h3Size:         24,   // 12pt
    h4Size:         22,   // 11pt
    colorH1:        '1F3864',   // mörkblå/marinblå
    colorH2:        '2F5496',   // mellanblå
    colorH3:        '2F5496',
    colorH4:        '404040',
    colorBody:      '000000',
    colorMuted:     '595959',
    bqBg:           'F2F2F2',
    bqBorder:       '595959',
    tableHeaderBg:  '2F5496',
    tableHeaderTxt: 'FFFFFF',
    tableAltBg:     'EAF0FA',
    codeBg:         'F5F5F5',
    codeTxt:        '333333',
  },

  aiab: {
    // Arvas International AB — AIAB-paletten
    font:           'Arial',
    fontHeading:    'Arial',
    fontMono:       'Courier New',
    bodySize:       22,   // 11pt
    codeSize:       20,   // 10pt
    h1Size:         36,   // 18pt
    h2Size:         28,   // 14pt
    h3Size:         24,   // 12pt
    h4Size:         22,
    colorH1:        '2A3F6F',   // Navy
    colorH2:        '4A6FA5',   // Blå
    colorH3:        '4A6FA5',
    colorH4:        '3D2E0A',
    colorBody:      '3D2E0A',   // Brun
    colorMuted:     '595959',
    bqBg:           'FDF6DC',   // Input-beige
    bqBorder:       '4A6FA5',
    tableHeaderBg:  '2A3F6F',   // Navy
    tableHeaderTxt: 'FFFFFF',
    tableAltBg:     'EDE5D0',   // Beige
    codeBg:         'F7F2E8',   // Krämvit
    codeTxt:        '2A3F6F',
  },

};

// ── CLI-argument ────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let profileName = 'capgemini';
const cleanArgs = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--profile' && args[i + 1]) { profileName = args[++i]; }
  else if (args[i].startsWith('--profile='))  { profileName = args[i].split('=')[1]; }
  else if (!args[i].startsWith('--'))         { cleanArgs.push(args[i]); }
}
const THEME = PROFILES[profileName] || PROFILES.capgemini;

if (!cleanArgs[0]) { console.error('Användning: node md2docx.js input.md [output.docx] [--profile capgemini|aiab|neutral]'); process.exit(1); }
const INPUT  = path.resolve(cleanArgs[0]);
const OUTPUT = cleanArgs[1] ? path.resolve(cleanArgs[1]) : INPUT.replace(/\.md$/i, '.docx');

// ── Inline parser: **bold** och `code` ────────────────────────────────────
function parseInline(text, base = {}) {
  const opts = { font: THEME.font, size: THEME.bodySize, color: THEME.colorBody, ...base };
  const tokens = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) tokens.push({ t: 'plain', s: text.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith('**')) tokens.push({ t: 'bold', s: tok.slice(2, -2) });
    else tokens.push({ t: 'code', s: tok.slice(1, -1) });
    last = re.lastIndex;
  }
  if (last < text.length) tokens.push({ t: 'plain', s: text.slice(last) });
  if (!tokens.length) return [new TextRun({ ...opts, text: '' })];
  return tokens.map(tok => {
    if (tok.t === 'bold') return new TextRun({ ...opts, text: tok.s, bold: true });
    if (tok.t === 'code') return new TextRun({ text: tok.s, font: THEME.fontMono, size: THEME.codeSize, color: THEME.codeTxt });
    return new TextRun({ ...opts, text: tok.s });
  });
}

// ── Byggstenar ─────────────────────────────────────────────────────────────
function para(children, opts = {}) {
  return new Paragraph({ children: Array.isArray(children) ? children : [children], ...opts });
}

function makeHeading(level, text) {
  const cfg = {
    1: { heading: HeadingLevel.HEADING_1, size: THEME.h1Size, color: THEME.colorH1 },
    2: { heading: HeadingLevel.HEADING_2, size: THEME.h2Size, color: THEME.colorH2 },
    3: { heading: HeadingLevel.HEADING_3, size: THEME.h3Size, color: THEME.colorH3 },
    4: { heading: HeadingLevel.HEADING_4, size: THEME.h4Size, color: THEME.colorH4 },
  }[Math.min(level, 4)];
  return para(
    parseInline(text, { font: THEME.fontHeading, size: cfg.size, color: cfg.color, bold: false }),
    { heading: cfg.heading, spacing: { before: 280, after: 100 } }
  );
}

function makeNormalPara(text) {
  return para(parseInline(text), { spacing: { before: 0, after: 160 } });
}

function makeBlockquote(lines) {
  const groups = [];
  let cur = [];
  for (const ln of lines) {
    const s = ln.startsWith('> ') ? ln.slice(2) : ln.startsWith('>') ? ln.slice(1).trimStart() : ln;
    if (!s.trim()) { if (cur.length) { groups.push(cur.join(' ')); cur = []; } }
    else cur.push(s);
  }
  if (cur.length) groups.push(cur.join(' '));
  return groups.map(g => para(parseInline(g, { color: THEME.colorMuted }), {
    spacing: { before: 100, after: 100 },
    indent: { left: convertInchesToTwip(0.3), right: convertInchesToTwip(0.3) },
    border: { left: { style: BorderStyle.SINGLE, size: 16, space: 8, color: THEME.bqBorder } },
    shading: { type: ShadingType.CLEAR, color: 'auto', fill: THEME.bqBg },
  }));
}

function makeCodeBlock(lines) {
  const result = [para([], { spacing: { before: 80, after: 0 }, shading: { type: ShadingType.CLEAR, color: 'auto', fill: THEME.codeBg } })];
  for (const line of lines) {
    result.push(para(
      [new TextRun({ text: line || ' ', font: THEME.fontMono, size: THEME.codeSize, color: THEME.codeTxt })],
      { spacing: { before: 0, after: 0 }, indent: { left: convertInchesToTwip(0.3) }, shading: { type: ShadingType.CLEAR, color: 'auto', fill: THEME.codeBg } }
    ));
  }
  result.push(para([], { spacing: { before: 0, after: 120 }, shading: { type: ShadingType.CLEAR, color: 'auto', fill: THEME.codeBg } }));
  return result;
}

function makeHRule() {
  return new Paragraph({
    children: [],
    spacing: { before: 160, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, space: 1, color: 'AAAAAA' } },
  });
}

function makeListItem(text, isCheckbox, checked) {
  const prefix = isCheckbox ? (checked ? '☑ ' : '☐ ') : '• ';
  return para(
    [new TextRun({ text: prefix, font: THEME.font, size: THEME.bodySize, color: THEME.colorH2, bold: true }),
     ...parseInline(text)],
    { spacing: { before: 60, after: 60 }, indent: { left: convertInchesToTwip(0.35), hanging: convertInchesToTwip(0.25) } }
  );
}

function makeTable(lines) {
  const rows = lines.filter(l => !l.match(/^\|[-|: ]+\|?\s*$/));
  if (!rows.length) return para([]);
  const parsed = rows.map(r => r.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim()));
  const colCount = Math.max(...parsed.map(r => r.length));
  const totalWidth = 9072;
  const colWidth = Math.floor(totalWidth / colCount);
  return new Table({
    width: { size: totalWidth, type: WidthType.DXA },
    columnWidths: Array(colCount).fill(colWidth),
    layout: TableLayoutType.FIXED,
    rows: parsed.map((cells, ri) => new TableRow({
      children: Array.from({ length: colCount }, (_, ci) => {
        const isHeader = ri === 0;
        const isAlt = !isHeader && ri % 2 === 0;
        return new TableCell({
          width: { size: colWidth, type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, color: 'auto', fill: isHeader ? THEME.tableHeaderBg : (isAlt ? THEME.tableAltBg : 'FFFFFF') },
          verticalAlign: VerticalAlign.CENTER,
          margins: { top: 80, bottom: 80, left: 100, right: 100 },
          children: [para(
            parseInline(cells[ci] || '', isHeader ? { color: THEME.tableHeaderTxt, bold: true } : {}),
            { spacing: { before: 0, after: 0 }, alignment: AlignmentType.LEFT }
          )],
        });
      }),
    })),
  });
}

// ── Huvud-parser ───────────────────────────────────────────────────────────
function parseMarkdown(content) {
  const lines = content.split('\n');
  const elems = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trimStart().startsWith('```')) {
      const code = []; i++;
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) { code.push(lines[i]); i++; }
      i++;
      if (code.length) elems.push(...makeCodeBlock(code));
      continue;
    }
    if (line.startsWith('|')) {
      const tbl = [];
      while (i < lines.length && lines[i].startsWith('|')) { tbl.push(lines[i]); i++; }
      elems.push(makeTable(tbl), para([], { spacing: { before: 0, after: 160 } }));
      continue;
    }
    if (line.startsWith('>')) {
      const bq = [];
      while (i < lines.length && lines[i].startsWith('>')) { bq.push(lines[i]); i++; }
      elems.push(...makeBlockquote(bq), para([], { spacing: { before: 0, after: 80 } }));
      continue;
    }
    if (line.match(/^[-*+] /) || line.match(/^- \[[ x]\] /i)) {
      while (i < lines.length && (lines[i].match(/^[-*+] /) || lines[i].match(/^- \[[ x]\] /i))) {
        const ln = lines[i];
        const cb = ln.match(/^- \[([ x])\] (.*)/i);
        elems.push(cb ? makeListItem(cb[2], true, cb[1].toLowerCase() === 'x') : makeListItem(ln.replace(/^[-*+] /, ''), false, false));
        i++;
      }
      elems.push(para([], { spacing: { before: 0, after: 80 } }));
      continue;
    }
    const hm = line.match(/^(#{1,6})\s+(.*)/);
    if (hm) { elems.push(makeHeading(hm[1].length, hm[2])); i++; continue; }
    if (line.match(/^---+\s*$/)) { elems.push(makeHRule()); i++; continue; }
    if (!line.trim()) { i++; continue; }
    elems.push(makeNormalPara(line));
    i++;
  }
  return elems;
}

// ── Bygg och spara ─────────────────────────────────────────────────────────
const md = fs.readFileSync(INPUT, 'utf8');
const doc = new Document({
  sections: [{
    properties: { page: { margin: { top: convertInchesToTwip(1), right: convertInchesToTwip(1.2), bottom: convertInchesToTwip(1), left: convertInchesToTwip(1.2) } } },
    children: parseMarkdown(md),
  }],
});
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUTPUT, buf);
  console.log(`OK [${profileName}]: ${OUTPUT}`);
}).catch(err => { console.error(err); process.exit(1); });
