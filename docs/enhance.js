/* repo → HTML 教材 — 頁面強化腳本
   （Python/C/GAS/shell 語法上色、data-hot 行強調、«N» 標注、本章目錄） */
(function () {
  'use strict';

  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ---------- C 語法上色 ---------- */
  var KW = new Set(('if else for while do return switch case default break continue goto sizeof ' +
    'typedef struct union enum static const extern inline register volatile ' +
    'unsigned signed NULL true false').split(' '));
  var TYPE = new Set(('void int char long short float double bool ' +
    'uint8_t uint16_t uint32_t uint64_t int8_t int16_t int32_t int64_t ' +
    'size_t ssize_t loff_t sector_t dev_t mode_t umode_t pgoff_t gfp_t ' +
    'u8 u16 u32 u64 s8 s16 s32 s64 journal_t handle_t tid_t').split(' '));

  var C_RE = new RegExp(
    '(\\/\\*[\\s\\S]*?\\*\\/|\\/\\/[^\\n]*)' +            // 1 comment
    '|("(?:[^"\\\\\\n]|\\\\.)*"|\'(?:[^\'\\\\\\n]|\\\\.)*\')' + // 2 string/char
    '|(^[ \\t]*#[ \\t]*\\w+(?:[ \\t]+[<"][^>"\\n]*[>"])?)' +   // 3 preprocessor
    '|\\b([A-Za-z_]\\w*)(?=\\s*\\()' +                     // 4 function call
    '|\\b(0[xX][0-9a-fA-F]+[uUlL]*|\\d+[uUlL]*)\\b' +      // 5 number
    '|\\b([A-Za-z_]\\w*)\\b',                              // 6 identifier
    'gm');

  function highlightC(text) {
    var out = '', last = 0, m;
    C_RE.lastIndex = 0;
    while ((m = C_RE.exec(text)) !== null) {
      out += esc(text.slice(last, m.index));
      last = C_RE.lastIndex;
      if (m[1]) out += '<span class="tok-cmt">' + esc(m[1]) + '</span>';
      else if (m[2]) out += '<span class="tok-str">' + esc(m[2]) + '</span>';
      else if (m[3]) out += '<span class="tok-pre">' + esc(m[3]) + '</span>';
      else if (m[4]) {
        if (KW.has(m[4])) out += '<span class="tok-kw">' + esc(m[4]) + '</span>';
        else if (TYPE.has(m[4])) out += '<span class="tok-type">' + esc(m[4]) + '</span>';
        else out += '<span class="tok-fn">' + esc(m[4]) + '</span>';
      } else if (m[5]) out += '<span class="tok-num">' + esc(m[5]) + '</span>';
      else if (m[6]) {
        if (KW.has(m[6])) out += '<span class="tok-kw">' + esc(m[6]) + '</span>';
        else if (TYPE.has(m[6])) out += '<span class="tok-type">' + esc(m[6]) + '</span>';
        else out += esc(m[6]);
      }
    }
    out += esc(text.slice(last));
    return out;
  }

  /* ---------- GAS 組語上色（pre.asm；AT&T 語法，.S/.s 檔案用） ---------- */
  var ASM_RE = new RegExp(
    '(\\/\\*[\\s\\S]*?\\*\\/)' +                       // 1 區塊註解（可跨行）
    '|(^[ \\t]*#[ \\t]*\\w+[^\\n]*)' +                 // 2 cpp 行（#include 等）
    '|(^[ \\t]*\\.[a-z_]\\w*)' +                       // 3 指示詞（.macro/.global…）
    '|(^[ \\t]*[A-Za-z_.\\\\][\\w\\\\]*:)' +           // 4 標籤（含巨集的 \\label:）
    '|(%[a-z][a-z0-9]{1,4}\\b)' +                      // 5 暫存器
    '|(\\$?0[xX][0-9a-fA-F]+\\b|\\$\\d+\\b|\\b\\d+\\b)', // 6 立即數/數字
    'gm');

  function highlightAsm(text) {
    var out = '', last = 0, m;
    ASM_RE.lastIndex = 0;
    while ((m = ASM_RE.exec(text)) !== null) {
      out += esc(text.slice(last, m.index));
      last = ASM_RE.lastIndex;
      if (m[1]) out += '<span class="tok-cmt">' + esc(m[1]) + '</span>';
      else if (m[2]) out += '<span class="tok-pre">' + esc(m[2]) + '</span>';
      else if (m[3]) out += '<span class="tok-kw">' + esc(m[3]) + '</span>';
      else if (m[4]) out += '<span class="tok-fn">' + esc(m[4]) + '</span>';
      else if (m[5]) out += '<span class="tok-type">' + esc(m[5]) + '</span>';
      else if (m[6]) out += '<span class="tok-num">' + esc(m[6]) + '</span>';
    }
    out += esc(text.slice(last));
    return out;
  }

  /* ---------- Python 上色（pre.py） ---------- */
  var PY_KW = new Set(('False None True and as assert break class continue def del elif else ' +
    'except finally for from global if import in is lambda nonlocal not or pass raise ' +
    'return try while with yield self super').split(' '));
  var PY_BUILTIN = new Set(('print len range list sum enumerate open int float str dict ' +
    'set tuple isinstance zip map').split(' '));

  var PY_RE = new RegExp(
    '(#[^\\n]*)' +                                                     // 1 comment
    '|((?:[rRbBfF]{1,2})?(?:"""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'' +
      '|"(?:[^"\\\\\\n]|\\\\.)*"|\'(?:[^\'\\\\\\n]|\\\\.)*\'))' +      // 2 string
    '|(@[A-Za-z_][\\w.]*)' +                                           // 3 decorator
    '|\\b([A-Za-z_]\\w*)(?=\\s*\\()' +                                 // 4 call
    '|\\b(\\d+\\.?\\d*(?:[eE][-+]?\\d+)?)\\b' +                        // 5 number
    '|\\b([A-Za-z_]\\w*)\\b',                                          // 6 identifier
    'g');

  function highlightPy(text) {
    var out = '', last = 0, m;
    PY_RE.lastIndex = 0;
    while ((m = PY_RE.exec(text)) !== null) {
      out += esc(text.slice(last, m.index));
      last = PY_RE.lastIndex;
      if (m[1]) out += '<span class="tok-cmt">' + esc(m[1]) + '</span>';
      else if (m[2]) out += '<span class="tok-str">' + esc(m[2]) + '</span>';
      else if (m[3]) out += '<span class="tok-pre">' + esc(m[3]) + '</span>';
      else if (m[4]) {
        if (PY_KW.has(m[4])) out += '<span class="tok-kw">' + esc(m[4]) + '</span>';
        else if (PY_BUILTIN.has(m[4])) out += '<span class="tok-type">' + esc(m[4]) + '</span>';
        else out += '<span class="tok-fn">' + esc(m[4]) + '</span>';
      } else if (m[5]) out += '<span class="tok-num">' + esc(m[5]) + '</span>';
      else if (m[6]) {
        if (PY_KW.has(m[6])) out += '<span class="tok-kw">' + esc(m[6]) + '</span>';
        else out += esc(m[6]);
      }
    }
    out += esc(text.slice(last));
    return out;
  }

  /* ---------- shell 上色 ---------- */
  function highlightShell(text) {
    return text.split('\n').map(function (line) {
      var m = line.match(/^(\s*)(\$|#)\s(.*)$/);
      if (m && m[2] === '$') {
        return esc(m[1]) + '<span class="sh-prompt">$</span> <span class="sh-cmd">' + esc(m[3]) + '</span>';
      }
      if (/^\s*#/.test(line)) {
        return '<span class="sh-cmt">' + esc(line) + '</span>';
      }
      return esc(line);
    }).join('\n');
  }

  /* ---------- data-hot 行強調 ---------- */
  function parseHotSpec(spec) {
    var set = new Set();
    spec.split(',').forEach(function (part) {
      var m = part.trim().match(/^(\d+)(?:-(\d+))?$/);
      if (!m) return;
      for (var i = +m[1]; i <= +(m[2] || m[1]); i++) set.add(i);
    });
    return set;
  }

  /* 把 data-hot 指定的行包進 .hot-line。行號 = offset + 區塊內第幾行（1 起算）；
     figure.listing 的 offset 取自 figcaption 的起始行號，所以 data-hot 寫原始碼行號。
     跨行的 span（多行註解）先在行尾補收、下一行重開，維持合法巢狀。 */
  function wrapHotLines(html, spec, offset) {
    var hot = parseHotSpec(spec);
    var carry = null;
    return html.split('\n').map(function (line, i) {
      var s = (carry || '') + line;
      var opens = s.match(/<span[^>]*>/g) || [];
      var closes = s.match(/<\/span>/g) || [];
      if (opens.length > closes.length) {
        carry = opens[opens.length - 1];
        s += '</span>';
      } else {
        carry = null;
      }
      return hot.has(i + 1 + offset) ? '<span class="hot-line">' + s + '</span>' : s;
    }).join('\n');
  }

  document.querySelectorAll('pre').forEach(function (pre) {
    /* pre.manual：作者手工上色/標注的頁面，enhance 完全不碰 */
    if (pre.classList.contains('diagram') || pre.classList.contains('manual')) return;
    var code = pre.querySelector('code');
    var target = code || pre;
    var text = target.textContent;
    if (pre.classList.contains('shell')) {
      target.innerHTML = highlightShell(text);
    } else if (pre.classList.contains('py')) {
      target.innerHTML = highlightPy(text);
    } else if (pre.classList.contains('asm')) {
      target.innerHTML = highlightAsm(text);
    } else if (/[;{}()#]|->|\breturn\b|\bstruct\b/.test(text)) {
      /* 只對看起來像 C 的內容上色（含常見符號），避免誤傷純文字 */
      target.innerHTML = highlightC(text);
    }
    /* «N» → 圓形標記：寫在 pre 的純文字裡（如實測輸出的逐行標注），
       不破壞「原始碼保持純文字」的逐字 diff 原則 */
    if (/«\d+»/.test(target.innerHTML)) {
      target.innerHTML = target.innerHTML.replace(/«(\d+)»/g, '<span class="mk">$1</span>');
    }
    if (pre.dataset.hot) {
      var offset = 0;
      var fig = pre.closest('figure.listing');
      var cap = fig && fig.querySelector('figcaption');
      var m = cap && cap.textContent.match(/:(\d+)/);
      if (m) offset = parseInt(m[1], 10) - 1;
      target.innerHTML = wrapHotLines(target.innerHTML, pre.dataset.hot, offset);
    }
  });

  /* ---------- 本章目錄（自動生成） ---------- */
  var main = document.querySelector('main');
  var header = document.querySelector('header.chap-header');
  if (main && header) {
    var hs = main.querySelectorAll('h2');
    if (hs.length >= 3) {
      var box = document.createElement('div');
      box.className = 'toc-box';
      var html = '<p class="toc-box-title">本章目錄</p><ol>';
      hs.forEach(function (h, i) {
        if (!h.id) h.id = 'sec-' + (i + 1);
        html += '<li><a href="#' + h.id + '">' + h.textContent + '</a></li>';
      });
      html += '</ol>';
      box.innerHTML = html;
      header.insertAdjacentElement('afterend', box);
    }
  }
})();
