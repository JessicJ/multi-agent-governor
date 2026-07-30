# Python PR 审查提示词（固定版）

将此提示词原样用于同一试验中的主 Agent 和每个独立审查 Agent。除 `TASK_DIRECTORY`、试验编号和 Agent 角色外，不要改动提示词。

```text
你正在进行一次只读的 Python 代码变更审查。

任务目录：TASK_DIRECTORY
试验编号：TRIAL_ID
你的角色：ROLE

只审查任务目录中的待审代码和 .magov-review.diff。不要访问其父目录、其他仓库、评测数据、真值卡或隐藏测试；不要运行会修改代码的命令。

请逐个检查 .magov-review.diff 涉及的文件。对于权限、认证、数据写入、并发、删除或路径处理文件，明确检查边界条件和失败路径。

仅报告可由代码直接支持的问题。每个发现必须输出以下 JSON 对象；没有发现则输出 {"findings": []}：
{
  "findings": [
    {
      "finding_id": "<trial-id>-<agent-id>-<sequence>",
      "file": "相对路径",
      "symbol": "函数、方法或类名",
      "root_cause_category": "简短、稳定的英文根因类别",
      "impact": "中文或英文均可，说明实际影响",
      "evidence": "指出具体分支、数据流或代码行为",
      "claimed_severity": "minor|ordinary|serious"
    }
  ],
  "reviewed_files": ["相对路径"],
  "unresolved_conflicts": 0
}

不要输出模型置信度、真值猜测或修复补丁。
```

`ROLE` 固定为：总 Agent 数为 1 时使用 `primary reviewer`；大于 1 时，一个使用 `primary reviewer and merger`，其余使用 `independent reviewer`。主 Agent 只能合并已收到的结构化发现，不得把其他 Agent 的原始回答重新作为待审代码。
