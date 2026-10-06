#!/usr/bin/env python3
"""隨 PR 共生教材的全書驗收：死鏈 + 前後章導覽鏈（頂部與底部各一組）+ 檔案健全。

用法: python3 check_book.py <docs_dir>

章節順序以 index.html 中章節連結的**出現順序**為準（不依賴檔名編號），
所以新增一章後必須先在 index.html 加卡片，這支腳本才驗得到它。
檢查項目：
  1. 所有指向本地 *.html 的 href 都存在
  2. 依 index.html 的順序，相鄰兩章互相連結，且每個方向至少出現 2 次
     （頁面頂部與底部各有一組導覽列——只改一處是最常見的漏）
  3. 每章連回 index.html 至少 2 次；每檔以 </html> 結尾
  4. 手繪 inline SVG 圖的契約：viewBox / role / aria-label 齊全、XML 合法、
     圖內不引用外部資源、**不含 HTML-only 標籤**（<b> 之類會把 svg 打斷，
     整張圖變空白，而 XML parser 看不出來）、圖號與出現順序一致、
     marker id 不撞、字不溢出方框
發現問題以非零狀態碼結束（0 = 過、1 = 判準沒過、2 = 環境／參數有問題）。

**這支刻意不驗「教材寫的 N 條測試」** —— 那條規則在 SKILL.md，但它必須真的把
該 repo 的測試跑起來（pytest / gtest binary / 該語言的 runner），做不到通用。
每個 repo 自己接一支，然後從這裡轉呼叫；要接就別留 --skip 旗標：
量不出來一律以 2 結束，跳過之後的 0 跟真的全綠長得一模一樣。
"""
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

# 結束碼契約：0 = 過、1 = 判準沒過、2 = 環境／參數有問題。用法錯誤絕不能回 1。
ARGS = sys.argv[1:]
if len(ARGS) > 1 or any(a.startswith('-') for a in ARGS):
    print(f'用法: {sys.argv[0]} [docs_dir]', file=sys.stderr)
    sys.exit(2)

DOCS = Path(ARGS[0] if ARGS else 'docs')
if not DOCS.is_dir():
    print(f'找不到目錄: {DOCS}', file=sys.stderr)
    sys.exit(2)

files = {f.name for f in DOCS.glob('*.html')}
failed = False


def hrefs(html):
    return re.findall(r'href="([^"#]+\.html)(?:#[^"]*)?"', html)


# 1) 死鏈
bad = []
for f in sorted(DOCS.glob('*.html')):
    for href in hrefs(f.read_text(encoding='utf-8')):
        if not href.startswith('http') and href not in files:
            bad.append(f'{f.name} -> {href}')
if bad:
    failed = True
    print('壞連結:')
    for b in bad:
        print(' ', b)
else:
    print('壞連結: 無')

# 2) 章節鏈（依 index.html 出現順序推導）
chapters = []
index = DOCS / 'index.html'
if index.exists():
    seen = set()
    for href in hrefs(index.read_text(encoding='utf-8')):
        if href in files and href != 'index.html' and href not in seen:
            seen.add(href)
            chapters.append(href)
else:
    failed = True
    print('缺少 index.html，無法推導章節順序')

texts = {name: (DOCS / name).read_text(encoding='utf-8') for name in chapters}

for a, b in zip(chapters, chapters[1:]):
    for src, dst, direction in ((a, b, 'next'), (b, a, 'prev')):
        n = hrefs(texts[src]).count(dst)
        if n < 2:
            failed = True
            print(f'{src}: {direction} 連到 {dst} 只有 {n} 處（頂部與底部導覽列應各一）')
        else:
            print(f'{src}: {direction} -> {dst} OK ({n} 處)')

# 3) 回目錄連結與檔案結尾
for name in chapters:
    n = hrefs(texts[name]).count('index.html')
    if n < 2:
        failed = True
        print(f'{name}: 連回 index.html 只有 {n} 處（應 >= 2）')
    if not texts[name].rstrip().endswith('</html>'):
        failed = True
        print(f'{name}: 缺 </html> 結尾')


# 4) 手繪 inline SVG 的圖表契約
#    字寬用估的（保守：全形 1.0em、比例字 ASCII 0.58em、等寬 0.60em），
#    寧可誤報也不要漏 —— 沒有 renderer 的環境裡這是唯一守得住版面的辦法。
FONT = {'s-lbl': (13.0, False), 's-sm': (11.5, False),
        's-mono': (11.5, True), 's-key': (12.5, True)}

# HTML5 規範裡「在 foreign content 中會導致 breakout」的標籤。
# 出現在 <svg> 內就會把 svg 提前關掉，整張圖不顯示。
BREAKOUT_TAGS = {
    'b', 'big', 'blockquote', 'body', 'br', 'center', 'code', 'dd', 'div', 'dl', 'dt',
    'em', 'embed', 'font', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'hr', 'i', 'img',
    'li', 'listing', 'menu', 'meta', 'nobr', 'ol', 'p', 'pre', 'ruby', 's', 'small',
    'span', 'strike', 'strong', 'sub', 'sup', 'table', 'tt', 'u', 'ul', 'var',
}


def text_width(txt, size, mono, bold):
    w = 0.0
    for ch in txt:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += size
        elif ch == ' ':
            w += size * (0.60 if mono else 0.28)
        else:
            w += size * (0.60 if mono else 0.58)
    return w * (1.05 if bold else 1.0)


total_figs = 0
for name in chapters:
    html = texts[name]
    svgs = re.findall(r'<svg\b.*?</svg>', html, re.S)
    total_figs += len(svgs)
    # ⚠ 只數 <figcaption> 裡的圖號。整頁 grep `圖 N.M` 會把**內文的交叉引用**
    #   也算成一張圖（「見圖 12.4」），於是「4 張 svg 但有 5 個圖號」——
    #   誤判的是判準，不是頁面。交叉引用是正常寫法，不該被禁。
    captions = re.findall(r'<figcaption>(.*?)</figcaption>', html, re.S)
    nums = [int(m) for cap in captions for m in re.findall(r'圖 \d+\.(\d)', cap)]
    if nums != list(range(1, len(nums) + 1)):
        failed = True
        print(f'{name}: 圖號與出現順序對不上 {nums}')
    if len(nums) != len(svgs):
        failed = True
        print(f'{name}: {len(svgs)} 張 svg 但有 {len(nums)} 個圖號')
    marker_ids = re.findall(r'<marker id="([^"]+)"', html)
    if len(marker_ids) != len(set(marker_ids)):
        failed = True
        print(f'{name}: marker id 重複 {marker_ids}')

    for i, raw in enumerate(svgs, 1):
        head = raw.split('>')[0]
        for attr in ('viewBox', 'role=', 'aria-label'):
            if attr not in head:
                failed = True
                print(f'{name} svg#{i}: 缺 {attr}')
        for bad in ('<image', 'foreignObject', 'http'):
            if bad in raw:
                failed = True
                print(f'{name} svg#{i}: 圖內出現 {bad}，違反單檔自足')
        # ⚠ HTML-only 標籤放進 inline SVG 會觸發 HTML 解析器的 foreign-content
        #   **breakout**：解析器當場關掉整個 <svg>，後面全部當 HTML 讀 ——
        #   結果是那張圖**一片空白**。而 XML parser 覺得 <b> 完全合法，
        #   所以下面那個 ET.fromstring 抓不到。要粗體用 <tspan font-weight="700">。
        html_only = sorted({t.lower() for t in re.findall(r'</?([A-Za-z][A-Za-z0-9]*)', raw)}
                           & BREAKOUT_TAGS)
        if html_only:
            failed = True
            print(f'{name} svg#{i}: 圖內有 HTML 專用標籤 {html_only} —— '
                  f'會把 svg 打斷，整張圖不會顯示。用 <tspan> 代替')
        try:
            root = ET.fromstring(raw.replace('&quot;', '"'))
        except ET.ParseError as exc:
            failed = True
            print(f'{name} svg#{i}: XML 不合法 {exc}')
            continue
        vb = root.get('viewBox')
        if not vb:
            continue
        view_w = float(vb.split()[2])
        parent = {c: par for par in root.iter() for c in par}
        boxes = [(float(r.get('x', 0)), float(r.get('y', 0)),
                  float(r.get('width')), float(r.get('height', 0)))
                 for r in root.iter()
                 if r.tag.endswith('rect') and r.get('width')
                 and 's-box' in (r.get('class') or '')]
        rows = []
        for node in root.iter():
            if not node.tag.endswith('text'):
                continue
            txt = ''.join(node.itertext())
            if not txt.strip():
                continue
            cls, cur = node.get('class') or '', node
            while not any(k in cls.split() for k in FONT) and cur in parent:
                cur = parent[cur]
                cls = (cur.get('class') or '') + ' ' + cls
            key = next((k for k in FONT if k in cls.split()), 's-lbl')
            size, mono = FONT[key]
            width = text_width(txt, size, mono, node.get('font-weight') == '700')
            x = float(node.get('x', 0))
            y = float(node.get('y', 0))
            anchor = node.get('text-anchor') or (
                parent[node].get('text-anchor') if node in parent else None) or 'start'
            if 'rotate(' in (node.get('transform') or ''):
                continue  # 直書另有量法，這裡不判
            x0 = x - width if anchor == 'end' else (
                x - width / 2 if anchor == 'middle' else x)
            x1 = x0 + width
            if x0 < 0 or x1 > view_w:
                failed = True
                print(f'{name} svg#{i}: 字溢出 viewBox 「{txt[:30]}」')
                continue
            rows.append((y, x0, x1, txt))
            for bx, by, bw, bh in boxes:
                if bh < 20 or bw < 40 or not (by <= y - size * 0.3 <= by + bh):
                    continue
                if not bx <= x <= bx + bw:
                    continue
                if x0 < bx + 3 or x1 > bx + bw - 3:
                    failed = True
                    print(f'{name} svg#{i}: 字溢出方框 「{txt[:30]}」')
                break
        rows.sort()
        for a_i in range(len(rows)):
            for b_i in range(a_i + 1, len(rows)):
                if abs(rows[a_i][0] - rows[b_i][0]) > 3:
                    break
                if rows[a_i][1] < rows[b_i][2] and rows[b_i][1] < rows[a_i][2]:
                    failed = True
                    print(f'{name} svg#{i}: 同列疊字 '
                          f'「{rows[a_i][3][:20]}」×「{rows[b_i][3][:20]}」')

print(f'手繪 SVG: {total_figs} 張，契約全過' if not failed else f'手繪 SVG: {total_figs} 張')

print('驗收結果:', '有問題，見上方' if failed else '全部通過')
sys.exit(1 if failed else 0)
