# -*- coding: utf-8 -*-
"""校验 final/ 标点修订: 1) 字词未被改动(剥离标点逐字对比) 2) 段落句末符号检测 3) 标题汉字 >= 2
标准(新章节起): 叙述区每段句末符号（。！？）≤ 2 个; 顿号/冒号纳入统计; 标题不得少于2个汉字
用法: python verify_punct.py [book] [vol]  # book 默认读 .env 的 CURRENT_BOOK, vol 默认 vol_01"""
import re, glob, os, sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
BOOK = sys.argv[1] if len(sys.argv) > 1 else os.getenv('CURRENT_BOOK', 'duanze')
VOL = sys.argv[2] if len(sys.argv) > 2 else 'vol_01'
BASE = os.path.join(os.path.dirname(__file__), '..', 'chapters', BOOK, VOL)
OLD, NEW = 'revised', 'final'
MAX_PERIODS_PER_PARA = 2  # 每段最大句末符号数（叙述区，对话段豁免）

def strip(text):
    """只保留汉字/字母/数字, 剥离所有标点空白 -> 字词指纹"""
    return re.sub(r'[^一-鿿A-Za-z0-9]', '', text)

QUOTED = re.compile(r'"[^"]*"')  # 引号内对话不参与标点统计

def count_cjk(title):
    """统计标题中的汉字数量（CJK统一表意文字区间）"""
    return len(re.findall(r'[一-鿿]', title))

def extract_title(path):
    """提取章节文件第一行的标题"""
    with open(path, encoding='utf-8') as f:
        t = f.readline().strip()
    t = re.sub(r'^#\s*', '', t)
    return t

def stats(path):
    """段落级句末符号检测 + 顿号/冒号统计"""
    t = open(path, encoding='utf-8').read()
    t = re.sub(r'^#.*$', '', t, flags=re.M).replace('---', '')
    # 剥离引号内对话
    narrative = QUOTED.sub('', t)
    # 按段落拆分，跳过空行和分隔符
    paragraphs = [p.strip() for p in narrative.split('\n\n') if p.strip()]
    # 统计每段的句末符号数
    para_counts = [(p, len(re.findall(r'[。！？]', p))) for p in paragraphs]
    over_limit = [(i+1, cnt, p[:40]) for i, (p, cnt) in enumerate(para_counts) if cnt > MAX_PERIODS_PER_PARA]
    # 顿号/冒号总数
    d = narrative.count('、')
    col = narrative.count('：')
    # 相邻短句检测：连续 3 个句末符号之间的内容均 ≤15 字且语义可能连续
    sents = [s.strip() for s in re.split(r'[。！？]', narrative) if s.strip()]
    short_runs = []
    i = 0
    while i < len(sents) - 2:
        if all(len(s) <= 15 for s in sents[i:i+3]):
            run_text = ' | '.join(sents[i:i+3])
            short_runs.append((i+1, run_text[:60]))
            i += 3
        else:
            i += 1
    return over_limit, short_runs, d, col

mismatch = []
over_limit_files = []
short_runs_files = []
short_title = []
rows = []
old_files = sorted(glob.glob(os.path.join(BASE, OLD, '*.md')))
new_files = sorted(glob.glob(os.path.join(BASE, NEW, '*.md')))
if not old_files:
    targets, diff_mode = new_files, False
else:
    targets, diff_mode = old_files, True
for f in targets:
    name = os.path.basename(f)
    nf = os.path.join(BASE, NEW, name)
    if not os.path.exists(nf):
        rows.append((name, 'MISSING', 0, 0, 0, 0))
        continue
    if diff_mode:
        old, new = open(f, encoding='utf-8').read(), open(nf, encoding='utf-8').read()
        if strip(old) != strip(new):
            mismatch.append(name)
        status = 'OK' if strip(old) == strip(new) else 'FAIL'
    else:
        status = '--'
    over, short, dn, coln = stats(nf)
    over_count = len(over)
    short_count = len(short)
    if over_count:
        over_limit_files.append((name, over))
    if short_count:
        short_runs_files.append((name, short))
    title = extract_title(nf)
    title_cjk = count_cjk(title)
    if title_cjk < 2:
        short_title.append((name, title))
    rows.append((name, status, over_count, short_count, dn, coln, title_cjk))

print(f"{'file':10s} {'verdict':6s} {'超限段':>5s} {'短句列':>5s} {'顿号':>4s} {'冒号':>4s} {'标题汉字':>6s}")
for r in rows:
    name, status, oc, sc, dn, coln, tcn = r
    print(f"{name:10s} {status:6s} {oc:5d} {sc:5d} {dn:4d} {coln:4d} {tcn:4d}")
print('-' * 60)
if mismatch:
    print(f"!! 字词被改动(需重做): {mismatch}")
elif diff_mode:
    print("!! 全部章节字词零改动 OK")
if over_limit_files:
    print(f"!! 段落句末符号超过 {MAX_PERIODS_PER_PARA} 个（叙述区）:")
    for fname, overs in over_limit_files:
        for idx, cnt, preview in overs:
            print(f"   {fname} 第{idx}段: {cnt}个句末符号 -> \"{preview}...\"")
else:
    print(f"!! 全部段落句末符号 <= {MAX_PERIODS_PER_PARA} 个 OK")
if short_runs_files:
    print(f"!! 相邻短句列（3句以上均≤15字，可能为AI断句碎片，建议逗号连接）:")
    for fname, runs in short_runs_files:
        for idx, preview in runs:
            print(f"   {fname} 第{idx}句起: \"{preview}...\"")
if short_title:
    print(f"!! 标题汉字不足2个: {short_title}")
else:
    print("!! 全部章节标题汉字数 >= 2 OK")

# 感官动词错配检测
SENSORY_MISMATCH = [
    (r'闻[见到的]*(光|颜色|影|星|火|月|日|声音|风|雷|震动|温度|冷|热)', '闻只接气味'),
    (r'听[见到的]*(光|颜色|影|星|火|月|日|气味|味|触|冷|热|痛)', '听见只接声音'),
]
sensory_issues = []
for f in new_files:
    name = os.path.basename(f)
    text = open(f, encoding='utf-8').read()
    for pattern, rule in SENSORY_MISMATCH:
        for m in re.finditer(pattern, text):
            line_no = text[:m.start()].count('\n') + 1
            snippet = text[max(0,m.start()-8):m.end()+8]
            sensory_issues.append((name, line_no, m.group(), rule, snippet))
if sensory_issues:
    print(f"!! 感官动词错配（AI通感错误——'闻'不能接光/声音，'听'不能接光/气味）:")
    for fname, lno, match, rule, ctx in sensory_issues:
        print(f"   {fname}:L{lno} \"{match}\" → {rule}  | 上下文: ...{ctx}...")
else:
    print("!! 感官动词搭配正常 OK")
