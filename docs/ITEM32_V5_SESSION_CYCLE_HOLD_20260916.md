# Item32 — Sep16会话恢复及原V5周期HOLD

## 真实结果

本次source `92dad8668d1c6d7fc435dba451745d679a5cf8ee`，唯一窗口14:30–15:30UTC，
启动严格早于15:10；原执行器于14:30:45.413549UTC退出2，`worker_failed`，admission HOLD。
不重放该身份，不将成功登录或HTTP200计作Item32完成。Readiness仍32/37。

- 本人安全保存已收到；原F会话绑定及14:07实际镜像断网加载通过，17条Cookie。
- 14:30:29.147645UTC原只读DB probe证明当时fresh0/34、active0、blocked0、写入0。
- DSL初始化1次及session初始化1次；session HTTP200/code0/success=true。
- 10次homefeed HTTP200/code0/success=true；首homefeed通过可用标题结构检查。
- 第11采集`search_recommend`在14:30:43.497731UTC返回HTTP200、`success=true`、
  integer code1000、1490bytes，无已知restriction tag/嵌套错误码。
  本地适配器以`remote_business_error`停止，阶段及原业务码完整留存。
- 合计13次物理HTTP=2初始化+11采集；10采集succeeded、1failed，未知0、自动重试0。
  本日理论余量23不满足另一个fresh0/34周期，不能用生产DB中的attempt0清除隔离台账11。
- 14:30:45.222196UTC原after probe再次证明server read-only、write/tuple_write0、
  xid未分配、ROLLBACK完成，与before同DB身份摘要；生产业务表无本次采集写入。
- 14:40:08.374695UTC最终读回：原unit inactive/dead/disabled、PID0/no job，
  任务容器及临时runtime目录均无残留；新会话配置保持，旧11份失败记录字节不变。
  网络/供应商增量费用未核实，保留UNKNOWN，无新模型/云资源/订阅或公开支付操作。

## 原因与准确边界

固定上游[cv-cat/Spider_XHS 7077c88原端点](https://raw.githubusercontent.com/cv-cat/Spider_XHS/7077c88f82771f547cc1afdadaec4025be2355e6/apis/xhs_pc_apis.py)
`get_search_keyword`以响应success判断，没有要求业务码必须为0。
NoteAI通用校验、V5后续校验、物理证据终态校验均额外限制code0，造成此次本地拒绝。
这不等于已获官方1000成功码说明；原1490bytes只保留了脱敏元数据，推荐词列表实际有效性UNKNOWN。
不得回填列表有效、把原failed改成succeeded、推断账号冻结，或重写旧Sep15未知根因。

必要局部修复进行中：仅推荐端点承认严格success和已识别typed code、保留原code1000，
还需实际data.sug_items及可用词结构，源提取限定该列表；其他端点/Tracking原约束保持。
适配器、安全计数投影与原终态校验需一致。测试只验证修复，不代替新真实周期。

## 原记录及恢复

原stage `/var/lib/noteai/item32-v5-package-20260916-92dad86`；
work `/var/lib/noteai/item32-v5-successor-20260916`；run `run-xu3tvxz7`。

| 原文件 | SHA256 |
|---|---|
| item32-admission.json | ba7bdfa68bfd6a13677f59e1269ee90f84a1baff74c7a5db13c5644b6a007f48 |
| worker-receipt.json | be21b73ee8b6c5050385964e084e1ce362d09a1b47c83520da800f0e6d05fd92 |
| task-store/hot_keywords.db | 38ec566db889f9202a5f6f828cb79a0bfbc0d78ee5e8761a2ff3ed90e9afcbc9 |
| database-before-probe.json | 75400e70a94e11103ce99f0e358eb4934a7121a189c116e902a5cb24dfec257b |
| database-after-probe.json | 9286c495c6c89e9f274b63024aa4ccc4ef18759c261ce57f602bfa9eac167530 |
| dispatch.log | f56f6676e971d9ea38701a2af772d7d2c6f0a676b746fb7493686943c77275b9 |
| hold-final-readback.json | b7c11b3013849ab1370d96fb36118cc710b02ecb1cd8113f8945ece01b45a4e2 |

最后一份2386byte原字节已核SHA保存于本机私有owner-save目录，含本次9原文件完整摘要与实际停止状态；
原SQLite、回执和独立before/after proof保留在F，不导出原供应商响应或凭据。
原executor `--v5-readback-only`显示`UNKNOWN_HOLD`，因失败没有candidate，**不是未知供应商结果**；
物理观察13/13闭合且admission未知计数0。它的runtime_state=NOT_READ已由单独实际恢复读回补证。

下一周期最早进入Sep17UTC；先完成兼容修复及新计划前驱绑定，明确保留这次11admissions/13HTTP。
旧work即使跨日也不可重放；下一个唯一入口须真实核新UTC桶与全部已封存记录，并重新证明fresh0/34。
Item33等待真实Item32终态及下一UTC桶；36/37/38沿原依赖，不创建空转资源。
