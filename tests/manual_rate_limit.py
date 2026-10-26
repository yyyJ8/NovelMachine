"""验证 429 限流重试逻辑（模拟，不调真实 API）"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import RateLimitError
from novel_rag.config import config
from novel_rag.ingestion.embedder import Embedder, _is_rate_limit, _retry_after


def make_rate_limit(headers=None):
    resp = Mock(status_code=429, headers=headers or {})
    return RateLimitError("rate limited", response=resp, body=None)


# 1. 辅助函数
assert _is_rate_limit(make_rate_limit()) is True
assert _is_rate_limit(Mock(status_code=500)) is False
assert _retry_after(make_rate_limit({"retry-after": "12"})) == 12.0
assert _retry_after(make_rate_limit({})) is None
print("OK  辅助函数 _is_rate_limit / _retry_after")

# 2. 429 后恢复：429 → 429（限流循环中 sleep 尊重 Retry-After）→ 成功
e = Embedder(api_key="test", base_url="http://x")
vec = [0.1] * config.embedding_dim
client = Mock()
client.embeddings.create.side_effect = [
    make_rate_limit({"retry-after": "2"}),   # 普通循环首次命中 429
    make_rate_limit({"retry-after": "2"}),   # 限流循环：sleep 后重试仍 429
    Mock(data=[Mock(index=0, embedding=vec)]),  # 恢复成功
]
e._client = client
with patch("novel_rag.ingestion.embedder.time.sleep") as sleep:
    result = e._embed_batch_with_retry(["text"])
assert len(result) == 1 and len(result[0]) == config.embedding_dim
assert sleep.call_count == 1, f"应 sleep 1 次，实际 {sleep.call_count}"
waited = sleep.call_args[0][0]
assert waited >= 2.0, f"应尊重 Retry-After=2s，实际等待 {waited}"
print(f"OK  429 重试恢复（等待 {waited}s = Retry-After）")

# 3. 持续 429：重试 rate_limit_max_retries 次后抛错
client2 = Mock()
client2.embeddings.create.side_effect = make_rate_limit()
e2 = Embedder(api_key="test", base_url="http://x")
e2._client = client2
with patch("novel_rag.ingestion.embedder.time.sleep"):
    try:
        e2._embed_batch_with_retry(["text"])
        print("FAIL 持续 429 应抛错")
        sys.exit(1)
    except RuntimeError as ex:
        assert "429" in str(ex)
        # 普通错误 3 次 + 限流 10 次 = 13 次调用
        assert client2.embeddings.create.call_count == config.max_retries + config.rate_limit_max_retries, \
            f"call_count={client2.embeddings.create.call_count}"
print(f"OK  持续 429 重试 {config.rate_limit_max_retries} 次后抛错（总调用 {client2.embeddings.create.call_count} 次）")

# 4. 批间延时
e3 = Embedder(api_key="test", base_url="http://x")
client3 = Mock()
client3.embeddings.create.return_value = Mock(data=[Mock(index=0, embedding=vec)])
e3._client = client3
with patch("novel_rag.ingestion.embedder.time.sleep") as sleep:
    out = e3.embed_texts(["a", "b", "c", "d"], batch_size=2, batch_delay=1.5)
assert len(out) == 4
# 3 批 → 2 次批间 sleep（batch_delay 路径）+ 0 次重试 sleep
assert sleep.call_count == 2, f"sleep count={sleep.call_count}"
print("OK  批间延时（3 批 → 2 次 sleep 1.5s）")

print("\n429 逻辑验证全部通过")
