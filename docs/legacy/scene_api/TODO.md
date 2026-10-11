# Scene API v2 TODO

> Historical checklist. Keep for planning history only; use the current architecture and plans docs for active work.

## Phase 1: 规范与模型
- [x] `README.md`：目标、范围、术语、系统边界
- [x] `SCENE_MODEL.md`：实体/关系 schema + 示例
- [x] `SCENE_VERSIONING.md`：版本规则与并发语义

## Phase 2: Query 协议
- [x] `QUERY_API.md`：6 个 query endpoint 的 I/O schema
- [x] `PLACEMENT_QUERY.md`：candidate 评分、解释字段定义
- [x] `SPATIAL_CONSTRAINTS.md`：挂载/净空/遮挡/覆盖约束定义

## Phase 3: Action 协议
- [x] `ACTION_API.md`：validate/execute 同步事务协议
- [x] `ACTION_TYPES.md`：`set_state/set_transform/set_sensor/highlight` 的强类型参数
- [x] `TRANSACTION_RULES.md`：strict 执行与回滚语义

## Phase 4: 错误与可观测性
- [x] `ERROR_CODES.md`：错误码、触发条件、修复建议
- [x] `EXECUTION_REPORT.md`：执行报告规范与示例
- [x] `OBSERVABILITY.md`：日志字段、trace_id、诊断建议

## Phase 5: 场景案例与验收
- [x] `SCENARIO_FRIDGE_WALL_SENSOR.md`：冰箱旁墙面贴装完整流程
- [x] `ACCEPTANCE_TESTS.md`：验收用例与通过标准

## Next Implementation Tasks (Code)
- [ ] Define C# DTOs under `VsensAgent/Assets/VsensAgent/SceneApi/V2/Models`
- [ ] Implement `SceneRegistry` with stable ID resolution
- [ ] Implement `SpatialQueryService` with surface extraction and candidate scoring
- [ ] Implement `ActionValidator` and `TransactionExecutor`
- [ ] Expose query/execute bridge in `WsClient` message routing
- [ ] Add integration tests for acceptance scenarios
