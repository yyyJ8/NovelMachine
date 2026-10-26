# -*- coding: utf-8 -*-
"""章节体检：标点规范 + AI 句式/通感自查

一本书 = 一个自包含目录，正文在 {book_dir}/chapters/ 下（可再分层，本脚本递归扫描 .md）。

检查项
  ── 硬性（不过即 FAIL）──
    1. 标题汉字数 ≥ 2
    2. 半角逗号 / 半角句号（中文正文不该出现）
    3. 引号必须成对
    4. 省略号必须用 ……，不得用 ...
    5. 破折号必须成对 ——，不得出现单个 —
    6. 感官动词错配（"闻"接光/声音、"听"接光/气味）
  ── 参考（只报告，不算失败）──
    7. 段落句末符号：叙述区每段 ≤ N 个 。！？（N 由 --max-periods 定，默认 2；
       短段流是某种写作风格，不是通用规范，想要硬性约束加 --strict）
    8. 逗号/句号比        9. 破折号密度（> 5/千字提示）
   10. 平均句长 / 超长句   11. 相邻短句列（连续 3 句均 ≤ 15 字，疑似 AI 断句碎片）
   12. 顿号数 / 单字逗号对

用法
  python _workflows/verify_punct.py                   # 扫 .env 里 BOOK_DIR/chapters
  python _workflows/verify_punct.py --book mybook      # 扫 <novels>/mybook/chapters
  python _workflows/verify_punct.py --dir <目录>       # 扫指定目录
  python _workflows/verify_punct.py a.md b.md          # 扫指定文件
  python _workflows/verify_punct.py --quiet            # 只出汇总与问题项

退出码
  0 全部通过 | 1 存在硬性问题 | 2 没找到章节文件

注：旧版 verify_punct.py 的 "revised vs final 逐字比对" 已移除——正文不再保留
originals/revised/final 三层副本，版本差异交给 git。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # 允许在未装 dotenv 的极简环境里跑
    def load_dotenv(*_a, **_k):
        return False

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MAX_PERIODS_PER_PARA = 2      # 叙述区每段最大句末符号数
MAX_EM_DASH_PER_K = 5         # 破折号密度上限（个/千字，仅提示）
MAX_SENTENCE_LEN = 60         # 超长句阈值
SHORT_SENT_LEN = 15           # 相邻短句判定长度

QUOTED = re.compile(r'"[^"]*"')          # 引号内对话不参与叙述区统计
SENSORY_MISMATCH = [
    # 注意：「闻风/闻讯/闻名」是成语，不是通感错配，故「风」不列入
    (r'闻[见到的]*(光|颜色|影|星|火|月|日|声音|雷|震动|温度|冷|热)', '闻只接气味'),
    (r'听[见到的]*(光|颜色|影|星|火|月|日|气味|味|触|冷|热|痛)', '听见只接声音'),
]


def resolve_path(env: str, default: Path) -> Path:
    """与 novel_rag.config._path 同语义：绝对路径原样用，相对路径相对仓库根。"""
    raw = os.getenv(env)
    if not raw:
        return default
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def book_dir_of(key: str) -> Path:
    return resolve_path("BOOK_DIR", ROOT / "novels" / key)


def collect(args) -> tuple[list[Path], str]:
    """返回 (章节文件列表, 来源说明)"""
    if args.files:
        return [Path(f).resolve() for f in args.files], "命令行指定文件"

    if args.dir:
        base = Path(args.dir).resolve()
        return sorted(base.rglob("*.md")), str(base)

    key = args.book or os.getenv("CURRENT_BOOK", "mybook")
    bdir = book_dir_of(key)
    chapters = bdir / "chapters"
    base = chapters if chapters.is_dir() else bdir
    return sorted(base.rglob("*.md")), f"{key} → {base}"


def strip_markup(text: str) -> str:
    """去掉标题行、分隔线、章末标记。"""
    t = re.sub(r"^#.*$", "", text, flags=re.MULTILINE)
    t = re.sub(r"[-*]{3,}", "", t)
    t = re.sub(r"（第[^）]+完）", "", t)
    return t


def narrative_of(text_clean: str) -> str:
    """剥掉引号内对话，只留叙述区。"""
    narrative = text_clean
    for q in QUOTED.findall(text_clean):
        narrative = narrative.replace(q, "", 1)
    return narrative


def count_cjk(s: str) -> int:
    return len(re.findall(r"[一-鿿]", s))


def inspect(path: Path, max_periods: int = MAX_PERIODS_PER_PARA,
            strict_periods: bool = False) -> dict:
    text = path.read_text(encoding="utf-8")
    clean = strip_markup(text)
    narrative = narrative_of(clean)
    cjk = count_cjk(clean)
    per_k = cjk / 1000.0 if cjk else 1.0

    r = {"path": path, "name": path.name, "issues": [], "notes": []}

    # 1. 段落句末符号（叙述区，跳空行与分隔符）
    paragraphs = [p.strip() for p in narrative.split("\n\n") if p.strip()]
    over = [(i + 1, len(re.findall(r"[。！？]", p)), p[:40])
            for i, p in enumerate(paragraphs)
            if len(re.findall(r"[。！？]", p)) > max_periods]
    r["over_paragraphs"] = over
    if over:
        msg = f"段落句末符号 > {max_periods} 个：{len(over)} 段"
        (r["issues"] if strict_periods else r["notes"]).append(msg)

    # 2. 标题
    m = re.search(r"^# (.+)$", text, re.MULTILINE)
    title = m.group(1).strip() if m else ""
    r["title"] = title
    r["title_cjk"] = count_cjk(title)
    if r["title_cjk"] < 2:
        r["issues"].append(f"标题汉字不足 2 个：{title!r}")

    # 3. 半角标点
    half_comma = [(i, ln.strip()[:60]) for i, ln in enumerate(narrative.split("\n"), 1)
                  for _ in re.findall(r"(?<!\d),(?!\d)", ln)]
    half_period = [(i, ln.strip()[:60]) for i, ln in enumerate(narrative.split("\n"), 1)
                   for _ in re.findall(r"(?<!\d)\.(?!\.)(?!\d)", ln)]
    r["half_comma"], r["half_period"] = half_comma, half_period
    if half_comma:
        r["issues"].append(f"半角逗号 {len(half_comma)} 处")
    if half_period:
        r["issues"].append(f"半角句号 {len(half_period)} 处")

    # 4. 引号成对
    r["quotes"] = clean.count('"')
    if r["quotes"] % 2:
        r["issues"].append(f"引号数为奇数（{r['quotes']}）")

    # 5. 省略号
    r["ellipsis_ok"] = len(re.findall(r"……", clean))
    r["ellipsis_dots"] = len(re.findall(r"(?<!…)\.{3,}(?!\.)", clean))
    if r["ellipsis_dots"]:
        r["issues"].append(f"用了 ... 代替 ……（{r['ellipsis_dots']} 处）")

    # 6. 破折号：密度 + 单个 —
    r["em_dash"] = len(re.findall(r"——", narrative))
    r["em_dash_per_k"] = r["em_dash"] / per_k
    if r["em_dash_per_k"] > MAX_EM_DASH_PER_K:
        r["notes"].append(f"破折号密度偏高 {r['em_dash_per_k']:.1f}/千字")
    pos = [m.start() for m in re.finditer(r"—", narrative)]
    single, i = 0, 0
    while i < len(pos):
        if i + 1 < len(pos) and pos[i + 1] == pos[i] + 1:
            i += 2
        else:
            single += 1
            i += 1
    r["em_dash_single"] = single
    if single:
        r["issues"].append(f"单个破折号（应成对 ——）{single} 处")

    # 7. 感官动词错配
    r["sensory"] = []
    for pattern, rule in SENSORY_MISMATCH:
        for hit in re.finditer(pattern, text):
            line = text[: hit.start()].count("\n") + 1
            ctx = text[max(0, hit.start() - 8): hit.end() + 8].replace("\n", " ")
            r["sensory"].append((line, hit.group(), rule, ctx))
    if r["sensory"]:
        r["issues"].append(f"感官动词错配 {len(r['sensory'])} 处")

    # 8. 逗号/句号比
    r["commas"] = narrative.count("，") + narrative.count("、")
    r["periods"] = narrative.count("。")
    r["ratio"] = r["commas"] / r["periods"] if r["periods"] else float("inf")

    # 9-12. 句长与断句
    sents = [s.strip() for s in re.split(r"[。！？]", narrative) if s.strip()]
    r["avg_sent"] = sum(len(s) for s in sents) / max(len(sents), 1)
    r["long_sents"] = [s for s in sents if len(s) > MAX_SENTENCE_LEN]
    runs = []
    i = 0
    while i < len(sents) - 2:
        if all(len(s) <= SHORT_SENT_LEN for s in sents[i:i + 3]):
            runs.append((i + 1, " | ".join(sents[i:i + 3])[:60]))
            i += 3
        else:
            i += 1
    r["short_runs"] = runs
    if runs:
        r["notes"].append(f"相邻短句列 {len(runs)} 处（可能该用逗号连接）")

    r["dunhao"] = clean.count("、")
    r["dunhao_candidates"] = len(re.findall(r"[一-鿿]，[一-鿿]", narrative))

    r["ok"] = not r["issues"]
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="章节标点与文风体检")
    ap.add_argument("files", nargs="*", help="指定章节文件")
    ap.add_argument("--book", help="书 key（默认读 .env 的 CURRENT_BOOK）")
    ap.add_argument("--dir", help="直接指定扫描目录")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总和问题项")
    ap.add_argument("--max-periods", type=int, default=MAX_PERIODS_PER_PARA,
                    help=f"叙述区每段句末符号上限（默认 {MAX_PERIODS_PER_PARA}）")
    ap.add_argument("--strict", action="store_true", help="把段落句末符号超限也算作硬性问题")
    args = ap.parse_args()

    files, source = collect(args)
    files = [f for f in files if f.is_file()]
    if not files:
        print(f"没找到章节文件：{source}")
        return 2

    print(f"扫描：{source}")
    print(f"文件：{len(files)} 个\n")

    results = [inspect(f, args.max_periods, args.strict) for f in files]

    if not args.quiet:
        print(f"{'文件':<14}{'判定':<6}{'超限段':>6}{'短句列':>6}{'逗号/句号':>10}"
              f"{'破折号':>7}{'标题字':>6}{'长句':>5}")
        print("-" * 68)
        for r in results:
            ratio = "∞" if r["ratio"] == float("inf") else f"{r['ratio']:.1f}"
            print(f"{r['name']:<14}{'OK' if r['ok'] else 'FAIL':<6}"
                  f"{len(r['over_paragraphs']):>6}{len(r['short_runs']):>6}"
                  f"{ratio:>10}{r['em_dash_per_k']:>7.1f}{r['title_cjk']:>6}"
                  f"{len(r['long_sents']):>5}")
        print("-" * 68)

    failed = [r for r in results if not r["ok"]]
    noted = [r for r in results if r["notes"]]

    if failed:
        print(f"\n!! 硬性问题（{len(failed)} 个文件）")
        for r in failed:
            print(f"\n  {r['name']}  〔{r['title']}〕")
            for msg in r["issues"]:
                print(f"    - {msg}")
            for idx, cnt, preview in r["over_paragraphs"]:
                print(f"      第{idx}段 {cnt} 个句末符号 → \"{preview}...\"")
            for ln, ctx in r["half_comma"][:3]:
                print(f"      半角逗号 ~L{ln}: {ctx}")
            for ln, ctx in r["half_period"][:3]:
                print(f"      半角句号 ~L{ln}: {ctx}")
            for ln, got, rule, ctx in r["sensory"][:5]:
                print(f"      L{ln} \"{got}\" → {rule} | ...{ctx}...")
    else:
        print("\n!! 硬性检查全部通过")

    if noted:
        print(f"\n-- 参考提示（{len(noted)} 个文件）")
        for r in noted:
            print(f"  {r['name']}: {'; '.join(r['notes'])}")
            for idx, preview in r["short_runs"][:2]:
                print(f"      第{idx}句起: \"{preview}...\"")
            if len(r["long_sents"]) > 3:
                print(f"      超长句 {len(r['long_sents'])} 句（>{MAX_SENTENCE_LEN} 字）")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
