# Risk Register

Last updated: 2026-07-30

## Critical Risks

### Complete first commercial launch is not yet releaseable

- 状态: Open Critical under `PROD-COMPLETE-FIRST-LAUNCH-001`; current release decision is `NO-GO`.
- 风险描述: 产品负责人已正式决定首次公开生产切流必须同时包含 XHS Trends、Tracking 和现有全部首发商业能力。Durable AI、私有存储/恢复、provider-isolated支付合同及Adapay离线适配器/专用运行时仓库门禁已经通过，但商户/真实mock兼容、生产对象存储/PITR、真实queue/dispatcher/processor、Tracking/Trends managed runtime、真实 XHS/AI 供应商、100任务容量、合规、ALB/TLS/监控/Smoke 等门禁尚未全部通过。任何把功能标为 `DEFERRED`、隐藏入口或先切 DNS 的做法都会违反产品范围且掩盖发布风险。
- 可能后果: 残缺商业版本、不可恢复或重复扣费、供应商/支付/隐私事故、真实用户暴露以及错误宣布上线完成。
- 建议验证方式: 以当前Handoff和readiness manifest的已验证依赖图为权威顺序；每个首发必需项必须有独立证据并达到 `VERIFIED`，且没有未接受的 Critical/High，才能申请 `PROD-FIRST-LAUNCH-DNS-CUTOVER-001`。
- 产品合同进展: `PROD-FIRST-LAUNCH-PRODUCT-CONTRACT-001` 已由产品经理总监独立审查并由产品负责人批准，状态 `VERIFIED`。H17–H22/R22及最终隔离PostgreSQL rehearsal/R23均为`PASS / 0C / 0H / 0M`。Tracking、Trends、Durable AI、私有存储/恢复、支付、UI/Admin及角色合同均为仓库/隔离`VERIFIED / NOT DEPLOYED`。当前源码候选为精确`b55f11882100e9ef919522540729e366a511f88f`；GitHub原生、隔离builder、五角色AMD64/SBOM/VEX、五个私有ACR immutable manifest及控制面digest绑定均已独立验证，精确API镜像现已分别部署并独立验收于API-C与API-F；Admin当前版本及其余运行时尚未部署。
- 当前量化状态/下一步: fail-closed ledger为仓库/隔离`12/12=100%`、内部生产部署`19/29=66%`、完整公开上线`19/38=50%`。最近计分完成项是`api_f_current_release=VERIFIED`；schema/roles、managed secrets、private storage及API-C/Admin peer均已在API-F Stage C保持非回归。当前唯一串行任务是`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`：必须从新鲜Admin前态部署精确Admin镜像与专用角色，完成loopback、权限负向矩阵、可逆晋升、API-C/API-F独立非回归、postcheck、rollback-ready与零残留闭环；完成前不得增加第20个readiness credit。
- 2026-07-30 Admin-only builder availability: fresh实例详情证明隔离AMD64 builder已因账户余额不足停止，故不再是Cloud Assistant可执行目标；持久磁盘和历史Build10/发布证据未被删除或覆盖。该builder无RAM role/key pair，未尝试启动、充值、创建凭据、执行命令、变更Registry endpoint或push。本机Docker daemon与Colima同样未运行，依据项目规则未在无确认时启动，arm64本机也不作为native证据。当前先以既有GitHub原生x86_64、固定Syft/Trivy和零Registry权限路径生成精确5335的Admin-only十一文件证据；default `main`不含该workflow，故独立审查拒绝不可触发的manual-dispatch假设。修正为feature-branch一次性added-path request：event、branch、exact commit、request内容/hash和五项false授权均在build前fail closed，普通push仍保持五角色与旧artifact名。该路径不等于私库发布或部署。生产API-C/API-F/旧Admin未触碰，readiness仍`19/29`。
- 2026-07-30 Admin evidence V1触发偏差: 唯一push run `30549134106`的构建/扫描/上传步骤完成，但实证GitHub在checkout前把`github.event.head_commit.added`表达式求值为false，工作流静默回落到controller commit `e7766ab`的五角色路径；下载包为43文件、五角色、无Admin control block，故只作为失败诊断，绝不作为精确`5335bda` Admin证据或readiness credit，也不盲目rerun。Registry/部署/数据库/服务/供应商/公开流量写均0。V2改为先checkout controller，再由真实Git对象强制单父、唯一新增非rename request、regular blob、精确十键schema2、固定SHA-256、`5335bda`祖先和唯一addition history；任何歧义直接失败，随后才第二次checkout精确release。V2 request SHA-256为`c5bd56148af0d780d3955ebb9ed5dafe0c7507ba6974da86b5830323c77009ef`，尚未push/run，readiness仍`19/29`。
- 2026-07-30 Admin exact 5335 native source candidate完成: V2 controller `e7039a3`本地exact resolver与唯一远端run `30550548144`均通过双checkout/control/build/scan/upload；唯一失败是保留的raw 0C/0H gate。下载artifact为精确11个regular files，summary SHA `19cbf144…38f7`，新Admin local ID `sha256:9ab915…d8cf7`且区别于两套b55身份；linux/amd64、noteai、OCI/role/entrypoint/CMD、Buildx/Trivy/RootFS/base-index均交叉一致。23行raw findings与b55完全相同（4C/19H，fixed-version空），secret/browser/forbidden OS均0，cryptography48.0.1恰1；image-context delta仅`model/crawler_config.json`。Secret-free GitHub receipt、新Admin-only VEX/review/verifier已由production gate `110/110`绑定，独立内容blocker0。该证据仅接受source candidate：registry digest为空，publication/deployment/database/service/public authorization全false，历史b55发布授权不复用；readiness仍`19/29`。下一硬阻塞仍是隔离AMD64 builder余额不足/停止，须先建立新的funded native publisher与单次不可变Admin tag证据，才能进入V3 canary。
- 2026-07-30 Admin发布替代路径只读审计: GitHub仓库/分支环境无ACR、Aliyun或OIDC发布凭据名，现有artifact仅含证据而无可中继OCI镜像；规范明确禁止API-C/API-F承担build，且两者现有证明仅覆盖private pull；本机为arm64、Docker/Colima停止且无private ACR路由。故当前不存在不增加权限或费用的合规publisher替代。唯一最小外部动作是补足既有PAYG隔离AMD64 builder余额并明确授权一次有界启动/按量费用；在此之前不启动本机Docker、不改生产节点职责、不开放Registry公网端点。
- 2026-07-30 Admin Stage C truthful-status blocker: Admin V1在任何连接或容器创建前因执行器误用`source/target`解析已证明的`type/src/dst` mount而失败并完成abort；隔离V2修正后canary start/identity均PASS。V2唯一ACL事务的392个表、完整列、15个序列、角色/ownership/function/default-ACL/database/schema/RLS-policy-name与回滚门禁均通过，唯一失败是错误要求`system_settings`恰有`model_registry/crawler_config`两行；生产runtime窄查询合法返回0行。版本化migration从未seed这两行，PostgreSQL合同允许1行，生产restricted read明确允许0行并禁止lazy write，因此不得以生产INSERT或ACL变更掩盖validator false-negative。V2已abort且旧Admin正式服务健康、canary/session/token/监听残留0、readiness仍`19/29`。独立源码审计同时发现真正的Admin credit blocker：0行会回退镜像内`crawler_config.json`的`enabled:true`，而Tracking/Trends仍`NOT STARTED`，Admin UI会错误显示“运行中”。当前唯一任务不变，但在新Admin晋升前必须把fallback改为默认停用、加入回归测试并发布新的Admin-only不可变候选；不得seed配置、启动Crawler或伪造运行状态。
- 2026-07-30 API-F exact-current Stage C完成: 从已推送API-C checkpoint `07ddcbcc`和API-F fresh历史unit/image基线开始，API-F自身pull证据独立绑定同一精确API manifest `sha256:612a7e57…17620`与config/local ID `sha256:dd955f9e…fd53`；累计短期Registry token/login/pull为`2/1/1`，auth/RSA/ciphertext残留0。candidate从API-F原unit逐字节派生，SHA为`23750496…65c1`、仅digest与storage env两项语义变化且systemd verify通过；只创建1代canary，创建/启动/删除各1、restart0，两次三轮验收均通过。首次promotion在实际restart后遭遇容器名可见性竞态，立即恢复旧unit/image并restart一次，独立证明rollback `PASS`；修正为有界visibility poll后第二次promotion成功，随后恰好1次显式restart改变container identity并重复三轮验收。canary与formal各1次全新read-only DB session、各1次终端ROLLBACK，`noteai_app`、默认/事务只读、XID未分配、tuple/database write0、`CONNECTED_UNKNOWN=0`；未重复API-C的migration-ledger拒绝。最终API-F b55 active/enabled/200/loopback/硬化形状通过，三份managed Secret、七键storage、两项lifecycle hash不变；API-C API和Admin unit/image/container/restart0/200/loopback均非回归。canary/18000/auth/credential/task process/temp unit/established DB连接残留0，旧unit/image保留回滚；数据库/schema/role/business/object/provider/ALB/TLS/DNS/public traffic写均0。Secret-free证据与独立semantic verifier已同时接入internal与production gate；定向`45/45`、production gate`109/109`、internal `19/29`、public `19/38`、compile/JSON/diff通过。
- 2026-07-30 API-C exact-current Stage C完成: 从已推送`84be4da`和fresh历史unit/image/Admin/API-F/受保护文件基线开始，仅发放1个短期Registry token、登录1次、拉取1次；精确API manifest为`sha256:612a7e57…17620`，config/local ID为`sha256:dd955f9e…fd53`，auth/RSA/ciphertext/transport残留0。三个相同命令hash的canary generation中，首个因本地duplicate-env计数假设失败并清理，后两个均通过3轮live/ready、database/model核心检查与read-only DB状态；自动restart/盲重试0。首次promotion实际重启后因错误要求durable-worker-only键触发强制rollback，旧`872c44e8…25` unit和`b1983bab…fedb` image恢复并健康；修正纯本地validator、完整rearm后同一candidate成功晋升，candidate unit SHA为`364a5e53…fc77`，随后恰好1次显式restart改变container identity并重复3轮验收。独立postcheck保留0-byte `PRE_CONNECT`工件、1次`CONNECTED_KNOWN / READ_ONLY_REJECTED / ROLLED_BACK / WRITE 0`的schema ledger最小权限拒绝，以及全新范围的1次read-only runtime session/ROLLBACK，验证`noteai_app`、默认/事务只读、XID未分配、transaction tuple write 0；`CONNECTED_UNKNOWN=0`。pre-cleanup `15/15`、final `11/11`，所有本地false-negative和cleanup allowlist/self-observation失败均append-only保留且无额外服务/DB动作。最终API-C exact b55 active/enabled/200/loopback/硬化形状通过，canary/18000/auth/credential/task script/process/temp unit为0，旧unit/image保留回滚；Admin与API-F fingerprint/restart0/200/loopback、managed secrets/storage/lifecycle hash均不变。新鲜RDS为Running PostgreSQL16、VPC/Intranet、Private1/Public0、账户`8/1/0`、窗口内8份成功automated FullBackup Snapshot且最新约18h；生产VPC ALB0。数据库/schema/role/business/object/provider/ALB/TLS/DNS/public traffic写均0。Secret-free证据为`deploy/production/evidence/production-api-c-current-release-verified-20260730.json`，独立semantic verifier同时绑定internal与production gate，Stage B deployment/canary=false原样保留；定向`43/43`、production gate`108/108`、compile/JSON/diff通过。
- 2026-07-29 V5生产schema/role完成（覆盖上一条旧量化状态）: 从`93d5d3b`精确构建并远端核验25源码+manifest、16 migrations、68,915-byte包；备份、私网、`3/1/0`、零残留及API-C/API-F/Admin门禁通过后，创建1个短期Super账户与API-C-only RSA。唯一pre-dispatch以1次强制只读连接/终端ROLLBACK/WRITE 0重证`0001`–`0008`、30表、5序列、两项accepted-risk和retention来源0。V5 apply只派发1次、自动重试0并确定`COMMITTED`，精确写`8 legacy SHA + 8 ledger + 2 seed + 0 retention + 0 existing business update`。独立forced-readonly outcome确定`COMMITTED`并验证`0001`–`0016`、16/16 SHA、56表、5序列、8角色、6个新NOLOGIN角色、7 memberships、6 owner-management edges、3136 table checks、419456 column checks、120 sequence checks，以及grant option/default ACL/owner mismatch/unexpected membership/elevation/app high-privilege inheritance均0。两项历史角色状态继续为零credit `ACCEPTED_RISK`，绝不标记`VERIFIED_FIXED`。结果先保存hash后，短期账户一次删除恢复`3/1/0`；API-C/Cloud Shell任务文件、RSA/密文/source/sentinel/result/error/container/process/变量全0，API-C/API-F/Admin仍active/ready/loopback-only。Secret-free证据为`deploy/production/evidence/production-schema-roles-v5-owner-committed-20260729.json`。当前内部readiness为`15/29=52%`、公开readiness为`15/38=39%`；schema apply、V3B、V4、004、005均永久no-retry。唯一下一任务为`PROD-FIRST-LAUNCH-MANAGED-SECRETS-001`。
- 2026-07-29受管Secret源码门禁: 新链路将生产初始LOGIN精确限制为Admin Runtime、AI Worker、Payment、Trends、Tracking五角色，Dispatcher因无独立消费者继续NOLOGIN；一次有界事务只允许5个LOGIN属性和5个密码写，membership/ACL/schema/业务行写固定为0。API-C先本机root-only staging再执行该唯一事务，API-F仅接收RSA-OAEP-SHA256+AES-256-GCM信封；XHS legacy值只在API-F内存中拆入两个最终0600文件，验证后删除，不经过Cloud Shell或非XHS角色。原子promotion保留显式rollback，最终7个连接均为forced-readonly；长期rotate/revoke包装器为root-owned 0750、stdin-only并要求旧凭据认证拒绝，且不启停服务。聚焦46/46、组合47（本地PG门禁skip）和独立PostgreSQL16 1/1通过，证明五角色登录、旧密码拒绝和NOLOGIN吊销；一次性容器删除且Colima恢复停止。三个测试非零均在生产连接/事务/写入0时归类PRE_CONNECT并已实质修复。生产尚未执行，readiness保持15/29=52%；必须先checkpoint/push精确源码，再刷新备份/私网/3/1/0/零残留/API/Admin基线，最多执行一次生产角色事务。
- 2026-07-29受管Secret真实前态窄修正: 新鲜控制面只读确认1个私网运行RDS、公网入口0、7份成功备份且最新小于13小时、账户`3/1/0`及任务对象0；API-C/API-F/Admin仍active、ready 200、loopback-only，任务根/容器/进程/数据库连接/事务/写入全0。API-F受保护键名审计证明旧`xhs.env`为root-only并仅含`noteai_xhs`数据库键，`/etc/noteai`与运行API容器内XHS cookie键均为0。该缺失不得用占位、复制或`DEFERRED`伪造：Managed Secrets仅为暂停中的Trends/Tracking创建专用数据库URL，真实XHS凭据仍是运行时激活和公开切流前的独立硬门禁。源码只新增network-none精确preflight并允许XHS最终文件在供应商凭据缺失时为数据库键单项；若旧cookie实际存在则仍只在API-F内存复制。此修正不提升provider readiness、不启动服务、不新增权限，且必须在账户/RSA/数据库动作前独立通过。
- 2026-07-29受管Secret维护镜像根因与收敛: 从当前精确源码构建的受管Secret包在API-C完成归档/manifest/hash核验后，`--network none`逐模块导入确定历史运行API镜像仅缺`cryptography`；任务账户/RSA/密文/sentinel/任务容器/5432连接/事务/写入均0，因此确定为`PRE_CONNECT`。不重建或重启现有API服务；runner与长期rotate/revoke包装器改为固定使用已通过AMD64/SBOM/VEX和唯一ACR digest验证、且含精确`cryptography 48.0.1`的current-source API镜像，并同时校验其local image ID。ACR实例只读发现唯一运行实例；一次未显式地域的临时token请求在token、pull和host action均0时返回认证失败，显式`cn-shenzhen`后只验证响应结构，不输出token。正式拉取必须使用内存token、节点临时RSA和密文传输，禁止把凭据放入Cloud Assistant命令、argv、日志或Git；拉取只增加可删除的精确Docker缓存，不部署/重启服务、不中断流量、不连接数据库。源码聚焦`26/26`及shell syntax通过；生产readiness仍为`15/29=52%`。
- 2026-07-29受管Secret生产完成: 从已推送`ee2ff4f`两次确定性构建14-member/25,588-byte最小包，archive SHA-256为`18010ee4…ec6`，zero-DSN、双节点manifest/hash、network-none import及不可变维护镜像身份全部通过。新鲜门禁证明私网RDS、公网0、48h内2份成功full backup、旧账户`3/1/0`、零任务残留及API-C/API-F/Admin active/ready/loopback-only。一个短期任务账户和3个RSA keypair经零明文文件/argv/log/Cloud Shell边界创建；pre-dispatch仅1次forced-readonly连接/ROLLBACK/WRITE 0。唯一生产事务只派发1次、自动重试0并确定`COMMITTED`，精确启用5个runtime LOGIN并更新5个密码，membership/ACL/schema/business-row写均0，永久no-retry。提交后的文件promotion因`/var/lib/noteai` staging与`/etc/noteai`目标跨挂载触发`EXDEV`，确定为`CONNECTED_KNOWN / COMMITTED`；API-C从精确加密bundle、API-F从仅加密传输在`/etc/noteai/.managed-secrets-v1`内完成一次零数据库same-filesystem恢复。API-C四连接、API-F三连接及独立全局连接均为forced-readonly，完整负向矩阵、ledger16、5 LOGIN、1 NOLOGIN dispatcher、6 owner-management edges、意外membership/elevation/ownership/业务值读取/写入均0。最终API-C 4份、API-F 3份distinct root:root/0600文件，两个节点各2个root:root/0750 rotate/revoke工具，legacy XHS、备份工件、重复/拒绝键均0；Trends/Tracking只含数据库键，真实供应商凭据仍为独立门禁。结果hash先固化后，短期账户仅1次删除请求并读回新基线`8/1/0`（3既有+5预期runtime、1 Super、0任务、0意外）；两节点任务根/RSA/密文/source/sentinel/result/error/container/process及Cloud Shell文件全0，RDS私网/备份与API/Admin非回归。仓库默认staging已改为同挂载`/etc/noteai/.managed-secrets-v1`并有回归断言，生产无需重跑。证据为`deploy/production/evidence/production-managed-secret-distribution-verified-20260729.json`；`managed_secret_distribution=VERIFIED`，内部`16/29=55%`、公开`16/38=42%`。唯一下一任务为`PROD-FIRST-LAUNCH-STORAGE-RECOVERY-RUNTIME-001`。
- 2026-07-29私有存储runtime源码收口: 从干净`e9a7a52`复核readiness为`16/29`并完成三路只读审计；V5 schema/ACL、受管Secret、不可变镜像及仓库存储合同可直接复用，本任务生产数据库连接/事务/写固定为0。审计发现Worker与对象型恢复证据CLI未调用已存在的fail-closed OSS环境初始化器；现已用最小改动让Worker所有已接受命令初始化同一RAM-role OSS adapter，让恢复CLI仅在非`--database-only` capture时初始化，verify与database-only保持对象网络0。聚焦存储/Worker/readiness `63/63`、Python compile及diff check通过；尚未进行OSS/RAM/ECS/service云变更，readiness不变。下一步先push精确源码，再用稳定CLI/Cloud Assistant刷新OSS/RAM/ECS/API只读基线；只允许私有endpoint、无静态AK、无真实用户数据、无服务重启及可清理的极小synthetic对象。
- 2026-07-29私有存储runtime新鲜只读基线与IMDS收口: 源码checkpoint `a459d81`已正常推送。应用内Cloud Shell登录过期且本机无CLI/profile，但Chrome既有认证会话可重新连接免费临时机，已明确拒绝付费NAS；未要求产品负责人登录。官方`aliyun` CLI可用且新版OSS API命令完整，未安装额外软件。只读发现总bucket 3、生产地域1、NoteAI专用0，账户级Block Public Access为false；三台NoteAI运行ECS中一台有公网地址并被排除，精确两台私网VPC API节点均无RAM role，故无角色覆盖冲突。控制面未暴露元数据token模式；仓库credentials adapter已显式`enable_imds_v2=True / disable_imds_v1=True / token 60s`。首次聚焦运行仅因旧门禁匹配单行源码而2项失败，生产/云/DB写0，确定`PRE_CONNECT`；门禁已升级为IMDSv2语义断言，聚焦恢复`63/63`。在push该加固checkpoint前不得进行OSS/RAM/ECS写入。
- 2026-07-29私有存储runtime基础设施与OSS签名根因: `42500ef`推送后已创建并读回1个私有Standard bucket、1个RAM角色和1个精确自定义策略；Block Public Access、AES256、`noteai-private/`两日生命周期/一日abort、Put/Get/Delete/List四动作、无通配资源、双私网API节点绑定及IMDSv2-required均通过，静态AK/数据库/服务部署/真实用户对象写为0。两节点当前源码镜像、root-only七键配置及network-none acceptance准备完成；绝对路径脚本漏`/app/model`曾在网络/对象连接前失败，清理后实质修复为`PRE_CONNECT`。首个synthetic Put到达OSS后返回`SignatureDoesNotMatch`，独立forced-readonly Head已确定该精确对象`NoSuchKey 404`，因此对象结果已知且无盲重试。源码与OSS规则精确证明内部metadata下划线被直接用于`x-oss-meta-*`，而OSS只允许字母/数字/连字符；最小修复仅在Aliyun Put边界将`_`映射为`-`，Get/Head沿用既有反向规范化，不改内部合同、数据库或对象键。聚焦`18/18 + 45/45`、gate`105/105`、compile/diff通过；必须先push该修复，再用exact-source overlay执行至多2个小于64字节的synthetic跨节点矩阵并全部删除。
- 2026-07-29私有存储SDK错误边界修正: metadata修复已推送为`23c6bdd`；主机直连GitHub失败在overlay/容器/对象动作前，确定`PRE_CONNECT`，随后Cloud Shell精确SHA下载并用3个Base64受限SendFile分段串行传到两节点，双节点56,490-byte装配SHA、transfer residue 0及network-none import均通过。全新random key的patched只读Head返回叶错误`NoSuchKey 404`，证明对象缺失但同时确认SDK V2的`OperationError`包装使旧`_status`读不到404/409/412，后续not-found/duplicate语义会错误失败。生产Put尚未开始，数据库/对象/服务写均0。最小修复仅有界跟随SDK `unwrap()`或异常cause并读取整数HTTP status，聚焦`63/63`、gate`105/105`、compile/diff通过；必须push并重新覆盖双节点后再运行两键只读前置。
- 2026-07-29私有存储runtime生产完成: 精确`b55f118`源码overlay在双私网API节点hash与network-none import通过；1个private Standard OSS bucket、1个四动作/零通配/精确prefix的custom policy与1个ECS trust RAM role绑定精确双节点，Block Public Access、private ACL、AES256、禁用加速、空日志目标、`noteai-private/`两日expiry/一日abort生命周期及IMDSv2-only全部独立读回。跨节点矩阵仅写2个小于64字节且不含用户数据的synthetic对象，验证双向Put/跨读、metadata/SSE、duplicate/wrong-prefix/bucket-ACL/static-key拒绝后全部删除，独立Head与prefix inventory均为0，永久禁止无冲突重跑。两节点root:root/0600七键配置、临时凭据形状、API-C/API-F/Admin active/ready/loopback-only和零任务根/容器/进程通过；RDS新鲜只读为私网运行1、公网0、账户`8/1/0`、七日成功full backup 7且最新<48h，本任务数据库连接/事务/写为0。初始签名拒绝确定为`CONNECTED_KNOWN / REJECTED / OBJECT ABSENT`且同对象重试0，其余传输/import/parser/region/quoting/UI错误均在云或数据库动作前确定`PRE_CONNECT`并实质修复，`CONNECTED_UNKNOWN=0`。Cloud Shell精确任务文件从9清到0，所有对象和临时材料残留0；聚焦`63/63`（4个显式本地PostgreSQL skip）、production gate`105/105`及compile/JSON/diff通过。Secret-free证据为`deploy/production/evidence/production-private-storage-runtime-verified-20260729.json`；`private_storage_runtime=VERIFIED`，内部`17/29=59%`、完整公开`17/38=45%`。唯一下一任务为`PROD-FIRST-LAUNCH-API-C-INTERNAL-001`。
- 2026-07-29 API-C当前镜像冲突与source-candidate收口: 已发布的`b06671f` API镜像不含生产已验证的IMDSv2-only、OSS metadata规范化及SDK包装异常状态提取修复，直接复用会回退`private_storage_runtime`，因此构成允许重建AMD64/SBOM/VEX/ACR的真实冲突。一次GitHub原生AMD64任务从精确`b55f118`构建五角色；build/inspect/SBOM/Secret/vulnerability/artifact均成功，末端raw 0C/0H门禁按预期fail-closed。43文件artifact summary SHA-256为`c6b1f206…162`；五角色base image、23条原始漏洞行、受影响包、entrypoint/CMD、平台及finding count均与已审计前态精确一致，仍为每角色`4C/19H`未抑制、Secret/browser/forbidden package为0、cryptography 48.0.1精确1。新独立verifier不改历史b066证据，额外证明镜像context仅`model/private_storage.py`与`model/durable_ai_worker.py`变化，registry/deployment授权均false；CycloneDX固定schema 0 error，定向11/11、组合29/29、production gate 106/106、compile/diff通过。本阶段阿里云registry/服务/DB/provider/公开流量写均0；readiness仍`17/29=59%`。下一步先push该checkpoint，再在已审计私网builder重建/复扫并通过一次有界私网发布绑定新digest，之后只对API-C做loopback canary与可逆晋升。
- 2026-07-29 API-C builder控制面恢复阻塞: b55 source-candidate/VEX已以`d6a06ae`正常推送。隔离x86_64 builder的唯一长调用已在此前成功派发，最后只读观测为`Running`，Syft已就绪、Trivy固定归档下载中，镜像/运行容器/数据库5432连接/registry/service动作均0。模型容量/网络中断后，应用内Cloud Shell返回`NoPermission`，Chrome中既有阿里云控制台会话也跳转登录，本机无Alibaba CLI/profile；未发送新Cloud Assistant命令，未重发构建，数据库连接/事务/写入及registry/service动作均0，故为确定`PRE_CONNECT`。交互式重新认证后必须先只读找回该唯一调用和terminal marker，禁止盲目重派；成功才进入独立证据比对和一次有界私有发布，失败则先按现有故障分级恢复确定结果。
- 2026-07-30 API-C builder中断链与Trivy缓存门禁: 既有认证会话恢复后只读找回完整控制链；最新build9已停止，root-only任务根保留，进程、运行容器、数据库5432连接、registry和service动作均为0。其状态文件只是超时前的初始六行，实际构建日志证明首个API镜像已成功导出，随后Trivy 0.72.0从官方默认镜像获取漏洞库时TCP 443超时；当前仅有1个b55镜像、7个前缀证据、无role summary/总summary，绝不等同43文件完成证据。首次接管审计因控制台表格文本折叠在连接前失败，归类`PRE_CONNECT`且无远端动作；修正后的两次审计均为只读。builder上的两份完整Trivy DB均为root-owned regular non-symlink且权限合格，但分别已超过24小时新鲜度上限且`NextUpdate`已过，`scan_ready=0`，禁止用`--skip-db-update`硬过。必须先从官方源在全新task-owned root-only缓存内取得合格DB并固定hash/metadata，再以源码树外、hash-bound continuation wrapper显式使用`--cache-dir`、`--skip-db-update`、`--skip-java-db-update`和`--offline-scan`；缺DB、过期、权限/链接异常、前后hash变化或扫描非零均fail closed。build9及其7文件/日志/局部镜像在最终证据保存前不得覆盖或清理。readiness保持`17/29=59%`。
- 2026-07-30 API-C新鲜Trivy缓存完成: 官方只读资料确认GHCR、Docker Hub与Public ECR为正式DB位置；builder匿名HTTPS探测中默认GCR镜像超时、Docker Hub不可达，GHCR和Public ECR可达。首次预取在目录/网络前因`pipefail + grep -q`终止，第二次在目录/网络前因归档保留的非root二进制UID被过严门禁拒绝，均为`PRE_CONNECT`且目标目录、进程、文件和网络请求0。独立来源证明确认build9/tools/共享缓存父目录root-only，二进制为单硬链、非链接、不可被group/world写，固定官方归档SHA精确唯一且归档内唯一`trivy`字节与当前二进制一致；纠正后的唯一下载显式使用匿名官方GHCR和全新task-owned缓存，15分钟上限内完成。独立验收确认4目录/6文件、root:root `0700/0600`、symlink/special 0，state/sidecar/metadata/SHA一致，新DB `UpdatedAt/DownloadedAt`在24小时内且`NextUpdate`未过；旧两份DB hash均未变化、日志error 0、Trivy进程0。DB SHA-256为`43c58b4f…54bfa0`，metadata SHA-256为`c22e0614…e4bb59`。该阶段只授权hash-bound offline continuation，不授权registry发布、部署、数据库、服务或公开流量；readiness仍`17/29=59%`。
- 2026-07-30 API-C build10扫描器门禁完成: b55远端source为精确HEAD，关键源码hash、原生证据脚本、Dockerfile、build9七文件前缀与API镜像身份均匹配；Git porcelain仅显示3份已物化且manifest SHA正确的LFS `.lgb`，普通diff/staged/untracked均0。宿主`python3`因版本过旧不支持future annotations而使原模型CLI预检非零，归类`PRE_CONNECT`；已存在b55 API镜像随后以`--pull never / --network none / --read-only / source ro / cap-drop ALL / no-new-privileges`的Python 3.11一次验证4/4模型工件，容器前后0、网络/数据库0。全新build10 root-only目录复制固定DB/metadata后，通过受限task-local Trivy shim对现有API镜像执行漏洞与Secret各1次；shim只接受五个固定b55角色、固定output和vuln/secret scanner，并强制`--skip-db-update --skip-java-db-update --offline-scan`。结果精确`4 Critical / 19 High / 0 Secret`，wrapper calls 2，DB与预取缓存前后hash不变。独立复核确认全部目录/文件权限、state/sidecar/report、source、链接/特殊文件0、Trivy进程0、任务/运行容器0、5432连接0。该门禁只授权在build10内执行原封不动的b55五角色证据脚本；registry发布、部署、服务和公网仍未授权，readiness保持`17/29=59%`。
- 2026-07-30 API-C build10完整构建已单次启动: 仅派发1次原封不动b55五角色原生证据脚本，使用源码树外受限scanner shim、固定新鲜DB、空Docker配置、确定性OCI元数据和硬超时；未登录/写registry，未连接生产数据库，未变更服务或公开流量。只读进度与静默诊断确认日志从8,122字节/108行增长到24,347字节/266行，已到BuildKit第16步下载Python依赖，source相关进程5、fatal 0、终态文件0、运行容器0、5432连接0；唯一`error`命中为Dockerfile内完整性校验代码文本，不是运行时失败。不得因输出暂时静默而重派；须等待该唯一调用终态并独立验收43文件后再授权私有发布，readiness仍为`17/29=59%`。
- 2026-07-30 API-C build10五角色证据独立验收完成: 原唯一调用在原生脚本完成43文件后由控制面硬超时终止，原wrapper/state/sidecar缺失，因此原调用保持`TIMEOUT`且绝不伪记`VERIFIED`；日志终止于`#28 DONE 0.0s`、fatal 0、进程/容器/5432连接0。task-owned验收不修改原始文件，前三次fail-closed分别暴露Buildx metadata为目录内预期`0644`、summary角色顺序非合同、build9因OCI-created不同而不应要求跨运行image-ID相等；三份失败state保留且未生成manifest/sidecar。修正v4与独立只读复核均验证43/43哈希、精确文件集/权限、五个唯一镜像身份、OCI/runtime-role/SBOM/report、固定scanner cache和三次失败历史；每角色仍为`4C/19H/0 Secret`，canonical漏洞语义与已审计b55一致。summary/manifest/acceptance SHA分别为`a8e1c7ca…c41d0`、`ec14390c…ca865`、`e16a3c3d…10a75`。A阶段只授权一次有界私有Registry发布，部署/数据库/服务/公网均未授权；readiness仍`17/29=59%`。下一原子阶段必须先证明五个新tag均不存在，再各push一次、读回五个唯一digest并完成新b55 Registry evidence/VEX/review；任何结果不明不得自动重试。
- 2026-07-30 API-C b55私有Registry发布完成: 控制面先证明五个精确immutable tag全部不存在、repository为private/NORMAL且TagImmutability=true；因私网endpoint配额为1，先hash-bound保存并移除production link，再建立builder-only私网link，ACR公网endpoint始终关闭且API-C/API-F保持active/ready200/loopback-only。首次publisher role因provider默认允许console login而在policy/attachment均0时删除；重建为console=false、精确ECS trust、3600秒和单repository token+pull/push最小策略，只绑定builder。CLI profile/region、local validator、首次token-response shell校验及task-local state writer的非零均发生在push前；首次token未登录/未持久化/未用于registry，所有push前错误均实质修复，控制台轮询失败仅为只读UI，绝无盲重推。五角色按固定顺序各push一次、manual retry 0；每角色push digest、retained manifest descriptor和ACR control-plane digest三向一致，五个digest唯一、NORMAL、linux/amd64，config digest逐一等于build10 local image ID且不等于manifest digest。最终tag为基线10+新增5。清理后Docker auth/临时目录、publisher attachment/policy/role、builder link/IMDS role/DNS/target ref/container/push process/5432连接均0；原production私网link已精确恢复RUNNING，API-C/API-F各私网ACR DNS1且健康非回归。19个root-only Secret-free publication文件保留14日，file/tree bytes为66,763/83,147，`SHA256SUMS` hash为`151f676b…b3ee`，链接/特殊/unsafe mode/credential pattern均0；Stage A原始bundle另为43文件。新Secret-free publication attestation分别保存local/config/push/manifest/control-plane五类独立观测并固定file+semantic SHA；`verify_b55_registry_release_vex.py`及三件VEX工件从该attestation构建，严格校验exact tag、Stage A TIMEOUT/43件/v4 acceptance、Trivy、SBOM/report、push-log、manifest、控制面及cleanup绑定并保持deployment/canary=false，历史b066文件未改。定向测试、production integration、readiness、gate 107/107及compile/JSON/diff均通过。Stage B不加分，仍`17/29=59%`；下一步仅API-C exact-digest loopback canary、可逆晋升、显式restart、独立postcheck和rollback-ready闭环。
- 2026-07-29 V5远端prepare目录模式根因: 从已推送`af58b897`精确构建的68,781-byte/26-file包在API-C的归档、manifest、runner、16 migration及零symlink检查全部通过，但首次network-none prepare在创建账户/RSA/密文/runner.env/sentinel或数据库连接前失败。独立诊断确认`PYTHONPATH`和`sys.path`正确、容器uid 999正确、生产镜像无`/task`卷冲突；宿主源码根为`0755`且文件为`0644/0755`，但归档只列普通文件，受限umask把隐含的`model/scripts/security/tools`目录建为`0700`，使容器能看到`tools`条目却不能遍历executor。所有诊断容器清零，数据库连接/事务/写入及V3B/V4/004/005重试均0，归类`PRE_CONNECT`。runner修复只在完整hash与root ownership通过后、prepare导入前把源码目录规范为`0755`，并在所有模式拒绝目录/文件权限漂移；migration、ACL、executor和auditor字节不变，新runner SHA为`5a906ce7…1ef`。聚焦`43/43`、production gate`105/105`、zero-DSN、shell及diff通过；readiness仍`14/29=48%`。修复checkpoint `93d5d3b`已推送；从该提交两次构建的精确包均为26普通文件/16 migration/68,915 bytes，archive `0624644a…9718`、manifest `9494ac7e…d9fc`、root-owned固定metadata、runner `0755`、其他文件`0644`、链接/AppleDouble 0，三分片为23,000/23,000/22,915 bytes且25/25 hash和zero-DSN通过。首次本地bsdtar固定mtime路径在归档前失败并以新USTAR writer实质修复，仍为`PRE_CONNECT`。证据为`deploy/production/evidence/production-schema-roles-v5-owner-remote-prepare-root-cause-20260729.json`与`deploy/production/evidence/production-schema-roles-v5-owner-mode-fix-package-20260729.json`；下一步清除本次PRE_CONNECT根/分片并只重做零库prepare，成功前不得创建账户或RSA。
- Schema/role执行器进展: `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`为`REPOSITORY + DISPOSABLE POSTGRESQL VERIFIED / PRODUCTION ATTEMPT ROLLED BACK / NOT DEPLOYED`。首个生产调用超时后未重试；独立强制只读审计证明新角色、新表、新权限和业务写入均为0。该次尝试的临时RDS Super账户、RSA材料及任务文件已全部清理，RDS当时恢复三账户/一Super/零任务账户。特权preflight确定根因为legacy ledger没有`sha256`而旧执行顺序先读取该列；修复后PostgreSQL 16.14从八条digestless legacy记录完成精确hash bootstrap、`0009`–`0016`、完整正负矩阵及apply-twice，意外表负向路径保持整事务回滚。成功隔离写入为8条hash backfill、8条migration ledger和2条固定seed，retention backfill及既有业务行更新为0。生产仍是`0001`–`0008`，因此本进展不提升账本分数，也不能继承为生产验收；当前恢复点和后续顺序以下一条为准。
- 2026-07-28 V3B确定性回滚: 精确25文件/16 migration包的全部hash、local zero-DSN import、remote network-none import和修复后的字节级DSN validator通过。生产runner在prepared/dispatch sentinel后返回51字节固定`execution_failed`，自动重试0；独立`default_transaction_read_only=on`审计以1次连接和终端ROLLBACK确定`database_outcome=ROLLED_BACK`，结果1410字节且SHA-256为`f7107f1c29d44904a4b71906f8f2ceead1d138685694838d396f59793baa95f3`。补充authority诊断仅有只读路径但以`UndefinedColumn`结束，数据库写入0且不得重跑。随后短期账户、RSA/密文、源码、10个本次result/error/sentinel、容器、进程及Cloud Shell文件全部清零；RDS读回3账户/1 Super/0任务账户、无公网入口、2个48小时内成功完整备份，API-C/API-F/Admin均active、ready 200、loopback-only。该事件必须标记`CONNECTED_KNOWN / ROLLED_BACK`，不得作为可重试权限。
- 2026-07-28 stage-safe authority-resolution checkpoint: `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-AUTHORITY-RESOLUTION-002`仅在仓库与一次性PostgreSQL 16内执行，数据库连接/事务/写入、云变更、服务变更、工单和公开流量均为0。执行器把意外失败固定到16个脱敏stage，连接前统一为`database_connection_failed`，保留既有fail-closed代码且不输出异常文本或DSN；`14/14`单元测试与`1/1`完整legacy first-apply/apply-twice/outcome/六负向突变集成通过，migration聚合SHA与runtime ACL字节不变，容器删除且Colima恢复停止。阿里云官方权限模型确认短期RDS高权限账号是无需工单的最小独立authority候选；它不属于runtime角色，不授权扩张`noteai_xhs`/`noteai_app`，也不授权owner变化。后继唯一任务为全新`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V4-001`：先push checkpoint及fresh只读基线，再以Cloud Assistant `SendFile`三段hash传输、一个新短期高权限账户、最多一次事务和零自动重试执行；在独立提交态核验前readiness仍为`14/29=48%`。
- 2026-07-28 V4 runner稳定化: 新增固定`prepare/preflight/apply/outcome`四模式runner；`prepare`在任何数据库材料创建前以network-none容器完成一次import，并把sentinel绑定到package manifest SHA，后三模式只接收RSA-OAEP-SHA256解密到stdin的短命值，环境、argv和日志留存为0。Outcome auditor新增显式受保护参数路径且不改变默认兼容接口；runner对成功apply只接受精确`8 SHA backfill + 8 ledger + 2 seed + 0 retention + 0 existing business update`，任何连接后非零结果均自动重试0并转入独立outcome判定。`28/28`runner相关测试、`37/37`schema/outcome/readiness、全量`1035/1035`（25 skip）、production gate`105/105`及shell/compile/diff均通过；migration与runtime ACL字节继续不变，生产/云动作仍为0。
- 2026-07-28 V4最小包闭包: 首包的显式包内zero-DSN import发现遗漏只读preflight模块及其固定registry evidence依赖，确定为`PRE_CONNECT`，账户/数据库连接/事务/写入/云变更均为0。经实质修复后，仅从已push的`8f6b8b68e24726ab6a57abfb805b9fd222238d0f`重建为26文件（含manifest）、25/25 hash、16 migration、64,252字节的metadata-free ustar；两次确定性构建SHA均为`0e16fd34404319902b1f15b9b1bccce6394f0ade5fb09ca0dd3979e1158bac5a`，AppleDouble/非常规成员0，三个分片最大23,000 raw/30,668 Base64字节且包内zero-DSN import通过。该结果只完成本地传输前门禁，不提升readiness；仍须fresh云只读基线、远端hash/network-none prepare、受保护短期账户、一次有界事务和独立outcome验证。
- 2026-07-28 V4生产确定性回滚: fresh控制面、远端25/25 hash、network-none import及受保护RSA-OAEP-SHA256传输均通过；强制只读pre-dispatch以1次连接和终端ROLLBACK重证精确`0001`–`0008`、30表、5序列、retention来源0、两项accepted-risk精确现状及ACL mismatch/grantable 0，结果3,853 bytes/SHA-256 `66821db9…7335`、数据库写入0。V4 schema apply只派发1次，runner返回初始`CONNECTED_UNKNOWN`和固定阶段`apply_runtime_acl_failed`，未重试；预声明的独立强制只读outcome以1次连接把结果确定为`CONNECTED_KNOWN / ROLLED_BACK / database_write=0`，结果1,410 bytes/SHA-256 `f7107f1c…95f3`。五类允许写入实际均为0，生产仍为`0001`–`0008`，readiness不加分。随后删除唯一短期Super账户、RSA/密文、包、目录、sentinel/result、容器/进程和Cloud Shell任务状态，读回`3账户/1 Super/0任务账户`及全部任务残留0；API-C/API-F/Admin仍active、ready 200、loopback-only，服务重启/部署/provider/公开流量均0。证据为`deploy/production/evidence/production-schema-roles-v4-rolled-back-20260728.json`。该V4数据库动作永久no-retry；固定阶段只授权source-level脱敏根因修复与独立离线验证，不授权另一生产事务。
- 2026-07-29 runtime-ACL精确根因与V5 owner路径: `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-RUNTIME-ACL-ROOT-CAUSE-003`仅修改仓库并使用一次性PostgreSQL 16，生产数据库/云/服务/供应商/公开流量动作均为0，V3B/V4重试均为0。PG16官方语义与独立probe共同证明：RDS高权限账户不是native superuser；NOSUPERUSER+CREATEROLE直接创建6个runtime role时，系统必然生成6条`ADMIN TRUE / INHERIT FALSE / SET FALSE`隐式管理边，旧合同加上既有accepted-risk边后从1变7，在`role_contract`即失败，尚未进入database/schema ACL。修复把事务内有效身份固定为持久`noteai_admin` migration owner，要求其精确拥有数据库及全部public对象；6条管理边固定归owner且不能INHERIT/SET，任何其他边继续fail-closed。ACL拆为10个脱敏子阶段，独立outcome新增owner矩阵，V5 runner使用全新目录并区分apply/audit事务字段。一次性PG16以非super短期executor完成首次`8 SHA + 8 ledger + 2 seed + 0 retention + 0 business update`、apply-twice五类全0、独立COMMITTED、6类负向突变全拒绝，并实际删除executor，owner mismatch/执行者ownership/残留均0。Secret-free证据为`deploy/production/evidence/production-schema-runtime-acl-root-cause-20260729.json`。此结果完成source-level根因任务但不等于生产部署，readiness仍`14/29=48%`；下一唯一任务是只读`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-OWNER-AUTHORITY-PREFLIGHT-004`，须证明生产owner/SET ROLE能力后才可建立全新V5有界事务，绝不继承或重跑V4。
- 2026-07-29 owner-authority只读链路本地checkpoint: 为`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-OWNER-AUTHORITY-PREFLIGHT-004`新增固定三查询/一次`SET LOCAL ROLE noteai_admin`/终端ROLLBACK的专用审计器，以及`prepare/audit`双模式host runner。runner的prepare先以network-none导入精确包，audit再从既有root:root/0600 Admin env以匿名stdin管道消费数据库值，不创建短期账户、RSA、密文、DSN文件或Secret环境/参数。定向`32/32`与一次性PG16完整集成`1/1`通过；首次本地观察仅因夹具未启用生产等价default-readonly而返回`CONNECTED_KNOWN / ROLLED_BACK / WRITE 0`且未进入apply，修正夹具后替换数据库通过。容器0且Colima恢复停止；生产数据库/云/服务/provider/公开流量动作仍为0。该checkpoint仅建立可审计的只读路径，不提升readiness；仍需从push后的精确源码构包、刷新云基线并最多执行一次生产只读审计。
- 2026-07-29 owner-authority生产只读已知拒绝: 从已推送`51ae877`精确构建26文件/25 hash/16 migration包；两次确定性gzip均为64,889 bytes、SHA-256 `f872ed20…4f51`，本地zero-DSN、远端`25/25` hash及network-none import全部通过。fresh控制面与host读回1个私网RDS、48h内成功full backup、`3账户/1 Super/0任务账户`、零任务残留及API-C/API-F/Admin active/200/loopback-only。004唯一audit建立1次连接及`REPEATABLE READ READ ONLY`事务，在固定`migration_owner_activation`阶段以SQLSTATE `42501`确定性拒绝：既有Admin runtime credential不能`SET LOCAL ROLE noteai_admin`；终端ROLLBACK、数据库写入/业务值读取/角色变化/自动重试均0，result为0 bytes、脱敏error为218 bytes。owner/production-state集合查询未到达，因此不伪称本轮重读ledger；rollback和write 0保持最后已证状态`0001`–`0008`。任务目录/包/sentinel/result/error/容器/进程/Cloud Shell状态随后清零，账户仍`3/1/0`且服务非回归。证据为`deploy/production/evidence/production-schema-owner-authority-preflight-known-failure-20260729.json`；readiness仍`14/29=48%`，004永久no-retry。唯一下一任务为全新`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-PRIVILEGED-OWNER-PREFLIGHT-005`：使用一个短期managed-RDS privileged account和API-C本机RSA进行独立只读能力验证；仅其通过后可开启全新V5事务，绝不重跑V4。
- 2026-07-29 privileged-owner 005本地checkpoint: 全新task/audit/run/application/account/root身份的005审计器仍固定3条集合SQL、1次`SET LOCAL ROLE noteai_admin`、`REPEATABLE READ READ ONLY`和终端ROLLBACK；明确记录004 predecessor为`no_retry`。session矩阵要求任务账户非native-super、直接`pg_rds_superuser` membership精确1、其他直接membership/owner直连membership/双向runtime membership/对象/default ACL/shared ACL与ownership依赖均0，并证明managed role到owner及session到owner的SET路径。API-C root边界先剥离Admin userinfo，拒绝query credential/host/service/options覆盖，只把脱敏topology与短期密码经匿名stdin送入审计容器；task/source/key/ciphertext权限、单硬链接、分离decrypt/audit error、结构化JSON及所有audit终态`cleanup_required=1`均fail-closed。PG16以非保留名构造等价两级SET链，session/owner/生产前态三合同`1/1`通过，终端rollback/write0，临时DB/角色/容器0并恢复Colima停止；不伪造`pg_`生产系统角色，真实`pg_rds_superuser`仍只能由005生产只读证据确认。三名独立只读auditor修改0；聚焦`31/31`、全量`1055/1055`（27 skip）、production gate`105/105`及zero-DSN/compile/shell/diff均通过。源码SHA为auditor `091a9667…c851`、runner `9ca9ad4b…c79d`，migration/runtime ACL/004源码字节不变。证据为`deploy/production/evidence/production-schema-privileged-owner-preflight-local-20260729.json`；生产数据库/账户/云/服务/provider/公开流量动作均0，readiness仍`14/29=48%`。
- 2026-07-29 privileged-owner 005远端prepare根因: 从已推送`a32cfb3`匿名精确取源构建24源码+manifest最小包，两次确定性归档一致（57,374 bytes，SHA-256 `68edfd45…18dc`），远端25文件/16 migration/manifest全部通过；network-none import仍在连接前失败。权限归一化后的新路径仍失败，专用无网络诊断随后精确确认生产API镜像内既有具体`tools`包遮蔽任务包namespace，最终为`ModuleNotFoundError`，而非hash、数据库或文件权限问题。每次均读回import/audit容器、sentinel、数据库连接、事务和写入为0，归类`PRE_CONNECT`且未重复数据库动作。最小修复只让005 runner在隔离容器显式使用`PYTHONPATH=/task/tools`并导入顶层任务模块，migration、runtime ACL、registry evidence及auditor字节均不变；新runner SHA-256为`8bd35738…9e28`，本地zero-DSN顶层import、shell syntax、聚焦`10/10`及diff检查通过。旧API-C任务根/容器/进程清零，控制面句柄过期导致一次空读亦以`InvalidDBInstanceName.NotFound`归类`PRE_CONNECT`，重新匿名解析唯一运行PostgreSQL后账户精确恢复`3/1/0`，数据库连接/事务/写入仍0。Secret-free证据为`deploy/production/evidence/production-schema-privileged-owner-preflight-remote-prepare-20260729.json`；readiness不加分，下一步必须从新push checkpoint重建并只重做零库prepare，凭据材料仍为0。
- 2026-07-29 privileged-owner 005生产只读验证完成: 从已推送`7c4204f`构建26源码+manifest、16 migration、67,915-byte确定性包，manifest SHA-256 `e359e44b…4439`、archive SHA-256 `66af35f6…0fc6`，local top-level zero-DSN、remote全部hash和network-none import通过。fresh基线为私网RDS、48h内2个成功full backup、账户`3/1/0`、API节点2且公网0、API-C/API-F/Admin active/ready/loopback-only和任务残留0。一个新短期managed-RDS privileged账户与API-C-only RSA经零明文文件/env/argv/log边界创建；005数据库审计仅派发1次，确定为`CONNECTED_KNOWN / READ_ONLY_CLASSIFIED / ROLLED_BACK / WRITE 0`，结果4,111 bytes/SHA-256 `fad95eaa…d2e`并由独立host-only validator核验完整字段。它证明executor非native-super、直接managed-privileged membership精确1、其他membership/owner/runtime/object/shared dependency全0，可`SET ROLE noteai_admin`；owner为non-super+CREATEROLE并精确拥有数据库/public对象；生产精确仍为`0001`–`0008`、30表、5序列、2历史runtime role、两项accepted-risk tuple不变、retention来源0。包闭包、manifest、自身health route、precleanup空集合pipefail及delete句柄未export等失败全部在数据库连接前独立判定`PRE_CONNECT`并作实质修复，未重跑数据库动作。结果先保存hash后清理：账户恢复`3/1/0`，任务账户/RSA/密文/source/result/sentinel/error/container/process/Cloud Shell文件与变量全0，RDS/API公网0，服务非回归。证据为`deploy/production/evidence/production-schema-privileged-owner-preflight-verified-20260729.json`；005永久no-retry且只授权全新`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V5-OWNER-001`单次事务，readiness在V5独立COMMITTED验证前仍`14/29=48%`。
- 2026-07-29 V5-owner runner稳定化: 仅修改`tools/production_schema_roles_runner.sh`及其测试，生产数据库/云/账户/服务/provider/公开流量动作均0。runner在network-none prepare与preflight/apply/outcome容器统一使用005已证明的`PYTHONPATH=/task/tools`和顶层import，消除生产镜像既有`tools`包遮蔽风险；保存的preflight和三个结果均改为结构化JSON精确校验，写入必须严格为`8 SHA + 8 ledger + 2 seed + 0 retention + 0 business update`，可执行tamper测试证明retention漂移会拒绝。task/source/key/ciphertext ownership/mode/symlink/hard-link合同fail-closed；所有prepare、PRE_CONNECT、CONNECTED_KNOWN、CONNECTED_UNKNOWN与成功终态均保持`cleanup_required=1`直到外部读回。新runner SHA-256 `790e5ad1…b10`；executor/outcome/preflight、runtime ACL `b5fc9e70…72d7`及migration aggregate `a6cc4fef…da73`字节不变；聚焦`29/29`、shell syntax、top-level zero-DSN及diff检查通过。此阶段不提升readiness，仍须从新push checkpoint构建V5独立最小包后才可创建fresh账户/RSA。
- 2026-07-29 V5-owner runner独立审计纠正: 三名只读auditor确认中间checkpoint `fa2ebae`的Python `assert`可被优化模式移除、apply/outcome矩阵覆盖不足、preflight非零分类过宽、解密与任务error合并且结果未绑定incident，因此该commit永久禁止打包。纠正版使用`python3 -I`显式fail-closed校验完整preflight/apply/COMMITTED/ROLLED_BACK矩阵，并在`PYTHONOPTIMIZE=1`下执行tamper回归；incident绑定package manifest，每个result再绑定incident/manifest/mode/hash，apply重验preflight binding，outcome重验成功apply binding。解密与任务stderr分离，成功要求两者均为0；只有结构化state-change或单行固定脱敏错误可归为已知非零，其余连接后均UNKNOWN。最终runner SHA-256 `98afd524…2be1`，checkpoint `efeb5bb`；executor/outcome/preflight、runtime ACL及16迁移聚合字节不变。focused `43/43`、production gate `105/105`、internal fail-closed gate、zero-DSN、shell syntax及diff检查通过；本阶段生产数据库/云/账户/服务/provider/公开流量动作均0且不提升readiness。
- 2026-07-29 V5-owner精确本地包: 仅从已推送`af58b89`提取25源码+manifest、16 migration，manifest SHA-256 `a49a9786…49a0`；两份metadata-free USTAR+gzip均为68,781 bytes且SHA-256 `02a01997…941b`。25/25 hash、26普通成员、root ownership metadata、runner `0755`、零AppleDouble/link/non-regular和包内zero-DSN顶层import全部通过。首次tar因目录递归造成重复成员、一次本地清理命令在启动前被安全层拒绝、一次辅助validator因引号未启动，三者均以生产连接/事务/写入、账户/RSA、云/服务/provider/公开流量全0归类`PRE_CONNECT`；只有全新普通文件归档允许后续传输。证据为`deploy/production/evidence/production-schema-roles-v5-owner-local-package-20260729.json`；readiness仍`14/29=48%`，凭据材料仍0，下一步先push证据再刷新必要只读生产基线。
- 2026-07-27安全换会话checkpoint: legacy-ledger修复已在`e5883abc01c4b009907bee550209d7036d383771`完成checkpoint并正常push。中断后的import失败均发生在`_connect()`之前，该轮没有数据库连接、事务或业务写入。为避免跨会话保留高权限材料，未使用的任务专用Super账户、API-C RSA/密文/源码目录及Cloud Shell runner/bundle已全部删除；控制面读回恢复`3账户/1 Super/0任务账户`，API-C/API-F任务目录和维护容器为0。API-C/API-F API及API-C Admin仍active、ready、loopback-only；零供应商、registry、公开流量和业务行变化。生产仍为`0001`–`0008`，readiness仍为`14/29=48%`。新会话必须从精确Git源码重建最小包，先通过无DSN import preflight，再新建短期账户并允许至多一次生产事务；任何数据库连接后禁止自动重试。
- 2026-07-27第二次安全换会话checkpoint: fresh控制面再次确认RDS备份新鲜、`3账户/1 Super/0任务账户`及API-C/API-F/Admin非回归；`e5883ab`精确21文件包的本地/解包无DSN import、48,631字节包体和SHA-256均通过。API-C临时RSA创建成功，但包体在首块精确marker不匹配时停止，未decode/extract/import；任务从未创建RDS账户、DSN、密文或`runner.env`，也未连接数据库。根因限定为云助手`CommandContent`原始文本语义及chunk模板`printf`占位符过度转义，不是产品源码或数据库失败。随后精确删除API-C任务目录/RSA/部分包体并读回任务目录0、维护容器0、API/Admin active、四探针200、8000/8001仅loopback；Cloud Shell任务文件和变量均为0。生产继续保持`0001`–`0008`与`14/29=48%`，下一会话必须先全新只读复核，再以预渲染并断言的传输脚本继续，不得继承浏览器/Cloud Shell内存。
- 2026-07-27生产UNKNOWN事件checkpoint: fresh备份、`3账户/1 Super/0任务账户`和API-C/API-F/Admin基线通过后，从`e5883ab`重建精确21文件包；首次归档因macOS AppleDouble元数据在凭据前被拒，使用`COPYFILE_DISABLE=1`重建为21普通文件/16迁移/零AppleDouble，21/21 SHA、registry、host与network-none容器import均通过。随后仅创建1个短期Super账户和3072-bit RSA，密文384字节且明文暴露/留存为0。强制只读pre-dispatch成功证明ledger精确`0001`–`0008`、pending `0009`–`0016`、legacy SHA缺失8及drift/blocker/retention/elevation为0。唯一生产apply随后返回`executor failure / database outcome UNKNOWN`，未重试；唯一独立强制只读判定也返回`UNKNOWN`，同样未重试。因此实际写入计数和当前schema状态未知，readiness保持`14/29=48%`，不得宣称回滚或提交。Secret-free证据为`deploy/production/evidence/production-schema-roles-unknown-20260727.json`。账户已读回`3/1/0`，API-C任务目录/RSA/密文/源码/runner/container与Cloud Shell文件/变量均为0，API-C/API-F/Admin继续ready且loopback-only。当前必须等待产品负责人选择新的事件处置方向；在此之前禁止任何数据库连接、apply、audit重试或下游任务。
- 2026-07-28确定性CONFLICT checkpoint: CTO获授权后新增独立outcome auditor，以精确22文件/16迁移包、network-none import和匿名OpenSSL管道执行唯一一次强制只读连接。结果为`CONFLICT`而非UNKNOWN：ledger canonical `0001`–`0008`、sha列/约束0、30表、5序列、2个legacy role、新角色/seed/retention均0，但`runtime_elevation_count=1`、双向`runtime_membership_count=1`。旧preflight虽然读取`rolinherit`，其elevated计数未包含该字段，membership也只检查runtime role作为member的单向边，因此旧“elevation/unexpected grant=0”不能覆盖本轮完整负向矩阵。审计只读、业务值读取0、数据库写入0且未重试；结果SHA为`3ebf703a…57b2`。清理读回`3账户/1 Super/0任务账户`，API-C/API-F任务目录、RSA、密文、runner、result、容器及Cloud Shell文件/变量为0，API-C/API-F/Admin继续ready且loopback-only。Secret-free证据为`deploy/production/evidence/production-schema-roles-conflict-20260728.json`；readiness仍为`14/29=48%`。
- 2026-07-28角色身份checkpoint: 独立identity auditor以一次强制只读连接把冲突精确绑定为`noteai_app ROLINHERIT`和`noteai_xhs -> noteai_admin`的唯一membership（`ADMIN TRUE / INHERIT TRUE / SET FALSE`），两endpoint均LOGIN/非superuser，ownership=0，且证明该状态早于失败schema事务。结果`1515` bytes、SHA-256 `98b188ac…eba`，数据库写入和业务值读取均为0。该次历史runner把DSN置于短命container进程环境中，持久化/打印为0，但不能作为新no-environment控制的证据；后继runner已改为stdin→局部参数。任务账户已清理；最新末态读回为1个运行PostgreSQL、48h内2个成功full backup（最新14h）、`3账户/1 Super/0任务`、API-C任务目录/sentinel/process/container全0、API-F任务目录/process/container全0、API-C/API-F/Admin active/ready/loopback-only、Cloud Shell任务文件/变量/process全0。Secret-free证据为`deploy/production/evidence/production-legacy-runtime-role-identity-20260728.json`。唯一纠正上限为1个`NOINHERIT`属性变化和1条grantor-bound membership revoke，ledger/schema/table/business row/LOGIN/password/ownership/ACL变化均为0；纠正尚未执行。候选corrector/auditor及no-environment runners已通过`35/35`五轮连续定向测试、`75/75`组合门禁和全量`1007`测试（24 skip）；测试夹具已显式消费受保护stdin以消除OpenSSL SIGPIPE竞态。
- 2026-07-28角色纠正只读拒绝checkpoint: 从`e5883ab`与`a90a2ff`精确重建25文件/16迁移最小包，25/25 SHA、无DSN import、network-none import及受保护stdin传输均通过；仅创建1个短期任务Super账户和3072-bit RSA，明文持久化/暴露为0。唯一强制只读corrector preflight建立1次连接和1次只读事务，在`database_precondition`确定性返回`CONNECTED_KNOWN / READ_ONLY_REJECTED`，事务回滚、数据库写入和业务值读取均为0；apply未执行且禁止自动重试。错误工件仅1行/214 bytes，SHA-256 `a1abd8ba…3e28`，无Secret命中；未持久化具体失败predicate，结合未变化的先前身份状态，executor capability仅为主要推断而非重试授权。随后删除任务账户、API-C源码/RSA/密文/sentinel/日志，最终读回1个运行PostgreSQL、48h内2个成功full backup（最新15h）、`3账户/1 Super/0任务`、API-C/API-F/Admin active/200/200/loopback-only、任务目录/进程/维护容器/Cloud Shell文件全0。Secret-free证据为`deploy/production/evidence/production-legacy-runtime-role-correction-rejected-20260728.json`；readiness保持`14/29=48%`。该纠正incident不得再进行数据库动作；完整恢复能力需要true PostgreSQL superuser，或同时为精确membership grantor、具备`CREATEROLE`且对`noteai_app`具备`ADMIN OPTION`的现有受保护执行身份；交互式登录或新凭据仍为产品负责人停点。依赖图中下一项安全独立任务为`PROD-FIRST-LAUNCH-MANAGED-SECRETS-001`。
- 2026-07-28受管Secret生产审计checkpoint: 新的Secret-free审计器只解析键名、root/mode/regular-file元数据和固定unit引用，`12/12`本地测试通过；生产审计对API-C/API-F各执行1次，数据库/供应商/服务/流量动作和Secret值输出均为0。现有API-C API/Admin与API-F API共3份最终命名文件均root:root/`0600`、节点内distinct、键名拒绝/重复0；API-F旧`xhs.env`同样root-only但不能替代Trends/Tracking分拆。最终7份节点文件仍缺Payment、AI Worker、Trends、Tracking 4份，两个节点rotation/revocation工具均0。API-C首个结果在外层JSON整段解析失败后从唯一任务JSON恢复且未重跑；API-F在浏览器传输超时/Cloud Shell过期前未dispatch，零目录/进程/容器读回后在新临时VM精确执行1次。证据为`deploy/production/evidence/production-managed-secret-distribution-audit-20260728.json`。由于四个缺失文件的专用`DATABASE_URL`依赖迁移`0009`–`0016`创建的最终角色，dependency已补为`production_schema_roles`；禁止用空占位或复制legacy凭据伪造通过。readiness保持`14/29=48%`。
- 2026-07-28角色恢复权限控制面checkpoint: 从已推送`d763ccc`干净基线执行`PRE_CONNECT`零数据库路径审计；RDS SQL audit为Disabled，扫描`6,060`条保留error log未发现精确membership grant，迁移窗口`1,152`条记录中runtime-role命中和相关角色共现均为0。零日志命中不证明凭据或grantor不存在，只能说明控制面无法独立证明true PostgreSQL superuser，或“精确grantor + CREATEROLE + 对noteai_app的ADMIN OPTION”完整非super能力。新鲜读回同时确认1个运行PostgreSQL、49h内2份成功备份（最近`2026-07-27T13:08:52Z`）、`3账户/1 Super/0任务账户`，API-C API/Admin及API-F API均active、live/ready `200`、非loopback listener 0；两节点任务目录/材料/进程/容器和Cloud Shell文件/变量/查询进程均0。本轮数据库连接/事务/写入、服务变更、部署、公开流量及Secret/ID/IP输出均0。一次本地JS parse和两次未闭合终端输入在`RunCommand`前停止；替换终端并改用分段内存传输后API-F只读审计仅执行1次。Secret-free证据为`deploy/production/evidence/production-schema-role-resume-authority-audit-20260728.json`。原纠正incident继续`CONNECTED_KNOWN / NO RETRY`；若不能证明现有qualifying path，RDS provider support必须实际执行精确`NOINHERIT`与grantor-bound revoke，或提供经独立验证满足完整能力的受保护路径后再建立新incident；单纯建议/许可不是技术能力或重试授权，legal review不能替代。
- 2026-07-28 provider-support intake checkpoint: 已从`4eb0be3`干净基线只读确认中国站同站主账号会话可访问真实工单创建表单，但账户未设置工单联系方式；表单强制要求手机号和验证，国际站入口也要求新登录。因此没有填写描述、选择产品/资源、输入/保存联系方式或点击提交，ticket/provider生产动作/数据库连接/事务/写入/服务变更均0，全部浏览标签已finalize。入口探测中的4个UI/导航失败均为`PRE_CONNECT`。一次过宽的只读console DOM snapshot在内部工具瞬时输出中包含账号元数据，但不含Secret、cookie、credential、私钥、连接串或用户内容，未写入Git、未进入provider ticket、未公开；随后停止full-page输出，只保留脱敏布尔/计数。证据为`deploy/production/evidence/production-schema-role-provider-support-intake-20260728.json`。产品负责人后续已明确把工单降为首发后可选修复事项，不再作为internal readiness或首次上线硬阻塞；该决定不授权新增`noteai_xhs`角色、ADMIN OPTION、DDL、角色管理或额外权限。
- 2026-07-28首发历史角色风险决定与新UNKNOWN checkpoint: 产品负责人允许首发暂时保留既有`noteai_xhs -> noteai_admin`成员关系，并只在`noteai_app`实际高权限继承为0时接受其`ROLINHERIT`；两项必须登记为零readiness credit的`ACCEPTED_RISK`，不得伪造为`VERIFIED_FIXED`。仓库已为精确两项固定risk ID实现窄范围gate支持、完整有效权限矩阵和独立只读auditor；未添加全局waiver，也未修改migration SHA/ledger。24文件/16 migration/23哈希及精确registry evidence在无DSN与network-none容器import通过，Linux干净归档为`53,830` bytes、SHA-256 `e8c9e876…40b8`、AppleDouble/symlink均0。前置目录权限、遗漏registry evidence、macOS metadata及浏览器文件选择失败均以sentinel/container/result证明为`PRE_CONNECT`并实质修复。最终唯一数据库dispatch建立连接后在`database_read`失败，结果临时文件为0 bytes、错误工件155 bytes/SHA-256 `e9efda9f…0fbb`，runner确定为`CONNECTED_UNKNOWN`；membership选项、effective privilege、`noteai_app`高权限继承、ledger、事务及数据库写入结果均未返回，严禁自动重试、schema事务或下游数据库任务，因此两项`ACCEPTED_RISK`尚未激活且readiness保持`14/29=48%`。API-C任务目录/分片/容器/进程已清零，API-C API/Admin与API-F API均active、live/ready 200、仅loopback；RDS控制面新鲜显示1实例/1运行中，但本轮未独立重证自动备份和公网入口。证据为`deploy/production/evidence/production-first-launch-role-risk-readonly-unknown-20260728.json`。一次控制台范围过宽导致瞬时内部工具输出包含云资源元数据，不含Secret/凭据/用户数据，未写入Git/工单/公开面；随后全部改为脱敏计数。仓库收口验证为定向`66/66`、全量`1020/1020`（24 skip）、production gate `105/105`，Python compile、runner syntax、JSON、Secret模式和diff检查均通过；历史e5883哈希保持不变，当前源码漂移继续在连接前fail-closed。
- 2026-07-28 CTO影响边界处置与新鲜恢复基线: 旧`production-first-launch-role-risk-readonly-unknown-20260728.json`原始`CONNECTED_UNKNOWN`、transaction/database outcome `UNKNOWN`和零自动重试全部保持不变；只因固定SHA auditor的数据库路径仅含session `SET`、`SHOW`、catalog/builtin privilege `SELECT`且runner不调用schema executor、该事件schema apply为0，产品负责人/CTO将该只读incident运维关闭为`HISTORICAL_CLOSED_BY_AUTHORIZED_IMPACT_BOUND`。全新数据库incident采用新ID、run ID、目录、application name、固定五阶段集合式SQL和独立工件，不属于旧audit自动重试。连接前fresh只读控制面确认1个运行RDS、零公网入口、48h内2份成功full backup（最新年龄界限20h）、data/log retention均14天、`3账户/1 Super/0任务账户`；API-C API/Admin及API-F API健康、仅loopback，root-owned `0600` env元数据通过，两节点任务残留及Cloud Shell任务文件均0。浏览器无登录、错误ECS拓扑假设和Cloud Assistant遗漏`ContentEncoding=Base64`等6个故障均在数据库连接/事务/写入0时定为`PRE_CONNECT`，经现有Chrome认证会话、项目+zone筛选、显式编码和隔离subshell实质修复。Secret-free证据为`deploy/production/evidence/production-schema-role-resume-baseline-20260728.json`；生产readiness仍`14/29=48%`、accepted-risk激活仍0、schema apply仍0。
- 2026-07-28 schema/role v2本地门禁: 新auditor以一次连接、`REPEATABLE READ READ ONLY`、4条固定集合式SQL和终端`ROLLBACK`读取session/ledger-inventory/role-graph/XHS ACL；PostgreSQL 16前态精确为0001–0008、30表/5序列、retention来源0、历史membership `ADMIN TRUE / INHERIT TRUE / SET FALSE`、app高权限继承0及XHS完整有效权限/grant option/default ACL差异0。写执行器已改为advisory lock优先，并在任何DDL前锁定精确ledger名、inventory、role fingerprint和retention来源0；首次隔离apply精确写8个legacy SHA、8个0009–0016 ledger及2个fixed seed，retention和既有业务row update均0，apply-twice五类写入全0。独立只读outcome要求16/16 SHA、56表/5序列/8角色、精确seed及表/列/序列/函数/default ACL完整矩阵；table grant option、column、sequence、trigger function、default ACL及extra membership六种突变全部CONFLICT/rejected，清理后恢复COMMITTED。定向`72/72`、PostgreSQL集成`1/1`、全量Python `1027/1027`（25 skip）、production gate`105/105`通过；本地任务容器0并恢复Colima停止。证据为`deploy/production/evidence/production-schema-role-v2-local-validation-20260728.json`；生产数据库动作仍0，readiness仍`14/29=48%`。
- 2026-07-28首发角色风险正式激活checkpoint: 从`5491471`干净基线构建25文件/16迁移/24哈希、无Apple xattr或symlink的ustar包（62,275 bytes，SHA-256 `84cfdea3…aa7a`），本地隔离与API-C `--network none`无DSN import均通过；新鲜RDS控制面仍为1运行实例、零公网入口、48h内2份成功full backup（最新<24h），API-C/API-F/Admin健康且仅loopback。仅创建1个短期Super账户与3072-bit RSA，明文持久化/环境/参数/日志暴露均0。唯一新数据库audit连接使用4条固定集合SQL、`REPEATABLE READ READ ONLY`并终端`ROLLBACK`，结果3,845 bytes/SHA-256 `59475549…5400`，确定为`CONNECTED_KNOWN`、数据库写入0、业务值读取0、自动重试0：ledger精确0001–0008、30表/5序列、retention来源0；唯一`noteai_xhs -> noteai_admin`边实时为`ADMIN TRUE / INHERIT FALSE / SET FALSE`，`noteai_app` incoming membership与高权限继承均0，XHS数据库/schema/210表检查/1,316列检查/15序列检查的mismatch、grantable、ownership、function与default ACL均0。raw auditor因旧指纹硬编码`INHERIT TRUE`返回`state_changed`，但其余session/ledger/XHS ACL全通过；依据产品负责人已批准的“接受精确现状”决定，两项固定risk ID现正式登记为零readiness credit的`ACCEPTED_RISK`，绝不标记`VERIFIED_FIXED`，首发后30天复核。仓库仅把precondition/outcome/gate绑定到实时`INHERIT FALSE`，未改migration bytes/SHA、未增加risk ID、未全局关闭门禁；`38/38`定向测试和一次可删除PostgreSQL 16完整apply/apply-twice/6负向突变均通过，任务容器0且Colima恢复停止。证据为`deploy/production/evidence/production-first-launch-role-risk-accepted-20260728.json`；readiness仍`14/29=48%`，因为0009–0016生产事务尚未执行。
- 生产故障分级规则: 任一非零退出先用Secret-free exact remote command fingerprint、sentinel、进程、容器、连接、事务和结果证据分为`PRE_CONNECT`、`CONNECTED_KNOWN`或`CONNECTED_UNKNOWN`。Cloud Shell、终端或控制面外层失败本身不等于`PRE_CONNECT`；读清远端状态前严禁重派。已证明连接前的传输/编码/引号/权限/路径/解包/启动/126/127错误必须清理并用实质性新方法继续，不得误停或重复原路径。若外层失败但远端已完成，必须恢复其`CONNECTED_KNOWN`结果且不得重跑。连接后确定或未知失败均禁止自动重试；只读诊断、状态读取和清理不构成重试。
- 授权边界: 产品负责人已授权CTO自行批准并持续执行达到`内部生产部署准备度100%`所需的有限、有界、可回滚任务，无需重复询问。该当前授权在此范围内取代下文历史逐项审批措辞；缺失的登录/新凭据仍需产品负责人完成交互式认证，公开DNS、真实用户流量、不可逆破坏、新产品决策、无上限费用和公开上线完成声明仍不在授权内。

### Current-source immutable release is published, not deployed

- 状态: current `b06671f` is `EXACT GITHUB SOURCE + FIVE ACR PRODUCTS VERIFIED / NOT DEPLOYED`; historical `2fa3a55` remains scoped to its old revision.
- 已关闭: exact revision `2fa3a5543876a6c8040ec17ca05a5461b101bbd7`在GitHub `x86_64` runner构建API、Admin、Payment、AI Worker、XHS五角色；普通CI通过，Secret和browser component均为0，每角色恰好一个`cryptography 48.0.1`。CycloneDX 1.6 VEX将12个Debian CVE绑定到五个local image ID、五份SBOM和115个BOM-Link。
- 原始风险未隐藏: canonical Trivy报告仍为每角色`4 Critical / 19 High`，zero-C/H原始门禁保持fail-closed；VEX只在精确AMD64 base、command graph和non-root/read-only/cap-drop/no-device合同下给出`not_affected`，不是scanner suppression、waiver、production exception或deployment authorization。
- 已关闭: GitHub workflow `30233565859`从精确`b06671f`构建五角色，普通CI、原生构建、Secret/SBOM/inspect/证据上传与CycloneDX 1.6 schema均通过；每角色仍是原始`4 Critical / 19 High`、Secret/browser/forbidden OS package为0、`cryptography 48.0.1`恰好1。
- 已关闭发布根: 隔离AMD64 builder从精确`b06671f`重建并发布五角色；ACR控制面tag/digest逐一匹配且五个digest唯一。GitHub与builder local image ID/SBOM serial明确分离；两套VEX各自保持12个disposition和115个BOM-Link。官方CycloneDX 1.6 schema为零错误。
- 清理/非回归: 一次性publisher role/policy、builder ACR link、Docker auth、临时auth目录和运行容器均为零；production保留唯一RUNNING的ACR/PrivateZone link。API-C/API-F未重启、未部署，前后loopback健康fingerprint完全匹配。零provider、零业务DB写入、零ALB/TLS/public DNS/traffic变化。
- 剩余High: 五个新digest尚未部署；生产schema/roles仍为`0001`–`0008`，`0009`–`0016`及最终roles/ACL未应用。Gate 0组合artifact已通过，但不得继承为schema migration或runtime deployment acceptance。local image ID仍不得当作registry digest，publication仍不得当作deployment acceptance。
- 防重复/回滚: 无source/base/SBOM/architecture/command/runtime/CVE-scope冲突时不得重复本构建、扫描或VEX。发布标签不可变；未部署阶段无需服务回滚。后续失败应保留历史运行digest、暂停新服务并使用已接受的旧服务配置。

### Billing or credit accounting is wrong

- 风险描述: Paid operations, monthly credits, recharge credits, refunds/topups, and token cost accounting are revenue-critical. A bug can undercharge users, overcharge users, or make admin revenue reports inaccurate.
- 涉及文件: `model/billing.py`, `model/api.py`, `model/admin_server.py`, `model/db.py`, `model/admin.html`, `NoteAI_Pro_Demo_Framer.html`, `tests/test_billing_token_cost.py`.
- 可能后果: Direct financial loss, user disputes, inability to price packages, wrong margin reporting.
- 建议验证方式: Unit tests for mixed monthly/recharge deduction, topup, refund, quota exhaustion, admin usage stats; real API smoke with a test user; compare user-side and admin-side usage rows.
- 是否需要用户确认后才能修改: yes.

### Auth/session/admin permission regression

- 风险描述: User auth and admin auth are separate。仓库UI/Admin合同已在`d358114…`把生产业务变更全部fail-closed；`9d8cd57…`完成原始低权限角色合同。真实只读预检随后证明托管RDS管理员已占用`noteai_admin`并具有管理权限，因此应用不得使用该同名角色。`PROD-FIRST-LAUNCH-ADMIN-RUNTIME-ROLE-COLLISION-001`已用新增`0016`和`noteai_admin_runtime`关闭仓库/隔离冲突，但生产仍未应用迁移/ACL或部署新镜像。
- 涉及文件: `model/auth.py`, `model/admin_auth.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`.
- 可能后果: Permission bypass, account takeover, unauthorized credit/subscription changes, leakage of user/admin data.
- 建议验证方式: 不重复已通过的仓库UI/Admin或Admin-role PostgreSQL合同。未来生产任务先只读preflight，再应用精确migration/ACL并验证loopback登录、读取、退出、失效、重启及业务零写入。
- 是否需要用户确认后才能修改: yes.
- 2026-07-26进展: `REVERIFY-009` 独立确认既有删除/租约、Admin/Tracking栅栏、H6时间合同及固定异常边界继续通过；安全+reasoning `63/63`、聚焦`114/114`、API合同`152/152`、全量`702`（跳过`5`）及就绪门禁`86/86`通过。仓库子路径仍有下面单独记录的expert结构化持久化High；真实 PostgreSQL contention、生产 migration/精确授权、供应商与受控生产验收仍为首发门禁。
- 2026-07-27进展: `PROD-FIRST-LAUNCH-UI-ADMIN-CONTRACT-001`为`PASS / 0C / 0H / 0M / NOT DEPLOYED`。完整串行Python `895`加`20`skip、E2E `68/68`及readiness `100/100`通过；无生产或外部影响，费用`¥0`。本风险保留为High仅因为精确DB角色及生产部署/运行时证据仍缺失。
- 2026-07-27角色进展: `PROD-FIRST-LAUNCH-ADMIN-ROLE-CONTRACT-001`为`PASS / 0C / 0H / 0M / NOT DEPLOYED`。Migration `0015` SHA `3ee9b85c…d66c`、实际LOGIN/session生命周期、Secret RLS、完整表列序列/角色矩阵`4/4`及全量Python `901`通过；临时资源清零并恢复Colima停止。High仅保留在生产preflight、migration/ACL/credential/image及HTTP运行时证据。
- 2026-07-27冲突修复: `PROD-FIRST-LAUNCH-ADMIN-RUNTIME-ROLE-COLLISION-001`为`PASS / 0C / 0H / 0M / NOT DEPLOYED`。新增migration `0016`不改写`0014/0015`，把Admin RLS身份改为`noteai_admin_runtime`；独立PostgreSQL Admin `4/4`、Payment `6/6`、Storage `4/4`和全量Python `945`通过，临时资源清零并恢复Colima停止。High仅保留在生产migration/ACL/credential/image及HTTP运行时证据。

### External browser CDN dependency is closed at repository level

- 状态: `CLOSED / REPOSITORY VERIFIED / NOT DEPLOYED / 0C / 0H / 0M` by `PROD-FIRST-LAUNCH-FRONTEND-ASSET-SELFHOST-001` at `22ae1e588abe7e201d9b671694203924ea391de3`.
- 已关闭: 用户前端和Admin仅从same-origin `/assets/vendor`加载固定ECharts `5.4.3`和Lucide `1.27.0`；不存在运行时CDN或浮动`latest`引用。精确上游文件、Apache-2.0/ISC许可证和SHA-256已入库。
- 证据: focused browser `3/3`、repository `10/10`、full serial E2E `69/69`、readiness `100/100`及hash/no-external-script检查通过。任务只读取公开npm metadata/package，费用`¥0`，临时打包目录已移入废纸篓。
- 剩余边界: 该提交尚未构建为新镜像或部署，因此只能关闭仓库供应链/可用性缺口，不能证明生产静态资源交付。
- 防重复/回滚: 无资产、HTML或服务路径冲突时不得重跑本任务；回滚仅撤销精确本地资源和引用，不涉及数据库、供应商或生产资源。

### Database migration or SQLite/PostgreSQL drift damages data

- 风险描述: Local SQLite and cloud PostgreSQL now share one helper surface but use different schema/migration paths. A new query can work locally and fail on PostgreSQL.
- 涉及文件: `model/db.py`, `model/hot_keywords.py`, `model/migrations/postgres/`, `scripts/render_predeploy.py`, `scripts/migrate_sqlite_to_postgres.py`.
- 可能后果: Data loss, incompatible columns, failed pre-deploy, broken API/Cron startup, partial data import if safeguards are bypassed.
- 建议验证方式: Apply every migration twice to a disposable PostgreSQL, run shared-state/trend/API/admin container probes, back up before any guarded SQLite import.
- 是否需要用户确认后才能修改: yes.
- 2026-07-26进展: additive migration `0009_account_security_compliance.sql` 仅存在于当前工作区，未对生产执行；最新生产证据仍为 `0001`–`0008`。R16接受H16的首写锁定期限、显式SAVEPOINT、SQLite严格时钟/purged形态、migration单读不可变bytes、八个历史锚、ASCII phone及权限非扩张，但发现未来`purged_at`不证明底层删除、SQLite付费创建时TEXT词法比较会误判合法时钟这两个Medium。权限流`PASS / 0C / 0H / 0M`，全量`721`加`5`skip、readiness`86/86`及既有门禁通过；总裁决仍为`FAIL / NO-GO / 0C / 0H / 2M`。生产preflight、备份、migration、GRANT和PostgreSQL预演继续禁止。
- 2026-07-27执行器进展: 当前仓库已新增显式确认、迁移bytes快照、advisory lock、5秒lock timeout、120秒statement timeout、单事务apply和独立只读verify。隔离PostgreSQL证明精确`0009`–`0016`、8角色及完整负向权限矩阵可原子通过；不调用`render_predeploy.py`、不seed Prompt、不启用LOGIN/Secret或服务。生产执行前风险仍是RDS短锁等待与历史状态漂移；任一precondition/SQL/矩阵不匹配均在commit前回滚，成功后不做破坏性down migration，而是保持新schema dormant和六角色`NOLOGIN`。

### Secrets or tokens leak into Git/logs

- 风险描述: Project uses many third-party keys and tokens. The repo is public per docs, so accidental secret leakage is severe.
- 涉及文件: `.env`, `model/.env`, `model/.env.example`, `docs/DEPLOYMENT_SECRETS.md`, logs, shell scripts, CI.
- 可能后果: API key compromise, account abuse, billing loss, forced key rotation.
- 建议验证方式: `git status`, secret scan with patterns excluding templates, review CI logs, never print `.env` values.
- 是否需要用户确认后才能修改: yes.
- 2026-07-14进展: 商业V1已选择免费默认服务密钥保护RDS/OSS静态数据，但该能力不能保存第三方Secret。起步方案使用ECS RAM Role/STS和受限部署注入，阿里云增量¥0；软件KMS加最低凭据配额约¥2,748/月延期。正式部署前仍须验证root-only权限、进程环境暴露面、日志脱敏、两节点分发、轮换和撤销runbook，因此风险未关闭。
- 2026-07-26仓库进展: runtime settings 已拒绝保留 Secret key 的数据库写入，并且即使历史行被伪造为 `is_secret=0` 也不会回退读取；XHS Cookie只允许受管环境注入，明文Cookie/state文件回退与Admin Cookie入口已关闭。Chat 图片、S3 artifact 和训练补数固定公开错误边界继续 `PASS`。独立R13已接受H13的generic map、真实Chat producer shape和非有限置信度修正；核心map `171/171`、真实Chat public leaves `472/472`、confidence direct `304/304`通过，安全+reasoning`72/72`、聚焦`123`通过加`5`个PostgreSQL跳过、API`152/152`、全量`711`通过加`5`跳过及既有门禁通过。R12仓库`1 High / 1 Medium`关闭；生产历史 Secret/日志、受管注入、双节点分发、轮换/撤销仍未验证，因此生产High不关闭。

### Real payment integration is not confirmed

- 状态: Open Critical / first-launch hard gate；历史 `DEFERRED` 结论已被产品范围决定废止。
- 风险描述: provider-isolated订单、回调验签/幂等、现金/权益账本、全额未用退款、对账/结算、Admin现金真相、transport-injected Adapay协议适配器和专用callback runtime已经仓库/隔离PostgreSQL验证；但没有商户准入、真实凭据、provider mock/live兼容、callback可达、生产migration/ACL、调度告警或真实资金证据。
- 涉及文件: `model/payment_contract.py`, `model/adapay_adapter.py`, `model/payment_adapter_runtime.py`, `model/payment_runtime.py`, `model/api.py`, `model/billing.py`, `model/admin_server.py`, `model/db.py`, migration `0014`, frontend pricing/credit UI.
- 可能后果: Users may receive credits without real payment, or paid launch cannot legally/financially reconcile transactions.
- 建议验证方式: 不重复已通过的零网络fixture。先做商户/渠道/凭据只读准入和provider mock验收，并明确解决官方账单文档HTTP示例与NoteAI强制HTTPS之间的兼容性；生产migration/ACL/Secret/回调可达和受控真实小额支付退款对账必须分别有界执行。
- 是否需要用户确认后才能修改: yes.
- 2026-07-27仓库进展: `PROD-FIRST-LAUNCH-PAYMENT-CONTRACT-001`在commit `4dbb56f2…`达到`REPOSITORY + DISPOSABLE POSTGRESQL PASS / NOT DEPLOYED`。聚焦`198/198`、全量`872`加`20`skip、E2E`66/66`、readiness`95/95`、PostgreSQL`6/6`通过；migration `0014` SHA为`ed788fdf…b0ad`。无provider、凭据、资金、生产数据库/权限、服务、镜像、云或流量动作，费用`¥0`；本Critical只因仓库合同不再是“ABSENT”，但真实支付上线门禁仍保持开放。
- 2026-07-27适配器进展: `PROD-FIRST-LAUNCH-PAYMENT-ADAPTER-001`在commit `d5121c6…`达到`REPOSITORY PASS / NOT DEPLOYED`。聚焦`236/236`、串行全量`887`加`20`skip、E2E`66/66`、readiness`96/96`及依赖/质量/编译/Compose通过；普通API拒绝callback，专用runtime默认disabled并验证精确DB角色，签名响应、退款、账单和exactly-once callback全为synthetic。未调用Adapay或使用商户/资金/生产资源，费用`¥0`；真实支付Critical继续保持开放。

### Alibaba production topology is not deployed; Gateway Staging is single-instance only

- 风险描述: 目标为阿里云华南完整生产主系统、Render Singapore 仅 Claude Gateway；ARCH-001已收口runtime调用，ARCH-002单实例Gateway已在Render Singapore Staging完成云端验证，但现有全栈Staging仍使用Local transport，阿里云主系统、2–4实例Gateway安全化和生产切流均未完成。
- 涉及文件: `model/model_router.py`, `model/api.py`, `model/billing.py`, `render.yaml`, deployment scripts and future Gateway service.
- 可能后果: 阿里云主系统无法按目标拓扑上线；部分请求仍直连 Claude；跨区域重试导致重复供应商费用；逐模型 usage/cost 漏记；未鉴权 Gateway 被滥用。
- 建议验证方式: 生产前完成共享原子防重放/限流、精确主机绑定、远端健康、timeout与partial-stream费用边界，然后建设阿里云并执行灰度/回滚；持续证明Gateway无业务数据库和持久内容。
- 是否需要用户确认后才能修改: transport 收口不需要；创建付费 Render/Alibaba 资源、真实 Claude Smoke 和生产切流需要。

### Claude Gateway shared control plane is verified on single-instance Staging, not Production scale

- 风险描述: ARCH-002P-A/B已在单实例Staging闭环；commit `d279caa`使用AWS Singapore DynamoDB与Render OIDC运行共享nonce/rate/operation/renewable fenced lease，真实credential method、TTL/IAM边界和双客户端单赢家均已无AI验证。但精确Gateway host/readiness/timeout、Render真实2–4实例、滚动/扩缩/崩溃/OIDC刷新/store断路组合尚未验证，Alibaba主系统的Kimi/queue与持久结果恢复也未完成。
- 涉及文件: `gateway/claude_gateway.py`, `model/claude_gateway_protocol.py`, `model/model_router.py`, `render.gateway.yaml`, `infra/aws/claude_gateway_control_plane.yaml`, ARCH-002P-C/D和BILL-002相关实现与测试。
- 可能后果: 当前共享状态不会在已测并发下重复claim，但生产切流仍可能因错误host、timeout层级、配置漂移或控制面中断导致Gateway拒绝新Claude调用；若Alibaba恢复链未完成，用户操作可能不可用或停在不确定态。
- 建议验证方式: 串行闭环C、BILL-002和D；执行精确authority/DNS/TLS/readiness/timeout合同，再做2→4→2、store全断、滚动、重启、取消和Key轮换矩阵。控制面不可达时Gateway继续保持零新Claude调用，Alibaba仅对可证明未dispatch的operation安全Kimi/排队。
- 是否需要用户确认后才能修改: C与FIN-003已验证；D的2–4实例基础费用已获批准，执行前只需列明演练窗口及是否动用剩余真实Claude次数。生产切流仍需单独确认。

### Alibaba production infrastructure exists, but application and recoverability do not

- 风险描述: 生产VPC、C/F两台私网API ECS、跨可用区高可用RDS、高可用Tair、VPC级SNAT/公网出站和三角色不可变ACR镜像已经存在；API-C/API-F及API-C Admin也已作为loopback-only受管服务通过当前有限验收。但ALB/TLS绑定、业务DNS、备份/PITR、对象存储、AI Worker、独立Trends/Tracking Worker、监控和恢复演练尚未闭环，现有API也没有真实用户流量。
- 涉及文件: future Alibaba deployment/IaC or runbooks, database predeploy/migrations, storage/worker adapters, DNS/CORS/payment callback configuration.
- 可能后果: 正式用户数据丢失、服务单点、无法恢复、回调不可达或配置漂移。
- 建议验证方式: 隔离生产环境部署；备份恢复到一次性实例并逐表对账；灰度、故障、容量、监控和回滚演练。
- 是否需要用户确认后才能修改: yes，涉及持续云成本、域名和生产数据。
- 2026-07-16进展: SMQ（原MNS）两队列目标约¥30–31/月、主域企业DNS加基础防御¥1,168/年、基础ICP备案服务¥0、恢复演练临时实例建议4小时上限¥30/24小时上限¥120/单次硬上限¥200，均已完成未下单报价。产品负责人已购买 `noteaipro.cn` 与防御性 `noteaipro.com`；独立云端核验确认两域名均为“正常”且有效至2027年7月，自动续费未显示开启。主域`.cn`为企业持有者；`.com`为个人持有者且仅作防御性占位。产品负责人已明确接受该差异，`.com`不得承载生产/备案，企业过户记为未来可选项而非上线门禁。根域/API/Admin三份正式Rapid DV为¥1,455/年；免费测试证书90天且不用于正式业务。备案核心文档要求ECS累计大于3个月；优先选择官方99计划2核2GiB/3 Mbps/40 GiB、¥99/年备案专机，并在购买后验证“可备案实例”，否则回退既有API节点续费3个月加1 Mbps、追加¥916.20。正式域名/TLS/备案ECS/DNS包首年规划¥2,845，完整月均规划¥3,850.88，首月含按量计提参考¥6,458.80。除两个域名外，其余资源仍未购买；99计划资格、证书换发、备案实际通过、恢复演练和最终DNS切换仍是生产上线门禁。
- 2026-07-16企业DNS付款前复核: 官方购买页已按 `noteaipro.cn` 单域、企业旗舰版、DNS攻击基础防御、1年配置，自动续费未勾选，实时应付¥1,168，与已批预算一致；页面停留在“立即购买”前，未产生订单或费用。付款后需独立核验实例与主域绑定，正式解析记录和DNS切换仍保持独立门禁。
- 2026-07-16防御域主体迁移: 产品负责人报告 `noteaipro.com` 已迁移到与主域相同公司名下，主体差异不再阻塞生产主线；等待阿里云域名列表的后续只读复核后再补云端 VERIFIED 证据。`.com`仍只作防御性占位，不购买第二份企业DNS、不承载生产或备案。
- 2026-07-18当前事实: 生产空库已完成`0001`–`0008`结构migration，未导入Staging数据或Prompt基线；企业DNS已绑定主域，根域/API/Admin三张正式证书已签发但未绑定。历史“未购买”报价只保留作决策证据，不再代表现状。生产应用、ALB、业务DNS和恢复能力仍未完成，因此不得宣称已上线。

### Commercial V1 cannot yet admit 100 simultaneous AI jobs

- 风险描述: 产品负责人已确认商业上线首阶段必须可靠受理100个同时AI任务（Claude或Kimi均可），未来扩展到1000个。仓库现已具备供应商无关持久job、`202` admission、Outbox、fenced Worker、3:1公平、回放及终态扣费/退款合同，但默认关闭且没有生产对象存储、publisher/dispatcher、真实processor或managed Worker。Claude Gateway自设全局并发2/RPM30，Kimi真实账号配额也未核验，因此100任务生产能力仍未成立。
- 涉及文件: `model/api.py`, `model/idempotency.py`, `model/model_router.py`, `model/billing.py`, future `ai_operations/task_queue/ai_worker`, PostgreSQL migrations, Alibaba SMQ/MNS/RocketMQ/IaC, SLS/CloudMonitor/Admin monitoring and `CAP-001/OPS-003` tests.
- 可能后果: 峰值任务被429/超时、断流后丢结果、Worker崩溃重复调用或重复扣费、Claude/Kimi雪崩切换、余额/Token配额耗尽后商业服务中断。
- 建议验证方式: 先以FakeProvider证明100任务均在2秒内持久受理，重复消息/崩溃/数据库短断下0丢失、0重复provider/扣费；再用小样本真实Claude/Kimi校准leaf时长、Token和成本，按队列深度/最老年龄及provider/model配额设置分级告警和升级Runbook。
- 是否需要用户确认后才能修改: 本地状态机、测试和监控合同不需要；阿里云付费资源、migration、真实AI样本、自动扩容预算及任何供应商/消费门禁升级需要。
- 2026-07-26进展: `PROD-FIRST-LAUNCH-DURABLE-AI-CONTRACT-001`已在`f0aaa20`完成仓库与隔离PostgreSQL验证；`PROD-FIRST-LAUNCH-STORAGE-RECOVERY-CONTRACT-001`又在`d2dfb37`关闭了私有OSS adapter、owner-bound media、对象补偿/生命周期、跨进程恢复和内容为空的restore manifest仓库合同。最终全量Python `833 run / 14 skipped / 0 failed`、E2E`66/66`、readiness`95/95`。这仍不关闭生产bucket/RAM角色、queue/processor、migration/roles、监控或100任务负载门禁。

### Durable AI repository contract is verified; production execution remains open

- 状态: `REPOSITORY + DISPOSABLE POSTGRESQL PASS / 0C / 0H / 0M / NOT DEPLOYED`；production仍为Open High。
- 已关闭: 默认禁用的owner-bound `202` admission、无原始内容SQL、opaque request/result refs、Outbox fenced claim/ack、3:1公平、逐调用provider admission、provider-free安全重投、unknown outcome不重试、成功/退款/settlement原子终态、结果回放、删除栅栏和对象补偿均有仓库/SQLite/PostgreSQL证据。migration `0012` SHA为`df72dedfb292700104fc394b5b326f33e4339cbf195f704278c56e08e44bec83`。
- 剩余 High: 生产私有bucket/RAM角色尚未创建或绑定，消息publisher、dispatcher进程和provider processor不存在；生产migration/角色/权限未应用，AI Worker镜像未构建/部署，监控、回滚、provider链和容量均未验收。Compose中的AI Worker仅为default-suspended fail-closed骨架，`--once`不能正常处理任务。
- 防重复: 没有Durable AI或Storage代码/migration SHA冲突时，不重复其离线/隔离PostgreSQL合同测试。下一证据必须来自生产只读preflight或后续正式runtime/provider/capacity门禁。
- 回滚: 当前无生产变更。后续保持admission disabled和Worker suspended；失败时停publisher/dispatcher/Worker、恢复旧digest和旧角色权限，但保留operation/settlement审计账本且不猜测provider unknown outcome。

### ALB health semantics could turn a Gateway outage into a whole-site outage

- 风险描述: 若ALB使用要求Claude Gateway在线的AI readiness作后端健康检查，Gateway或新加坡链路故障会同时摘除两台仍可提供登录、账务、历史结果、Kimi或排队服务的Alibaba API节点。
- 涉及文件: `model/api.py`, `model/admin_server.py`, ALB健康配置、Claude readiness tests和生产runbook。
- 可能后果: 单一AI供应商故障被放大为全站不可用。
- 建议验证方式: ALB仅探测进程、PostgreSQL和必需本地模型；以Gateway全断场景证明两API节点仍健康且Claude不会被不安全重试。
- 是否需要用户确认后才能修改: 本地合同不需要；真实ALB配置或生产故障演练需要批准。

### Cross-border Claude data boundary and China launch compliance are unresolved

- 风险描述: 阿里云主系统通过新加坡 Gateway 调用 Claude 时，Prompt、正文和聊天上下文会跨区域；当前 Chat 多模态路径还可能传递图片/base64。用户告知、数据最小化、备案/许可适用性、隐私/退款条款和第三方处理者清单尚未按目标拓扑完成专业确认。
- 涉及文件: Claude transport/Gateway, Chat multimodal routing, privacy policy, user agreement, refund policy, data retention and compliance records.
- 可能后果: 超范围传输、用户告知不足、支付入网受阻或监管风险。
- 建议验证方式: 建立字段级数据地图；默认在阿里云用 Kimi Vision 转文本后只发送必要文本；由中国执业律师或合规顾问确认最终文件和路径，技术验收核对实现一致。
- 是否需要用户确认后才能修改: yes for final product/data policy; safe minimization tests and documentation inventory can start read-only.
- 2026-07-25仓库进展: 已建立字段级数据地图、版本化隐私/留存/退款/跨境页面及机器合同，并明确境内优先处理图片、仅跨境最小必要文本；注册要求隐私与跨境两项独立同意，服务端保存版本化接受记录并可幂等补录。该内容是产品合同实现，不是中国执业律师、消费者保护、处理者或跨境机制的专业批准；公开流量仍被阻断。

## High Risks

### Default-branch Dependabot alerts require exact release triage

- 状态: Open High / evidence triage required。普通push `0e9a923…` 成功后，GitHub远端报告默认分支共有 `14` 个Dependabot告警（`10 High / 3 Moderate / 1 Low`）；这只是当前平台汇总，不证明这些告警都存在于当前发布提交或具备可达利用路径。
- 风险描述: 未逐项核对package、受影响版本、当前分支可达性和已有容器扫描/VEX之前，既不能忽略这些告警，也不能把默认分支计数直接当成当前候选的确认漏洞。
- 建议验证方式: 建立只读 `PROD-FIRST-LAUNCH-DEPENDABOT-TRIAGE-001`，读取当前告警、锁文件/镜像包版本和修复版本，按当前release commit去重；任何依赖升级必须单独回归并重新构建扫描，不能用旧VEX覆盖新版本。
- 2026-07-26只读进展: 默认分支14项均来自较旧候选（Pillow 13项、python-multipart 1项）；当前分支已经固定Pillow `12.3.0`和python-multipart `0.0.31`，按当前候选版本去重后survivor为`0`。告警不得手工关闭；只有当前候选进入默认分支后由平台重新计算，才能关闭本High。
- 回滚: 只读triage无回滚；若后续升级，回滚仅限精确dependency/lockfile delta及新镜像，不改写旧扫描证据。

### XHS Trends snapshot evidence exception is closed and must not recur

- 状态: Mitigated and verified on API-F by `PROD-XHS-TRENDS-SNAPSHOT-EVIDENCE-ENTRYPOINT-OVERRIDE-001`（2026-07-25）；保留本条用于防止把一次性例外误当成持久授权。
- 风险描述: RETRY-002 已证明默认 suspended Worker、脱敏日志、run-scoped health/ledger 和四表精确写入边界，但原 harness 在容器退出后无法从 tmpfs 复制 snapshot。第一次零写入 exporter 任务又被 hardened entrypoint 正确拒绝。关闭证据缺口因此需要一次明确批准的 `--entrypoint python` 安全例外。
- 当前状态: 单次例外以脱敏的临时云执行身份、精确 XHS digest、`--pull never`、非 root、只读 root、cap-drop、供应商阻断和强制数据库只读运行；仅调用现有 exporter 一次并在进程内验证 schema `1`、六域、`90` 关键词、`37,743` bytes 和 SHA-256 `31b19d6351f48db762a4d98be173bcb72629691d4437230ba1ae6b839063d1bd`。前后 `30` 张 public 表 DML counters、四表总量/时间戳和权限均未变化；容器、tmpfs、临时证据和进程已清理，API-F loopback `200/200` 未变。
- 剩余风险: 该成功结果只证明一次性只读 exporter 路径和 retained Canary rows 的 artifact 合同，不授权持久绕过 entrypoint，不证明真实供应商采集，也不等于已启动或晋升 Trends 服务。重复使用例外会削弱已验收的命令 allowlist。
- 建议验证方式: 不重复该例外，也不重复业务写入 Canary。未来若需要常设诊断命令，应通过独立代码/镜像任务把固定命令加入 allowlist 并重建验证；若要启动 managed Trends 或调用供应商，另立精确生产任务。
- 是否需要用户确认后才能修改: yes。任何再次 entrypoint override、代码/镜像变更、managed Trends 启动、真实供应商、Tracking、权限或 ALB/TLS/DNS/流量动作均需分别明确批准。

### XHS managed-service and real-supplier path remain unverified

- 状态: Open High / first-launch hard gate。旧 suspended Trends 功能、写入、Snapshot、零供应商、API-F非回归和清理保持 `VERIFIED`；`PROD-XHS-TRENDS-LONGRUN-CONTRACT-001`又独立关闭了仓库和隔离PostgreSQL的长期合同，状态`PASS / 0C / 0H / 0M / NOT DEPLOYED`。这些子项不得重跑，但不等于真实供应商或managed promotion通过。
- 风险描述: Trends 尚未作为长期服务运行，真实 XHS session/signer/接口/限流/挑战路径从未生产验证。Tracking是独立进程和写入路径；两者的仓库合同都已通过，但生产仍为`NOT DEPLOYED / NOT STARTED`。当前生产`noteai_xhs`仍是历史权限并集；仓库虽已定义`noteai_xhs_tracking`和`noteai_xhs_trends`，但`0010/0011`及角色变更尚未应用。singleton、资源、重启、日志和回滚实现只有离线/隔离证据，尚无managed runtime证据。
- 可能后果: 若直接解除 suspended 或长期共置在 API 节点，可能发生供应商会话失效、重复或重叠运行、CPU/内存争用、扩大数据库权限影响面、日志泄露或无法可靠回滚。
- 建议验证方式: `PROD-XHS-TRENDS-LONGRUN-CONTRACT-001`没有代码/SHA冲突时不得重复。后续严格按生产只读preflight、新不可变发布、基础设施/精确角色、默认suspended内部部署、最小真实DB只读验证和`PROD-XHS-TRENDS-MANAGED-PROMOTE-001`推进；Tracking仍走自己的真实XHS和promotion门禁。
- 费用和回滚: 真实供应商验证、独立 Worker ECS 或持续日志/网络资源会产生外部影响及可能费用，必须重新报价和批准；历史 Worker pair 参考约¥783.64/月、OSS约¥65/月、SLS约¥12/月，不是当前报价。运行时回滚为恢复 suspended、停止对应 singleton 并回到零 XHS 服务基线。
- 是否需要用户确认后才能修改: yes。真实 XHS、session/Cookie、解除 suspended、数据库权限/迁移、Trends/Tracking 启动、Worker ECS、ACR、代码/镜像、ALB/TLS/DNS/流量均需精确批准。

### XHS Tracking repository contract is verified; production promotion remains open

- 状态: Repository/isolated PostgreSQL `PASS / 0C / 0H / 0M`; production `NOT DEPLOYED / NOT STARTED`，仍为首发 High 门禁且不得继承 Trends 证据。
- 已关闭: `PROD-XHS-TRACKING-CONTRACT-HARDEN-001`已关闭canonical URL、每次供应商调用前原子claim、15分钟lease、24h/7d at-most-once admission、每日300硬上限、确定性growth/memory、stale unknown不重试、删除/调用栅栏、非零失败退出、read-only health和独立`noteai_xhs_tracking`最小权限合同。migration `0010` apply-twice/SHA/脏历史回滚、约束、完整角色负向矩阵和三组独立终审均通过。
- 剩余 High: 生产历史URL/时间/owner preflight、`0009/0010`应用、精确角色创建/授权、不可变digest构建和默认suspended内部部署、一个自有笔记的24h/7d真实XHS有界证明，以及singleton/reboot/kill/alert/rollback尚未验收。服务保持停止。
- 防重复: 没有相关代码或migration SHA变化时，不重复当前隔离PostgreSQL rehearsal或离线模拟矩阵；下一证据必须来自生产只读preflight、正式发布候选或后续明确有界的真实链路/managed promotion阶段。
- 回滚: 当前无生产变更。后续始终先保留suspended；发生异常只停止Tracking singleton并回到旧digest/旧角色合同，保留审计行，不删除业务证据，不影响Trends/API/Admin。
- 授权边界: CTO可继续仓库、离线和只读preflight；真实XHS、生产写入、服务启动、持续付费资源、公开流量和不可逆动作仍受总授权边界限制。

### Repository secret/log/Admin boundary is verified; production history and delivery remain unverified

- 状态: `R13 REPOSITORY FINDINGS CLOSED / PRODUCTION HIGH REMAINS`。R8正向shape Medium、R12结构持久化High和非有限confidence Medium均已在仓库级关闭；固定 Chat/S3/training 异常边界、PostgreSQL时间合同、严格Chat消息、精确良性allowlist、普通per-schema拒绝及既有嵌套schema继续 `PASS`。生产接受尚未完成。
- 风险描述: 仓库对保留 Secret key 禁止数据库fallback，Provider/Crawler/Training/Admin输出使用固定事件码、计数和摘要hash，Admin动态字段统一转义。H13把两个generic projector的例外限制到schema递归发现的三条整数map路径并复用typed bounded sanitizer；真实`chat_start`只转发既有typed Fact/market context；所有非有限expert confidence统一fail-closed。独立R13以新fixture验证三路径、真实ChatStart和四阶段生命周期，零private survivor且零approved-shape loss。一个补充非Map断言因审计者错误期待未声明record保留为`{}`而停止；源审查确认typed schema应整体省略该项，不构成产品缺陷。
- 涉及文件: `model/runtime_settings.py`, `model/security_redaction.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`, Crawler/Downloader及安全负向测试。
- 可能后果: 若生产未采用最终安全版本或历史数据不处置，数据库、备份或日志仍可能暴露Cookie、URL/query、正文、Prompt、Token或异常原文；未经验证的Secret注入、双节点分发或撤销流程也可能造成服务中断或凭据残留。
- 建议验证方式: H13/R13不得在没有冲突新证据时重复。先执行另批的本地可销毁PostgreSQL预演，再分别批准生产只读历史/权限preflight、受管Secret双节点分发与轮换/撤销验证、历史日志/数据清理和专业合规审查。
- 是否需要用户确认后才能修改: 本地PostgreSQL服务启动、任何后续代码修改、生产历史清理、Secret分发/轮换、migration、权限或服务变更必须另行单独批准。

### Security/compliance retention integrity passed repository and disposable PostgreSQL gates; production application remains open

- 状态: `H17–H22 + R22 PASS / 0 Critical / 0 High / 0 Medium`；`PROD-FIRST-LAUNCH-SEC-COMPLIANCE-POSTGRES-REHEARSAL-002` 与 R23 PostgreSQL/生命周期独立终审均为 `PASS / 0C / 0H / 0M`，回归复核只依赖最终清理。精确任务容器/卷已删除为零，Colima已恢复停止基线。这是隔离 PostgreSQL 16 证据，不等于生产迁移或部署完成。
- 已关闭根因: 未来/伪造 purge marker、SQLite 付费创建词法误判、保留身份和主内容身份移动、purge 后及同事务复活、直接 SQLite duplicate/REPLACE、startup/helper 重复登记冲突均由 H17–H22 关闭。R22 通过 `13/13` 聚焦、`134/134` 安全/推理/部署/健康、`152/152` API、全量 `734 passed + 5 skipped`、readiness `86/86` 及质量/编译/Compose/diff。
- 动态 PostgreSQL 证据: migration 首次 `9`、二次 `0`、SHA ledger `9`；drift、非规范/重复手机号和非法源时间历史均失败关闭并原子回滚。`noteai_app` 表 `100/145`、序列 `5/10`，`noteai_xhs` 表 `20/225`、序列 `3/12`；retention 六列、Notes `parent_id`、Diagnoses 零 UPDATE 精确成立。两角色均非 owner/superuser、无 `BYPASSRLS`/membership/DDL/grant option/ledger 权限。
- 动态生命周期证据: orphan/wrong-owner/prepurged、live-primary/future marker 全部拒绝；Note/Diagnosis delete-before-marker 成功。purged row 审计可见但后续 UPDATE 为 `rowcount=0`；同事务和并发复活均 `23514` 且无 survivor。helper exact/等价时区/省略 clock 重复保持整行及 `xmin` 不变，owner/clock 冲突 fail closed。
- 剩余 High: migration `0009`、生产 `noteai_app` 权限收缩/新增权限、生产历史数据 preflight、备份和 processor 调度均未执行；当前生产仍为 `0001`–`0008`。生产回填可能立即产生到期候选，必须先做只读数量/时钟/手机号/回填影响统计、备份证据、精确写入上限和暂停/回滚门禁。
- 建议验证方式: R16–R23 的已关闭根因和本地演练不得重复。下一串行任务应执行生产只读 preflight；只有历史数据、当前权限、备份和发布 checkpoint 全绿后才能制定 production migration/permission plan。
- 回滚: 当前尚无生产变更，无需生产回滚；本地 rehearsal 只删除带精确 task label 的容器/卷。未来生产执行前必须保留可验证备份，先暂停 processor，失败时停止发布并恢复旧应用/权限合同，不宣称备份内容已删除。

### Historical R16 retention findings — superseded by H17–H22, R22 and disposable PostgreSQL evidence

- 状态: `HISTORICAL / CLOSED AS ROOT-CAUSE INPUT`。`PROD-FIRST-LAUNCH-SEC-COMPLIANCE-REVERIFY-016` 当时为 `FAIL / 0C / 0H / 2M`；其两个 Medium 已由 H17–H22、R22 和隔离 PostgreSQL 证据关闭，不得继续作为当前 next-task 或 Open 风险。
- 已关闭的R15根因: Note与Diagnosis真实DELETE首次写入稳定墓碑，12次并发重试不改变三个时钟；`30d-1µs`清理0、精确`30d`清理2、二次清理0。SQLite升级在rename/create/copy/drop/index五个故障边界全部回滚并可重试，stale marker fail closed。SQLite合法clock、非法INSERT/UPDATE、正常free自动到期和delete-before-marker顺序均通过。R15的`1 High / 3 Medium`不再保留为Open。
- Medium — purged状态不证明真实删除: format-valid且顺序合法的未来`purged_at`可在底层Note/Diagnosis仍存在时直接写入；Python validator接受，status立即显示`purged`，processor在当前及原期限后都跳过，底层两类内容仍各1条。当前processor正常路径正确，但`noteai_app`拥有UPDATE，SQLite/PostgreSQL持久边界没有将marker限制为真实删除转换。
- Medium — SQLite付费创建时按TEXT词法比较: SQLite运行分支用`started_at <= created_at < expires_at`文本比较，和已接受的明确时区/外围空白clock合同不一致。实际`record_content()`临时库探针`3/3`误判：真实付费被标成`free_7d`、真实免费被标成`paid_indefinite`、外围空白的真实付费也被标成`free_7d`。PostgreSQL分支使用typed clock，不继承此问题。
- 已接受migration/input证据: 两文件六个突变边界`12/12`保持同一原始bytes和ledger SHA；实际9个migration各只读一次且仅`0009` pending；invalid UTF-8、stored drift、missing、untrusted digestless与竞争snapshot均fail closed；8个历史锚匹配。7个有效phone归一为单一身份，228个Unicode/mixed case在事务前拒绝；PostgreSQL静态clock/状态约束与SQLite既有source/deadline负向矩阵通过。
- 已接受权限和回归: migration `0009`无GRANT/REVOKE、role/owner/default/schema/function/trigger扩张；`noteai_app`精确20个新DML边界，`noteai_xhs`对五张新表`0/20`允许；完整预期矩阵app表`102/143`、序列`5/10`，XHS表`20/225`、序列`3/12`。安全+部署`91/91`、健康`22/22`、合并`113/113`、API`152/152`、全量`721`加`5`skip、readiness`86/86`及质量/编译/Compose/diff通过。
- 建议修复方式: 仅在明确批准的`PROD-FIRST-LAUNCH-SEC-COMPLIANCE-HARDEN-017`中以failing-first修复两个Medium：让purged marker只能由真实delete-before-marker转换产生且未来marker/status fail closed；SQLite付费创建判断必须解析为真实时刻再比较。必须保持正常paid/free处理、free自动到期、H13–H16已接受控制及权限零扩张。
- 后续门禁: H17完成后必须由新批次R17独立复核；只有R17通过，才可另行申请修改后PostgreSQL预演。真实PostgreSQL行为继续`UNKNOWN`。
- 回滚: H14–H16均未部署，生产仍停留`0001`–`0008`，当前无需生产回滚。H17若实施，只允许撤销其精确delta，不得丢弃H13–H16已接受控制。
- 是否需要用户确认后才能修改: yes。H17、R17、PostgreSQL预演、生产preflight/migration/GRANT均分别需要明确批准。

### Retention and account-deletion controls are verified before production application

- 状态: Open High / first-launch production gate；仓库、SQLite、隔离 PostgreSQL 和 R23 生命周期已通过，High 仅保留在生产历史/preflight、migration/permission、备份与调度未执行的层级。
- 风险描述: 新实现提供幂等 purge processor、账户主数据删除和外部备份清除证据确认；过期请求租约不再永久饿死删除，Admin 用户写也进入相同栅栏。H17–H22/R22/R23 已关闭 R16 的伪造 marker 和付费分类问题，并证明 PostgreSQL 身份/权限/并发边界。Migration `0009`仍未执行，production processor未调度，备份系统不能由应用自行宣称清除。历史免费内容回填后可能立即达到purge条件。
- 可能后果: 生产继续无限保留应删除内容，或在没有预览、备份和用户沟通时批量清理历史数据；账户删除也可能只记录期限而没有可验证的主库/备份执行证据。
- 建议验证方式: H17–H22、R22及隔离PostgreSQL不得在无冲突新证据时重复。下一步只读统计生产 backfill/purge候选、手机号和四类源时间兼容性，并核对当前角色负向矩阵；任何生产应用前必须确认备份、精确批次上限、暂停开关、证据格式和回滚边界。
- 回滚: migration/processor 未执行前保持当前生产不变；未来执行时先禁用调度并保留备份，回滚代码/调度而不伪造“备份已清除”证明。
- 是否需要用户确认后才能修改: yes for production migration、GRANT、purge/deletion processor、历史清理或备份操作；只读独立审查不涉及费用或生产写入。

### Private storage/recovery repository contract is verified; production recovery is unproven

- 状态: `REPOSITORY + DISPOSABLE POSTGRESQL PASS / 0C / 0H / 0M / NOT DEPLOYED`；production仍为Open High。
- 已关闭: `d2dfb376587c86031681c5d6b1a52f40d619032e`实现官方OSS SDK/ECS RAM Role fail-closed adapter、owner-bound opaque media、流式边界、跨进程/重启、TTL/账户删除、对象补偿、孤儿dry-run和一致性只读restore manifest；migration `0013` SHA为`1268cdb9696965f02d5be88882b3dc8a2f9f7b589a2b0da5193d1bb8408ccb76`。隔离PostgreSQL 16.14角色/约束`4/4`、source/restored 46表/13 migrations精确匹配、全量`833`及readiness`95/95`通过。
- 剩余 High: RDS虽运行且生产migration仅到`0008`，仍无确认的生产连接池/连接预算/故障重连、私有bucket/RAM角色/对象生命周期和监控，未应用`0013`，也未执行真实跨节点managed proof或隔离PITR恢复演练。
- 可能后果: 连接风暴或主备切换后应用不恢复；未部署正确私有对象边界时媒体/任务输入不可用；数据库和对象恢复点不一致。
- 建议验证方式: 不重复仓库合同。先完成只读生产preflight；随后按独立云任务创建私有bucket/RAM角色、应用精确migration/权限、验证两节点/Worker；最后恢复到新隔离RDS并用create-once脱敏manifest逐表/逐对象对账，绝不覆盖源实例。
- 回滚/授权: 当前无生产变更。真实恢复实例、OSS、production migration/GRANT、对象删除或持续费用需要明确云任务边界；失败时保持Durable admission和Worker suspended、恢复旧digest/角色并保留证据。

### Render Blueprint Sync Hook may require rotation after controlled-tool exposure

- 风险描述: ARCH-002P-D核对Render Blueprint设置时，受控页面自动化快照意外包含真实Sync Hook值。本账本不保存该值，但必须按潜在泄露处理并由`SEC-006`跟踪轮换。
- 涉及文件: 不涉及仓库文件；Render Blueprint凭证与运维runbook。
- 可能后果: 未授权的Blueprint同步触发、部署或配置干扰；盲目断开/重建Blueprint又可以造成服务漂移。
- 建议验证方式: 仅通过Render官方自助入口或Support轮换，证明旧Hook失效；不读取/打印新值；复核Auto Sync=No、Gateway min2/max4、环境配置和手工回滚能力未变。
- 是否需要用户确认后才能修改: 无损自助轮换可作为最小安全处置；若需断开/重建Blueprint或联系Support，须先告知用户影响。

### Cross-account Chat cache can expose a previous account's note snapshot

- 状态: Mitigated and verified on Render Staging by commit `513675d`（2026-07-12）；保留本条用于防回归。
- 风险描述: 前端使用未绑定用户的全局 `noteai_chat_session` localStorage；登录/注册和慢/失败 `/auth/me` 恢复链可能把账号 A 的标题、正文、评分、版本及 session/note 标识展示给账号 B。
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, Chat/auth 前端 tests；防御纵深可能涉及 `model/api.py` Chat session ownership load。
- 可能后果: 共享设备、token 失效或同页账号切换时发生跨账号机密性泄露。后端当前在计费和写入前拒绝异账号 session，但不能阻止缓存内容先显示。
- 建议验证方式: 两个合成账号脱敏哨兵 E2E；覆盖慢/失败认证、注册/登录身份变化、logout、403 清理、同账号刷新恢复；API 继续验证所有权检查先于计费/写入。
- 是否需要用户确认后才能修改: no，最小安全修复不改变产品、计费或数据保留政策。

### SSE progress and terminal recovery can leave successful paid work looking stuck

- 状态: 客户端/协议部分已由 `PERF-001B` 在 Render Staging 验证（commit `2579c08`/`f8b98b4`）；持久回放、provider-free stale lease、unknown outcome与退款一致性已由Durable AI仓库/隔离PostgreSQL合同关闭，但真实storage/queue/Worker/provider运行仍未验收。
- 风险描述: 真实 Staging Smoke 中 Analyze 阶段继续推进但百分比停在34%，Generate 停在0%，Chat 正式内容返回后输入框仍延迟恢复；当前客户端 parser/终态状态机和 durable replay 边界不完整。
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, SSE/Chat e2e 与 contract tests；持久回放另涉及 billing/db/migration。
- 可能后果: 用户误以为付费任务失败、重复提交或离开页面；断流/重启窗口可能出现结果、usage、退款和幂等状态不一致。
- 建议验证方式: `PERF-001B` 和已完成Durable AI合同不得重复实施；先完成Storage/Recovery，再在managed runtime中验证真实断连回放、stale/unknown、对象一致性和退款。不得自动重试结果不明的付费 AI。
- 是否需要用户确认后才能修改: 客户端/协议兼容修复不需要；migration、结果保留期限和真实故障 Smoke 需要。

### Frontend/backend payload drift

- 风险描述: Static frontend manually constructs payloads for AI diagnosis/generation/chat. Backend Pydantic models evolve separately.
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, `tests/test_frontend_report_static.py`, `tests/e2e/content-intent.spec.js`.
- 可能后果: UI controls become decorative, backend ignores user intent, requests fail or silently use defaults.
- 建议验证方式: Playwright route interception, backend contract tests, static assertions for all required fields.
- 是否需要用户确认后才能修改: no for tests/docs; yes for behavior changes.

### Core AI quality may regress despite scoring gates

- 风险描述: V0.4 scoring, prompts, fact routing, sanitizers, and ranker interact. Passing score does not automatically mean content is natural or valuable.
- 涉及文件: `model/api.py`, `model/model_router.py`, V0.4 model/training files, prompt manager files, quality artifacts.
- 可能后果: Generated titles/body feel templated, fake, low-value, or inconsistent across industries.
- 建议验证方式: Real-chain smoke for each core industry and each creation direction; record title/body/score/fact decisions; human review.
- 是否需要用户确认后才能修改: yes for prompt/model/business behavior changes.

### Market timing freshness gate can block core flows

- 风险描述: Production rules require fresh industry trend evidence. If worker/cloud snapshot/authorized source is missing or stale, API may return market timing unavailable.
- 涉及文件: `model/hot_keywords.py`, `model/scheduler_a.py`, `model/market_timing_worker.py`, `model/api.py`, `docker-compose.yml`, `docs/MARKET_TIMING_CLOUD_PIPELINE.md`.
- 可能后果: AI diagnosis/generation fails in production or uses stale evidence if guard regresses.
- 建议验证方式: Worker smoke on cloud-like environment, freshness tests, API behavior test with stale/missing data.
- 是否需要用户确认后才能修改: yes.

### Model artifact loading and deployment are fragile

- 风险描述: Production requires V0.4 artifacts and SHA checks. Git LFS availability is platform-dependent; private S3 credentials and object paths must be exact.
- 涉及文件: `model/artifacts/`, `model/model_registry.json`, `model/artifact_loader.py`, `scripts/fetch_model_artifacts.py`, `Dockerfile`, `scripts/docker_entrypoint.sh`, docs.
- 可能后果: Service starts with missing/legacy model, startup failure, wrong scoring behavior.
- 建议验证方式: `python scripts/fetch_model_artifacts.py --check-only --required`, production readiness gate, container startup smoke.
- 是否需要用户确认后才能修改: yes.

### External provider reliability/cost risk

- 风险描述: Claude/Kimi/Amap/Meituan calls have timeouts, concurrency limits, token costs, and possible regional network issues.
- 涉及文件: `model/model_router.py`, `model/api.py`, `model/fact_enrichment.py`, `model/billing.py`.
- 可能后果: Empty responses, failed OCR, slow diagnosis, inaccurate billing cost, poor user experience.
- 建议验证方式: Provider-specific smoke tests with timeout/retry logging and usage record checks; avoid logging secrets.
- 是否需要用户确认后才能修改: yes for live-cost tests or provider changes.

### Render AI latency exceeds the current user-facing promise

- 风险描述: 真实 staging 样本中，诊断约 194–228 秒、生成约 257 秒、对话深度重写约 146 秒，而前端按钮仍承诺“约30–60秒”。
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, `model/model_router.py`, 多 Agent/评分/二修流程。
- 可能后果: 用户认为系统卡死或虚假承诺，重复提交导致重复扣分和更高模型费用。
- 建议验证方式: 先修正文案与进度/防重复提交；再用阶段耗时日志定位 Claude 并发、评分和二修瓶颈，优化后保持同一质量门禁做 A/B 实测。
- 是否需要用户确认后才能修改: 文案与防重复提交可按事实修复；改变 Agent 数量、模型、并发或二修策略需要用户确认，因为可能影响交付质量和费用。

## Medium Risks

### Render Free PostgreSQL expires and has no backups

- 风险描述: `render.yaml` intentionally uses Free PostgreSQL for staging. It expires after 30 days and does not include backups.
- 涉及文件: `render.yaml`, `docs/RENDER_DEPLOYMENT_GUIDE.md`.
- 可能后果: Test data becomes inaccessible and is eventually deleted if the database is not upgraded/exported.
- 建议验证方式: Record creation date, configure a reminder, export important test data, and upgrade before using production-like records.
- 是否需要用户确认后才能修改: yes, because plan upgrades create cost.

### Video cache disk prevents zero-downtime API deploys

- 风险描述: Staging API uses a 1GB Render disk for six-hour video frame recovery. Render cannot perform zero-downtime replacement for a disk-attached service and cannot scale it horizontally.
- 涉及文件: `render.yaml`, `model/api.py`, `docs/RENDER_DEPLOYMENT_GUIDE.md`.
- 可能后果: Brief deploy interruption, disk pressure if cleanup fails, and inability to scale beyond one API instance.
- 建议验证方式: Upload/restart/recover smoke, disk usage monitoring, and replace the cache with object storage before horizontal scaling.
- 是否需要用户确认后才能修改: yes.

### Fact enrichment can pollute delivery copy

- 风险描述: Generic fallback facts or placeholders can leak into publishable body if routing/sanitizers regress.
- 涉及文件: `model/api.py`, `model/fact_enrichment.py`, `tests/test_api_contracts.py`.
- 可能后果: Unnatural copy, fake facts, loss of user trust.
- 建议验证方式: Tests for no placeholder sentences, decision intent requiring confirmed merchant, Amap/Meituan facts natural integration.
- 是否需要用户确认后才能修改: yes for behavior changes.

### Screenshot OCR gating can break upload workflows

- 风险描述: The rule requires every uploaded screenshot to finish AI recognition before diagnosis. Failures or pending state handling can block users.
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, Kimi/Moonshot OCR helpers.
- 可能后果: Users cannot start diagnosis after uploading images; or diagnosis starts without full visual context.
- 建议验证方式: Browser/e2e upload tests with multiple images, failure handling tests, API OCR smoke.
- 是否需要用户确认后才能修改: no for tests; yes for UX/business rule changes.

### Admin and frontend pricing displays may drift from backend billing

- 风险描述: Pricing page, balance dialogs, profile/admin usage views must match `billing.py`.
- 涉及文件: `model/billing.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`, `NoteAI_Pro_Demo_Framer.html`.
- 可能后果: User confusion, support disputes, wrong package economics.
- 建议验证方式: Tests that frontend/admin read `/billing/tiers` and usage endpoints rather than hard-coded stale values.
- 是否需要用户确认后才能修改: yes for pricing changes.

### Spider_XHS private HTTP interface, session and platform behavior may drift

- 风险描述: 生产候选已从 Playwright/Chromium Worker 转为商业授权 Spider_XHS 的非官方只读 HTTP 适配器。商业授权不等于小红书平台授权；接口、签名资产、Cookie、账号限制、风控和平台规则仍可能变化。生产角色默认暂停，且不提供浏览器、代理轮换、登录或 challenge 绕过回退。
- 涉及文件: `Dockerfile`, `model/spider_xhs_http.py`, `model/vendor/spider_xhs/`, `model/crawler.py`, `model/scheduler_a.py`, `model/market_timing_worker.py`, `model/xhs_acquisition.py`, `docker-compose.yml`, `render.yaml`.
- 可能后果: 首页推荐、搜索、详情或分页失效；会话被限制；当天真实证据不足导致市场时机质量门禁返回不可用。错误域 Cookie 若未过滤还可能造成 Secret 泄漏，因此域、过期和去重规则属于发布门禁。
- 建议验证方式: 每次发布核验固定上游 commit/tree、两份 signer SHA、Cookie host/expiry 过滤、默认暂停、生产角色 fail-closed、零浏览器回退、固定只读 endpoint、分页上限、Secret 扫描和无网络 fixture 测试。真实会话 smoke 必须单独批准、限量并可立即重新暂停；接口异常时回滚为手工/截图证据输入，不恢复 Playwright。
- 是否需要用户确认后才能修改: 离线测试和安全收口不需要；任何真实小红书调用、会话替换、解除暂停或平台策略决定都需要明确批准。

### XHS direct-HTTP session can expire and requires operator action

- 风险描述: `xhs-http-runtime` 依赖由用户登录生成的专用账号会话；提醒机制已部署，但平台风控、Cookie 到期、签名或接口变化仍会令会话失效并需要人工重新登录。会话健康是本地、无付费调用的配置判断，不代表平台在线验证成功。
- 涉及文件: `model/scheduler_a.py`, `model/market_timing_worker.py`, `model/xhs_acquisition.py`, `model/admin_server.py`, `model/admin.html`, `render.yaml`。
- 可能后果: 六个核心行业无法达到真实新鲜证据门禁，Cron 退出非零，市场时机证据停止更新。
- 建议验证方式: 管理端显示 `已验证 / 登录已失效 / 需要检查`；Render Cron 仅失败通知；每次重新登录后以真实采集证据验证，而不是只检查 Cookie 是否存在。
- 是否需要用户确认后才能修改: 重新登录和替换 Cookie 需要用户确认；健康检测和无敏感值提醒可按现有方案维护。

### XHS evidence source diversity can regress

- 风险描述: 当前四类来源已在 Render 真实通过；未来页面/API 变化仍可能让来源退化，而单看关键词总数可能掩盖来源单一。
- 涉及文件: `model/scheduler_a.py`, `model/xhs_acquisition.py`, `model/market_timing_worker.py`, `model/admin_server.py`。
- 可能后果: 市场时机证据数量达标但缺少用户主动搜索与趋势信号，降低报告可信度。
- 建议验证方式: 每轮记录 `homefeed / search_result / search_recommend / hot_search` 独立数量及 API 响应指标；云端至少确认搜索结果和推荐来源非零，再评估是否增加来源多样性门禁。
- 是否需要用户确认后才能修改: 观测与解析修复不需要；新增硬性来源门禁需要产品确认和生产样本校准。

## Low Risks

### `model/api.py` is too large

- 风险描述: Many unrelated concerns live in a single large file.
- 涉及文件: `model/api.py`.
- 可能后果: Hard to review, accidental regressions, duplicated logic.
- 建议验证方式: Increase tests around changed behavior before any refactor.
- 是否需要用户确认后才能修改: yes, because refactor risk is high.

### Static HTML is hard to maintain

- 风险描述: A very large single HTML file holds layout, state, API calls, and rendering.
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`.
- 可能后果: UI regressions, hidden duplicate state, hard-to-test changes.
- 建议验证方式: Keep Playwright e2e and static tests close to every UI contract.
- 是否需要用户确认后才能修改: yes for structural refactor.

### Generated/local artifacts can clutter reviews

- 风险描述: Probe JSON, crawler logs, pycache, local screenshots, test reports, and DB changes can appear during development.
- 涉及文件: `quality/*.json`, `model/data/*.json`, `__pycache__/`, `test-results/`, local DB files.
- 可能后果: Accidental noisy commits or leaking local state.
- 建议验证方式: `git status --short`, `.gitignore`, explicit staging.
- 是否需要用户确认后才能修改: no for docs/gitignore; yes before deleting artifacts.

### Missing local Git LFS filter creates false model modifications

- 风险描述: 本机未安装或未启用 Git LFS filter 时，三份已跟踪 `.lgb` 会显示 modified，即使业务模型内容没有被主动修改。
- 涉及文件: `.gitattributes`, `model/artifacts/*.lgb`。
- 可能后果: 误把大模型二进制加入提交、污染 diff 或破坏远端 LFS 指针。
- 建议验证方式: 使用 LFS-safe status 核对；提交时只显式 stage 目标文件；恢复 Git LFS 后再处理工作树表现。
- 是否需要用户确认后才能修改: 安装依赖或改模型文件需要确认；排除 staging 不需要。

### No confirmed lint/typecheck command

- 风险描述: CI relies on py_compile and unittest, but no lint/typecheck workflow is confirmed.
- 涉及文件: `package.json`, `.github/workflows/ci.yml`, Python files.
- 可能后果: Style drift, dead code, dynamic runtime bugs.
- 建议验证方式: Add lint/typecheck only after user approval; otherwise rely on tests.
- 是否需要用户确认后才能修改: yes.

### Documentation can become stale

- 风险描述: Rapid changes to AI strategy, billing, deployment, and model training may outpace docs.
- 涉及文件: `docs/`, `.codex/`, `AGENTS.md`.
- 可能后果: Future agents follow outdated assumptions.
- 建议验证方式: Update handoff after each stage and reconcile docs before checkpoint commit.
- 是否需要用户确认后才能修改: no for handoff/docs, yes for code behavior.
