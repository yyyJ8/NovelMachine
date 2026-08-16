#!/usr/bin/env python
"""
RAG 命令行入口

用法:
  python cli.py ingest --genre xianxia              # 摄入指定题材
  python cli.py ingest --all                          # 摄入所有资料
  python cli.py query "金丹期有什么特点"               # 单次查询
  python cli.py query "金丹期" --genre xianxia        # 限定题材查询
  python cli.py query --interactive                   # 交互式查询
  python cli.py info                                  # 显示索引状态
  python cli.py clean --collection xianxia_cultivation # 清空 collection
  python cli.py clean --all                           # 清空全部
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

from novel_rag.config import config, get_all_collections, get_collections_for_genre
from novel_rag.pipeline import IngestionPipeline, QueryPipeline
from novel_rag.ingestion.chunker import ChunkStrategy

console = Console()


# ═══════════════════════════════════════════════
# Subcommand: ingest
# ═══════════════════════════════════════════════

def cmd_ingest(
    genre: str | None = None,
    all_genres: bool = False,
    strategy: str = "markdown",
    clear: bool = False,
    strict: bool = False,
    incremental: bool = False,
):
    """摄入资料到知识库"""
    strategies = {
        "classical": ChunkStrategy.CLASSICAL,
        "fixed": ChunkStrategy.FIXED,
        "markdown": ChunkStrategy.MARKDOWN,
        "sentence": ChunkStrategy.SENTENCE,
    }
    chunk_strategy = strategies.get(strategy, ChunkStrategy.CLASSICAL)
    pipeline = IngestionPipeline()

    if all_genres:
        console.print("[bold]🚀 摄入全部题材...[/bold]")
        total = {}
        for g in _discover_genres():
            console.print(f"\n[cyan]▶ 题材: {g}[/cyan]")
            try:
                result = pipeline.run(
                    genre=g, strategy=chunk_strategy, clear_existing=clear,
                    strict=strict, incremental=incremental,
                )
                total.update(result["collections"])
            except Exception as e:
                console.print(f"[red]  ✗ {g} 摄入失败: {e}[/red]")
        _print_ingest_summary(total)
    elif genre:
        result = pipeline.run(
            genre=genre, strategy=chunk_strategy, clear_existing=clear,
            strict=strict, incremental=incremental,
        )
        _print_ingest_summary(result["collections"])
        _print_ingest_warnings(result.get("warnings", []))
    else:
        console.print("[red]请指定 --genre <题材名> 或 --all[/red]")


def _print_ingest_warnings(warnings: list[str]):
    """打印摄入过程中的非致命失败汇总（不再静默跳过）"""
    if warnings:
        console.print(f"\n[yellow]⚠ {len(warnings)} 项失败已跳过:[/yellow]")
        for w in warnings:
            console.print(f"  [red]✗[/red] {w}")


def _discover_genres() -> list[str]:
    """发现所有题材：配置文件注册的 + _bible/ 下实际存在的目录（并集，确定性排序）"""
    from novel_rag.genre_registry import genre_registry

    genres = set(genre_registry.genre_keys())
    if config.bible_dir.is_dir():
        for p in config.bible_dir.iterdir():
            if p.is_dir():
                genres.add(p.name)
    return sorted(genres)


def _print_ingest_summary(stats: dict):
    """打印摄入统计"""
    table = Table(title="摄入结果")
    table.add_column("Collection", style="cyan")
    table.add_column("Chunks", style="green", justify="right")
    total = 0
    for col, count in sorted(stats.items()):
        table.add_row(col, str(count))
        total += count
    table.add_row("[bold]合计[/bold]", f"[bold]{total}[/bold]", style="bold")
    console.print(table)


# ═══════════════════════════════════════════════
# Subcommand: query
# ═══════════════════════════════════════════════

def cmd_query(
    query_text: str | None = None,
    genre: str | None = None,
    top_k: int = 5,
    interactive: bool = False,
    rerank: bool = False,
    search_only: bool = False,
):
    """查询知识库"""
    pipeline = QueryPipeline()

    if interactive:
        _interactive_query(pipeline, genre, top_k, rerank, search_only)
    elif query_text:
        _single_query(pipeline, query_text, genre, top_k, rerank, search_only)
    else:
        console.print("[red]请提供查询文本，或使用 --interactive[/red]")


def _single_query(
    pipeline: QueryPipeline,
    query_text: str,
    genre: str | None,
    top_k: int,
    rerank: bool,
    search_only: bool,
):
    """执行单次查询"""
    console.print(f"\n[dim]查询: {query_text}[/dim]\n")

    results = pipeline.search(
        query=query_text,
        genre=genre,
        top_k=top_k,
        use_reranker=rerank,
        verbose=False,
    )

    if not results:
        console.print("[yellow]未找到相关内容[/yellow]")
        return

    if search_only:
        # 只显示检索结果
        _print_search_results(results, top_k)
    else:
        # 检索 + 生成
        console.print("[bold]📖 参考资料:[/bold]")
        _print_search_results(results, top_k)

        console.print("\n[bold]🤖 生成回答:[/bold]\n")
        result = pipeline.generate(
            query=query_text,
            genre=genre,
            top_k=top_k,
            use_reranker=rerank,
            stream=True,
        )
        console.print(f"\n\n[dim]引用来源: {len(result.sources)} 条[/dim]")
        for s in result.sources:
            console.print(f"  [{s['index']}] {s['source_file']} ({s['collection']})")


def _interactive_query(
    pipeline: QueryPipeline,
    genre: str | None,
    top_k: int,
    rerank: bool,
    search_only: bool,
):
    """交互式查询模式"""
    console.print("[bold]🔍 交互式查询模式[/bold]")
    console.print("  输入查询文本，输入 [bold red]quit[/bold red] 或 [bold red]exit[/bold red] 退出")
    console.print(f"  题材: {genre or '全部'}, Top-K: {top_k}, Rerank: {rerank}\n")

    while True:
        try:
            query_text = console.input("[bold green]>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见!")
            break

        if not query_text:
            continue
        if query_text.lower() in ("quit", "exit", "q"):
            console.print("再见!")
            break

        _single_query(pipeline, query_text, genre, top_k, rerank, search_only)
        console.print()  # 空行分隔


def _print_search_results(results, top_k: int):
    """格式化打印检索结果"""
    table = Table(show_header=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Score", style="cyan", width=8)
    table.add_column("来源", style="yellow", width=20)
    table.add_column("内容", style="white", max_width=60)

    for i, r in enumerate(results[:top_k], 1):
        src = r.metadata.get("source_file", "?")
        table.add_row(
            str(i),
            f"{r.rrf_score:.4f}",
            src[:18],
            r.text[:100].replace("\n", " "),
        )

    console.print(table)


# ═══════════════════════════════════════════════
# Subcommand: info
# ═══════════════════════════════════════════════

def cmd_info():
    """显示索引状态"""
    pipeline = QueryPipeline()
    info = pipeline.info()

    console.print(Panel.fit("[bold]📊 RAG 知识库状态[/bold]"))

    # ChromaDB 统计
    chroma_table = Table(title="ChromaDB 向量库")
    chroma_table.add_column("Collection", style="cyan")
    chroma_table.add_column("Chunks", style="green", justify="right")

    total = 0
    for col, count in sorted(info["chroma_collections"].items()):
        chroma_table.add_row(col, str(count))
        total += count
    chroma_table.add_row("[bold]合计[/bold]", f"[bold]{total}[/bold]", style="bold")
    console.print(chroma_table)

    # BM25 状态
    bm25_table = Table(title="BM25 关键词索引")
    bm25_table.add_column("已加载 Collection", style="magenta")
    for col in sorted(info["bm25_loaded"]):
        bm25_table.add_row(col)
    if not info["bm25_loaded"]:
        bm25_table.add_row("[dim](无)[/dim]")
    console.print(bm25_table)

    # 配置
    config_table = Table(title="配置")
    config_table.add_column("参数", style="dim")
    config_table.add_column("值", style="white")
    config_table.add_row("Embedding 模型", config.embedding_model)
    config_table.add_row("Chunk 大小", str(config.chunk_size))
    config_table.add_row("Chunk 重叠", str(config.chunk_overlap))
    config_table.add_row("检索 Top-K", str(config.retrieval_top_k))
    config_table.add_row("RRF k", str(config.rrf_k))
    config_table.add_row("ChromaDB 路径", str(config.chroma_persist_dir))
    console.print(config_table)


# ═══════════════════════════════════════════════
# Subcommand: clean
# ═══════════════════════════════════════════════

def cmd_clean(collection: str | None = None, all_collections: bool = False):
    """清空索引"""
    from novel_rag.storage.chroma_store import ChromaStore
    store = ChromaStore()

    if all_collections:
        console.print("[bold red]⚠ 确认要清空所有 collection 吗? (y/N)[/bold red]")
        confirm = input().strip().lower()
        if confirm == "y":
            for col in store.list_collections():
                store.delete_collection(col)
            console.print("[green]已清空所有 collection[/green]")
        else:
            console.print("[dim]已取消[/dim]")
    elif collection:
        store.delete_collection(collection)
    else:
        console.print("[red]请指定 --collection <名称> 或 --all[/red]")


# ═══════════════════════════════════════════════
# Main CLI
# ═══════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="📚 网文写作 RAG 知识库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cli.py ingest --genre xianxia
  python cli.py query "金丹期"
  python cli.py query --interactive
  python cli.py info
  python cli.py clean --collection xianxia_cultivation
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── ingest ────────────────────────────────
    ingest_parser = subparsers.add_parser("ingest", help="摄入资料")
    ingest_parser.add_argument("--genre", type=str, help="题材名称 (xianxia, wuxia, ...)")
    ingest_parser.add_argument("--all", action="store_true", help="摄入全部题材")
    ingest_parser.add_argument("--strategy", type=str, default="classical",
                               choices=["classical", "fixed", "markdown", "sentence"], help="分块策略")
    ingest_parser.add_argument("--clear", action="store_true", help="摄入前清空已有数据")
    ingest_parser.add_argument("--strict", action="store_true",
                               help="任一环节失败立即报错退出（默认收集 warnings 继续）")
    ingest_parser.add_argument("--incremental", action="store_true",
                               help="增量摄入：只处理新增/变更文件（依据 mtime+size 指纹）")

    # ── query ─────────────────────────────────
    query_parser = subparsers.add_parser("query", help="查询知识库")
    query_parser.add_argument("query_text", type=str, nargs="?", help="查询文本")
    query_parser.add_argument("--genre", type=str, help="题材名称")
    query_parser.add_argument("--top-k", type=int, default=5, help="返回条数")
    query_parser.add_argument("--interactive", "-i", action="store_true", help="交互式查询")
    query_parser.add_argument("--rerank", action="store_true", help="启用重排序")
    query_parser.add_argument("--search-only", "-s", action="store_true", help="仅检索，不生成回答")

    # ── info ──────────────────────────────────
    subparsers.add_parser("info", help="显示索引状态")

    # ── clean ─────────────────────────────────
    clean_parser = subparsers.add_parser("clean", help="清空索引")
    clean_parser.add_argument("--collection", type=str, help="要清空的 collection")
    clean_parser.add_argument("--all", action="store_true", help="清空全部")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "ingest":
        cmd_ingest(
            genre=args.genre,
            all_genres=args.all,
            strategy=args.strategy,
            clear=args.clear,
            strict=args.strict,
            incremental=args.incremental,
        )
    elif args.command == "query":
        cmd_query(
            query_text=args.query_text,
            genre=args.genre,
            top_k=args.top_k,
            interactive=args.interactive,
            rerank=args.rerank,
            search_only=args.search_only,
        )
    elif args.command == "info":
        cmd_info()
    elif args.command == "clean":
        cmd_clean(
            collection=args.collection,
            all_collections=args.all,
        )


if __name__ == "__main__":
    main()
