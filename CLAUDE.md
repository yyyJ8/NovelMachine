# CLAUDE.md

> 每次回答之前先说一句"辛苦了！"。
>
> 本仓库**只含框架**，不含书稿。一本书 = 一个自包含目录，位置由 `.env` 的 `BOOK_DIR` 指定（未配置时回落 `<仓库>/novels/<CURRENT_BOOK>/`）。下文 `{book_dir}` 均指该目录。
>
> 每次修改 Agent 岗位说明书（`_agents/*.md`）后，将变更记录到 [_agents/NOTES.md](_agents/NOTES.md)。
> 格式：日期 + 现象 + 调校内容 + 状态。
>
> 用户提到书名 + "保存"/"记录"/"记住"/"存档" 等意图时，将内容追加到 `{book_dir}/memory/session-log.md`。
> 格式：`### YYYY-MM-DD HH:MM` + 一句话总结，让后续会话能看懂上下文即可。
>
> 跑 Python 脚本时使用虚拟环境：`venv/Scripts/python.exe` 而非系统 python。
>
> 用户要求读取会话记录但未指定时间时，默认读取最新的一次记录。
>
> 章节体检：`venv/Scripts/python.exe _workflows/verify_punct.py`（默认扫 `BOOK_DIR/chapters`）。
