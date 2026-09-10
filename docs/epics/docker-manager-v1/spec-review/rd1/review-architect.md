# Rd1 架构师透镜审查报告 (review-architect)

> 透镜: architect · 轮次: rd1
> 隔离声明: 仅读 spec.md + scope.md，未读其他透镜 review。
> 降级说明: 单会话 GUI 环境，由作者窗口代执行架构师透镜（用户已确认方案 A）。

## 审查发现

### 无 BLOCK 项

### WARN

A1 | spec.md:L62 | 技术决策缺失 | §3 声明无持久化数据，但文件拷贝(D4)需写后端临时目录，属有状态IO；"用后清理"未定义谁来清/何时清/失败残留兜底 -> 违反铁律7(延期写下来)
建议: §3/§4 补临时目录创建与清理策略（启动清 / TTL / 下载完成即删 / 残留预案）并命名负责模块。

A2 | spec.md L2 D2 | 技术决策缺失 | socket 直连具宿主机完全权限，风险表对策"仅受信任环境"过笼统
建议: §6 落地可执行对策：仅限 localhost 暴露、禁止映射 0.0.0.0 公网端口、compose 注明。

A3 | spec.md L4 | 架构图缺失(铁律6) | 数据流只有表格，无模块边界/架构图
建议: spec 补 Mermaid 或文本模块图，标示 backend(router->services/docker.py->docker SDK->daemon) 与 nginx/前端边界。

### INFO

I1: 无平台自身健康检查契约(/api/health) -> plan 阶段加，供 compose healthcheck。
I2: 前端容器状态刷新方式未定(主动刷新 vs 非阻塞变化通知)，v1 手动刷新可接受。
I3: 未设计多主机(P1)，符合 YAGNI；无越界决策，越界评审通过。

## 结论
架构方向合理，无 BLOCK。3 WARN + 3 INFO 均不阻塞关闭。建议修订接受 A1、A2(spec 内补可执行单行对策)。