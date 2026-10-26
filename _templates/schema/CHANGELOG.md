# Schema 变更日志

## 2026-08-12 — v1.2

**修改范围**：6 个已有模板

| 文件 | 变更 | 原因 |
|------|------|------|
| `character-schema.yaml` | 新增 `beasts: []` 关联字段 | 和 `beasts.yaml` 的 `contract_owner` 形成双向关联——formations/artifacts 已有双向，灵兽不应例外 |
| `formations.yaml` | `deployer` → `deployed_by`；新增 `known_by: []` | 查"守山大阵归哪个宗门"不再需要从 sect-config 方向查找——阵法自身持有反向指针 |
| `realm-system.yaml` | `physique_system.list` 删除 `owner` 和 `awakened` | 全局体质目录只存定义（名称/等级/能力），角色持有/觉醒状态统一在 `character-schema.yaml` 填写——单一权威源 |
| `sect-config.yaml` | `缺陷` → `defect` | 全 schema 统一英文键名 |
| `novel-state.yaml` | `foreshadowing` 新增 `hook_ref` 字段 | 和 `character-schema.story_function.hook` 联动：hook 是伏笔声明，foreshadowing 是伏笔追踪，`hook_ref` 做桥接 |

---

## 2026-08-12 — v1.1

**修改范围**：5 个已有模板 + 1 个新增模板

### 修改

| 文件 | 变更 | 原因 |
|------|------|------|
| `realm-system.yaml` | `world_rules` 硬编码列表 → `world_rules_ref: see world-structure.yaml` | 与 `world-structure.yaml` 重复定义，统一由后者持有 |
| `items.yaml` | 法宝/武器/丹药/符箓 加 `made_from: []`；灵材 `use` 改为列表并加 `used_in: []` | 跨表关联——丹药用灵材炼、武器用灵材铸，AI 查表时能追溯成品↔原料 |
| `character-schema.yaml` | `motivation.phase_1/2/3` 从裸字符串改为 `{goal, trigger_chapter}` 结构 | motivation 和章节号挂钩，novel-state 写到对应章时自动触发弧光检查 |
| `character-schema.yaml` | 新增 `formations: []` 和 `artifacts: []` 关联字段 | 反向指向 `formations.yaml` / `items.yaml`，角色持有什么一目了然 |
| `sect-config.yaml` | 新增 `formations: []` 字段 | 宗门拥有的阵法，指向 `formations.yaml` |

### 新增

| 文件 | 说明 |
|------|------|
| `events.yaml` | 关键事件模板——含参与者/因果/伏笔/物品/地点/境界变化，粒度远超 `novel-state.yaml` 的 `key_events: []` |

---

## 2026-08-12 — v1.0

初始创建 8 个通用修仙小说配置模板：

| 文件 | 覆盖维度 |
|------|----------|
| `character-schema.yaml` | 角色（9 种 role_type + 灵根/体质/境界/功法/技能） |
| `realm-system.yaml` | 境界体系（九境 + 金手指 + 体质体系 + 世界规则） |
| `world-structure.yaml` | 世界观（势力 + 跨区域 + 地点 + 秘境 + 上界） |
| `sect-config.yaml` | 宗门配置（权力结构 + 弟子等级 + 功法 + 外部关系） |
| `items.yaml` | 器物（法宝/武器/丹药/符箓/灵材） |
| `beasts.yaml` | 灵兽/妖兽/神兽 |
| `formations.yaml` | 阵法/禁制 |
| `novel-state.yaml` | 进度追踪（分章状态 + 角色状态 + 伏笔 + 灵脉） |
