# 书目录脚手架

一本书 = 一个自包含目录。新开一本：

```bash
cp -r _templates/book-scaffold D:/novels/mybook
```

然后在 `.env` 里指过去：

```env
CURRENT_BOOK=mybook
BOOK_DIR=D:/novels/mybook
```

## 目录约定

```
{BOOK_DIR}/
├── book.yaml          ← 书名/题材/状态（自描述，第一个改这个）
├── novel_state.yaml   ← 角色/伏笔/时间线快照（随写作更新）
├── world/             ← 三大设定 + 角色/势力/物品 YAML
├── outline/           ← 总大纲（book.md）
├── volumes/           ← 卷纲（vol-01.md …）
├── beats/             ← 章级节拍设计（ch-01.md …）
├── chapters/          ← 正文（可再分卷：vol_01/ch_001.md）
├── reviews/           ← 审稿报告（ch_001/…）
└── memory/            ← session-log / author-direction / continuity-catch
```

## 各目录谁写谁读

| 目录 | 谁写 | 谁读 |
|------|------|------|
| `book.yaml` | 人 | 主编 |
| `novel_state.yaml` | 主编（每章定稿后） | 主编 / Writer / Reviewer / Inspector |
| `world/` | WorldBuilder + 人 | 主编拼上下文 |
| `outline/` `volumes/` `beats/` | Outliner + 人 | 主编 / Writer |
| `chapters/` | Writer | 主编（拼前文）/ Inspector |
| `reviews/` | Reviewer / FormatChecker / Inspector | 主编 |
| `memory/` | 主编 + 人 | 主编（每次会话开始） |

## 注意

- `world/` 的字段规范以 `_templates/schema/` 为准
- 一本写完的书 **不要删**——把 `book.yaml` 的 `status` 改成 `completed` 或 `archived`，换 `BOOK_DIR` 写下一本
- 正文版本管理交给 git（不再需要 `originals/revised/final` 三层副本）
