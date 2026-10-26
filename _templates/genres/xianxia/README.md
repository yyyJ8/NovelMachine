# xianxia/templates/ —— 写作字段参考（非权威）

> ⚠ **权威 schema 在 `_templates/schema/`**（character-schema / sect-config / items / beasts / formations / realm-system / world-structure / novel-state）。
> 本目录仅作**写作时的字段清单参考**，不参与代码摄入，也不被 Agent 说明书引用。

## 与 _templates/schema/ 的关系

| 本目录文件 | 对应权威模板 | 说明 |
|-----------|-------------|------|
| character-fields.yaml | `_templates/schema/character-schema.yaml` | 角色字段（本目录偏写作速查：identity/static/dynamic） |
| faction-fields.yaml | `_templates/schema/sect-config.yaml` | 势力/宗门字段 |
| item-fields.yaml | `_templates/schema/items.yaml` | 物品/法宝字段 |
| location-fields.yaml | `_templates/schema/world-structure.yaml` | 地点/秘境字段 |

## 使用约定

- 开新设定时，以 `_templates/schema/` 的结构化模板为准写入 `{book_dir}/world/`；
- 本目录字段清单可作写作时快速检查（如角色的 primary/secondary 外貌特征、物品的 usage_limit/cost）。
- 本目录文件为 `.yaml` 格式，摄入时不会被加载（loader 只收 .md/.txt/.pdf），不会污染 RAG。
