# Clarification Node

`clarification` 只负责把可澄清的缺失信息转换成用户可回答的问题和候选选项。

当前主要场景是双人比较缺少明确的两位候选人。普通上下文缺失由 validator 判定失败，
不会在这里猜测用户指代。

输入来自 plan/execution/answer errors；输出写入 clarification question/options。该节点不调用
工具、不修改计划、不生成业务答案。
