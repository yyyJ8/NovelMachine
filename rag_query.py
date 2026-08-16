#!/usr/bin/env python
"""
RAG 查询工具 — 为 Agent 提供 JSON 格式输出。

用法:
  python rag_query.py "金丹期如何突破"              # 检索 + 生成回答
  python rag_query.py "金丹期" --search-only         # 只检索，不生成
  python rag_query.py "天劫" --top-k 10              # 指定返回条数
  python rag_query.py "阵法" --genre xianxia         # 限定题材
  python rag_query.py "内丹" --search-only --jsonl   # JSONL 格式

输出:
  --search-only 模式: 返回 JSON 数组，每个元素包含 text/score/source/title
  默认模式: 返回 JSON 对象，包含 answer/sources
"""

from __future__ import annotations

import json
import argparse

from novel_rag.pipeline import QueryPipeline


def main():
    parser = argparse.ArgumentParser(description="RAG 查询（JSON 输出）")
    parser.add_argument("query", type=str, help="查询文本")
    parser.add_argument("--genre", type=str, default=None, help="题材名称")
    parser.add_argument("--top-k", type=int, default=5, help="返回条数")
    parser.add_argument("--search-only", action="store_true", help="仅检索")
    parser.add_argument("--jsonl", action="store_true", help="JSONL 格式输出")
    args = parser.parse_args()

    pipeline = QueryPipeline()

    results = pipeline.search(
        query=args.query,
        genre=args.genre,
        top_k=args.top_k,
        verbose=False,
    )

    if args.search_only:
        output = []
        for r in results:
            output.append({
                "text": r.text,
                "score": round(r.rrf_score, 4),
                "source": r.metadata.get("source_file", ""),
                "title": r.metadata.get("title", ""),
                "dynasty": r.metadata.get("dynasty", ""),
                "author": r.metadata.get("author", ""),
                "collection": r.metadata.get("collection", ""),
            })

        if args.jsonl:
            for item in output:
                print(json.dumps(item, ensure_ascii=False))
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        result = pipeline.generate(
            query=args.query,
            genre=args.genre,
            top_k=args.top_k,
            stream=False,
        )

        output = {
            "answer": result.answer,
            "sources": []
        }
        for s in result.sources:
            output["sources"].append({
                "index": s.get("index", "?"),
                "source": s.get("source_file", ""),
                "title": s.get("title", ""),
                "score": s.get("rrf_score", 0),
            })

        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
