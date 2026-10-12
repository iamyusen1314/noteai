# 高德月快照与休闲娱乐体验修复记录

本记录属于 `codex/amap-leisure-repair-20261012` 独立修复分支。生产统一由“启动NoteAI授权续期发布”安排；当前安全恢复优先，这不是要求立即改动生产。所有验收项必须区分代码修复、隔离测试、通知、部署和真实供应商结果。

## 版本证据与边界

| 对象 | 已核实的代码/构建 | 本次结论 |
| --- | --- | --- |
| 用户称“9月26日版本”的首个上线版本 | `d28f79c1702860a54e2e5174b7a569bdcd5707c8`；API image `sha256:35a61b6c37c06539e0053340b17f187458cdb9d912b11302a949c45e315b428c`；静态构建 `generation-recovery-d28f79c17028-s2` | 历史真实部署证据确认；本次未在维护中启动线上新鲜探针 |
| 正在准备的后续版本 | 集成 `4bdb58b0aa650840f167ad1797d055d8caa06f14`；应用候选 `86ff10db4dc12e60ef35a342e3bf438ac81ed23f`；H5 `f18584d14c3249bd5c548430ab2dd4722a1abd78` | 仍未确认上线；10月12日22:02北京 CURRENT 记录处于同一维护安全恢复 |

旧版证据来源：原主目录 `.codex/handoffs/current-task.md` Sep26 CURRENT，静态 S4 在 `2026-09-25T15:58:11.913952Z` 完成，北京9月26日00:08一次小视频真实验收。该历史验收不作为本次行业/高德验收。

后续版本来源：工具实际返回的聊天标题“启动NoteAI授权续期发布”，ID `01a0f7cb-70cc-71d3-bd42-2cc75bdae2d3`，host `local`；其原用户指令与集成目录 CURRENT 相互对应。目录为 `/Users/openclaw/.codex/worktrees/shared-account-main-integration/noteai`，分支 `codex/shared-account-main-integration-20260927`。本窗口没有写入该目录或操作其进程。

旧版/应用候选/集成版本的原 `model/amap_quota.py` SHA256 都是 `638ca7c3fdb44d892a1d41570bef1b766c829c092b13aabd8372818fe0f3322d`；迁移0031都是 `58673d89e80331c56b9561f1cbb61b6dd7f2448ee6e89b4937df3fa2a35de445`。原 `prompt_composer.py` 都是 `d63b0d3dd1cdd2cc9674fbcdaff83790688665afa9593b76384d952944c209b6`；`v04_domain_policy.py` 都是 `dfbd6b1d66d75b7de08b71c2bb7b1d265f02d3361d6f70f65027a8dd73d2818a`。两版均受影响，不能推定新版已解决。

## 高德完整原因链

1. 用户生成/诊断的事实决策进入 `model/fact_enrichment.py`，`_search_amap()` 请求关键字搜索，必要时请求同一POI的详情。每一个物理HTTP都先经过 `_fact_get()` → `amap_quota.admit()`；配额拒绝发生在 `client.get()` 之前。
2. `amap_quota.admit()` 使用数据库事务、账户锁及锁后的数据库时钟；读取账户 `noteai-primary-amap-account` / 服务组 `basic_search` 的最新月份桶。两个既有Key与两个接口共享同一个账户额度，不能按Key重复分配。
3. 快照在生产 PostgreSQL `amap_quota_buckets`，物理请求的保守占用及结果在 `amap_quota_attempts`。0031迁移只建表和最小运行权限，不初始化快照；API/Admin运行角色没有快照INSERT权。快照基线不可修改，占用不回退，包括UNKNOWN。`_bucket()` 每次读库，不存在进程内quota缓存或环境TTL设置。时间解析要求带时区并统一UTC，PG使用锁后clock_timestamp，进程时区不是此代码的过期依据；数据库实际时钟仍须现场核对。
4. 历史官方观察在9月15日录入：月份9月，范围北京时间9月1日至10月1日，额度50000、官方观察已用1；本地后续准入另累计。9月19日的控制台再次观察并不等于将基线重新写入。历史说明明确“新月须实际官方额度恢复快照”，但仓库没有每月续期入口、任务或消费者。
5. 过期条件为 `DB now + 10 seconds >= stored period_end`；10秒是发出请求的边界余量，不是从观察时刻算的短TTL。9月内正常准入；北京时间10月1日到月界后，同一9月桶正确拒绝 `AMAP_QUOTA_SNAPSHOT_EXPIRED`。`read_status()` 原来只在 `now >= end` 显示过期，临界10秒内与准入结果不一致，也没有显式运营续期动作提示。
6. 该异常经 `FactProviderError` 返回事实缺失；缺失事实不进入生成内容。现有生成缓存仅缓存已取得的事实，不能续期额度，也不能证明Key/供应商故障。候选版在配额准入之前还有 durable provider fence；它必须保留。

**证据支持的根因是月度配额观察生命周期缺少运营续期闭环，而不是Key失效或高德故障。** 当前症状与历史9月桶到期一致，但本次尚未读到生产当前桶及实际Key的新鲜投影，不能排除生产状态后来变化。Key用户已确认正常；9月16日曾实际证明API进程与保留0902来源相等，这只是历史。今天的运行Key与 `noteai-rot-0902` 内存相等、同一官方账户/服务组、当前DB-clock和bucket仍须发布窗口在安全恢复后只读核对。

高德官方说明把月配额/用量指向控制台，当前公开文档未提供已核实可使用的官方账户用量读取API：[配额说明](https://lbs.amap.com/api/webservice/guide/tools/flowlevel)、[基础服务计费](https://lbs.amap.com/pages/base_service_price)。本修复不会虚构自动统计API或把网页缓存当最新观察。

## 最小修复与每月操作闭环

修复中的受控入口 `tools/refresh_amap_quota_snapshot.py` 只接收已由操作人核实的当月官方观察及其原字节SHA；默认计划只读，应用必须显式 `--apply`，使用既有维护数据库通道与同一账户锁。密钥仅从隐藏环境进入内存比对，输出只含结果布尔/错误枚举。材料摘要和操作人声明不等于工具自动核实官方真实。

- 精确校验Asia/Shanghai月界、锁后DB时钟、观察新鲜性、账户/服务组/Key身份；不复制上月额度或自动猜本月额度。
- 上月过期后追加真实当月桶；同月同一基线幂等NOOP，保留所有已用与限制；不同基线冲突，不UPSERT或重置。官方不足继续停止高德；真实零额度安全HOLD。
- 观察不可读、Key/账户不一致、DB失败均停止；提交结果UNKNOWN只读核对，绝不自动重试。历史认证/账户拒绝跨月保留。
- Admin只读显示到期日期、临近月界和待续期动作；准入及显示采用一致10秒边界。普通用户提示明确官方月度额度记录到期，不暗示Key失效。

**运营责任：现有发布/维护负责人**在每月最后一个工作日查看Admin到期提示并准备下一次读回；新月官方实际范围出现后核实同账户当前额度/已用，保留脱敏观察材料，先plan再按既有维护流程apply，随后只读核实新桶与限制。官方材料不可用时保留安全停高德，不放开付费超额。此流程可重复每月，未创建新发布流程或自动任务。

实际本月续期、维护角色和官方材料尚未使用；此处“修复”仅指可重复入口、提示与恢复机制，不能声称线上自动恢复或已生效。

维护入口只在原发布方已安排的维护通道内使用，命令不携带凭据：

```text
python tools/refresh_amap_quota_snapshot.py --evidence /private/actual-observation.json --official-observation /private/actual-console-artifact --plan
python tools/refresh_amap_quota_snapshot.py --evidence /private/actual-observation.json --official-observation /private/actual-console-artifact --apply
```

需要原维护进程隐藏环境中的 `NOTEAI_AMAP_REFRESH_DSN`、已实际观察的 `AMAP_WEB_KEY` 和 `NOTEAI_AMAP_OBSERVED_KEY`；不得把完整DSN或Key放在命令参数、聊天、日志或仓库。默认plan使用PG READ ONLY事务，不导入业务db、不自动建库或迁移。apply会拒绝API/Admin运行角色，需要既有受控维护角色，不新增权限。

证据JSON version=1，字段为 `account_scope`、`service_group`、`period`、`period_start`、`period_end`、`time_zone`、`quota`、`official_used`、`observed_at`、`source`、`official_observation_sha256`、`attestations`。固定scope为本账户/basic_search，source为 `amap_console_base_search_statistics`；月份、精确北京时间边界、额度/已用必须来自实际当月控制台。`attestations` 的字段为 `console_account_matches`、`key_alias`、`key_scope`、`runtime_key_observed_at`、`verified_at`、`enterprise_certified`、`license_purchased`、`owner_risk_accepted`、`exclusive_noteai_use`。Key alias须为已确认0902，scope为web_service；声明须经操作人实核，不从测试fixture复制。新月插入时，官方观察与Key读回/核实时点均须在最近24小时内；此24小时只约束新材料入库，不延长旧月期限。原owner授权从上一桶继承，当前账单未知保持NULL。

plan通过后apply仍重新上锁取DB clock并校验。`commit_unknown` 时不要重跑apply，先用只读数据库通道核对该period、snapshot SHA、admitted_count和旧限制，保存实际COMMIT结果；不能用进程异常推定数据库未提交。官方0额度进入安全HOLD，官方quota>0但used==quota入库后仍为exhausted。以上没有启用付费超额。

## 行业修复范围

新通用行业为“休闲娱乐体验”，覆盖洗浴、汤泉、水疗/SPA、按摩/足浴等真实到店体验。保持原页面与操作方式，补齐共享领域定义/别名、三个既有页面选择器及素材识别映射、生成策略、事实检索决策、提示词、诊断与校验、偏好域兼容。内容围绕环境、流程、卫生、服务感受、真实价格/套餐/时间等体验事实，禁止治疗疾病和医疗功效断言；医院/诊疗内容不能仅凭“按摩”归入休闲。

保持原模型124维、既有七行业/历史笔记兼容及Trends六域不变。新行业没有真实趋势覆盖时如实缺失，不重跑Item32/33/34。

## 美团追加核查与最小修复

用户追加要求一并检查美团，以下均为本次只读取证或隔离模拟测试。

- 两版美团都不读取 `amap_quota_buckets`，没有按月快照、月界截止或自动额度复位，因此没有与高德相同的内部月快照到期链。旅行事实路径为 `_search_meituan_travel()` → 固定官方 `@meituan-travel/travel-cli` 1.0.16 → `voyage query`。
- Token读取顺序为 `MEITUAN_AI_HUB_TOKEN`、`MEITUAN_OPEN_TOKEN`、既有本地配置兜底；每次查询使用0700临时HOME、0600临时配置文件并清理。代码无cookie/session、Token期限元数据或refresh-token自动续期。`ready`仅证明CLI和Token存在，不能证明今天供应商允许查询。事实缓存默认TTL0，无本地事实时的失败不会缓存；显式下一次请求可在授权恢复后重新读取，无后台无限重试。
- 共有缺口：父进程 `MEITUAN_RAW_JSON=1` 被白名单传给CLI。固定CLI的raw JSON分支先输出并return，跳过后续授权失败exit3的处理；应用仅凭returncode识别授权失败，会把401/Token过期错误JSON误记为无匹配事实。用同一模拟授权拒绝复现：prose/exit3为 `AUTH_FAILED`，raw JSON/exit0却无error_code。生产是否启用了该变量尚未确认，不能称今天正在发生。
- 最小修复仅删除子进程白名单中的该变量，保留既有正文和错误退出码合同；不更换Token、不改CLI、不增加外部请求。6项新增和29项既有事实测试共35项PASS，全部mock subprocess，不是真实美团验收。
- CLI本机实读：`/opt/homebrew/lib/node_modules/@meituan-travel/travel-cli/mttravel-bundle.cjs`，428037字节，SHA256 `8a0527bb6e8b9074cf0221756f35bca989945e8436e4841596a7b7bf79ae06d8`，与两版Docker固定来源一致；关键实现位于14466（Token）、14481（单次POST）、14505（raw分支）、14510（授权exit）、14549（环境开关）。当前生产二进制没有新鲜读回。
- 最近保留的真实成功是 `2026-09-14T00:17:26.094081Z`（北京08:17），旧分析操作matched、CLI1、物理HTTP及费用UNKNOWN；它不证明今天授权有效。候选版对绑定durable worker的CLI调用仍在发送前返回 `MEITUAN_TRAVEL_DURABLE_FENCE_UNAVAILABLE`，以防无法逐HTTP记录的隐藏调用。本补丁保留该保护；若新版要在此路径交付美团事实，现有发布方仍需单独证明安全adapter与真实供应商结果，不能删fence冒充修复。

待发布方安全恢复后核查：美团运行Token来源身份（不输出值）、配置开关/超时、真实授权与供应商额度、固定CLI哈希以及候选执行路径。无需在聊天中提供任何密钥。

## 隔离验证与实际限制

候选原基线已运行 `tests.test_amap_quota tests.test_amap_quota_acl`：30项收集，15项实际PASS，15项PG专用跳过。该结果验证既有保护能复现月过期，不代表续期修复、PostgreSQL权限或线上验收通过。

旧版修复提交顺序：`e648fda`（续期入口/状态/Admin）、`f092782`（维护事务绑定public schema）、`a016a7c`（事实检索与美团配置/提示/Admin行业选择）、`f08a20f`（行业全链路）、`3549949`（纯图临床主题/医疗否定结构）、`94644f0`（医疗扫描与普通待确认事实分离及双重否定）。旧版最终代码 `94644f0`，基线仍为d28，无生产部署。

最终旧版代码 `94644f0`：130项Python收集，115项PASS，15项真实PostgreSQL专用测试跳过；15项Node PASS。Python使用本机3.14虚拟环境，3.11仅对10个修改后的源文件编译语法通过，未做3.11依赖完整环境验收。局部行业回归39 Python/17 Node及最后14项行业检查也通过，但与最终组合有重叠，不累计为独立验收数量。

最终候选适配代码 `18e46e8f98b72a9629936d8c853f3b7527f74760`（基于4bdb）：139项Python收集，124项PASS，15项PG跳过；15项Node PASS。root在最终HEAD又执行一次与旧版相同组合，加候选专属 `tests.test_fact_trend_provider_fence` 9项；两版最终代码的完整组合日志如下，不把前一checkpoint结果冒称最终HEAD结果。

命令与完整日志：

```text
DATABASE_URL=postgresql:///offline-import-only NOTEAI_FACT_SEARCH=0 <isolated-python> -m unittest tests.test_amap_quota_refresh tests.test_amap_quota tests.test_amap_quota_acl tests.test_meituan_configuration_contract tests.test_fact_enrichment tests.test_leisure_industry tests.test_v04_composite_features tests.test_frontend_report_static tests.test_prompt_management.PromptComposerContractTests.test_api_and_admin_preview_share_composer_for_all_domains tests.test_prompt_management.PromptComposerContractTests.test_every_industry_preview_contains_substantive_shared_runtime_rules
node --test tests/frontend_leisure_industry.test.js tests/frontend_account_media_library.test.cjs
```

日志为 `/Users/openclaw/.codex/tmp/noteai-amap-leisure-20261012/old-version-final-python.log`、`old-version-final-node.log`、`candidate-version-final-python.log`、`candidate-version-final-node.log`；Amap25项专属及55项组合、行业39项/17项和医疗追加的原日志分别保留。最终组合没有warning/失败，测试材料不会自动成为正式供应商观察。未为补PG验收启动共享Docker或修改本机服务，现Colima socket不可用；PG连接/权限/提交故障仅fake connection验证，不能称真实PG通过。

| 测试要求 | 已实际执行 | 限制 |
| --- | --- | --- |
| 高德正常/过期/刷新失败/不足/恢复 | TempSQLite真实事务与MockTransport，失败HTTP0、恢复下一独立请求HTTP1、同月幂等/并发/回滚/COMMIT_UNKNOWN/旧限制保留 | 官方材料、PG与线上未验 |
| 行业分类和选择 | 洗浴/汤泉/水疗/按摩及SPA/足浴别名、临床主题排除、页面选择/OCR/Admin后端预览；手工Tracking/Admin选择器补齐并源检 | 截图模型回复mock，未做真实Tracking与Admin登录操作 |
| 单图/九图 | 实际截图处理、OCR合并、完整素材观察到生成stream `p3_done`、Prompt及标题/正文/话题/备选标题解析 | 模型/视觉回复mock，正文整形和打分部分stub；未证明真实模型质量、最终保存/记账或线上完整业务交付 |
| 事实成功/失败 | 精确同店匹配与返回字段、缺失不编造、数值/权益/时长事实边界、正向医学功效拦截、显式否认不误拦截 | 不是真实供应商与模型结果 |
| 原行业/124维/趋势六域 | 原域Prompt、固定124列及六域契约、新域无benchmark/trend返回NULL和暂无证据 | 不声称已训练新行业或已有真实行业基准 |

新行业部署前还需只读核对 `NOTEAI_MARKET_TIMING_REQUIRED`：默认0可如实降级；若显式为1，缺新鲜趋势仍按既有503门禁停止。本修复没有降低证据保护或修改生产该设置，不得以离线降级测试推定线上可用。

原页面QA：`http://127.0.0.1:15912/NoteAI_Pro_Demo_Framer.html`，1440×900/390×844；Browser skill未提供，按技能用既有Playwright。实际选择新行业、输入brief、诊断域同步、OCR别名和缺基准DOM检查均通过；业务console error0，桌面仅既有WebGL ReadPixels驱动warning。付款capabilities GET被离线stub，没有支付操作。页面身份、非白屏、无框架overlay、截图、交互检查通过。独立服务与浏览器已关闭。

Admin QA仅抽取原 `renderAmapAccountStatus` 组件到私有file fixture，1100×850/390×844，通过expired/soon/closing/unknown四态切换与溢出检查；不是经过真实登录的Admin验收。QA JSON分别位于 `industry/browser-qa.json` 与 `admin-amap-component-qa.json`。

未执行项目明确保留：真实官方当前配额读取、今天实际Key身份新鲜证明、生产续期、真实高德检索、真实模型单图/九图生成、生产页面回归、供应商账单/费用验收。离线fixture与mock结果不可冒充这些项目。

## 发布衔接

两种安排均由现有发布窗口决定：

1. **旧版小修复**：适合安全恢复完成、旧版仍将继续运行且业务阻塞需先解决时。先核对实际旧镜像/页面及0902来源；额度运营续期本身可由原发布方单独按真实资料处理，现有API逐次读DB，新桶核实入库后无需为额度读取而重启API；行业与提示补丁需旧版最小构建/页面回归。风险是增加一次生产维护且后续升级可能覆盖，因此升级必须携带同一修复回归。
2. **随新版统一纳入**：适合新版已经重新具备可靠发布前置条件时；对候选的worker fence/API/H5用三方patch适配并重新构建证据，不能复用尚未包含本补丁的冻结镜像。风险是当前旧版仍保持高德缺失/行业不全直到该安排实际生效。

当前不提供未经证据支持的上线时间。代码commit、离线测试、跨窗口通知和实际生产生效分别记录。

## 旧新版适用结论与剩余验收

| 版本 | 高德 | 休闲娱乐 | 美团 | 部署状态 |
| --- | --- | --- | --- | --- |
| 已上线d28构建 | 正确过期门禁与缺运营续期入口存在；隔离补丁94644f0完成并测试 | 原7域缺失确认；全链路隔离补丁完成并测试 | 无同类月快照；RAW_JSON错误状态缺口修复并mock测试 | 本窗口未部署，当前Key/桶新鲜读回仍UNKNOWN |
| 后续候选4bdb/app86ff/H5f185 | 同原始quota代码受影响；候选18e46e8适配并测试 | 同缺失；候选18e46e8适配并测试 | 同RAW_JSON缺口修复；bound-worker CLI保护仍禁止隐藏HTTP | 候选不是已上线证明；原发布方安全恢复优先 |

适配方式是同一组补丁三方应用，无冲突、无不同业务实现。候选 `fact_enrichment.py`、API、memory和原H5变更保留；未把旧版文件整份覆盖。候选额外Amap admission fence、KnownProviderFailure与UNKNOWN语义经过9项独立回归。候选提交链 `1fa9459` → `02380a8` → `18e46e8` 是本窗口适配检查点，不是原发布目录的HEAD；不能将它当成已由原发布方纳入的证据。

上线前剩余项由原发布方统一安排：安全恢复终结和实际旧构建读回；当前DB-clock/period/end及历史限制；0902运行Key的隐藏内存相等与官方账户/服务组归属；本月真实官方额度和观察材料；原受控维护权限与真实PG续期/幂等/失败读回；NOTEAI_MARKET_TIMING_REQUIRED真实值和新域缺趋势的既有门禁；美团真实授权/额度/CLI与候选安全执行路径；真实模型单图/九图、事实成功/失败与生产PC/H5回归。没有任何新费用或生产操作在本窗口执行，没有本轮上线时间承诺。

## 完整可转发交接文字

致“启动NoteAI授权续期发布”（01a0f7cb-70cc-71d3-bd42-2cc75bdae2d3）：当前安全恢复优先，这不是要求立即改动生产，也不是新的部署授权。本窗口按Owner要求在独立worktree修复业务问题，没有改你的目录、进程、数据、生产或冻结恢复输入。

首个上线“9月26日版本”有历史部署绑定d28f79c/API镜像35a61b6c…/静态generation-recovery-d28f79c17028-s2；后续候选为你原集成4bdb58b/app86ff10d/H5f18584d，尚未确认上线。两版原amap_quota、0031和行业Prompt/策略相同，两问题均不能推定新版已解决。

高德复现：在隔离临时数据库保留9月实际形状基线，将DB-clock置10月月界之后，amap_quota.admit在HTTP前返回AMAP_QUOTA_SNAPSHOT_EXPIRED，facts为空且不编造。原因链为一次官方月度观察→amap_quota_buckets immutable基线→最新月桶读回→DB-clock+10秒>=period_end→查询前拒绝；原9月记录北京时间10月1日止，无每月续期入口。Key正常与此错误可同时存在。今天实际Key/当前桶尚未新鲜核实，勿将历史0902读回充当今天证明。

修复增加每月受控官方观察plan/apply入口与72小时到期提示，默认只读；仅真实新月追加，同月NOOP保留用量/限制，失败停止、未知提交不重试，不延长旧有效期或清额度。原API逐次读DB，真实新月入库后无需为额度读取重启API。权限/schema/账单UNKNOWN和不编造行为保留。

休闲娱乐复现：原页面无法选择、共享taxonomy/Prompt无类别，API事实决策只允许美食/旅行。补丁覆盖洗浴、汤泉、水疗/SPA、按摩/足浴选择/识别/别名/检索/生成与诊断校验，原页面不改版；单图/九图全素材进入实际函数，标题/文案/话题解析有离线测试；治疗等医学功效拒绝，真否句/未知询问保留。固定124维、原七行业与Trends六域保留，新域benchmark/trend缺失为UNKNOWN。需确认实际NOTEAI_MARKET_TIMING_REQUIRED；如为1，原缺趋势503门禁仍保留。

美团没有该月快照，但两版共有RAW_JSON=1使固定CLI跳过授权错误exit3、被误当无事实的配置缺口。已仅禁传该变量并模拟验证；实际Token/额度仍待核实。候选bound-worker CLI仍由MEITUAN_TRAVEL_DURABLE_FENCE_UNAVAILABLE阻断隐藏请求，未绕过，需你后续确认可交付安全路径。

旧版代码序列e648fda/f092782/a016a7c/f08a20f/3549949/94644f0，独立分支codex/amap-leisure-repair-20261012；候选最终18e46e8f98b72a9629936d8c853f3b7527f74760，独立分支codex/amap-leisure-candidate-check-20261012。候选三方合并无冲突，保留你的durable/API/H5差异。旧版最终130收集/115PASS/15PGskip，候选139收集/124PASS/15PGskip，Node各15PASS；真实PG、官方检索、模型、线上均未验，mock不是线上证明。

完整原因/代码文件/复现与命令、日志、截图和剩余条件在 `/Users/openclaw/.codex/worktrees/amap-leisure-repair-20261012/noteai/docs/AMAP_LEISURE_REPAIR_20261012.md`。请在安全恢复完成后按你的既有发布安排纳入补丁及回归，重建受影响冻结构建的版本证据，避免后续升级覆盖。旧版先做小修复适合旧版仍需持续服务且阻塞需提前解决；统一新版适合后续发布前置条件已成熟，能少一次维护但旧版问题等待期更长。具体先后由你结合真实进度决定，本窗口不另开发布流程。

## 文件与职责

| 文件 | 目的 |
| --- | --- |
| `tools/refresh_amap_quota_snapshot.py`、`model/amap_quota.py` | 可重复每月运营续期、幂等/失败保护和只读到期状态，不更改生产0031与运行写权限 |
| `model/fact_enrichment.py` | 明确过期原因，休闲门店/事实类别匹配，美团CLI正文/授权错误合同 |
| `model/admin.html`、`NoteAI_Pro_Demo_Framer.html` | 原页面内补新行业选择及截图映射、未知证据展示；Admin到期/续期提示 |
| `model/v04_domain_policy.py`、`prompt_composer.py`、`quality_objective.py` | 共享行业/别名、专家和生成规则、诊断质量要求 |
| `model/api.py` | 素材分类、到店检索决策、生成/诊断提示与医学/事实边界；NULL证据投影 |
| `model/memory.py` | 新行业/别名的真实偏好作用域，与已有行业隔离 |
| `model/hot_keywords.py`、`v04_composite_features.py` | 新行业缺证据返回UNKNOWN，已有商业槽位支持；固定模型维度/六域来源不变 |
| 新 `test_amap_quota_refresh.py`、`test_meituan_configuration_contract.py`、`test_leisure_industry.py`、`frontend_leisure_industry.test.js`；原 `test_prompt_management.py` | 对应离线行为与兼容回归，mock边界在测试与本报告明确 |

## 页面证据（全部隔离或模拟）

原页面手机选择与brief输入；未提交付费生成：

![独立本地原页面休闲娱乐选择](/Users/openclaw/.codex/tmp/noteai-amap-leisure-20261012/industry/leisure-390.png)

原Admin组件抽取后模拟“即将到期”；不是生产Admin：

![模拟Admin月度续期提示](/Users/openclaw/.codex/tmp/noteai-amap-leisure-20261012/admin-amap-soon-mobile.png)
