# NoteAI Production Deployment Execution Plan

Status: `ITEM34 GENERATION1 SCOPE APPROVED / EXECUTION IN PROGRESS / OLD WINDOW SEALED / OTHER PRODUCTION PAUSED`

Date: 2026-09-09 (current scope below; July sections retained as history)

Task: `PROD-DEPLOY-PLAN-001`

The bounded Item34 job below has failed and closed safely. Its old observation
window must not be replayed or restarted. Retained approval and commands are
execution history, not authorization to repeat them or run other Items.

**本次已获owner一次批准：Item34 同对象新T0受控实施（2026-09-09）。** 批准基线
`11074c6147cc4acebb3b72c2470fe25debe49c0e`，其本计划SHA256为
`e77d033a5c25392f48d66a6bf2ed3e6331727728915386a1634d2d4921a24162`。
owner在ACR恢复后明确回复“批准”；以下范围串行执行，不逐命令再次申请。沿用下方现有
八步实施材料与全部SQL/hash，唯一XHS源码仍为fcc863f，不复用旧窗口授权。
现有ACR身份已恢复，余下申请限于：把该唯一已构建镜像/host包传至API-F并发布至既有
私网仓库新不可变tag `item34-xhs-fcc863f-g1-20260909`；0019 verify-only及0020
preflight/apply/verify；同一owner-owned原笔记的新鲜T0及原managed row的owner CAS；
24h/3d各一次受控采样与原managed验证（仅精确Tracking unit的必要替换、daemon-reload、
有界start/health/stop及原unit/配置恢复）、两次临时attempts SELECT/撤回、精确停止、
失败reconcile/CAS恢复和现有Evidence保存。新作业核心7表9distinct（含0020账本1行）、旧新合并13distinct、
新增最多2admissions/0自动重试，旧认证/注册/900gift不重做。真实provider费用与
既有传输/存储增量未知时保留UNKNOWN；无新增固定费用、Builder或其他资源。

ACR认证入口已核实：容器镜像服务 → `noteai-prod-shenzhen` → 访问凭证；当前页面
提供“设置固定密码”和“生成临时密码”。9月7日下午Handoff记载通过ACR页面生成
临时凭据，值未读取/记录，当时Password提示已取消；晚间owner报告Login Succeeded
及后续push成功不能证明使用过owner亲设的固定密码。不得要求owner回忆未经证明
存在的固定密码，也不得将当前一次AUTH_DENIED直接归因为凭据过期。
此前只检查manifest，未发起docker login，故当时没有Password输入提示。
September9后续owner已设置固定密码并在终端隐藏输入；主代理在既有API-F root
会话执行下列精确命令一次，已实际读回Login Succeeded及返回root提示。
认证使用现有合法身份的正常凭据流程；命令为
`docker login --username=aliyun0345188616 noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com`。
只有命令实际到达Password提示后才请owner在终端隐藏输入，不发聊天、不重置密码、
不开放公网。控制台MFA不代替Docker仓库认证；主代理未生成或读取新凭据、
登录成功后仅做一次旧manifest只读验证（既有612a7e57...17620 digest，timeout30s），
返回真实manifest且退出码0；未下载镜像层。当前认证阻断解除，先前拒绝原因仍不猜测。
截至2026-09-09 19:52:47北京时间，stat-only读回/root/.docker为700/root、
config.json为600/root；未读取内容。Docker仍提示未加密保存，未配置credential helper，
文件访问限制不冒充加密。未来同主机/root在凭据有效时可复用，但Workbench/MFA独立。
生产发布/0020/同对象新T0及下述验证恢复现在仅在本段已批准范围内执行；
其余Item/全局自动化继续PAUSED。

新T0尚未实测，不预填。实施时按真实T0记录24h窗口[T0+24h,T0+72h)及3d边界T0+72h，
当前线程用时钟等待并在每个阶段核对持久化status后仅调用既有durable launcher一次；
不依赖PAUSED任务唤醒。若线程被中断，恢复只读status，不重放UNKNOWN；若24h已
越界则封存该路径。24h完成后读回真实完成/snapshot时间，并给出3d的北京时间和
同一线程继续方式。此申请不包含API/Payment/ALB/SG/DNS实施或其他Item真实执行。

执行材料恢复：原/private/tmp两个包已不存在，既有Colima原镜像仍匹配fcc863f源码、
OCI index及config39dac3bb...719f01。已原样export，27个content blobs全部实算通过，
没有重建或改标签。以下为当前实际传输包；压缩/容器tar元数据不同不改镜像身份：

| 当前文件（目录 `/Users/openclaw/Downloads/noteai-item34-fcc863f/`） | bytes | SHA256 |
|---|---:|---|
| `item34-xhs-fcc863f-linux-amd64.docker.tar.gz` | 377759397 | `af7c177451c1c056a40abdadbfc1335641798f1dd68579533ff2d87172b15d69` |
| `item34-host-fcc863f.tar.gz` | 48566 | `cf06fcef012b7408e3c6a2ab383d3d3c936e55cb62ecd067a8c423223c39208f` |

host包恰有原11个allowlisted常规文件，逐一由fcc863f提交恢复并核对原SQL/源码hash；
包含该源码的private-bind helper（28c06849...327f0），不混入后续Item36代码。
旧包及旧源码身份保留在历史段，不能据旧传输hash核对当前包。

当次前置实测：2026-09-09 20:05:30北京时间，现有noteai_admin确认全局
started/UNKNOWN/UTC日admissions均0，原ACL未扩大、十个范围内表无额外enabled
noninternal trigger；20:07:01固定原row/旧failed attempt精确CAS状态满足、history SHA
`3f14d4342114bc283c88f9c90a65748ad62a4216ec1f1d2147dc03c54c37bb40`，
旧id/submitted_at/published_at未变。20:27:16原0019 verify-only逐字段读回ledger1、
policy1、RLS/qual exact，本作业INSERT0。该结果不代表0020已执行或新T0已建立。
前序上传路径故障（下方已有替代路径实测）：SSM不支持传文件；ECS/OOS官方上传组件出现跨域脚本异常，
仍未选择/提交文件。目标/root、root/root、0600、不覆盖、超时1800s已准备；
改用既有身份/资源内正常传输路径，不扩大权限、不减弱浏览器安全。ACR认证已恢复。

传输路径补充（当次执行事实）：既有私有OSS桶
`noteai-private-prod-20260729-c60cc608`，前缀`noteai-private/item34/g1-20260909/`。
20:53:53北京时间，唯一host gzip上传成功，并由API-F既有角色
`noteai-storage-api-20260729-c60cc608`以IMDSv2/V4/内网GetObject一次取回，
48566bytes及cf06fcef...208f全SHA通过。落地目录
`/var/lib/noteai/item34-image-build-20260906/g1-20260909-transport/`root0700，文件0600。
实际命令通道为现有ECS云助手立即执行；Workbench SSM断开，不再依赖其上传或残留输入。
旧b8镜像仅作为无业务环境的SDK工具，下载0自动重试、失败保留partial后只读核实；
不是旧采样器执行。新镜像上传已提交一次，完成后同样精确Get/字节数/hash校验，再load/push。
没有新建桶、授权角色或固定计费资源；实际传输/存储费用未知，不记录为0。

21:08已落地source/workdir：`/var/lib/noteai/item34-image-build-20260906/g1-20260909`
（root0700，11文件逐hash通过）。主机Python3.11.6，5个Python文件语法通过。
未来binding为该目录`observation-binding.json`；24h/3d/managed及必要restore journal
各用其下未使用文件，绝不复用父目录旧journal。21:10原Tracking仍disabled/inactive/dead，
原unit SHA4392872f...91f82d匹配；`--current-image`实际为本地config
`sha256:a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec`，不能误用API registry digest。
固定XHS页面现在要求网站安全验证，已请求owner本人处理；未取得新指标/新T0，
该路径暂停不阻止已批准的镜像发布和独立准备，且不请求新URL/绕过验证。

当次续读：21:25 journald实际有效5项匹配、服务active；现有Tracking告警正常，
仅复用原通知历史、未修改规则。DMS新标签出现WebSocket及登录权限提示，未申请权限；
原owner标签21:40:21仍实际查询成功：noteai_admin/三owners、globalstarted/UNKNOWN0、
0019exact1/0020absent、原ACL未变。原OSS上传任务随后明确success2/uploading0/failed0，
唯一镜像Get已派发一次。较早HEAD因对象尚未核实而返回OperationError，其具体原因
未定位，不猜测403/凭据过期，也未重试；以后按Get真实字节数/SHA读回继续load/push。

**唯一XHS镜像已实际发布。** 21:41:21整包Get/hash通过，单次load后21:43:40目标
主机隔离验证Python3.11.15/x86_64与九源码hash通过。检查曾误用两个镜像内路径；
冻结Dockerfile85实际复制到/app/model，修正检查路径后通过，无重建/重load/改OCI标签。
21:46:06一次push退出0；21:47:00 tagmanifest、config、平台、本地RepoDigests交叉匹配。
后续只使用真实引用：
`noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:a2ee0f2ef94191af45b2af1dce192379194bd103e5084204f7ff224457ab6a88`。
config保持`sha256:39dac3bb52cf49296e2e11e9156fc045408345cb32786456e4e26f45fb719f01`，
源码仍fcc863f。传输目录已保存image-push.log/.exit/.pid和image-published-manifest.json，
root0600；遇到断线只读这些原结果，不重新push。0020尚待执行，新T0未建立。

## September9 authenticated inputs and C implementation (no production execution approval)

Owner has restored Aliyun login. The September8 login stop below is historical.
Main agent used existing root Workbench sessions and existing DMS `noteai_admin`;
no new identity, role grant, credential reset or production task was started.
DMS's optional new `AliyunServiceRoleForDMS` creation was cancelled. Cloud UI and
host reads below concern configuration/metadata, not user/order/note payloads.

**Item34 DB owner input is now concrete.** DMS SELECT at
2026-09-09 07:23:54.161471+08:00 returned database `noteai`, PostgreSQL160013,
active/session role `noteai_admin`. `tracked_notes`, `tracking_provider_attempts`
and `schema_migrations` are all owned by that role, active_is_owner/can_set_owner/
schema USAGE/CREATE all true, RLS/force RLS false on those three tables.0019 ledger
hash is `bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f`;
0020 ledger absent and generation columns count0. `noteai_app` has no SELECT on
attempts or migration ledger; it does have SELECT on the other five named core
tables. Attempts ACL is exactly
`{noteai_admin=arwdDxt/noteai_admin,noteai_xhs_tracking=ar/noteai_admin}`.
Existing config policy `noteai_xhs_tracking_config_read_v1` remains SELECT,
PERMISSIVE/public, current_user restricted to Tracking and is_secret=0 for the
two config keys. No config values or business rows were read.

The first bounded READ ONLY batch completed with ROLLBACK but DMS exposed only
the last status; a SELECT-only result was truncated, so its existing metadata
fields were expanded into46 scalar rows and read through the UI. That final
SELECT reports transaction_read_only=off; it contains no DML/DDL/grant. Do not
claim the final DMS connection is transaction-enforced read-only. Metadata proves
owner privileges, not a successful future DDL/grant/revoke or a fresh no-UNKNOWN
business preflight. Those exact checks remain inside the future bounded job.

**Item36 actual C/F inputs.** Fresh F07:17:25 and C07:24:18 Beijing systemd
projections show API enabled/active/running, no drop-ins, NeedDaemonReload=no,
no outstanding Job and NRestarts0. F Payment is not-found; C Payment is loaded,
disabled/inactive/dead. F Tracking/Trends are disabled/inactive; C has neither
unit. C07:34:49 Docker projection confirms x86_64, exact API container
`872cfd4ec0f5d61ff99036851a74a8ef4890fabe9fadb7a80c2f5c5e1a8e4aa6`, running,
bridge, loopback8000, Docker restart=no and no Payment container. API ref remains
the old private `noteai/app@sha256:612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620`;
image config `dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53`.
No production health request or full Docker Env read was performed.

C=`i-wz9j36od3nf2b1uw7bvg`/10.42.10.44/app switch
`vsw-wz93ahnxzaztndac48er3`; F=`i-wz9bgztwf1tiakww2ops`/10.42.11.166/app
switch `vsw-wz9u43x14smx5vl8mo51x`. Shared VPC=`vpc-wz90181in1rs2zqpnn9o3`,
API SG=`sg-wz98p0xa5040vpnyvgys`. Current ingress has only TCP22 from
100.104.0.0/16; no TCP8000 grant. ALB reserved C switch
`vsw-wz943c5e3hy03rrkuyo40`=10.42.0.0/24 and F switch
`vsw-wz91uof0a4blq54yi09zn`=10.42.1.0/24 are available,252 addresses each.
Future ALB-only8000 source rules must be explicitly applied and read back with
the listener/backend job; these source subnets are not the app switches.

C actual Secret-free unit bytes now live in `tests/fixtures/item36-api-c.service`
(1577bytes/SHA46010368ded3db5567bca45afb75f18383ccf23de6aa6d0d99299d87701677e6)
and `tests/fixtures/item36-payment-c.service`
(1481bytes/SHA40a49dbee82bbb6f617d2ec439b1ab608b980ceea60125a20dc09a83737547bb).
Remote exports required exact historical installed hashes and API env allowlist;
no .env content was accessed. Payment also exactly matches the cd1ae7a template
with its accepted ad582745…02e2b image. A simple F→C comparison failed safely;
actual C preserves its own StartLimit/KillMode/timeouts/short Docker arguments.

The existing renderer now accepts only separate `-e`/`-v` as the already-checked
long env/volume options. Actual C regression verifies private bind, future image
replacement and Payment namespace with prior-unit rollback;14 focused checks pass.
Independent read-only audit confirms only the intended bytes change. No candidate
image rebuild/relabel is needed for this host preparation helper correction.

Runnable local outputs under `/private/tmp/noteai-prep-20260909/`:

| Output | SHA256 | Application boundary |
|---|---|---|
| `api-c-bind/noteai-api.service.candidate` | `01909adec06ec678d26a03a405331b0e8cb3e1d6ed22706ed36d611444697dbb` | only bind changes to10.42.10.44:8000; old image retained |
| `api-c-bind/noteai-api.service.rollback` | `46010368ded3db5567bca45afb75f18383ccf23de6aa6d0d99299d87701677e6` | exact enabled/running C original |
| `payment-api-c/noteai-payment.service.candidate` | `20fe15cfb4c245192961e52cb8c6c2f50e9c5edeafedb0c64cf58650c38c1e17` | API-C namespace, callback1, no publish; real unpublished-image placeholder remains |
| `payment-api-c/noteai-payment.service.rollback` | `40a49dbee82bbb6f617d2ec439b1ab608b980ceea60125a20dc09a83737547bb` | restore existing C unit disabled/inactive; do not remove it as on F |

Candidate image update, private binding, and Payment first enable are separate
implementation actions. Real f3 API/Payment artifacts stay valid; a future real
publication supplies their digest arguments. A placeholder is not apply-ready
service content, but publication absence does not require a rebuild or block
completion of the local preparation. Native signal/stop caveat below remains.

**ALB/TLS and fresh quote.** Shenzhen ALB instance list confirms zero instances;
no real listener/backend/DNS target can yet be filled. Existing API certificate
is Issued `26148574-cn-hangzhou`, subscription `cas_dv-cn-ev94vjind00k`, covering
api.noteaipro.cn and www.api.noteaipro.cn, valid2026-07-18 08:00:00 through
2027-02-02 07:59:59 Beijing. Fingerprint7356F712ED37DE4D6FD9D40969EE971B6459BB63;
RSA2048/RapidSSL TLS RSA CA G1 → DigiCert Global Root G2 → DigiCert Global Root CA.
Console chain validity is2017-11-02–2027-11-02 and2024-01-18–2031-11-10.
Cloud deployed resources0. Subscription expiry2027-07-19 is not certificate expiry.
Only public metadata/chain was viewed; no key/package download or TLS binding.

Authenticated quote form: Shenzhen, IPv4 public Standard ALB, production VPC,
C/F reserved ALB switches, automatic two EIPs, pay-by-traffic, no shared bandwidth.
Displayed ALB0.125CNY/hour (list0.147), LCU0.042CNY/unit (list0.049); separate same
region BGP EIP form displays0.020CNY/IP/hour and current CDT tiered traffic.
720h atLCU1/EIP2 comparison is149.04CNY before traffic. This is recalculated from
September9 displayed inputs, not reused from the old149.04 estimate, and is not
a spend ceiling or binding order quote. Forms state final discount at order;
tax inclusion, validity duration and final contractual discount are UNKNOWN.
No order/config-list save, agreement, purchase or resource change was submitted.
[Current CDT pricing](https://help.aliyun.com/document_detail/410942.html) gives
mainland0.80/0.75/0.70/0.65CNY perGB by successive0–10/10–50/50–150/>150TB tiers;
account-wide free allowance is shared and its remainder was not requested, so
no free traffic is assumed. Future approval needs a finite traffic/spend ceiling.

Fresh EIP list: both addresses allocated, none free. ICP EIP
`eip-wz9upi1f15ywx1nsdhy9l` is attached to C; the other is attached to existing NAT.
Neither can be silently repurposed.

**ACR and DNS final readback.** Existing ACR `cri-xpuhaclqkxlwy47t`, repository
`crr-itdckfeycjvs274j`/noteai/app is private/normal with immutable versions, no
code source. Private endpoint10.42.10.49 is effective in the production VPC via
the C app switch; public switch aria-checked=false and public whitelist empty.
All18 current versions on one unfiltered page contain no proposed
`item34-xhs-fcc863f-g1-20260909`; old b8 tag remains. No tag was reserved/pushed.
API-F07:37:24Beijing `docker manifest inspect` of the exact old612a digest returned
rc1/AUTH_DENIED. Only metadata was requested, no layer download. This is a real
credential-path blockage, not proof of expired password or a network/root cause;
no repeat request or Docker config/Secret read. Console session is working.

Fresh noteaipro.cn DNS page has exactly3records/onepage, empty search: only
`_dnsauth`, `_dnsauth.api`, `_dnsauth.admin` TXT, all enabled TTL600s. No root `@`,
`api` or `admin` business records exist. Their actual before-state is ABSENT,
not missing old record IDs/values. Future authorized creation must retain the
returned exact new IDs for rollback and preserve all3 TXT records. No DNS edit,
record ID invention, nameserver change or public probe was made.
Item34 new T0 remains unstarted.
Readiness30/38; no terminal Evidence/manifest change.

## Current local preparation — September8 (no production execution approval)

### Item34 同对象新 T0：实施材料已接通，生产仍未授权

最终可运行XHS产物已保存，源码`fcc863f65ad1d3d788e8936ef1284a9ab27ad025`：
`/private/tmp/noteai-prep-20260908/item34-xhs-fcc863f-linux-amd64.docker.tar.gz`，
377808949bytes，SHA256`f4e39dbcd57fcc9c4eef63f8db6ffde8a0e8a108ebce1c7ed41637a86d7a9ed3`。
唯一tag`noteai-local/xhs:fcc863f`，27个content blobs逐个校验，Docker load回读成功。
本机Docker `.Id`为OCI index `ab538ef4e1f21e18a9c2c20198b250e88c304d39167fff95ca583a58fae2dc94`；
archive config为`39dac3bb52cf49296e2e11e9156fc045408345cb32786456e4e26f45fb719f01`，
二者有真实index→manifest→config关系，均不是已发布ACR digest。未来按API-F实际Docker
读回的image identity绑定容器，不把本地OCI index冒称config或云端digest。

对应host传输包`/private/tmp/noteai-prep-20260908/item34-host-fcc863f.tar`，
11个regular成员、256000bytes，SHA256
`1ccdcd629f7a32c6e7d71f23f379345b42a4ad2aee6ed822d8f1094d907698b7`；
wrapper/checkpoint/durable、既有managed/private-bind helper、冻结unit、0020及三SQL、
0019 verify均逐字节匹配，包含恢复所需依赖。没有Secret、真实binding、新T0或日志。
没有上传/发布，新范围授权与实际owner/ACR会话读回后才可使用。

实际镜像验证：116个打包文件含3个真实LFS模型匹配；Python3.11.15/linux-amd64/
UID999、xhs-http role及全部源码标签匹配，无Playwright。原生entrypoint执行
_config_snapshot，以本地noteai_app只读连接隔离PG16.15、读回预置非Secret配置；
临时DB和LOGIN属性恢复。真实Docker模板只返回允许的绑定环境字段，明确排除另一
合成Secret字段，未启动worker。最终镜像内23个PG测试3.342s通过，不用旧测试镜像
覆盖新源码；117个离线执行/恢复/Evidence回归通过。镜像构建使用已授权的可信依赖
下载，未创建云端Builder；本机执行不冒充API-F生产镜像验收或真实72h观察。


复用同一篇 owner-owned 笔记 `6a7954010000000026034707`，不索取新 URL。
批准依据仍为 `docs/XHS_TRACKING_PRODUCTION_CONTRACT.md:107–112`；旧窗口
`FAILED_24H_OLD_WINDOW_EXPIRED` 永久封存。以下是未来一次申请的最小范围，
不是9802111旧授权的续用，也没有设定或启动新T0。

依赖顺序与实际对象：

1. 现有合法会话只读核对实际数据库名、三表`tracked_notes` /
   `tracking_provider_attempts` / `schema_migrations`的owner、owner可激活性、
   schema CREATE权限、原ACL/撤权通道、旧失败attempt、无全局started/UNKNOWN。
   DMS服务角色只解决DMS接入；不替代DB实际owner与权限。September9已读回三表
   owner均为noteai_admin、schema CREATE可用、0019存在/0020未安装，详见顶部。
   生产执行前仍核对当前ACL、精确历史attempt及无started/UNKNOWN，不新增广泛grant。
2. 仅受控发布本次最终XHS候选到既有ACR私网不可变tag，读回真实digest；API、Payment、
   ALB部署不是此前置。旧b8镜像原样保留。费用为既有传输/存储及后述真实请求增量，
   未知不记0；无Builder、扩容、新账号、固定收费资源或公开ACR。
3. 0019仅用原verify读回（本作业INSERT0）；以实际三表owner执行以下0020
   preflight/apply/verify，先在同会话绑定`noteai.item34.expected_database=noteai`及
   `noteai.item34.expected_owner=noteai_admin`（执行前再核对实际身份）。
   apply只安装schema/CAS，未开启观察。
   原生migration也会被未来`render_predeploy.py`发现；该生产入口仍PAUSED。
   不能在已有0020的DB上用缺0020的旧源码运行predeploy；正常API启动不运行迁移，
   因此API/Payment f3运行产物无需重建。
4. 经新范围明确批准后，通过合法XHS浏览器重新读取同对象的新鲜详情，保存真实UTC/
   北京时钟与likes/saves/comments作为新T0，不使用旧缓存、发布时间或历史snapshot。
   浏览器可产生多条网络请求、访问/会话副作用，次数与费用未知时如实保留未知。
   不调用NoteAI注册、赠分或再次POST；原managed row已经存在。
5. actual table owner在有界事务中调用`public.noteai_item34_open_observation`，
   参数为原track/owner、previous_generation=0、精确旧failed attempt、新T0和新指标。
   函数CAS当前行至generation1，保留id、submitted_at、published_at及旧attempt；
   默认日常worker不claim新代次。提交后由noteai_admin精确只读核对结果，UNKNOWN不重放。
   将同一7字段binding写入现有root-only文件：track_id、owner_id、generation、
   observation_started_at、initial_snapshot、previous_attempt_id、previous_attempt_sha256。
   wrapper/worker在claim与admission行锁内核对完整binding和旧history SHA。
   T0阶段不提前调用app wrapper bind，不额外增加一次grant或把临时SELECT留到24h。
6. 每个采样阶段先确认owner撤权通道、保存原ACL，仅新增noteai_app attempts SELECT
   （影响全部该角色会话）；随后才运行app wrapper bind/snapshot与dispatch。24h的bind
   应为ALREADY_BOUND/target_rows_mutated0。沿用现有durable launcher的
   `run --observation-binding <root0600文件>`，同一
   binding分阶段`24h`与`3d`，分别使用未用过的journal和`g1-24h`/`g1-3d`精确容器。
   24h真实完成及snapshot严格在[T0+24h,T0+72h)；3d在T0+72h之后且晚于24h。
   两阶段最多2个新provider admission、0自动重试，普通定时器/自动化不恢复。
   24h后明确下一阶段的实际时间及当前线程继续方式，不能依赖PAUSED任务唤醒。
7. 每阶段结束及异常时按原ACL立即只撤本阶段新增授权，撤回失败立即报告，不把授权
   留到下一阶段。按精确CID、实际镜像/命令/
   非Secret环境binding停止任务；不同stage或重复binding拒绝操作。只投影允许的Docker
   字段，不读完整容器Env。durable restore沿用原journal/CAS，采样UNKNOWN不妨碍已知
   配置的精确恢复；恢复失败立即报告，不能为了验收覆盖并发状态。
8. 完成现有managed Tracking验证、停止/恢复/读回、ACL撤回及Evidence保存。managed
   缺口仍为incomplete，不能用两次采样替代。沿用既有managed helper、真实unit模板和
   journal，不另建executor/receipt。DDL事务失败rollback；提交后保留schema/ledger/
   history，只停止精确任务、恢复配置和新增ACL，不删除数据或down migration。

未来同会话有界开窗SQL形状如下；所有`<...>`仅在新范围获准、真实T0/owner读回后
按同一binding替换为审核过的字面量。占位材料不能直接执行；不创建独立迁移/执行体系。

```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '45s';
SELECT public.noteai_item34_open_observation(
  '<original_track_uuid>', '<original_owner_uuid>', 0,
  '<sealed_failed_attempt_uuid>', '<fresh_zoned_T0>'::timestamptz,
  '<fresh_likes_saves_comments_JSON>'::jsonb
) AS opened_generation;
COMMIT;
```

返回1仅代表CAS已知成功；由noteai_admin独立读回原track/id/timestamps、generation/
T0/initial/next_check_at=T0+24h、旧attempt完整hash及零新attempt。wrapper bind留到
24h临时SELECT作用期，应返回ALREADY_BOUND/target_rows_mutated0。失联只做该只读
reconcile，不重发开窗SQL。

本地已验证的计数兼容：新采样6表8distinct，加一次0020 ledger为7表9distinct；
旧核心5表6distinct原样保留，合并13distinct、累计3admissions。distinct不是DML次数。
新范围必须明确批准该前瞻计数和必要DDL/临时ACL/安全失败副作用。旧认证/注册/900gift
只在旧辅助记录中保留，不再执行。现有validator的显式generation1分支引用同一canonical
文件的prospective_observation子记录；校验固定封存根SHA、完整binding/原track时间、
0019 verify-only/0020 INSERT1、原managed终态和同一辅助写摘要。未来批准后才在原manifest
绑定observation_authorization的checkpoint/plan SHA；当前manifest、canonical及30/38不变。

SQL及host来源（SHA256；均未上传/执行）：

- `model/migrations/postgres/0020_tracking_observation_generation.sql`：`22ef0a2c21529fe4d8ed38c42c2283ae61e6e6822d6411bd07620d353042d7a9`。
- `scripts/postgres/item34-observation-generation-preflight.sql`：`7b7ab54f532cbebc1256dd7c390fc4aa35b7700797212ac456dc9b2babafad3c`。
- `scripts/postgres/item34-observation-generation-apply.sql`：`c3e7d27e01605b5b6f1edeaa2a01b0b2c2d2f64043ea8986f21f27828ed5856f`。
- `scripts/postgres/item34-observation-generation-verify.sql`：`1001e9ea9477b7941dc2f95dfbffbc13e68a3f1432c736a8ff1c1aea0e6284bf`。
- `deploy/production/execute_item34_tracking.py`：`7f3eb11f3378369431161c7d54e319da4505ad67e3a5e550efc3f8625e6bd42e`。
- `tools/execute_item34_tracking_checkpoint.py`：`027980d8f0298c5f5de71ed1e91793aa26f25597594a329d6e141d88f27a9a98`。
- `tools/run_item34_tracking_durable.py`：`9e476127c270390a6269df33fc37c74ccec8c3880426d809000ef5c5c7597916`。

23个实际Python3.11/amd64 PG16测试通过，包含非superuser三表owner、全部verify结果集、
失败DDL/ledger同事务回滚、原生migration发现/checksum拒绝、完整binding漂移和真实worker
两阶段写集。31个旧Tracking/性能契约通过。117个checkpoint/wrapper/durable/evidence
离线回归通过；测试修复曾暴露容器内旧checkpoint遮蔽新工具路径，实际封装必须逐文件核验。
入口已放行严格限定的只读_config_snapshot阶段命令，最终XHS镜像验证已通过，见本节顶部。
旧生产失败原因仍未定位；本地错误码保留修复不能声称供应商已恢复。


Current runnable API/Payment candidates are built from source checkpoint
`f3deedbc1dfdbc7db2ffdd7213df2198c5e1d25d`, including the Item30 Kimi repair,
Item31 runtime binding and the PostgreSQL connection-options correction.
The combined archive is
`/private/tmp/noteai-prep-20260908/api-payment-f3deedb-linux-amd64.docker.tar.gz`,
377756229 bytes, SHA256
`c95e557ee67e5cd6c8b228fb04170ce770a4629d8cbe69a124129ef1fb530ae1`.
It contains exactly the API and Payment local tags; all 33 content-addressed
blobs match their hashes. These are unpublished artifacts. Local image IDs and
archive config hashes are not ACR publication digests. Later documentation
commits do not change the actual source identity or require relabelling.

Both images match 115 packaged source/dependency files, three real LFS models,
Python 3.11.15, linux/amd64 and UID999. Actual role entrypoints return live/ready
200 in an isolated shared namespace: API uses temporary SQLite and V04 models;
Payment uses PG16, a local test role and synthetic callback configuration.
Both packaged DB helpers now retain read-only on / statement timeout 5s / lock
timeout 1s; the health override changes only statement timeout to 1s. The server
rejects a zero-row UPDATE in read-only mode. No production DB was contacted.
The actual API also completes full startup on fresh PG16/19 migrations with
noteai_app granted only SELECT managed_prompts, zero business seed rows and
the original read-only PGOPTIONS: live/ready200, V04 loaded, on/5s/1s confirmed.

Local shutdown has an explicit platform limitation. API SIGTERM exits 143 after
complete shutdown. Payment as PID1 under local amd64 emulation logs complete
shutdown but remains in sigsuspend and reaches bounded stop exit137, without OOM.
A minimal signal.raise_signal program, with no NoteAI imports, reproduces that
PID1 behavior. The same Payment image with local Docker --init returns ready200
and exits143 in 0.24s. This isolates the observed behavior to the local signal/
PID1 runtime boundary; it does not prove the native production host's behavior.
No speculative application shutdown patch or production --init change is made.
Keep the normal native stop/readback in the existing future implementation.
The restored older local API passes health and its namespace has no Payment
listener. This is a local first-enable rollback rehearsal, not proof of the
production before-state or graceful PID1 stop acceptance.

Historical September8 cloud input path (superseded by September9 readback): the existing API-F terminal remained visible, but a
Workbench new-connection attempt explicitly returned account not logged in or
login expired. The connection form was cancelled; no host command/login was
submitted. The existing fresh ECS tab shows the Aliyun login page. API-C unit,
ALB/TLS and account quote inputs still need an authenticated read; none are
inferred from API-F or old pricing. No production execution was resumed.

Item31's explicit per-transaction canary writer is saved at `e2b2de9`; its real
isolated PG16 chains and failure readback are detailed below. Current Item34
managed preparation now renders the exact frozen suspended unit and validates
restricted service/container/health projections against the candidate image.
An injected-adapter bounded start/health/stop/CAS-restore sequence reuses the
existing durable Journal; real fsync failure and UNKNOWN recovery are tested.
The native host binding is now implemented in that same module, with the original
lock, exact file/CAS, bounded commands and restricted Docker projections. A start
timeout with an outstanding systemd job must receive a bounded stop even if no
container is visible; unresolved stop/job or foreign state prevents restoration.
The prepared native binding does not satisfy managed terminal fields.25 managed
cases pass in actual Python3.11 isolation; native operations are tested through
an injected runner/temporary filesystem. Three actual local Docker create-only
projection cases pass without exposing environment values. No real systemd start,
provider or production DB health was run. Existing DoD and time rules are unchanged.

Before any future live application, bind the reviewed host launcher and current
manager scope for daemon-reload, real published candidate, current log/alert/role
evidence, and the same owner-owned target and prospective anchor/count compatibility. Durable
original/intent records support interrupted readback; no automatic resume/replay
or process-kill recovery success is claimed. Failed services, outstanding jobs or
concurrent changes remain explicit UNKNOWN rather than an unapproved reset/retry.

The existing durable launcher now has the separate `managed` action below. It
does not load the old sampler and rejects stage/track/restore arguments. Initial
journal failure prevents dispatch; UNKNOWN is nonzero and successful process
completion remains INCOMPLETE.17 Python3.11 launcher/default-path regressions pass.
Current API-F host Python is3.11.6; after08:03 Beijing reconnect its API and Trends
both show NeedDaemonReload=no, without any actual reload or service action.

The following is **prepared command material, not authorization to execute**.
Reuse the existing host source/workdir layout and its root-only journal directory;
bind actual paths and freshly read image/config IDs only in the future approved
application. Include the updated durable launcher, managed helper, its existing
private-bind helper import and frozen Tracking template. Do not use or overwrite
the old completed sampler's journal, unit name or archived host bundle.

```bash
sudo -n systemd-run --unit=noteai-item34-managed-once --property=Restart=no \
  --property=UMask=0077 /usr/bin/python3 \
  "$ITEM34_SOURCE/tools/run_item34_tracking_durable.py" managed \
  --current-image "$CURRENT_TRACKING_IMAGE" --image "$REAL_ACR_VPC_DIGEST" \
  --image-id "$REAL_IMAGE_CONFIG_ID" --journal "$ITEM34_WORKDIR/managed.host.jsonl"
```

This one-shot host process is independent of the Workbench connection. Confirm
the exact unit/journal are unused before an authorized launch; an uncertain
response requires exact unit/journal readback, never relaunch. Existing log and
original-unit/intent records must survive interruption. No timer, automatic
resume, broad reset or old-window restart is added. This entry has not been
uploaded/run in production; a same-target/new-anchor/count-compatible owner scope is
still needed before any new production execution.

September8 07:11–07:24 Beijing API-F read-only configuration checks confirm
Tracking disabled/inactive/dead and no running service-labelled container, unit
SHA `4392872f292a8caef960cc4f8eea34fed62791e783f6dcfc75f7655f2891f82d`.
API remains active with its old immutable image and127.0.0.1:8000 binding;
unit SHA `f591f43b0377402dbc026c4e7f5eee08bc8b884fd9e3523fe775fa5a8f0bb936`.
Existing Workbench access works without owner action. No Secret/DB/provider or
service/config mutation was performed; current cloud alert and effective
journald observations remain LAST_KNOWN, despite the matching journald file hash.

The actual API-F unit is now the Item36 renderer regression fixture. Its exact
quoted PGOPTIONS and explicit unprivileged flag are supported without accepting
other quotes/overrides. A real bind-only candidate and byte-exact rollback are
saved in `/private/tmp/noteai-prep-20260908/api-f-bind/`, with candidate SHA
`824207e1b9fdfe744fe70b97af2130350c9fb2fd84d5c03a4a89d07c0d0387ac`.
Only the host address becomes10.42.11.166; image/PGOPTIONS/other bytes are retained.
This is PREPARED_NOT_APPLIED and distinct from image update, rolling deployment,
Payment first enablement and complete Item36 acceptance. No ACR/Git push.

18 managed preparation/recovery +10 Item36 checks pass in actual Python3.11
linux/amd64 isolation; failure logs and exact current artifacts are indexed in
the existing Handoff. No new Evidence/receipt/gate/version envelope or Readiness
credit is created. All production remains stopped and30/38 remains unchanged.

## Item34 当次最小生产实施申请 — 2026-09-07

**本次真实结果（北京时间9月7日22:31）：测试账号与900积分已完成；Item34失败，
旧窗口EXPIRED，Readiness保持30/38。**正常注册一次及/auth/me身份读回成功；
同一session于22:13:46正常POST固定宠物猫笔记，wrapper绑定原批准due，保留
真实submitted_at及初始snapshot。既有DMS owner一次赠分提交后，22:18:39独立
读回balance900、purchased0、used0、精确gift1/用户流水1。绑定SQL的SHA256为
`5b320924a39a5be873d9e1f7f749d73d0078e2fd46e4fce8743e8ffcca412c75`。
密码由owner隐藏输入，手机号仍未绑定。不存在重复注册/发分或付费订阅。

精确24h一次任务产生1worker/1provider admission，22:23:58失败，error_code为
`xhsadaptererror`；collected0/failed1，没有VERIFIED结果或合格24h snapshot。
原始具体adapter码已被运行代码丢弃，原因未定位；admission先于签名/HTTP，
不能把它当作已证明的HTTP发出或把费用记0。22:26:09恢复读回确认config回到
原状态、safety及其他跟踪行未变、目标needs_manual且检查时间/指标/下次调度
为空，无活动/UNKNOWN attempt。额外restore未再写配置或调用供应商。
精确任务容器已停止exit1并保留失败证据，Tracking disabled/inactive/dead。
临时SELECT在需要的读回后撤回；22:29:50独立验证app SELECTfalse及原ACL完全恢复。
0019已提交及既定b8ae59c镜像保持原真实身份，不删除或重建。

实测22:31:37已超过严格24h截止22:30:38，且没有截止前合格证据，因此旧窗口
EXPIRED。**不重试24h、不执行3d、不自动重启观察。**下方原批准动作仅保留其
历史范围；现存失败结果与恢复hash写在同一canonical Evidence和Handoff中。
核心部分结果为5表6distinct对象，辅助认证/注册/赠分进入原同一辅助账本及
总摘要；它们没有冒充终态7表9行或全库实测DML。错误码保留及必要候选产物现已
完成本地修正和验证，见下方现行准备节；新生产观察仍须具体方案与owner批准，
当前无需owner再执行已完成的命令。

**新观察方案待决定，尚未授权或启动：**当前不能只改起点后重放。具体约束：

- `tools/execute_item34_tracking_checkpoint.py:22`起固定目标、anchor及due；
  `tools/submit_item34_managed_track.py:27`、既有wrapper的源码绑定及
  `tools/internal_deployment_readiness_gate.py:4988`也绑定原对象。未来对象/起点
  必须前瞻性明确批准，不能改旧Evidence、OCI标签或validator来获得旧窗口通过。
- `deploy/production/execute_item34_tracking.py:1823`要求pending且零历史attempt；
  当前needs_manual/failed1不满足。`model/migrations/postgres/0010_tracking_execution_contract.sql:249`
  的attempt外键会随删除track级联删除，且`UNIQUE(track_id,stage)`禁止同track
  再做24h。不得删旧行/attempt、回退状态或新建账号绕开no-replay。
- `model/api.py:14330`、`:14365`使同账号同笔记合法POST返回409；wrapper`:1217`
  又要求该note全局恰好一行，另一账号提交同笔记同样不能解除约束。
  **批准DoD没有要求新笔记**：`docs/XHS_TRACKING_PRODUCTION_CONTRACT.md:107–112`
  要求同对象真实初始snapshot/T0及row/attempt绑定。先前索取新URL已撤回；
  原owner-owned对象的新T0按下述方案准备，不能靠修改旧row时钟直接启动。
- `scripts/postgres/item34-0019-apply.sql:29`拒绝已有policy/ledger；已提交0019
  只应按原verify读回。当前validator`:5371`的7表9distinct口径含迁移1/attempt2，
  新作业必须先明确旧0019与旧失败attempt作为历史前置、新写入另实测的兼容口径，
  不能把旧迁移伪报为新INSERT或将三次attempt挤成两次。现行批准DoD未修改。

原对象前瞻性实施方案（尚未应用schema或批准生产执行）：

1. 保留原track、owner及全部旧Evidence/attempt；tracked_notes增加当前窗口代次和
   真实新T0，attempts增加代次，旧记录默认为0。唯一键改为(track_id,generation,stage)。
   禁止用每次执行的run_id冒充窗口身份，禁止新增账号/删行绕过唯一键。
2. 新窗口只能由明确批准的一次动作CAS原代次及旧失败attempt身份后开启；普通claim、
   重连、启动不生成代次。claim/admit/finalize和当前窗口结果同时绑定代次；全局活动/
   UNKNOWN及UTC日额度仍跨全部代次统计。真实新T0必须来自新一次同对象初始snapshot，
   不使用旧发布时间或回填时间。现有0019仅verify，不再apply。
   原T0实际来自已认证XHS浏览器的新鲜详情（旧canonical71–88），NoteAI POST并不采集
   初始指标。最小候选沿用一次明确授权的同对象浏览器详情新读取，保留真实时钟与指标；
   不重截旧缓存页面。该读取可能有多条网络请求、访问记录及会话更新，另记影响和费用，
   不能称外部调用0或费用0。随后两个checkpoint仍最多2个Tracking admission。
   若改为程序化T0并记durable admission，则新窗口共3、加旧失败历史共4；当前24h/7d
   schema不能藏一个T0阶段，7表9/合并13的候选预算必须重算。
3. 当前实施预算须区分历史和新作业。旧核心真实为5表6distinct；若新增迁移1并沿用其余
   成功写集，新作业候选为迁移1/原track1/新attempt2/growth1/memory1/events2/settings1
   共7表9distinct；与旧历史合并为13distinct、attempt累计3。9月8日隔离PG16已用
   真实crawler两阶段SQL和Tracking角色验证该条件预算，逐表断言旧events2/settings1，
   新attempt2/events2及两代合并写集。采样本身为6表8distinct；加一次候选迁移才为
   7表9。窗口实际DML为track8/attempt4/events2/settings2/growth1/memory1，
   不能把distinct当实际DML次数。旧历史仍为5表6distinct；历史HTTP仍含UNKNOWN。
4. 未来申请包含最小迁移及回滚边界、已有合法对象绑定、真实T0、两个时间窗口、两次最多
   2新admission/0重试、权限临时授撤、managed验证及恢复。新一代结果在现有canonical
   文件追加前瞻性部分，旧分支/失败事实不变；需明确批准新的计数口径和执行范围。

本地工程已实现：`model/crawler.py` / `model/tracking_contract.py`显式绑定generation，
普通调度只claim旧代次；新代次必须同时给出固定track、stage、generation。新T0按
存储anchor计算窗口和3d due，growth/memory去重身份也按代次隔离，旧代次语义不变。
全局活动/UNKNOWN及UTC额度跨代次；admission在等锁后复核日期、租约和阶段，
24h成功写入在等锁后及事务最后复核截止。COMMIT与对应snapshot是否真正早于截止
仍须实际外层读回证明，不能由事务内时间或本地合成时钟代替。

原先隔离设计夹具现已收敛为顶部绑定的原生0020及三份SQL，测试夹具只保留
隔离数据库名约束。existing wrapper/checkpoint/durable已实现显式新generation分支，
旧常量/历史来源保持原样。当前尚无新T0、生产迁移或执行授权，顶部为现行材料。


沿用本节原时间规则：24h在[anchor+24h,anchor+72h)，3d在anchor+72h或之后
（含边界），且晚于24h采样；
不新增误差、最低间隔或managed全窗口要求。未来一次申请应明确目标/真实anchor、
上述计数兼容方案，再列必要候选XHS发布与digest读回、现有0019只读确认、正常
managed提交/绑定、每阶段临时ACL及撤回、两次最多2admission/零自动重试、验证/
失败恢复/Evidence保存。不得重做账号/赠分、0019 apply或隐含API/Payment/ALB
部署；费用只允许经批准的既有资源增量，未知金额不记0。本段是待决定草案，
不是新执行授权；原失败原因仍未定位，新候选只改善下次失败诊断。

**当日晚间 owner 新增单账号授权：**明确允许创建一个长期测试业务账号，
owner随后选择`noteai_`前缀用户名以避免未验证手机号登录；精确目标SHA256为
`56e5c09dfca80f6c2f70b328fc42af3c125bdd97c8beb47b93747f2e16cf7387`。
密码owner隐藏双次输入并正常确认注册说明；手机号留空、未验证。
允许一次900积分gift、paid_rmb0，不改变订阅或权限。通过当前正常注册API和
既有DMS owner执行`owner-test-account-gift-20260907.sql`，绑定真实注册UUID；
未知结果只读回，不重新发分。注册最多4次直接DML、gift最多3次，实际计数未知，
新增5个distinct辅助对象纳入原canonical同一auxiliary及总写入摘要。
原7表9core对象、旧401失败、观察起点、22:30:38截止、两次provider上限不变。
22:02已先验证指定账号和gift不存在、相关权限齐备、五表无额外用户trigger，
实际API源码一致。该授权不扩展其他账户或生产Admin写权限，不接通SMS。

Owner 在本窗口以明确用户指令批准9802111此节范围，覆盖正常执行、结果读回、
已知失败处置及Evidence保存。**仅本Item34作业解除PAUSED**；其他Item生产、
全局定时任务/自动化、Git push仍PAUSED。批准基线为
`9802111a27b131e510c1c686870121baead5c45d`；该基线计划文件SHA256为
`ae5b7fa36456dd01a7c1b9be63889d0e9d86298e54d354082c90859b0116e47d`。
批准必要认证写入、指定policy DDL、临时SELECT/grant撤回及安全失败写入的
辅助范围；它们须与核心7表9distinct行同时记录和核验，不能用拆日志掩盖越界。
允许此授权补充进入既有记录和必要校验，原目标、时钟、两次采样/no-replay、
Secret隔离与真实终态不变。镜像保持真实b8ae59c源码身份，不因文档提交重建。
已接受既定377806447字节镜像在现有资源的传输/存储及最多2次请求的实际增量，
未知金额不记0；不得新增Builder、扩容、订阅或固定费用。本节取代下方七月整套发布顺序，
不要求先重建全部角色、更新 API、部署 Payment 或完成 ALB。

**历史晚间续行（21:49前；后续结果以上方收尾为准）：**owner已报告API-F Docker Login Succeeded。既定镜像通过同一
Workbench任务传输，Wi-Fi切换中断后由owner恢复；主机整包SHA/bytes、load、
Python3.11.15/UID999及8源码hash已验证。新tag一次push exit0，Registry manifest
读回匹配同一config；实际digest为
`sha256:6735b6f243437a87945f837b9f51bbcca49bef51c24fb028f6e94351a1da54b4`。
21:21重新确认owner/ACL/无用户trigger后，精确0019 preflight/apply/verify已成功；
21:28:57独立目录读回确认ledger1、policy1、完整qual正确、RLS及原ACL未变。
已有一行迁移账本和指定policy DDL。21:37第二次输入产生一次401认证失败，
managed POST/provider均未dispatch；其辅助认证写入上界4、实际行数未知，
原生journal保留。首次空输入为零请求；owner再次明确要求重新输入后，
第三个独占journal读回也为401：共两次真实认证失败，辅助写入累计上界8、
实际未知；均未产生managed POST。Owner不记得设过NoteAI产品密码，也没有
已确认的登录会话。现有短信实现仅非生产测试发送，不能用它绕过当前阻断；
不创建账户、重置凭据或伪造session。Host原wrapper已保留并替换为批准SHA，
两份helper已安装。下一步需要合法的既有NoteAI业务身份，非API-F/阿里云账号。
21:47补齐真实search_path绑定确认；21:49 Tracking保持disabled/inactive/dead，
无Item34任务容器及阶段journal。旧窗口仍UNPROVEN，截止条件不变。
暂未新增临时SELECT。20:49:42主机
读回31G可用、Python3.11.6、Tracking disabled/inactive。领域由owner确认关于
宠物猫，使用`宠物猫`。具体执行状态同步在现有Handoff和canonical中。

**下午已经完成的数据库入口：**DMS默认角色及指定系统策略已在13:20:40/41落地。
现行 `https://dms.aliyun.com/` 已有 noteai_admin → noteai-prod-postgres/noteai
会话；13:47:17目录只读读回确认三张表owner、SET ROLE能力、RLS及最低ACL，
0019 policy/ledger均0。旧DMS入口过时，勿再要求owner重复授权。
现行页面提出的另一角色AliyunServiceRoleForDMS已取消，没有授权。
下午ACR临时密码已生成但值未读取/保存，等待owner时取消输入；晚间状态见上。
没有0019 apply、grant、业务写入或provider dispatch。完整当前读回见既有
canonical Evidence的production_execution_20260907和现有Handoff顶部。

### 0019 的实际 SQL、身份与确认

仓库外既有文件已经逐字读取并核对；为恢复保存的副本放在已有
`scripts/postgres/`，不是另一套迁移。执行时先逐字比较两处并校验以下 SHA256：

| 阶段 | 原实际文件位置；仓库恢复副本同名 | SHA256 |
|---|---|---|
| preflight | `/private/tmp/item34-0019-preflight.sql`；`scripts/postgres/item34-0019-preflight.sql` | `dbfac34fe06bbec9e81bd0cad0e33131f7ba1ff25575d447c82adc1013869d41` |
| apply | `/private/tmp/item34-0019-apply.sql`；`scripts/postgres/item34-0019-apply.sql` | `4ace3f3591a4e922fec7917664bd1e5f1fd7193901b1a8ef93b6375a940a5cca` |
| verify | `/private/tmp/item34-0019-verify.sql`；`scripts/postgres/item34-0019-verify.sql` | `00f85944d37be8ff4b6e89478b56df35302fa2d16950203dfe9e2e0ba65bfa7a` |

verify 原 hash `2c14d2340b862a9e321df319cc1009dee4e4bcc454c83ff94d711b2657f76bf9`；
本次唯一修正是在其只读事务内补 `SET LOCAL ROLE noteai_admin`，两处副本一致。
preflight/apply 内容未变。canonical `0019_xhs_tracking_runtime_config.sql`
仍为 `bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f`。

对象是现有 PG16 `noteai-prod-postgres`，数据库名已由当前DMS会话与SQL读回
确认为`noteai`，不新建或猜测。执行会话须使用**已有能够
SET ROLE noteai_admin 的数据库身份**，且 settings 与 ledger 的 owner 都应为
noteai_admin。preflight 检查身份、search_path、RLS 开启且不 FORCE、无同名
policy/0019 ledger。apply 用 SERIALIZABLE、限定超时、迁移 advisory 事务锁，
只创建 `noteai_xhs_tracking_config_read_v1` SELECT policy 并插入一行0019账本；
不更改 Secret、表结构、角色 membership 或运行开关。policy 只允许 Tracking
读取非 Secret 的 `crawler_config`、`xhs_collection_safety`。verify 应返回 owner、
正确 search_path/RLS、精确 ledger=1、policy=1，并核对实际 qual 与 canonical SQL。

DMS 的 `AliyunDMSDefaultRole` 是**阿里云授予 DMS 服务的 RAM 角色**，只能解除
当前 DMS 云资源访问授权提示。MFA 完成不产生 PostgreSQL owner 权限。若选择
DMS 路径，owner 在 **RDS → noteai-prod-postgres → 登录数据库/DMS → 当前
AliyunDMSDefaultRole 授权提示**中授权给 DMS 服务，并在实际要求时本人完成
MFA；之后仍须在该实例的 DMS SQL 窗口使用上述已有数据库执行身份。若已有
另一条合法 owner 会话可完成同样 SQL，DMS 授权不是强制前置。不通过给 app
迁移权限、新建账号或在聊天中传递连接串来绕开它。

已用真正隔离 PG16.15 执行三份 SQL：正确 owner 应用/只读验证成功，重复 apply
被拒且结果不变，owner 不匹配时 policy 与 ledger 均无落地。它证明脚本行为，
不证明当前生产 owner 会话已可用。

### 已定位的最小执行器权限缺口

现有 `execute_item34_tracking.py` 的 snapshot/bind 强制 `noteai_app`，会读取
`tracking_provider_attempts`；现有 ACL 仅给 Tracking 此表权限，0019不会修复。
隔离 PG16 已复现 app SELECT 被拒、临时 grant 后可读、revoke 后权限恢复。
本次 owner 已明确批准：由上述 owner **仅临时 GRANT SELECT ON
public.tracking_provider_attempts TO noteai_app**，以及恢复原 ACL。先保存原
ACL/有效权限；已有授权绝不能在结束时误撤。此 grant 对所有 noteai_app 会话
生效，暴露该 attempts 表的读取能力，非仅某个容器或 UUID；不授写权限、
迁移账本权限或角色 membership。

每阶段完成 postflight、配置恢复读回、必要失败安全处理、worker 清理及证据
固化后立即撤回本次新增 grant；3d 前允许在**同一次批准**内再次临时授予及
撤回。撤权前须完成需要 snapshot 的 reconciliation，不能在 worker 一退出
就撤。UNKNOWN 不允许重放，也不允许无限保留临时权限。其余所需 app SELECT
为 settings/tracked_notes/crawler_events/growth_records/user_memories；源码
ACL 已覆盖，生产执行前只查当前权限布尔值，任何额外缺口停下报告，不扩权。

### 合法 managed row 与既有 API

目标固定为 `https://www.xiaohongshu.com/explore/6a7954010000000026034707`。
唯一创建入口是现有 NoteAI API 的 **POST /notes/track-url**（已登录用户页面
发起；内部调用必须携带同一合法用户身份）。owner 需在 NoteAI 页面登录其
现有账户并选定确实属于自己的跟踪对象；若现有会话有效，可直接沿用。
不猜 user_id，不创建诊断身份，不直接 SQL INSERT managed row。

现有API只绑定主机127.0.0.1:8000时，在API-F现有Item34源码布局放置
`tools/submit_item34_managed_track.py`，与已有durable Journal同目录复用。
完成上述生产preflight后，owner在终端正常输入既有账户及隐藏密码；脚本使用
同一合法token对固定对象正常POST/必要读回，不输出或保存密码/token。执行示例：
`python3 "$ITEM34_SOURCE/tools/submit_item34_managed_track.py" --domain 宠物猫 --journal "$ITEM34_WORKDIR/managed.host.jsonl"`。
排他日志在登录前落盘，单次登录/单次创建，未知结果只读回、不重放；没有注册、
直接SQL或供应商调用。未知发布时间为null，真实服务器字段保存于同一执行日志。

合法请求使用实际 source_note/version/session（若提供则验证所属关系）、
标题和发布时间事实。平台仅有“08-10”不构造 ISO 时钟；未知 published_at
可依原接口传 null，服务端真实提交时间照常保存，随后走既有 bind 调度。
认证副作用须计入执行范围：有效会话查验是 SELECT；过期 token 校验可能
DELETE user_sessions；必要的正常登录可能写 auth_login_limits、更新
users.last_login、INSERT user_sessions。请求本身在写入围栏/重复检查后
INSERT 一行 tracked_notes（服务端 submitted_at/next_check_at）；无供应商调用。
请求超时先按该合法用户与固定对象读回，不能盲目重提；409读回已有行而不造新行。
之后仅由现有 wrapper 的 bind 更新该行 next_check_at，保留真实 submitted_at，
不倒填发布时间、观测时间或 Evidence。认证附带写入单独如实保存在原执行记录，
不能冒充 Item34 核心7表之外零业务活动。

源码审查确认已部署 b55 API 的 TrackUrlInput、track_url、身份/所有权/写围栏
相关函数与当前源码相同；Item34 无需先升级 API 或 Payment。该结论不把旧
API 当成已整合 Item30 Kimi 的全产品候选。

### 必要候选产物及发布对象

仅需 `xhs-http-runtime`，承载已有 wrapper、checkpoint、Tracking worker 和
provider-free healthcheck。实际入口保留 `/app/scripts/docker_entrypoint.sh`。
本地已生成 `noteai-local/item34:b8ae59c`，OCI revision 为完整
`b8ae59cbf1c8423b832dab385eb3f0d367298b71`，关键源码与本次代码 checkpoint
没有漂移。该镜像在隔离运行中实测 Python3.11.15、linux/amd64/x86_64、UID999、
8个 source SHA 一致，cryptography50.0.0、psycopg3.3.4，pip check 通过。
可传输的本地 Docker 产物已保存为
`/private/tmp/noteai-prep-20260907/item34-xhs-b8ae59c-linux-amd64.docker.tar.gz`，
377806447 bytes，SHA256
`79ba76c546bf20d71b8e2c1f27ce95805b93d70cfbf663f9cf105e9401b7d6eb`。
本地 OCI image index digest
`sha256:cb17d276d79a0b6b8bc0ad64a11a5ef0aa8e23bd8b9b00bd35ce62eca42f0a27`
**不是 ACR 发布凭据**。ACR digest 必须在真正 push 后读回并与所发布内容核对，
当前未填造，也不阻断本地准备。

归档内该index指向linux/amd64 OCI manifest
`7b444143c77dcdd44e83a8a2d50f9330febb12df37afa641653d13c454e99897`，其config为
`5c4291f7062352ea07cce6e1ab02c274dc1267f4fd5aa07d293dd5050c3754eb`。
API-F classic Docker加载后的Id等于此config，三层引用及SHA均已核验。后续
validator的immutable_artifact_sha256沿用原wrapper实际返回的config/image Id。

旧 v2 `/Users/openclaw/Desktop/noteai-item34-xhs-overlay-20260906-v2.tar.gz`
的112个源码文件与当前版本完全匹配（archive SHA
`f7e5fbe5718578ac810daa3a01fe92dd4a63f93051ece833b8e75a96d61c2788`），
不能错用 `/private/tmp/noteai-item34-xhs-overlay-20260906` 的旧v1内容。
v2继承旧base的cryptography48.0.1，当前要求50.0.0；因此本次选择上面的已构建
候选供发布，保留原v2作为比较对象。本次只构建此必要角色，没有重建全角色。
本地 Colima `noteai-prep` 为无主机挂载/无agent转发/无端口转发的独立环境，
使用QEMU运行amd64；它提供候选平台验证，不是生产宿主验收。

发布目标是**现有** ACR 私网实例的 `noteai/app`，使用既有 API-F 私网连接，
发布一个绑定本候选的新 immutable tag（预定 `item34-20260907-b8ae59c`，先核实
不存在，不覆盖旧tag）。上次一次 manifest 请求为 UNAUTHORIZED/ACCESS_DENIED；
凭证过期还是权限原因仍未定位，不再重复同一拒绝请求。本次已明确批准
使用既有合法主体完成一次 ACR 认证恢复和发布；若需要人工登录，owner 到
**容器镜像服务 ACR → 当前深圳私网实例 → 访问凭证/仓库 noteai/app 操作指引**，
在受控主机完成现有身份的认证，不在聊天中交出密码。不重置凭证、扩RAM权限、
开放公网或新增Builder；现有权限仍拒绝则保留脱敏错误并停止。

### 时间与一次批准的有序动作

直接沿用 canonical Evidence 的 latest_owner_amendment/observation 和
`docs/XHS_TRACKING_PRODUCTION_CONTRACT.md` 的 later-binding条款，以及
`validate_item34_tracking_evidence`：起点2026-09-04 22:30:38+08仅证明真实初始
4/2/2快照。24h允许区间为 **[2026-09-05 22:30:38+08, 2026-09-07 22:30:38+08)**；
3d为后一个边界起且晚于24h，attempt完成不晚于对应snapshot。没有新增±误差、
两样本间48h最低间隔、3d最晚截止或managed row/服务覆盖整72h的要求。

历史实测时钟2026-09-07 12:40:25北京时间，当时canonical两checkpoint仍null、attempts空，
最近生产只读记录为10:53:57目标行0；本轮没有新生产/供应商Evidence。
状态 **UNPROVEN**，旧窗口此时仍可实施，前提是全部前置及24h真实完成/快照
均在当晚22:30:38之前。若到执行时已错过且没有原有有效Evidence，停止本方案
的24h执行并报告不相容；不补采倒填、不改DoD、不自动重启。

### 同一次执行的断线保存与恢复

`tools/run_item34_tracking_durable.py`是host侧原生结果保存入口，只调用原
wrapper/checkpoint；它不进入b8ae59c镜像，不改OCI标签，不替换迁移或验收。
在已有Item34源码目录保留deploy/production与tools相对布局，放置此host文件；
执行记录使用既有Item34 workdir内的root-only0700目录/0600排他文件。
先确认实际host目录再代入下述变量，不把变量名当成已存在的部署路径。

```bash
sudo -n systemd-run --unit=noteai-item34-24h-once --property=Restart=no \
  --property=UMask=0077 /usr/bin/python3 \
  "$ITEM34_SOURCE/tools/run_item34_tracking_durable.py" run \
  --stage 24h --track-id "$REAL_POST_UUID" --image "$REAL_ACR_VPC_DIGEST" \
  --journal "$ITEM34_WORKDIR/24h.host.jsonl"
```

这是一次性无重启host进程，不是timer、全局自动化或API/Payment部署；Workbench
断线不终止它。回包丢失先查询精确unit及原journal，不重复启动。journal在activate
之前fsync原始非Secret配置、原时间和active CAS时间；保存postflight/worker信息
后才允许原cleanup，正常原checkpoint结果也保存于同一journal。
3d在实际边界之后才由本任务主代理启动，使用对应3d unit/journal；不依赖旧PAUSED
heartbeat自动唤醒。当前20:00提醒仅提醒人工登录，并不启动任何阶段。

若host进程实际退出且配置仍需恢复，只调用此文件的`restore --restore-from
原阶段.host.jsonl --journal 未用过的恢复日志路径`。恢复取得原排他锁、停止精确
阶段容器，读取实际配置；已等于原值则不写，仅当当前hash及时间精确等于保存的
active状态才调用原transition restore。其他情况CAS冲突停下，不调用authorization
生成新时间、不调用provider。磁盘持续失败也不挡住配置恢复或原session-stop
安全处理，但结果仍UNKNOWN；新run的任何前置落盘失败均禁止activate。
恢复不等于采样验收，原reconcile/必要读回、ACL撤回和managed验证仍按原范围完成。

1. **准备执行入口**：确认既有owner数据库会话和API-F原服务/权限状态；按上文
   有需要才完成DMS默认服务角色授权及既有ACR认证。一次受控传输本地候选至
   API-F、load、push到既有ACR、读回实际digest；核验平台/Python/8个源码hash，
   后续仅用 `私网仓库@sha256:真实digest`。资源不足或auth继续拒绝就停止。
2. **0019及最低读权限**：执行既有preflight→apply→verify；保存owner/ledger/
   policy结果及原ACL。每阶段按上文临时授予app对attempts的SELECT。
3. **真实用户创建与绑定**：合法POST创建/确认唯一managed row，现有wrapper
   bind只改next_check_at。确认无既往attempt、目标唯一、全局无started/unknown，
   既有Tracking session/signer就绪；只记录非敏感布尔值/hash，不读取Secret值。
4. **24h then 3d**：各一次现有 `execute_item34_tracking.py` / checkpoint流程，
   每次只启动 `python crawler_worker.py --once --limit 1`。两阶段合计最多2个
   provider admission，0自动重试；先读真实配额和共享session stop。暂时激活
   crawler_config，按CAS恢复原值/时间；24h后仅schedule同一目标至3d边界。
   单次结束完成结果读回、stop/cleanup、Evidence保存及临时SELECT撤回。
5. **Item34自身的必要验证**：在API-F保留原Tracking unit/image/enabled/active
   精确状态，只对Tracking unit绑定真实新digest，保持显式suspended、Restart=no，
   人工有界start→provider-free healthcheck→stop及恢复演练；核对singleton、
   资源/restart/log/alert控制，将managed验证绑定已经完成的一个attempt，
   不产生第三次供应商调用。只恢复先前批准状态，不enable定时服务/自动化。
   若现有managed promotion实现不能证明某字段，按真实缺口保持incomplete，
   不把静态renderer或suspended进程存活当成全部PASS。

必要结果读回与失败处置已经包含在此一次申请内，不在获批后逐条重复询问。
明确失败在COMMIT前回滚SQL；COMMIT回包丢失为UNKNOWN，先owner verify，绝不
直接重放apply。已提交0019在后续失败时保留为dormant additive migration，
不删policy/账本。provider start/result不明先停止精确任务容器并用原
reconcile/readback恢复判定；reconcile可能stop容器，**不是纯只读动作**。
已知challenge/logout按原代码可写一行xhs_collection_safety停止旗标。
配置恢复使用原值/时间CAS，失败不强盖并发修改；保留attempt、失败记录、
原镜像及SQL状态，终止后续采样，撤回本次新增临时读取权，不删业务数据。

核心批准写范围仍是现行7表9个distinct rows（schema_migrations1、tracked_notes1、
tracking_provider_attempts2、growth_records1、user_memories1、crawler_events2、
system_settings1）；这里修正9802111中最后两项写反的文字，沿用原validator的2/1，
没有修改核心计数要求。同一row的claim/finalize/config多次UPDATE并不等于仅9次DML。
另外明确纳入必要认证写入、policy DDL、临时grant/revoke和安全失败写入范围，
如实记录，不能为凑终态隐藏副作用。必要辅助动作写入同一canonical Evidence的
可选authorized_auxiliary_effects，并纳入原write ledger的hash投影；历史无此字段
的Evidence仍沿用原hash算法。认证仅限既有账户的正常流程，不新增用户或更改
余额/其他users列；password login成功的直接行变更上界6、失败上界4，过期token
清理上界1，依据现有auth/account_security源码。未安装生产认证DML采集器时，
实际次数保留null，标SOURCE_BOUNDED_NOT_OBSERVED，不能把上界或null写成实测0。
这些不是包含trigger的全库计数；执行前核对相关表是否有额外用户trigger，若发现
未批准副作用则先停止并报告。核心out_of_contract=0只描述本受控执行中未超出
核心及明确批准辅助范围，不声称整个生产期间全库只发生9次DML。临时SELECT逐
阶段记录原ACL与恢复读回，安全flag失败写入不使失败attempt满足终态。
若发现真实不相容或效果归属不明，保持incomplete，不能仅拆日志宣称零越界。
Evidence仅写既有canonical路径/原workdir，
完全满足批准DoD及validator后才计分。

**影响/费用边界：**使用现有ECS/RDS/ACR容量，没有新云Builder/计费资源、
无支付、无模型批次。两个XHS HTTP读请求的adapter没有单次付费API价目，
现有网络/ACR存储计费增量不能捏造为精确0元；批准对象是一个已构建镜像的
现有实例传输/存储及两次请求，数据库DDL有限定锁等待，Tracking有界验证使用
既有CPU/内存。若服务要求购买/扩容/新账单项或给出新增固定费用，停止，
不将该费用隐含进本次申请。本机下载构建和PG16测试无需云Builder报价。

## Paused preparation update — 2026-09-07

This section describes current local preparation. The historical image table
below belongs to its dated release and is not the next candidate. The owner's
subsequent confirmation authorized the bounded readbacks recorded in the current
Handoff. It did not authorize production writes, publication, service changes,
provider requests, payments, DNS, role grants or paid resources. Those remain
PAUSED. This document itself grants no execution permission.

### Candidate source and affected regressions

The recovery starts at `58859ce737337446698dd0a72a218718633953e9`, whose parent
is accepted Item30 `429b55a7bf652c8a9b4b5f47ca769ea5cba8ef29`.
`model/model_router.py` already contains the Item30 Kimi usage compatibility
change, and `Dockerfile` copies that source into the runtime. The old b55 API
image did not receive the temporary Item30 probe overlay. A future authorized
build must bind the final preparation commit and actual role-image contents;
neither an old image nor the historical Item30 PASS proves the new release.
Use `test_model_usage_audit` and `test_item30_real_ai_provider_chain` as mocked
current-source regressions, plus affected payment/API/runtime checks. They do
not replay the accepted provider chain. The original b8 XHS image was published
only under the closed Item34 approval above; the new local candidates below
have not been transferred or published.

September7 after23:00: actual source checkpoint
`54b06bee359e58963bb5898e2d06275988e474a7` now has two verified linux/amd64
Python3.11.15/UID999 artifacts. XHS `noteai-local/item34:54b06be` reuses b8 with
only crawler diagnostic preservation; API `noteai-local/api:54b06be-lfs` uses
the existing api-runtime Dockerfile and includes the Item30 Kimi patch. All114
runtime files match source and resolved model release hashes. The API model
bytes were verified against Git LFS OIDs and release sizes/hashes; the earlier
pointer-only context and `noteai-local/api:54b06be` are rejected, not candidates.
One failed network-none dependency install was followed by authorized trusted
downloads in local Colima; no paid Builder was created. Exact archives/SHA256
and LOCAL OCI indices are indexed in the existing Handoff. Later docs/collector
changes do not relabel these images as a different source commit. No new
registry digest exists or is needed for this completed local validation.

Image-derived tests passed19 XHS/renderer/mocked-Kimi checks, the real offline
Node signer basic/RAP/rejection test, and17 API/mocked-Kimi checks. Actual normal
API entrypoint loaded required v0.4-composite assets with no model bypass;
network-none HTTP /health/live and /health/ready returned200, Docker healthy.
This proves executable local image/SQLite/model health, not production PG,
provider session, deployment or Item36 acceptance. Preserve failed fixture/
build logs alongside final logs; no historical Item30 provider replay occurred.

The persisted offline launcher is `scripts/run_paused_local_checks.py`. Invoke
it with `env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin .venv/bin/python`, followed by
the script and explicit `tests.test_*` module names, or `--readiness` for the
existing static ledger. It disables dotenv/network/PostgreSQL, uses temporary
SQLite and rejects protected paths. These are Python process guards, not a
substitute for an OS sandbox or production image validation. Do not use test
discovery across the seven protected paths. Local takeover checks used
Python3.14.4; future release checks must cover the actual Python3.11 image.

### Item31 bounded DML and callback preparation

`PAYMENT_DIRECT_READY_FOR_LIVE` describes the completed engineering preparation
only: the actual API/Payment/operator transaction binding, coverage matrix,
isolated PG16 chains, durable result readback and current runnable role images
are implemented and verified. It is not terminal DONE or permission to execute.
Merchant/ingress readiness, exact live identity/ACL/trigger/FK bindings, temporary
DDL and a separately approved real two-channel canary remain live prerequisites.

September8 current implementation: actual API startup/shutdown, both Payment
callback routes and the existing canary CLI now bind the same collector. Docker
copies the existing tool to `/app/model/collect_item31_canary_dml.py`; no alternate
operator entrypoint, global transaction hook or permanent audit service is added.
The Payment process owns one LISTEN/control pair, broker and existing journal;
API and operator use one unreconnectable private Unix connection each. Every
business writer uses a fresh CompatRow connection set to autocommit before any
SQL, then the existing BEGIN/register/fsync/SQL/complete/COMMIT sequence.

Binding inputs are one reviewed non-secret JSON via
`NOTEAI_ITEM31_DML_BINDING_FILE` and its `NOTEAI_ITEM31_DML_BINDING_SHA256`:
`activation`, `provider`, `targets`, `work_directory`, `user_id`,
`idempotency_key_hash`, `app_id`, `create_context`, `reconciliation_run_id`.
Use the existing approved canary identities; preparation chooses none. JSON
`create_context` is the four-field output of the existing API canary fence;
its user/provider/activation/create-key digests must agree with the normal
activation environment. `targets` uses the existing installation renderer's
finite mappings (all12 allowed writer tables plus users/usage_records/paid-credit
consumption sentinels). An explicitly bound reconciliation run UUID makes its
run/items predicates knowable before SQL; default non-canary UUID behavior stays
unchanged. No field holds a password, DSN, signature or checkout token.

Malformed activation, hash-only/file-only configuration, wrong subject/provider,
missing coverage or an interrupted broker rejects startup/action; there is no
ordinary-writer fallback. Operator orders are checked against the fixed user's
key/provider/app/live/CNY/1200-fen scope BEFORE gateway/action admission. Gateway
callback authentication precedes event/order resolution and first INSERT.
An expired window stops new actions but lets an already admitted worker save its
result. Cancellation waits for that original worker; no provider resubmission.

All three containers must mount the SAME existing canary work-directory volume
at the same path, with actual UID999 and directory0700/socket0600. Sharing the
API network namespace alone does not share files. Only one provider capture is
active; close/remove its reviewed temporary DDL before the other provider's
approved capture. This preserves the two-channel first-launch decision.
Start the API container to establish its network namespace, then start Payment
inside it while API startup waits at most15s for the first socket. Do not wait
for API healthy before starting Payment. This is one initial connection, with
no reconnect after UNKNOWN. The actual local candidate pair has now established
the namespace and broker with dispatches 0.18s apart, completed full ASGI startup,
captured one registered synthetic mutation and read back the sealed journal.
That rehearsal is independent of the earlier PG hook test and remains local.

Close new API/operator admission, let already admitted worker/callback actions
finish, stop API/operator, then stop Payment last. Payment closes broker
admission before sealing and reading its existing journal. An active peer EOF,
lost COMMIT/registration ACK, lost LISTEN stream or fsync failure keeps UNKNOWN.
A nonempty completed journal is never overwritten at process restart. Resolver
references remain installed through shutdown; removal cannot expose default SQL.
Only later explicit Item31 approval can install/remove the exact temporary DDL,
mount these inputs or admit a real provider/payment action.

September7 local implementation: `tools/collect_item31_canary_dml.py` now
provides the selected minimal source: temporary, canary-predicate AFTER ROW
triggers emit transactional `pg_notify`; one dedicated LISTEN connection
persists only operation/table/transaction and identity hashes in the existing
canary work directory. No audit table, general logging service, new dependency,
production installer or automatic provider path was added. Each provider's
existing canary uses its own activation/target mapping; API and Payment writers
for that canary share the same capture. Do not combine two different orders
under one single-value target mapping.

The explicit integration order is: review reachable writer tables/ACLs and
trigger/rule/FK effects; render `installation_sql(activation, targets)` with
existing known canary IDs; owner applies temporary DDL only under later Item31
approval; create `CanaryCapture` with the same activation/targets/provider;
inside each writer's explicit BEGIN call `bind_transaction`, synchronously
`capture.register` before admitting DML, perform the existing canary action,
call `transaction_complete` in that SAME transaction, then COMMIT. After an
explicitly confirmed ROLLBACK call `rolled_back`; a lost COMMIT reply is not a
rollback. Close admission to all writers before `finish(admission_closed=True)`.
Capture calls are serialized by the existing orchestrator. Read retained data
with `read_journal(path, **capture.context)`; output maps into the existing
`write_mutations_by_table` / `write_ledger_readback_sha256`, never terminal DONE.
Use `removal_sql` to remove only those exact temporary triggers/function after
live closure; no cascade and no permanent role expansion.

True isolated PG16.15 plus Python3.11 passed14 collector tests:
separate API-like/Payment-like writer processes, committed multirow and nested
trigger/cascade effects, duplicate UPDATE versus ON CONFLICT/zero-row no-op,
SAVEPOINT and outer rollback, wrong target, changed transaction, listener loss,
in-flight tail, fsync failure and persisted binding mismatch. The two added
tests use the real CompatRow factory and selected real payment event SQL.
These remain isolated PostgreSQL transactions, not real paid canaries or proof
that all production API/Payment writers are already instrumented. The collector binds
activation/provider/coverage hash and backend PID/transaction/nonce, records no
row values, cannot resume a disconnected stream, and leaves incomplete results
UNKNOWN. Trigger notifications discarded by rollback are not counted.
The same journal is first retained as `.incomplete`; only after the full tail
and file fsync succeed is it atomically published without overwriting a final
path. Even simultaneous fsync/truncate failure leaves unpublished bytes UNKNOWN.

The collector now uses an independent tuple metadata cursor on the SAME writer
connection, preserving CompatRow and any unread business cursor result. The
real event test executes `_record_event` / `_finish_event` against current0014/
0018 event schema/guard, including duplicate UPDATE and SAVEPOINT rollback,
then reads the durable three-mutation result. Imports are temporarily bound to
a fixed local PG socket URL with cleared environment; the fixture cannot
initialize workspace SQLite or inherit a supplied database URL. The first
fixture omitted0018's duplicate column and failed; final corrected14-test run
passes without DATABASE_URL or SQLite fallback supplied to the container.

The smallest valid event predicate is the fixed authenticated
`provider_event_id_hash`, not order_id: a real event is INSERTed with NULL
order_id, then bound by UPDATE, while the trigger checks both OLD and NEW.
This test covers one synthetic event identity only. Full payment/refund canaries
must bind each actual action/event and all reachable writers explicitly; no
whole-provider/merchant target or global db.transaction hook is introduced.
Wrapping the outer canary action is insufficient because the real functions
open several independent transactions and Payment callbacks run in another
process. Each must register before first DML and signal completion before its
own COMMIT, with known rollback and lost-commit UNKNOWN handled separately.

Remaining live application is concrete: install/remove this temporary DDL only
for reviewed canary scope and activate the implemented runtime binding for
**every** API/Payment transaction before any DML; include forbidden-table sentinels for all reachable out-of-contract
writes. The current source supports INSERT/UPDATE/DELETE; TRUNCATE, missing
writer registration, absent trigger coverage, unknown trigger/rule/FK effects
or an interrupted listener preclude complete DML evidence. Do not infer all
other tables had zero writes. This Item31 DDL/integration and real funds are
outside the Item34 one-time application above.


Use the existing canary action journal and canonical Item31 Evidence, without
adding a global audit service, receipt schema or wider long-lived Payment role.
The real collector must cover each actual transaction in the two 1200-fen
canaries; preserve failed/UNKNOWN evidence and stop rather than replay.

| Action | Existing source and rows to account for | Evidence limitation to close |
|---|---|---|
| Create and admit order | Actual `POST /payments/orders` → create/admit → worker success/UNKNOWN; `payment_orders` | PG16 covers both providers, repeat create, normal result, timeout, cancellation, admission COMMIT ACK loss and callback-before-provider-response. |
| Authenticate callback/query | Actual Payment HTTP → authenticated event transaction; event/order/cash/position/entitlement/credits/credit_transactions | Both real local signature algorithms and real PG rows; dynamic authenticated event hash and user/key-scoped order predicate. Production transport/ACL/merchant approval are not claimed. |
| Duplicate notification | `_record_event` increments `duplicate_delivery_count` | Actual HTTP/PG duplicate commits one event UPDATE, zero second cash/entitlement grants. |
| Full unused refund | Existing executor prepare/admit/mark and authenticated refund query | PG16 covers three submission transactions and real terminal reversal rows; no invented Alipay refund callback. Submission remains pending until authoritative result. |
| Query/reconciliation | Existing operator pending query; bound `reconcile_bill` run/items | PG16 covers pending query UPDATE, matched whole-day bill, duplicate source/no extra DML, missing/mismatch item rows and explicit UUID propagation. This is a whole-provider/day bill boundary, not an unproven canary-only bill. |
| Settlement | Existing `record_settlement_summary` function | Explicit factory now covers its standalone SQL; PG16 verifies source-bound row. No new settlement HTTP/CLI was created. |
| Process lifecycle | Actual API/Payment ASGI hooks, existing operator `main`, two real child writers | Dedicated autocommit adaptation, one journal, normal closure/readback, malformed binding and different-key order rejection before provider admission. |

Only an existing valid canary session enters this payment scope. Normal valid
authentication is read-only; expired-session cleanup in auth.py occurs before the
payment factory and is not counted by this collector. Login/registration/token
creation and account preparation must be separately disclosed/authorized outside
the payment measurement window. No all-authentication/all-business zero-DML claim
is made. The isolated HTTP fixtures generate their sessions before capture.

`tests/test_payment_query_financial_evidence.py` now exercises real SQLite
statement rowcounts and committed-transaction boundaries for the duplicate
notification path. It proves the offline distinction between DML and final
state, not PostgreSQL trigger coverage or production provenance. At that earlier stage, production
DML capture lacked an established source covering both API and Payment
processes. The local collector and runtime binding above now cover the implemented writer
paths; production installation, exact current ACL/trigger/FK readback and real
canary evidence remain incomplete. The already-completed
bounded RDS readback below did not establish a suitable existing DML source;
it is not a request to repeat that investigation. Before live funds, apply the
explicit runtime binding and review actual trigger/ACL/FK coverage above. Do not
enable broad SQL logging, record parameters or infer DML from SELECT snapshots.
Missing capture keeps Item31 incomplete; best-effort create/callback logs and
`pg_stat_*` aggregate deltas cannot close it.

Authorized September7 readback narrowed this gap. The existing PG16 instance's
SQL-insight page shows `开启审计日志`. A server-enforced read-only API session
returned `log_statement=ddl` and no installed `pgaudit` among the requested
extension names; no audit function was enabled. The same session cannot SELECT
the migration ledger or tracking attempts, and must not be granted broad rights
just to make evidence convenient. Query visibility is not historical DML proof.

The [official PostgreSQL audit description](https://help.aliyun.com/zh/rds/apsaradb-rds-for-postgresql/sql-insight-or-audit)
says audit uses database-kernel SQL capture, excludes PgBouncer SQL, and records
failed SQL in error logs rather than audit logs. Enabling changes log_statement
to all. The [PG-supported detail API](https://help.aliyun.com/zh/das/developer-reference/api-das-2020-01-16-getdassqlloghotdata)
has separate UpdateRows, ReturnRows, TransactionId, ThreadID and State fields;
their presence does not establish committed INSERT/UPDATE/DELETE effects after
rollback/savepoint or trigger-internal effects. The documented
[transaction analysis](https://help.aliyun.com/zh/das/user-guide/transaction-analysis)
prerequisites list MySQL engines, not this PostgreSQL instance. Do not infer
PG support from a generic DAS transaction-analysis description.

Audit enablement is both a configuration and charging change, outside the read
authorization. [Official V3 mainland pricing](https://help.aliyun.com/zh/das/product-overview/billing-details-of-the-previous-version)
lists log import CNY0.24/GB, optional index0.24/GB and insight0.08/GB, plus
retention/query-dependent costs; security audit has a separate minimum charge.
Actual selected version/options/volume are unknown, so there is no instance
quote. Do not buy or enable it as the default answer to the Item31 gap.

The local fixture observer now handles the contract's literal SAVEPOINT,
ROLLBACK TO SAVEPOINT and RELEASE forms. A real entitlement-write-then-fail
case commits cash1/order1/event2 affected rows and rolls back all entitlement
effects. This is why summing successful rowcounts at outer COMMIT is insufficient.
It is a correction to offline counting, not to the production rollback code.
Any later canary-scoped capture must distinguish attempted and committed effects,
retain transaction/savepoint boundaries, classify disconnects UNKNOWN, and cover
both API and Payment paths. Enabled trigger/internal-rule effects and durable
readback remain unproven. Keep using the existing canary action journal and
Evidence fields; do not add a global logging platform or new approval gate.

The fixed real notification endpoints are:

- `https://api.noteaipro.cn/payments/wechat/callback`
- `https://api.noteaipro.cn/payments/alipay/callback`

The provider must resolve that hostname and reach valid TLS on port 443.
A developer hosts entry, `curl --resolve` or an ALB pre-DNS probe cannot make
provider callbacks reach NoteAI. API forwards only those exact paths and
allowlisted headers/body to the co-located Payment namespace on 127.0.0.1:8002.
The normal ordering routes remain fenced until merchant approvals and capped
canary activation are ready. There is therefore a real sequencing decision:
the owner must approve a bounded, provider-reachable callback ingress before
Item31 Live funds while preserving the separate Item38 public-launch decision,
or explicitly change the launch sequence. This document does not authorize
DNS, opening other business routes, a different callback domain, or a
single-channel launch. The existing two-provider requirement remains unchanged.

### Item36 local implementation, health and rollback

These are three separate implementation actions, not interchangeable completion:

| Action | Actual local result / next implementation | Genuine dependency |
|---|---|---|
| Candidate API image update | Current `noteai-local/api:f3deedb` includes the Item30 repair, real canary binding and corrected DB connection restrictions; source and actual role health pass. The earlier 54b image is retained only as a prior local artifact. The renderer separately replaces exact old/new immutable images and preserves port/rollback bytes. Publication and actual node input binding remain pending. | Local health is not API candidate deployment. No Payment/ALB prerequisite for the Item34 track-url route. |
| Private API binding | API-F actual1510-byte unit is bound to SHA f591f43b…936; its private10.42.11.166 candidate SHA824207e1…ac and exact rollback are retained under /private/tmp/noteai-prep-20260908/api-f-bind/. API-C still needs its own current unit bytes/hash before apply. | Requires approved network scope and exact host input. Does not require Payment first activation merely to change a bind, but must preserve any previously active callback namespace. |
| Payment first activation | C was disabled/inactive and F unit not-found at last readback. First installation/configuration, immutable image, shared API container namespace, service start, health and public callback verification remain real actions. | Merchant/canary authorization and provider-reachable callback ingress before live funds. Keeping disabled state is rollback preservation, not first activation or full deployment. |

Do not start any of these three as an implicit Item34 dependency. Item36
terminal dependencies on33/34 remain; its local preparation can run separately.


Fresh September7 service/container metadata shows both APIs on the old b55
image and loopback8000. Payment is loaded/disabled/inactive on API-C; its unit
is not-found on API-F, and neither exact-name container inspection succeeded.
No shared Payment/API namespace or new live health probe is therefore proven.
This September7 observation is LAST_KNOWN except the September8 API-F readback
at the top of this plan. API-F bytes have now been exported and rendered; API-C
has not. Current API-F live/DB health, Payment state and API-C input still require
fresh readback before apply. Stored Docker `healthy` is insufficient. Two current
ECS console read attempts hit CDP focus-emulation timeouts before new metadata;
this is a resource-read PATH_BLOCKED, not a program stop or evidence of lost MFA.

`tools/prepare_item36_private_bind.py` is a pure local renderer with no apply,
cloud, subprocess, database or environment-loading path. Given a reviewed
Secret-free API unit copy, its exact SHA-256 and that node's confirmed RFC1918
IPv4 address, it changes only the single loopback 8000 mapping and writes a
candidate plus byte-identical rollback. It rejects source drift, extra ports,
public/loopback target addresses, shell expansion and mutable image identities.
The actual API-F fixture matches the exported source hash and renders successfully;
its current candidate remains a local artifact and has not been applied. API-C
must not be inferred by changing the F node name/IP.
Production Compose now defaults API binding to loopback; a future reviewed
private binding must be explicit.

The same tool has a mutually exclusive `--candidate-image` mode requiring
`--expected-image` plus the same original unit SHA. It replaces only the real
Docker image argument, preserves the existing loopback/RFC1918 port and writes
the same byte-identical rollback. A bounded literal-options parser rejects
application arguments after image, fake publish text in option values, unknown
options and unsafe network scope. Both modes need an actual reviewed host unit;
synthetic API-C inputs are not marked READY_TO_APPLY. The bound F file is ready for its scoped application review, subject to fresh native readback. Candidate digest
binding is done after real publication; its current absence does not prevent
local source/artifact verification.

Payment namespace preparation now reuses that same renderer and the frozen
`noteai-payment.service.template` (SHA3c7a78e7…1685). Its `--payment-namespace`
mode derives only the exact noteai-api-c/f container name from a reviewed real
API unit. Callback0/1 is explicit; an unpublished image retains the visible
`@@NOTEAI_PAYMENT_IMAGE@@` placeholder, never an invented registry digest.
The actual F-bound first-enable candidate is
`/private/tmp/noteai-prep-20260908/payment-api-f/noteai-payment.service.candidate`,
SHA67291769f8643d7ef1e3a234bb1affa5735cbb83936bece49f7ffc257400ddfe.
It binds network=container:noteai-api-f, callback1, no independent public port.
It still needs the actual published Payment digest before application. The prior
F not-found observation means no rollback file is invented: after fresh absence
confirmation, rollback stops/removes only the exact newly installed candidate
and returns to absent/disabled, not an empty unit or a running old service. A
previously loaded C unit requires its actual bytes/hash and exact state rollback.
12 renderer regressions pass locally; these are not Payment live health proof.

Actual September8 candidate-container verification now covers115 source/dependency
files, both real role entrypoints, Python3.11.15/linux-amd64/UID999, V04 models,
normal callback-off503, synthetic callback-on200 with isolated PG16 role, API
namespace replacement and explicit Payment recreation. Real production ASGI
startup/one registered synthetic UPDATE/ordered shutdown produced a durable
one-mutation readback. These are local tests, not production ACL/merchant/ALB or
Item36 terminal evidence. Logs and interimf49 archive are indexed in Handoff.

That rehearsal also confirmed a real application defect: its DB helper replaced
PGOPTIONS, dropping read-only/statement/lock timeout controls. The f3deedb repair
is included and verified inside both final local API/Payment candidates; prior
f49 artifacts are superseded for release. DSN/PGOPTIONS precedence, UTC and
explicit health timeout behavior are preserved.
After this repair the current F unit's read-only intent is effective when not
superseded by explicit DSN options; validate the effective session in a future
approved check. A production payment canary needing writes must explicitly
include scoped removal/restoration of that setting in its approved unit/config
change. Neither the renderer nor connection helper silently disables it.

For a future authorized application, retain the current API/Payment unit bytes,
immutable image refs, container identities and prior enabled/active/callback
states on each node. First verify the exact ALB-source TCP8000 security-group
rule and zero wider ingress. Then process API-C followed by API-F, keeping the
other accepted node available. On each node:

1. Stop an enabled Payment callback service before replacing its API namespace;
   retain the prior disabled state if Payment was not enabled.
2. Apply the specifically approved candidate-image update and/or private-bind
   change (compare each actual image/unit input separately), start that API, and verify the new
   container identity, private socket, `/health/live` and `/health/ready` with
   the existing repeated healthy-readback contract.
3. If Payment was enabled, explicitly recreate/start it in the new API container
   namespace and verify loopback 8002 readiness and matching provider identity
   summaries. `BindsTo`/`PartOf` stops the old container; it does not prove that
   a stopped Payment service has automatically returned. Compose `depends_on`
   alone is likewise not recovery evidence.
4. Only after the node passes may the next node proceed. For known failure,
   restore the captured original API unit/image and original callback state;
   if previously enabled, recreate Payment in the restored namespace and verify
   again. UNKNOWN stops progress pending readback. Do not delete databases,
   audit history, prior images or unrelated cloud resources.

ALB readiness is a provider-free GET of `/health/ready`; payment, XHS and model
supplier calls are not health dependencies. Validate both backends, exact
SNI/Host against the actual ALB endpoint, TLS/certificate binding and a fresh
post-bind three-unit NDR readback. Retain before-state for only known
task-created resource rollback. Emit the existing canonical Item36 Evidence
only after genuine provider readbacks and its validator pass.

Item36 terminal still depends on Items33+34, capacity100, fresh provider quote
and explicit fixed/variable cost approval. Private-bind and health preparation
can proceed independently of those terminal dependencies. No current quote,
cloud wrapper or live execution is implied. The old monthly estimate and
preparation-only NDR mask0 record remain LAST_KNOWN/reference-only.

### Item32/35/37/38 independent preparation status — September8

Item32: the unique successor recovery archive remains current (4 regular files,
30186bytes, SHA00eb73fdbbd62f541c000a7d29940ef3a417fecd756046fa59c2f694366ada13).
Seven source/HOLD/signer bindings match; no repack for unrelated document changes.
Its UTC September7 dispatch23:40/finishSeptember8 00:00 limits are expired. This
is a time PATH_BLOCKED. Before future authorization, retain the same WORK_ROOT,
old sealed records and old package. A prospective date rebind updates the same
executor's four time constants, canonical plan and executor hash/package together;
only after fresh absence of dispatch/admission/export and used0/remaining34 is
proven may the one not-yet-run successor proceed. No new diagnostic identity,
account or automatic date rollover is needed or authorized. readback-only remains
inert and does not confer completion or reconnect a supplier request.

Item35: the existing frozen review package and its10 scope files still match;
current implementation wiring does not change the professional review scope.
Keep the existing legal_privacy and provider_commercial_and_xhs signed categories,
four document approvals and zero unclosed conditions; do not add a requirement
for two different natural persons or freeze a duplicate package. Existing package
already lists the subject/contact/retention/provider questions still needing
real professional answers. No self-signature or message to others has occurred.

Item37 local scenario mapping uses the existing FIRST_LAUNCH_UI_ADMIN_CONTRACT,
chat-delivery-consistency, sse-stall-guard, quota-ui, admin-production-readonly
specs plus the actual Item31 HTTP/PG canary fixtures. The intended chain is
current candidate → controlled pre-DNS ingress → normal result/UNKNOWN/duplicate/
refund → current alert → exact recovery. It does not replay Items27/28 or count
local mocks as commercial acceptance. Real prerequisites30/31/35/36 remain.

Item38 preparation keeps the existing root/API/Admin hostname scope and no
invented www/additional names. A future DNS change must bind each record's actual
ID/type/value/TTL and its exact before-state to the actual accepted ALB target;
update rollback restores the old value/TTL, newly created records may only be
removed by their returned exact IDs, and unrelated records are left intact.
Current business records/ALB/certificate state are LAST_KNOWN until fresh reads.
Pre-DNS SNI tests and provider callback ingress are not owner public launch.
Actual public action still requires terminal37 plus the explicit owner Go-Live
statement and reviewed traffic limits. No DNS change or public traffic is made.

Fresh quote collection inputs, to complete in the existing plan after a current
provider read: cn-shenzhen, one ALB across the existing C/F zones/vSwitches, LCU1,
EIP2,720h monthly comparison; list ALB and each EIP hourly fees, LCU unit price,
public traffic price/GB and a separately approved traffic/spend ceiling. Include
quote time/expiry, tax/currency, selected configuration and any discount/payment
conditions. Old149.04 or missing fields are never a fresh quote and null is not0.
Read-only certificate inputs are exact Issued certificate ID, api.noteaipro.cn
coverage/validity, chain and binding; backend inputs are the two real node IDs/
private IPs/8000, GET /health/ready200, HTTPS443/SNI/Host and ALB-only source SG.
No purchase, new EIP/ALB, listener/certificate binding, SG or DNS action is authorized.

## 1. Immutable release set

All production pulls must use the private VPC registry hostname and the exact
manifest digest. Tags may be displayed for operators, but may not be used as
the deployed identity.

| Role | Private immutable image |
|---|---|
| API | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:17706e1802afc136ac8f9a621d4199a7f9749da733290e923e42268eff42e0d1` |
| Admin | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733` |
| XHS HTTP | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:452c2faf7853ce58d93e43c05fb6217a9a6cc1e4c81345d8cef2f50acabd79af` |

Every image must report `linux/amd64`, application/OCI revision
`a635692a899ee02c6905cd694611c14e0da4594a`, source
`https://github.com/iamyusen1314/noteai`, version
`git-a635692-amd64-r1`, non-root user `noteai` / UID/GID `999`, and its
expected `api`, `admin`, or `xhs-http` role marker. Local Docker image IDs are
not registry digests.

## 2. Proposed first-release placement

| Host | Initial service | Initial exposure |
|---|---|---|
| API-C | API canary, then accepted API; Admin only after both APIs pass | API canary on loopback; Admin loopback-only until a later ALB approval |
| API-F | API canary, then accepted API; XHS services only after separate XHS/DB-write approval | API canary on loopback; XHS exposes no HTTP port |

API-C is deployed and accepted first. API-F is never deployed merely because
API-C succeeded; it has its own digest/config/readiness acceptance. Admin is
single-instance for the first internal release and remains unreachable from
the public Internet. The XHS image supplies two process roles,
`xhs-trends` and `xhs-tracking`; both stay stopped until their separate gate.

This placement uses existing paid ECS capacity and does not create a Worker
host. CPU, memory, disk and failure-domain suitability must be rechecked before
execution. If either host lacks headroom, stop and request a capacity decision;
do not silently colocate more roles or buy capacity.

## 3. Blocking findings before any deployment

1. `PROD-DEPLOY-ENV-SPLIT-001` closes the original repository-side shared
   env-file defect. The later Tracking contract further splits Trends and
   Tracking, so API, Admin, Trends and Tracking now use four distinct inputs;
   `scripts/validate_production_env_files.py` rejects unknown, duplicate or
   cross-role Secret key names without printing values. The live files and
   their permissions still require read-only verification on API-C/API-F.
2. API-C/API-F Docker, disk, current containers, service definitions, ports,
   private ACR DNS, registry-auth method and runtime-env metadata are not
   currently re-observed. A read-only node audit is mandatory.
3. RDS current availability, backup/PITR state and schema versions `0001`-
   `0008` need a fresh read-only check. Ordinary API/Admin start must not run
   migration. `scripts/render_predeploy.py` also writes the managed Prompt
   baseline and is therefore excluded without a separate database-write
   approval.
4. The Admin listener placement is intentionally loopback-only for this
   internal stage. Public/private ALB exposure requires a later listener,
   security-group and authentication review.
5. `NOTEAI_XHS_COLLECTION_SUSPENDED=1` prevents real XHS collection, but the
   market worker can still write baseline/freshness state to PostgreSQL and a
   local snapshot. XHS service start therefore needs an explicit bounded
   production-write approval even while external collection remains suspended.
6. ALB, TLS binding, DNS cutover, real provider checks, payment and public
   traffic are outside this plan.

## 4. Serial rollout gates

### Gate 0 — read-only production preflight

- Reconfirm exact host IDs/names and that only API-C/API-F are in scope.
- Record Docker/Compose versions, architecture, free disk/memory, current
  container/image/service state, bound ports and existing release paths.
- Hash current deployment definitions and record current immutable image refs;
  do not output environment values.
- Verify each role env file is root-owned `0600`, contains only allowlisted key
  names, and has no unknown/duplicate names. Do not print values.
- Resolve the private ACR hostname from both nodes and verify intended VPC
  routing. No registry login, manifest request or pull in this gate.
- Read RDS availability, schema-migration versions, backup/PITR metadata and
  connection limits without changing data.
- Run `tools/collect_production_database_preflight.py` only through an
  authenticated least-privilege metadata credential/session. Inject its DSN
  through a hidden protected process environment; never place it in command
  arguments, evidence or logs. Require connection- and transaction-level
  read-only mode, bounded timeouts, aggregate-only source checks, rollback and
  close.
- Reduce the observation to a Secret-free JSON artifact and require
  `tools/production_readonly_preflight_gate.py` to pass. Do not record host
  IDs, IP addresses, connection values, user rows or long logs.
- Stop on any unexpected running application, public listener, mutable image
  ref, Secret exposure, low disk, architecture mismatch or unrecorded change.

### Gate 1 — deployment-template closure

- Confirm the completed role-specific env-file inputs for API, Admin and XHS.
- Run the key-name validator against all three external files before Compose
  resolution; reject unknown, duplicate or cross-role Secret names.
- Preserve UID/GID `999`, read-only root, `cap_drop: ALL`,
  `no-new-privileges`, bounded `/tmp`, no devices, no privileged mode and the
  single bounded data mount.
- Resolve the Compose file offline and verify every image matches
  `repository@sha256:<64 lowercase hex>`.
- Run the production hardening, readiness and production-readiness tests.
- Create a `[skip render]` deployment-control commit. This commit is not an OCI
  revision and does not require an image rebuild.

### Gate 2 — API-C canary and promotion

- Capture the current service/config/image state and rollback command before
  any pull.
- Authenticate only to the private VPC registry using a temporary,
  least-privilege mechanism; never reopen the public ACR endpoint.
- Pull only the exact API digest, then immediately verify RepoDigest,
  `linux/amd64`, OCI revision and role marker.
- Start a loopback-only canary on an unused port with the production runtime
  constraints. Do not run migration or any real provider call.
- Require `/health/live` HTTP `200` and `/health/ready` HTTP `200` three times
  over at least 60 seconds. Readiness must contain only healthy PostgreSQL and
  required local-model checks.
- Inspect bounded, redacted logs and prove no migration, supplier request,
  billing mutation or Secret output occurred.
- Only after independent acceptance may the same digest/config replace the
  inactive API-C production service. Keep it outside ALB.

### Gate 3 — API-F canary and promotion

- Repeat Gate 2 independently on API-F; do not copy API-C's result.
- Confirm digest and role/config parity with API-C.
- Require repeated zero-AI readiness and retain API-C as the rollback-safe
  accepted node.
- Keep API-F outside ALB until independent acceptance.

### Gate 4 — Admin internal deployment

- Pull only the exact Admin digest on API-C and verify its registry/OCI
  identity before start.
- Require the dedicated `noteai_admin_runtime` database role and the accepted exact
  session/read-only operational permission matrix. Do not reuse `noteai_app`
  or the managed RDS administrator named `noteai_admin`,
  and do not force the entire connection read-only: login/logout require only
  `admin_sessions` `SELECT, INSERT, DELETE`, while all business mutations are
  denied independently by application capability gates and database ACL/RLS.
- Start loopback-only. Require `/health/live` HTTP `200` and
  `/health/ready` HTTP `200`; Admin readiness blocks only on PostgreSQL and a
  configured Admin credential.
- Prove one login, authenticated `/admin/capabilities` read, masked user/queue
  views, logout and token invalidation without business writes. Every mutation
  endpoint must return HTTP `409` before database/file/process work.
- Do not mutate Prompt/configuration, expose the port publicly or add it to ALB
  in this gate.

### Gate 5 — XHS HTTP processes

- Keep both processes stopped until separately approved.
- When approved, pull the exact XHS digest on API-F and verify identity.
- Start `xhs-trends` before `xhs-tracking`, never together.
- Keep `NOTEAI_XHS_COLLECTION_SUSPENDED=1`, leave snapshot upload disabled,
  keep crawler configuration disabled, and make no real XHS request.
- Trends has no healthcheck. Tracking uses only its provider-free read-only
  schema/role healthcheck and `restart: "no"`; a failed round stays stopped
  for evidence review instead of automatically retrying. Acceptance also
  requires the expected non-root process command, bounded redacted logs and
  proof of zero external collection.
- Any database/snapshot writes must match the separately approved bounded
  list. Do not use a browser fallback, proxy rotation or challenge bypass.

### Gate 6 — later network release

ALB creation, backend registration, TLS binding, DNS cutover, public smoke and
real supplier calls are separate tasks with separate cost and production-impact
approval. No earlier gate implies approval for Gate 6.

## 5. Health and acceptance contract

| Role | Liveness | Readiness / acceptance |
|---|---|---|
| API | `/health/live`: process-only HTTP `200` | `/health/ready`: HTTP `200` only when PostgreSQL and the required local model are healthy; HTTP `503` otherwise |
| Admin | `/health/live`: process-only HTTP `200` | `/health/ready`: HTTP `200` only when PostgreSQL and Admin credential presence are healthy; HTTP `503` otherwise |
| XHS Trends | No HTTP listener or Docker healthcheck | Process/command identity, runtime constraints, suspension state, bounded logs and zero external collection |
| XHS Tracking | No HTTP listener; provider-free read-only Docker healthcheck | Exact role/schema readiness, stale/unlinked-attempt failure, suspension state, bounded logs and zero external collection |

Claude, Kimi, Amap, Meituan, XHS, market freshness, crawler and payment are not
load-balancer health dependencies and must not be called by these probes.

## 6. Rollback

- Never delete the prior image, release directory, environment metadata or
  evidence during rollout.
- A canary failure rolls back by stopping/removing only the new canary and
  restoring the recorded inactive state.
- API-C promotion failure restores its prior service/config. API-F failure
  stops API-F and retains accepted API-C.
- Admin failure stops only Admin and leaves both APIs unchanged.
- XHS failure sets/keeps collection suspended and stops only the failing XHS
  process. Do not fall back to Playwright/Chromium.
- No schema migration is included, so application rollback does not perform a
  database downgrade or destructive cleanup.
- Registry image deletion, production-data cleanup and cloud-resource deletion
  are never automatic rollback actions.

## 7. Cost and duration

- No new cloud resource is required by this plan.
- Existing fixed ECS/RDS/Tair/ACR/NAT charges continue whether deployment
  occurs or not.
- Worst-case unshared image transfer for two API copies plus one Admin and one
  XHS copy is about `4.18 GB`; shared layers should reduce actual transfer and
  disk consumption. Use only the private VPC registry path. Registry/network
  billing must be rechecked before execution.
- Reserve at least `12 GiB` free Docker storage per participating node so the
  accepted prior image/config can remain available for rollback.
- Expected operator window after all blockers close: read-only preflight
  20–30 minutes; API-C 20–30 minutes; API-F 20–30 minutes; Admin 15–20
  minutes. XHS activation is a separate window. Stop rather than compressing
  observation periods.
- No AI, map, Meituan, XHS or payment usage cost is permitted in the zero-AI
  rollout.

## 8. Approval sequence

1. `PROD-DEPLOY-ENV-SPLIT-001` — repository-only env-file separation,
   key-name validation and `[skip render]` deployment-control commit.
2. `PROD-DEPLOY-PREFLIGHT-001` — next approval: read-only
   API-C/API-F/RDS/private-network
   audit; no ACR access or production writes.
3. `PROD-API-C-ROLL-001` — exact-digest private pull, loopback canary and
   zero-AI API-C acceptance.
4. `PROD-API-F-ROLL-001` — same independent API-F rollout.
5. `PROD-ADMIN-ROLL-001` — loopback-only Admin rollout.
6. `PROD-XHS-ROLL-001` — separately bounded XHS process start and allowed
   database-write list while external collection stays suspended.
7. ALB, TLS, DNS and public/real-provider smoke remain later approvals.
