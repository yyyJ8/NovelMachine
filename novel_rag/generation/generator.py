"""
检索增强生成 —— 把检索结果组装成 prompt，调用 LLM 生成答案。

Prompt 模板:
  - 系统角色 + 参考资料 + 用户问题
  - 要求 LLM 标注来源
  - 资料不足以回答时诚实说明

使用方式:
    from novel_rag.generation.generator import Generator
    gen = Generator()
    result = gen.generate("金丹期怎么突破", search_results)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from novel_rag.config import config
from novel_rag.retrieval.hybrid_search import HybridSearchResult


# ── 默认 Prompt 模板 ─────────────────────────

DEFAULT_SYSTEM_PROMPT = """你是一位专业的网文写作助手，精通仙侠题材的设定与创作。

## 规则
1. 基于下方「参考资料」回答问题
2. 如果资料中有答案，请准确引用并标注来源编号
3. 如果资料不足以回答，请诚实说明"当前知识库中未找到相关信息"
4. 可以基于已有知识做合理的创作延伸，但需标注"创作建议"
5. 回答简洁有条理，适合写作者参考使用"""

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_system_prompt(genre: str | None = None) -> str:
    """
    按题材加载生成 system prompt。

    优先级: prompts/{genre}.txt → prompts/default.txt → 内置默认。
    别人接入自己的题材时，在 novel_rag/prompts/ 下放同名 .txt 即可定制生成风格。
    """
    if genre:
        p = _PROMPTS_DIR / f"{genre}.txt"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()

    p = _PROMPTS_DIR / "default.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()

    return DEFAULT_SYSTEM_PROMPT


def build_prompt(
    query: str,
    chunks: list[HybridSearchResult],
    system_prompt: str | None = None,
    max_chunks: int = 5,
) -> str:
    """
    组装完整的生成 prompt。

    格式:
        ## 系统角色
        {system_prompt}

        ## 参考资料
        [1] (来源: {source_file} / {title})
        {chunk_text}

        ## 用户问题
        {query}

        请回答:
    """
    system = system_prompt or DEFAULT_SYSTEM_PROMPT

    ref_lines: list[str] = []
    for i, chunk in enumerate(chunks[:max_chunks], 1):
        source = chunk.metadata.get("source_file", chunk.metadata.get("filename", "未知"))
        title = chunk.metadata.get("title", "")
        src_label = f"{source}" + (f" / {title}" if title else "")
        ref_lines.append(f"[{i}] (来源: {src_label})\n{chunk.text}")

    references = "\n\n".join(ref_lines)

    return (
        f"## 系统角色\n{system}\n\n"
        f"## 参考资料\n{references}\n\n"
        f"## 用户问题\n{query}\n\n"
        f"请回答:"
    )


@dataclass
class GenerationResult:
    """生成结果"""
    answer: str
    sources: list[dict] = field(default_factory=list)
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Generator:
    """LLM 生成器（使用 SiliconFlow Chat API）"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        # 默认从配置读取（.env 可配 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）
        self.api_key = api_key or config.effective_llm_api_key
        self.base_url = base_url or config.effective_llm_base_url
        self.model = model or config.llm_model

    def generate(
        self,
        query: str,
        search_results: list[HybridSearchResult],
        system_prompt: str | None = None,
        max_chunks: int = 5,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> GenerationResult:
        """
        基于检索结果生成回答。

        参数:
            query: 用户问题
            search_results: 混合检索结果
            system_prompt: 自定义系统提示词
            max_chunks: 最多引用几条资料
            temperature: 创意度（0=严谨, 1=创意）
            max_tokens: 最大输出长度
            stream: 是否流式输出（流式时返回完整 answer，不逐字打印到 stdout）
        """
        from openai import OpenAI

        prompt = build_prompt(query, search_results, system_prompt, max_chunks)

        # 提取来源信息
        sources: list[dict] = []
        for i, chunk in enumerate(search_results[:max_chunks], 1):
            sources.append({
                "index": i,
                "text_snippet": chunk.text[:200],
                "source_file": chunk.metadata.get("source_file", "未知"),
                "title": chunk.metadata.get("title", ""),
                "collection": chunk.collection,
                "rrf_score": chunk.rrf_score,
                "rerank_score": chunk.rerank_score,
            })

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

        if stream:
            answer_parts: list[str] = []
            for chunk in response:
                if chunk.choices[0].delta.content:
                    answer_parts.append(chunk.choices[0].delta.content)
            answer = "".join(answer_parts)
            return GenerationResult(answer=answer, sources=sources, model=self.model)
        else:
            return GenerationResult(
                answer=response.choices[0].message.content,
                sources=sources,
                model=self.model,
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
            )
