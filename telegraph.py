#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegraph Clone - File unico, solo libreria standard Python.
v4: URL = titolo (con rinomina automatica in modifica) + modifica solo autore
    + editing avanzato + PWA mobile.
Avvio:  python telegraph.py
Apri:   http://localhost:5000
Requisiti: Python 3.8+ (nessun pip install)
"""

import http.server
import socketserver
import sqlite3
import json
import re
import uuid
import os
import struct
import zlib
import unicodedata
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime

PORT = int(os.environ.get('PORT', 5000))
DB_FILE = 'telegraph.db'

# ============================================================
# SLUG: traslitterazione esplicita + normalizzazione
# ============================================================
ACCENT_MAP = {
    'à':'a','á':'a','â':'a','ã':'a','ä':'a','å':'a',
    'è':'e','é':'e','ê':'e','ë':'e',
    'ì':'i','í':'i','î':'i','ï':'i',
    'ò':'o','ó':'o','ô':'o','õ':'o','ö':'o',
    'ù':'u','ú':'u','û':'u','ü':'u',
    'ç':'c','ñ':'n','ý':'y','ÿ':'y',
    'ß':'ss','æ':'ae','œ':'oe',
    'À':'A','Á':'A','Â':'A','Ã':'A','Ä':'A','Å':'A',
    'È':'E','É':'E','Ê':'E','Ë':'E',
    'Ì':'I','Í':'I','Î':'I','Ï':'I',
    'Ò':'O','Ó':'O','Ô':'O','Õ':'O','Ö':'O',
    'Ù':'U','Ú':'U','Û':'U','Ü':'U',
    'Ç':'C','Ñ':'N','Ý':'Y',
}

def make_slug(title):
    """Trasforma il titolo in uno slug leggibile e stabile."""
    s = ''.join(ACCENT_MAP.get(ch, ch) for ch in title)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-')
    if len(s) > 80:
        s = s[:80].rsplit('-', 1)[0]
    return s or 'page'

def unique_slug(db, base, exclude_slug=None):
    """Genera slug univoco: se esiste già, aggiunge -2, -3, ..."""
    slug = base
    counter = 2
    while True:
        q = 'SELECT 1 FROM pages WHERE slug=?'
        params = [slug]
        if exclude_slug:
            q += ' AND slug != ?'
            params.append(exclude_slug)
        if not db.execute(q, params).fetchone():
            return slug
        slug = f"{base}-{counter}"
        counter += 1

# ============================================================
# DATABASE
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                content TEXT NOT NULL,
                edit_token TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS slug_redirects (
                old_slug TEXT PRIMARY KEY,
                new_slug TEXT NOT NULL
            )
        ''')
        db.commit()

# ============================================================
# ICONE PWA
# ============================================================
def make_png(size, rgb=(36, 129, 204)):
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    header = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    raw = b''
    for _ in range(size):
        raw += b'\x00' + bytes(rgb) * size
    idat = zlib.compress(raw, 9)
    return header + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')

ICON_192 = make_png(192)
ICON_512 = make_png(512)

MANIFEST_JSON = json.dumps({
    "name": "Telegraph", "short_name": "Telegraph",
    "start_url": "/", "scope": "/",
    "display": "standalone", "orientation": "portrait",
    "background_color": "#ffffff", "theme_color": "#2481cc",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
})

SERVICE_WORKER_JS = """
const CACHE = 'telegraph-v4';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
"""

# ============================================================
# TEMPLATE EDITOR
# ============================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#2481cc">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Telegraph">
<title>Telegraph</title>
<style>
* { box-sizing: border-box; }
html, body { margin:0; padding:0; background:#fff; color:#000;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:18px; line-height:1.6; -webkit-text-size-adjust:100%; }
body { min-height:100dvh; display:flex; flex-direction:column; }
a { color:#2481cc; text-decoration:none; }
a:hover { text-decoration:underline; }
.top-bar { display:flex; justify-content:space-between; align-items:center;
  padding:12px 20px; max-width:720px; width:100%; margin:0 auto;
  font-size:14px; color:#999; }
.top-bar .logo { font-weight:700; color:#000; font-size:15px; letter-spacing:-0.3px; }
.top-bar .actions { display:flex; gap:14px; align-items:center; }
.top-bar .actions button { background:none; border:none; padding:0; font-size:13px;
  color:#999; cursor:pointer; font-family:inherit; text-transform:uppercase; letter-spacing:0.5px; }
.top-bar .actions button:hover { color:#000; }
.editor-wrap { flex:1; max-width:720px; width:100%; margin:0 auto;
  padding:0 20px 80px; position:relative; }
#title { width:100%; border:none; outline:none; font-size:32px; font-weight:700;
  line-height:1.3; padding:8px 0 4px; background:transparent; font-family:inherit; color:#000; }
#title::placeholder { color:#ccc; font-weight:400; }
#author { width:100%; border:none; outline:none; font-size:16px;
  padding:4px 0 24px; background:transparent; font-family:inherit; color:#000; }
#author::placeholder { color:#ccc; }
#story { width:100%; min-height:50vh; border:none; outline:none; font-size:18px;
  line-height:1.7; padding:0 0 100px; background:transparent; font-family:inherit; color:#000; }
#story:empty::before { content:attr(data-placeholder); color:#ccc; pointer-events:none; }
#story h2 { font-size:26px; margin:28px 0 8px; font-weight:700; }
#story h3 { font-size:20px; margin:22px 0 6px; font-weight:700; }
#story blockquote { border-left:3px solid #000; margin:16px 0; padding:2px 0 2px 16px; }
#story pre { background:#f4f4f4; padding:12px; border-radius:4px; overflow-x:auto;
  font-family:ui-monospace,Menlo,Consolas,monospace; font-size:14px; margin:16px 0; }
#story hr { border:none; border-top:1px solid #ccc; margin:24px 0; }
#story img { max-width:100%; height:auto; display:block; margin:16px 0; }
#story iframe { max-width:100%; margin:16px 0; }
#floating-menu, #image-menu { position:absolute; display:none; background:#2b2b2b;
  border-radius:4px; padding:4px 3px; z-index:100; box-shadow:0 2px 8px rgba(0,0,0,0.25);
  flex-wrap:wrap; gap:1px; max-width:calc(100vw - 20px); }
#floating-menu.show, #image-menu.show { display:flex; }
#floating-menu button, #image-menu button { background:none; border:none; color:#fff;
  font-size:14px; padding:6px 8px; cursor:pointer; font-family:inherit;
  border-radius:3px; line-height:1; min-width:26px; }
#floating-menu button:hover, #image-menu button:hover { background:#444; }
#floating-menu button.active { background:#555; }
#floating-menu .sep, #image-menu .sep { display:inline-block; width:1px; height:16px;
  background:#555; margin:6px 3px; vertical-align:middle; align-self:center; }
.line-tools { position:absolute; left:-44px; top:0; display:flex; flex-direction:column;
  gap:4px; opacity:0; transition:opacity 0.15s; }
.line-tools button { width:32px; height:32px; border:none; background:transparent;
  cursor:pointer; font-size:18px; color:#999; border-radius:4px;
  display:flex; align-items:center; justify-content:center; }
.line-tools button:hover { background:#f0f0f0; color:#000; }
.editor-wrap.show-tools .line-tools { opacity:1; }
.modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.4);
  z-index:500; justify-content:center; align-items:flex-start; padding:40px 16px; overflow-y:auto; }
.modal-overlay.open { display:flex; }
.modal-box { background:#fff; max-width:720px; width:100%; border-radius:6px;
  padding:32px 28px; position:relative; }
.modal-box .close { position:absolute; top:12px; right:16px; background:none; border:none;
  font-size:24px; cursor:pointer; color:#999; line-height:1; }
.modal-box h2 { margin-top:0; font-size:26px; }
.draft-item { padding:14px 0; border-bottom:1px solid #eee; }
.draft-item .d-title { font-weight:600; font-size:16px; }
.draft-item .d-meta { font-size:13px; color:#999; margin-top:4px; display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
.draft-item .d-meta a { cursor:pointer; }
.warning-box { background:#fff8e6; padding:16px; border-radius:6px; margin:20px 0; border-left:4px solid #f0ad4e; }
.warning-box p { margin:0 0 8px; }
.warning-box p:last-child { margin-bottom:0; }
.warning-box .small { font-size:13px; color:#666; }
.btn-primary { background:#2481cc; color:#fff; border:none; border-radius:6px;
  padding:10px 18px; font-size:15px; font-weight:600; cursor:pointer; font-family:inherit; }
.btn-primary:hover { background:#1a6aa8; }
.btn-secondary { background:#eee; color:#333; border:none; border-radius:6px;
  padding:10px 18px; font-size:15px; cursor:pointer; font-family:inherit; }
.btn-secondary:hover { background:#ddd; }
.edit-link-input { width:100%; padding:10px; font-size:13px;
  font-family:ui-monospace,Menlo,monospace; border:1px solid #ccc; border-radius:4px;
  box-sizing:border-box; background:#fafafa; }
@media (max-width:600px) {
  html, body { font-size:17px; }
  .top-bar { padding:10px 12px; font-size:13px; gap:6px; }
  .top-bar .logo { font-size:13px; }
  .top-bar .actions { gap:7px; }
  .top-bar .actions button { font-size:11px; letter-spacing:0.2px; }
  #btn-logout { display:none; }
  .editor-wrap { padding:0 14px 80px; }
  #title { font-size:26px; }
  #story { min-height:45vh; }
  .line-tools { left:auto; right:-36px; flex-direction:row; top:-4px; }
  .line-tools button { width:28px; height:28px; font-size:16px; }
  #floating-menu button, #image-menu button { font-size:13px; padding:6px 6px; min-width:24px; }
  .modal-box { padding:24px 20px; }
}
@supports (padding: env(safe-area-inset-bottom)) {
  .editor-wrap { padding-bottom: calc(80px + env(safe-area-inset-bottom)); }
}
</style>
</head>
<body>
<div class="top-bar">
  <span class="logo">Telegraph</span>
  <div class="actions">
    <button id="btn-new">NEW</button>
    <button id="btn-preview">PREVIEW</button>
    <button id="btn-pages">PAGES</button>
    <button id="btn-publish">PUBLISH</button>
    <button id="btn-logout">LOGOUT</button>
  </div>
</div>
<div class="editor-wrap" id="editor-wrap">
  <input id="title" type="text" placeholder="Title" autocomplete="off" spellcheck="false">
  <input id="author" type="text" placeholder="Your name" autocomplete="off">
  <div id="story" contenteditable="true" data-placeholder="Your story..."></div>
  <div class="line-tools" id="line-tools">
    <button id="btn-image" title="Carica immagine">📷</button>
    <button id="btn-embed" title="Embed video/social">&lt;/&gt;</button>
  </div>
</div>
<div id="floating-menu">
  <button data-cmd="bold" title="Grassetto"><b>B</b></button>
  <button data-cmd="italic" title="Corsivo"><i>i</i></button>
  <button data-cmd="underline" title="Sottolineato"><u>U</u></button>
  <button data-cmd="strikeThrough" title="Barrato"><s>S</s></button>
  <span class="sep"></span>
  <button data-cmd="h2" title="Titolo grande">T</button>
  <button data-cmd="h3" title="Sottotitolo">t</button>
  <span class="sep"></span>
  <button data-cmd="justifyLeft" title="Allinea a sinistra">⇤</button>
  <button data-cmd="justifyCenter" title="Centra">↔</button>
  <button data-cmd="justifyRight" title="Allinea a destra">⇥</button>
  <button data-cmd="justifyFull" title="Giustifica">☰</button>
  <span class="sep"></span>
  <button data-cmd="insertUnorderedList" title="Elenco puntato">•</button>
  <button data-cmd="insertOrderedList" title="Elenco numerato">1.</button>
  <span class="sep"></span>
  <button data-cmd="blockquote" title="Citazione">&ldquo;</button>
  <button data-cmd="codeblock" title="Blocco codice">&lt;/&gt;</button>
  <button data-cmd="hr" title="Riga orizzontale">—</button>
  <span class="sep"></span>
  <button data-cmd="link" title="Link">🔗</button>
</div>
<div id="image-menu">
  <button data-img="left" title="Allinea a sinistra">⇤</button>
  <button data-img="center" title="Centra">↔</button>
  <button data-img="right" title="Allinea a destra">⇥</button>
  <span class="sep"></span>
  <button data-img="small" title="Piccola">S</button>
  <button data-img="medium" title="Media">M</button>
  <button data-img="large" title="Grande">L</button>
  <button data-img="full" title="A tutta larghezza">⇔</button>
  <span class="sep"></span>
  <button data-img="delete" title="Elimina immagine">🗑</button>
</div>
<div class="modal-overlay" id="preview-modal">
  <div class="modal-box">
    <button class="close" data-close="preview-modal">&times;</button>
    <h2 id="preview-title"></h2>
    <p id="preview-author" style="color:#999;font-size:15px;margin-top:-8px;"></p>
    <div id="preview-body"></div>
  </div>
</div>
<div class="modal-overlay" id="pages-modal">
  <div class="modal-box">
    <button class="close" data-close="pages-modal">&times;</button>
    <h2>Le mie pagine</h2>
    <div id="pages-list"></div>
  </div>
</div>
<div class="modal-overlay" id="published-modal">
  <div class="modal-box">
    <button class="close" data-close="published-modal">&times;</button>
    <h2>✅ Pagina pubblicata!</h2>
    <p>Il tuo articolo è online:</p>
    <p style="font-size:15px;"><a id="pub-link" target="_blank" rel="noopener"></a></p>
    <div class="warning-box">
      <p><b>⚠️ Salva il link di modifica</b></p>
      <p class="small">Solo chi ha questo link può modificare la pagina. Se lo perdi o cancelli i dati del browser, non potrai più modificarla.</p>
      <input id="pub-edit-link" class="edit-link-input" readonly onclick="this.select()">
    </div>
    <div style="display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap;">
      <button id="pub-copy" class="btn-secondary">Copia link modifica</button>
      <button id="pub-go" class="btn-primary">Vai alla pagina</button>
    </div>
  </div>
</div>
<script>
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
const DRAFT_KEY = 'tg_draft';
const MYPAGES_KEY = 'tg_mypages';
const state = {
  currentSlug: null,
  editToken: null,
  autosaveTimer: null,
  selectedImg: null,
};
const titleEl = document.getElementById('title');
const authorEl = document.getElementById('author');
const storyEl = document.getElementById('story');
const editorWrap = document.getElementById('editor-wrap');
const lineTools = document.getElementById('line-tools');
const floatingMenu = document.getElementById('floating-menu');
const imageMenu = document.getElementById('image-menu');

document.addEventListener('selectionchange', () => {
  const sel = window.getSelection();
  if (sel.rangeCount === 0 || sel.isCollapsed || !storyEl.contains(sel.anchorNode)) {
    floatingMenu.classList.remove('show');
    return;
  }
  const range = sel.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  const wrapRect = editorWrap.getBoundingClientRect();
  floatingMenu.classList.add('show');
  let left = rect.left - wrapRect.left + rect.width/2 - floatingMenu.offsetWidth/2;
  let top = rect.top - wrapRect.top - floatingMenu.offsetHeight - 8;
  if (top < 0) top = rect.bottom - wrapRect.top + 8;
  floatingMenu.style.left = Math.max(0, Math.min(left, wrapRect.width - floatingMenu.offsetWidth)) + 'px';
  floatingMenu.style.top = top + 'px';
  ['bold','italic','underline','strikeThrough',
   'justifyLeft','justifyCenter','justifyRight','justifyFull',
   'insertUnorderedList','insertOrderedList'].forEach(cmd => {
    const b = floatingMenu.querySelector('[data-cmd="'+cmd+'"]');
    if (!b) return;
    if (document.queryCommandState(cmd)) b.classList.add('active');
    else b.classList.remove('active');
  });
});

floatingMenu.addEventListener('mousedown', (e) => {
  e.preventDefault();
  const btn = e.target.closest('button');
  if (!btn) return;
  const cmd = btn.dataset.cmd;
  if (cmd === 'link') {
    const url = prompt('URL del link:');
    if (url) document.execCommand('createLink', false, url);
  } else if (cmd === 'h2' || cmd === 'h3') {
    document.execCommand('formatBlock', false, cmd);
  } else if (cmd === 'blockquote') {
    const cur = document.queryCommandValue('formatBlock');
    document.execCommand('formatBlock', false, cur === 'blockquote' ? 'p' : 'blockquote');
  } else if (cmd === 'codeblock') {
    const cur = document.queryCommandValue('formatBlock');
    document.execCommand('formatBlock', false, cur === 'pre' ? 'p' : 'pre');
  } else if (cmd === 'hr') {
    document.execCommand('insertHorizontalRule', false, null);
  } else {
    document.execCommand(cmd, false, null);
  }
  floatingMenu.classList.remove('show');
  scheduleSaveDraft();
});

storyEl.addEventListener('focus', () => editorWrap.classList.add('show-tools'));
storyEl.addEventListener('blur', () => setTimeout(() => {
  if (!lineTools.matches(':hover')) editorWrap.classList.remove('show-tools');
}, 200));
function positionLineTools() {
  const sel = window.getSelection();
  if (!sel.rangeCount) return;
  const r = sel.getRangeAt(0).cloneRange();
  r.collapse(true);
  const rects = r.getClientRects();
  if (!rects.length) return;
  const wrapRect = editorWrap.getBoundingClientRect();
  lineTools.style.top = (rects[0].top - wrapRect.top) + 'px';
}
storyEl.addEventListener('keyup', positionLineTools);
storyEl.addEventListener('click', positionLineTools);

document.getElementById('btn-image').addEventListener('mousedown', (e) => {
  e.preventDefault();
  const input = document.createElement('input');
  input.type = 'file'; input.accept = 'image/*';
  input.onchange = () => {
    const file = input.files[0];
    if (!file) return;
    if (file.size > 5*1024*1024) { alert('Immagine oltre 5 MB.'); return; }
    const reader = new FileReader();
    reader.onload = (ev) => {
      insertAtCursor('<img src="'+ev.target.result+'" style="display:block;margin:16px auto;width:100%;">');
      scheduleSaveDraft();
    };
    reader.readAsDataURL(file);
  };
  input.click();
});

storyEl.addEventListener('click', (e) => {
  if (e.target.tagName === 'IMG') {
    state.selectedImg = e.target;
    showImageMenu(e.target);
  } else {
    hideImageMenu();
  }
});
function showImageMenu(img) {
  const imgRect = img.getBoundingClientRect();
  const wrapRect = editorWrap.getBoundingClientRect();
  imageMenu.classList.add('show');
  let left = imgRect.left - wrapRect.left;
  let top = imgRect.top - wrapRect.top - imageMenu.offsetHeight - 4;
  if (top < 0) top = imgRect.bottom - wrapRect.top + 4;
  imageMenu.style.left = Math.max(0, Math.min(left, wrapRect.width - imageMenu.offsetWidth)) + 'px';
  imageMenu.style.top = Math.max(0, top) + 'px';
}
function hideImageMenu() {
  imageMenu.classList.remove('show');
  state.selectedImg = null;
}
imageMenu.addEventListener('mousedown', (e) => {
  e.preventDefault();
  e.stopPropagation();
  const btn = e.target.closest('button');
  if (!btn || !state.selectedImg) return;
  const action = btn.dataset.img;
  const img = state.selectedImg;
  if (action === 'delete') {
    img.remove();
  } else if (action === 'left' || action === 'center' || action === 'right') {
    img.style.display = 'block';
    if (action === 'left')   img.style.margin = '16px auto 16px 0';
    if (action === 'center') img.style.margin = '16px auto';
    if (action === 'right')  img.style.margin = '16px 0 16px auto';
  } else if (action === 'small')  { img.style.width = '30%'; img.style.maxWidth = '30%'; img.style.height = 'auto'; }
  else if (action === 'medium')   { img.style.width = '60%'; img.style.maxWidth = '60%'; img.style.height = 'auto'; }
  else if (action === 'large')    { img.style.width = '85%'; img.style.maxWidth = '85%'; img.style.height = 'auto'; }
  else if (action === 'full')     { img.style.width = '100%'; img.style.maxWidth = '100%'; img.style.height = 'auto'; }
  hideImageMenu();
  scheduleSaveDraft();
});

document.getElementById('btn-embed').addEventListener('mousedown', (e) => {
  e.preventDefault();
  const url = prompt('Link YouTube / Vimeo / Twitter:');
  if (!url) return;
  let html = '';
  if (/youtube\.com|youtu\.be/.test(url)) {
    const m = url.match(/(?:v=|youtu\.be\/)([^&?/]+)/);
    if (m) html = '<iframe width="100%" height="315" src="https://www.youtube.com/embed/'+m[1]+'" frameborder="0" allowfullscreen></iframe>';
  } else if (/vimeo\.com/.test(url)) {
    const m = url.match(/vimeo\.com\/(\d+)/);
    if (m) html = '<iframe width="100%" height="315" src="https://player.vimeo.com/video/'+m[1]+'" frameborder="0" allowfullscreen></iframe>';
  } else if (/twitter\.com|x\.com/.test(url)) {
    html = '<blockquote class="twitter-tweet"><a href="'+url+'"></a></blockquote>';
    if (!window.twttr) {
      const s = document.createElement('script');
      s.src = 'https://platform.twitter.com/widgets.js';
      document.head.appendChild(s);
    }
  } else {
    html = '<p><a href="'+url+'" target="_blank">'+url+'</a></p>';
  }
  insertAtCursor(html);
  scheduleSaveDraft();
});

function insertAtCursor(html) {
  storyEl.focus();
  const sel = window.getSelection();
  if (sel.rangeCount && storyEl.contains(sel.anchorNode)) {
    const range = sel.getRangeAt(0);
    range.deleteContents();
    const div = document.createElement('div');
    div.innerHTML = html;
    const frag = document.createDocumentFragment();
    let node, last;
    while ((node = div.firstChild)) last = frag.appendChild(node);
    range.insertNode(frag);
    if (last) {
      range.setStartAfter(last); range.collapse(true);
      sel.removeAllRanges(); sel.addRange(range);
    }
  } else {
    storyEl.innerHTML += html;
  }
}

function scheduleSaveDraft() {
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = setTimeout(saveDraft, 800);
}
function saveDraft() {
  const d = {
    title: titleEl.value.trim(),
    author: authorEl.value.trim(),
    content: storyEl.innerHTML,
    updated: Date.now(),
  };
  if (!d.title && !d.author && !d.content.trim()) {
    localStorage.removeItem(DRAFT_KEY);
    return;
  }
  localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
}
function clearDraft() { localStorage.removeItem(DRAFT_KEY); }
function restoreDraft() {
  const raw = localStorage.getItem(DRAFT_KEY);
  if (!raw) return;
  try {
    const d = JSON.parse(raw);
    if (d.title) titleEl.value = d.title;
    if (d.author) authorEl.value = d.author;
    if (d.content) storyEl.innerHTML = d.content;
  } catch (e) {}
}
[titleEl, authorEl, storyEl].forEach(el => el.addEventListener('input', scheduleSaveDraft));

function getMyPages() {
  try { return JSON.parse(localStorage.getItem(MYPAGES_KEY) || '[]'); }
  catch (e) { return []; }
}
function setMyPages(arr) { localStorage.setItem(MYPAGES_KEY, JSON.stringify(arr.slice(0, 200))); }
function saveMyPage(entry) {
  const pages = getMyPages().filter(p => p.slug !== entry.slug);
  pages.unshift(entry);
  setMyPages(pages);
}
function updateMyPageTitle(slug, title) {
  const pages = getMyPages();
  const p = pages.find(x => x.slug === slug);
  if (p) { p.title = title; setMyPages(pages); }
}

document.getElementById('btn-new').addEventListener('click', () => {
  const hasContent = titleEl.value.trim() || authorEl.value.trim() || storyEl.innerHTML.trim();
  if (hasContent && !confirm('Iniziare una nuova pagina? La bozza in corso verrà scartata.')) return;
  clearDraft();
  titleEl.value = '';
  authorEl.value = '';
  storyEl.innerHTML = '';
  state.currentSlug = null;
  state.editToken = null;
  const btn = document.getElementById('btn-publish');
  btn.textContent = 'PUBLISH';
  btn.disabled = false;
  window.history.replaceState({}, '', '/');
  window.scrollTo(0, 0);
  titleEl.focus();
});

document.getElementById('btn-pages').addEventListener('click', () => {
  renderMyPages();
  document.getElementById('pages-modal').classList.add('open');
});

function renderMyPages() {
  const list = document.getElementById('pages-list');
  const pages = getMyPages();
  if (!pages.length) {
    list.innerHTML = '<p style="color:#999;">Nessuna pagina pubblicata. Premi PUBLISH per crearne una.</p>';
    return;
  }
  list.innerHTML = pages.map(p => {
    const date = new Date(p.date).toLocaleDateString('it-IT');
    const token = localStorage.getItem('tg_token_' + p.slug);
    const actions = [];
    actions.push('<a href="/'+encodeURIComponent(p.slug)+'" target="_blank">Apri</a>');
    if (token) {
      actions.push('<a data-edit="'+escapeAttr(p.slug)+'">Modifica</a>');
      actions.push('<a data-copy="'+escapeAttr(p.slug)+'">Copia link modifica</a>');
    } else {
      actions.push('<span style="color:#bbb;">(senza token di modifica)</span>');
    }
    return '<div class="draft-item">' +
      '<div class="d-title">'+escapeHtml(p.title || 'Senza titolo')+'</div>' +
      '<div class="d-meta">'+date+' · '+actions.join(' · ')+'</div>' +
      '</div>';
  }).join('');
  list.querySelectorAll('[data-edit]').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const slug = a.dataset.edit;
      const token = localStorage.getItem('tg_token_' + slug);
      window.location.href = '/edit/' + encodeURIComponent(slug) + '?token=' + encodeURIComponent(token);
    });
  });
  list.querySelectorAll('[data-copy]').forEach(a => {
    a.addEventListener('click', async (e) => {
      e.preventDefault();
      const slug = a.dataset.copy;
      const token = localStorage.getItem('tg_token_' + slug);
      const url = location.origin + '/edit/' + encodeURIComponent(slug) + '?token=' + encodeURIComponent(token);
      try { await navigator.clipboard.writeText(url); alert('Link di modifica copiato negli appunti.'); }
      catch (err) { prompt('Copia questo link:', url); }
    });
  });
}

document.getElementById('btn-publish').addEventListener('click', async () => {
  const title = titleEl.value.trim();
  const author = authorEl.value.trim();
  const content = storyEl.innerHTML.trim();
  if (!title) { alert('Inserisci un titolo.'); titleEl.focus(); return; }
  if (!content || content === '<br>') { alert('Scrivi qualcosa.'); storyEl.focus(); return; }
  const btn = document.getElementById('btn-publish');
  const isEdit = !!state.currentSlug && !!state.editToken;
  btn.disabled = true;
  btn.textContent = isEdit ? 'UPDATING...' : 'PUBLISHING...';
  try {
    if (isEdit) {
      const res = await fetch('/api/page/' + encodeURIComponent(state.currentSlug), {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: state.editToken, title, author, content}),
      });
      if (!res.ok) throw new Error('Aggiornamento fallito');
      const updated = await res.json();
      const newSlug = updated.slug || state.currentSlug;
      if (newSlug !== state.currentSlug) {
        localStorage.setItem('tg_token_' + newSlug, state.editToken);
        localStorage.removeItem('tg_token_' + state.currentSlug);
        const pages = getMyPages().map(p => p.slug === state.currentSlug
          ? Object.assign({}, p, { slug: newSlug, title: title }) : p);
        setMyPages(pages);
        state.currentSlug = newSlug;
      } else {
        updateMyPageTitle(state.currentSlug, title);
      }
      window.location.href = '/' + encodeURIComponent(newSlug);
    } else {
      const res = await fetch('/publish', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, author, content}),
      });
      if (!res.ok) throw new Error('Pubblicazione fallita');
      const data = await res.json();
      localStorage.setItem('tg_token_' + data.slug, data.edit_token);
      saveMyPage({ slug: data.slug, title: title, date: new Date().toISOString() });
      clearDraft();
      state.currentSlug = data.slug;
      state.editToken = data.edit_token;
      const publicUrl = location.origin + '/' + encodeURIComponent(data.slug);
      const editUrl = location.origin + '/edit/' + encodeURIComponent(data.slug) + '?token=' + encodeURIComponent(data.edit_token);
      document.getElementById('pub-link').href = publicUrl;
      document.getElementById('pub-link').textContent = publicUrl;
      document.getElementById('pub-edit-link').value = editUrl;
      document.getElementById('published-modal').classList.add('open');
      btn.disabled = false;
      btn.textContent = 'PUBLISH';
    }
  } catch (err) {
    alert('Errore: ' + err.message);
    btn.disabled = false;
    btn.textContent = isEdit ? 'UPDATE' : 'PUBLISH';
  }
});

document.getElementById('pub-copy').addEventListener('click', async () => {
  const url = document.getElementById('pub-edit-link').value;
  try { await navigator.clipboard.writeText(url); alert('Link copiato.'); }
  catch (err) { document.getElementById('pub-edit-link').select(); document.execCommand('copy'); alert('Link copiato.'); }
});
document.getElementById('pub-go').addEventListener('click', () => {
  window.location.href = document.getElementById('pub-link').href;
});

document.getElementById('btn-preview').addEventListener('click', () => {
  document.getElementById('preview-title').textContent = titleEl.value || 'Senza titolo';
  document.getElementById('preview-author').textContent = authorEl.value || '';
  document.getElementById('preview-body').innerHTML = storyEl.innerHTML || '<p style="color:#ccc;">Nessun contenuto.</p>';
  document.getElementById('preview-modal').classList.add('open');
});

document.getElementById('btn-logout').addEventListener('click', () => {
  if (!confirm('Vuoi disconnetterti da questo dispositivo? Le pagine pubblicate restano online ma, senza il link di modifica, non potrai più modificarle da qui.')) return;
  Object.keys(localStorage).forEach(k => { if (k.startsWith('tg_token_')) localStorage.removeItem(k); });
  state.currentSlug = null; state.editToken = null;
  alert('Disconnesso.');
});

document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => {
  document.getElementById(b.dataset.close).classList.remove('open');
}));
document.querySelectorAll('.modal-overlay').forEach(o => o.addEventListener('click', (e) => {
  if (e.target === o) o.classList.remove('open');
}));
document.addEventListener('click', (e) => {
  if (!e.target.closest('#image-menu') && e.target.tagName !== 'IMG') hideImageMenu();
});
function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escapeAttr(s) {
  return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
}

(function init() {
  const m = window.location.pathname.match(/^\/edit\/(.+)$/);
  if (m) {
    const slug = decodeURIComponent(m[1]);
    const token = new URLSearchParams(window.location.search).get('token') || '';
    fetch('/api/page/' + encodeURIComponent(slug) + '?token=' + encodeURIComponent(token))
      .then(res => { if (!res.ok) throw new Error('Token non valido'); return res.json(); })
      .then(data => {
        titleEl.value = data.title;
        authorEl.value = data.author;
        storyEl.innerHTML = data.content;
        state.currentSlug = slug;
        state.editToken = token;
        document.getElementById('btn-publish').textContent = 'UPDATE';
      })
      .catch(err => { alert('Errore: ' + err.message); window.location.href = '/'; });
  } else {
    restoreDraft();
  }
})();
</script>
</body>
</html>
"""

# ============================================================
# TEMPLATE PAGINA PUBBLICATA
# ============================================================
PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#2481cc">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>__TITLE__ — Telegraph</title>
<style>
* { box-sizing:border-box; }
body { margin:0; padding:0; background:#fff; color:#000;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:18px; line-height:1.7; }
.wrap { max-width:720px; margin:0 auto; padding:48px 20px 120px; }
h1 { font-size:32px; line-height:1.3; margin:0 0 4px; font-weight:700; }
.meta { color:#999; font-size:15px; margin-bottom:32px; }
.content h2 { font-size:26px; margin:28px 0 8px; }
.content h3 { font-size:20px; margin:22px 0 6px; }
.content blockquote { border-left:3px solid #000; margin:16px 0; padding:2px 0 2px 16px; }
.content pre { background:#f4f4f4; padding:12px; border-radius:4px; overflow-x:auto;
  font-family:ui-monospace,Menlo,Consolas,monospace; font-size:14px; }
.content hr { border:none; border-top:1px solid #ccc; margin:24px 0; }
.content img { max-width:100%; height:auto; }
.content iframe { max-width:100%; }
.edit-bar { margin-top:64px; text-align:right; }
.edit-bar button { background:none; border:none; color:#2481cc; font-size:15px;
  cursor:pointer; font-family:inherit; text-transform:uppercase; letter-spacing:0.5px; }
.edit-bar button:hover { text-decoration:underline; }
@media (max-width:600px) {
  body { font-size:17px; }
  .wrap { padding:32px 14px 100px; }
  h1 { font-size:26px; }
}
</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <div class="meta">__AUTHOR____DATE__</div>
  <div class="content">__CONTENT__</div>
  <div class="edit-bar"><button id="edit-btn" style="display:none;">Edit</button></div>
</div>
<script>
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
const slug = "__SLUG_JS__";
const token = localStorage.getItem('tg_token_' + slug);
if (token) {
  const b = document.getElementById('edit-btn');
  b.style.display = 'inline';
  b.addEventListener('click', () => {
    window.location.href = '/edit/' + encodeURIComponent(slug) + '?token=' + encodeURIComponent(token);
  });
}
</script>
</body>
</html>
"""

# ============================================================
# HANDLER HTTP
# ============================================================
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status, content, ctype='text/html; charset=utf-8'):
        if isinstance(content, str): content = content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj), 'application/json')

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if not length: return {}
        try: return json.loads(self.rfile.read(length))
        except Exception: return {}

    def _error_page(self, code, title, message):
        html = f'''<!DOCTYPE html><html><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{code} — {title}</title>
        <style>body{{font-family:-apple-system,sans-serif;max-width:600px;margin:60px auto;padding:0 20px;color:#333}}
        h1{{font-size:28px;margin-bottom:12px}}a{{color:#2481cc}}</style></head>
        <body><h1>{code} — {title}</h1><p>{message}</p>
        <p><a href="/">← Torna alla home</a></p></body></html>'''
        return self._send(code, html)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == '/manifest.json': return self._send(200, MANIFEST_JSON, 'application/manifest+json')
        if path == '/sw.js':          return self._send(200, SERVICE_WORKER_JS, 'application/javascript')
        if path == '/icon-192.png':   return self._send(200, ICON_192, 'image/png')
        if path == '/icon-512.png':   return self._send(200, ICON_512, 'image/png')
        if path == '/':               return self._send(200, INDEX_HTML)

        m = re.match(r'^/edit/([^/]+)$', path)
        if m:
            slug = m.group(1)
            token = query.get('token', [''])[0]
            page = get_db().execute('SELECT * FROM pages WHERE slug=?', (slug,)).fetchone()
            if not page:
                return self._error_page(404, 'Pagina non trovata',
                    'Questa pagina non esiste. Controlla il link.')
            if token != page['edit_token']:
                return self._error_page(403, "Solo l'autore può modificare",
                    "Questa pagina è protetta. Solo chi l'ha creata, usando il suo link di modifica, "
                    "può modificarla. Se sei l'autore, riapri il link di modifica che ti è stato "
                    "mostrato alla pubblicazione.")
            return self._send(200, INDEX_HTML)

        m = re.match(r'^/api/page/([^/]+)$', path)
        if m:
            slug = m.group(1)
            token = query.get('token', [''])[0]
            page = get_db().execute('SELECT * FROM pages WHERE slug=?', (slug,)).fetchone()
            if not page: return self._json(404, {'error': 'not found'})
            if token != page['edit_token']: return self._json(403, {'error': 'invalid token'})
            return self._json(200, {
                'slug': page['slug'], 'title': page['title'],
                'author': page['author'], 'content': page['content'],
                'edit_token': page['edit_token'],
            })

        m = re.match(r'^/([^/]+)$', path)
        if m:
            slug = m.group(1)
            redirect = get_db().execute('SELECT new_slug FROM slug_redirects WHERE old_slug=?', (slug,)).fetchone()
            if redirect:
                self.send_response(301)
                self.send_header('Location', '/' + quote(redirect['new_slug']))
                self.end_headers()
                return
            page = get_db().execute('SELECT * FROM pages WHERE slug=?', (slug,)).fetchone()
            if page:
                author_str = ''
                if page['author']:
                    author_str = page['author'].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;') + ' — '
                slug_js = page['slug'].replace('\\','\\\\').replace('"','\\"')
                html = (PAGE_HTML
                        .replace('__TITLE__', page['title'].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'))
                        .replace('__AUTHOR__', author_str)
                        .replace('__DATE__', page['created_at'][:10])
                        .replace('__CONTENT__', page['content'])
                        .replace('__SLUG_JS__', slug_js))
                return self._send(200, html)
            return self._error_page(404, 'Pagina non trovata',
                'Questo articolo non esiste o è stato rimosso.')

        return self._error_page(404, 'Pagina non trovata', 'URL non riconosciuto.')

    def do_POST(self):
        if self.path == '/publish':
            data = self._read_json()
            title = (data.get('title') or '').strip()
            author = (data.get('author') or '').strip()
            content = data.get('content') or ''
            if not title: return self._json(400, {'error': 'Titolo obbligatorio'})
            if not content.strip() or content.strip() == '<br>':
                return self._json(400, {'error': 'Contenuto obbligatorio'})
            base = make_slug(title)
            with get_db() as db:
                slug = unique_slug(db, base)
                edit_token = uuid.uuid4().hex
                db.execute('INSERT INTO pages (slug,title,author,content,edit_token) VALUES (?,?,?,?,?)',
                           (slug, title, author, content, edit_token))
                db.commit()
            print(f'[PUBLISH] titolo="{title}" -> slug="{slug}"')
            return self._json(200, {'slug': slug, 'edit_token': edit_token})
        return self._json(404, {'error': 'not found'})

    def do_PUT(self):
        m = re.match(r'^/api/page/([^/]+)$', self.path)
        if not m: return self._json(404, {'error': 'not found'})
        slug = m.group(1)
        data = self._read_json()
        token = data.get('token', '')
        page = get_db().execute('SELECT * FROM pages WHERE slug=?', (slug,)).fetchone()
        if not page: return self._json(404, {'error': 'not found'})
        if token != page['edit_token']: return self._json(403, {'error': 'invalid token'})
        title = (data.get('title') or page['title']).strip()
        author = data.get('author') if data.get('author') is not None else page['author']
        content = data.get('content') or page['content']
        new_slug = slug
        with get_db() as db:
            if title != page['title']:
                base = make_slug(title)
                candidate = unique_slug(db, base, exclude_slug=slug)
                if candidate != slug:
                    db.execute('INSERT OR REPLACE INTO slug_redirects (old_slug,new_slug) VALUES (?,?)',
                               (slug, candidate))
                    new_slug = candidate
                    print(f'[RENAME] "{slug}" -> "{new_slug}"')
            db.execute('UPDATE pages SET slug=?,title=?,author=?,content=?,updated_at=datetime("now") WHERE slug=?',
                       (new_slug, title, author, content, slug))
            db.commit()
        return self._json(200, {'ok': True, 'slug': new_slug})

# ============================================================
# AVVIO
# ============================================================
if __name__ == '__main__':
    init_db()
    print('=' * 60)
    print('  Telegraph Clone v4')
    print('=' * 60)
    print(f'  Locale:  http://localhost:{PORT}')
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        lan_ip = s.getsockname()[0]
        s.close()
        print(f'  Mobile:  http://{lan_ip}:{PORT}  (stessa Wi-Fi)')
    except Exception:
        pass
    print('  Ctrl+C per fermare')
    print('=' * 60)
    try:
        server = socketserver.ThreadingTCPServer(('0.0.0.0', PORT), Handler)
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer fermato.')
    except OSError as e:
        print(f'\nErrore: {e}')
        print(f'La porta {PORT} è occupata. Prova: PORT=5001 python telegraph.py')