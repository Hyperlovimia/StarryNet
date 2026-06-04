# 2026-06-03 StarryNet Docker + 实物节点 PoC 变更记录

## 背景

原 StarryNet 将卫星节点和地面站节点都放在单台 Docker 主机上，通过 Docker bridge 网络模拟 ISL/GSL 链路，并在容器接口上用 `tc qdisc` 注入延迟、丢包和带宽限制。

本次变更的目标是验证“Docker 容器节点 + 实物机器节点”统一处理的 PoC：每台真实 Linux 板子或非 Docker VM 上运行一个 StarryNet 容器，这个容器代表一个真实拓扑节点；跨机器链路使用 Docker Swarm 的 attachable overlay 网络承载。

## 核心决策

- 不把 StarryNet 节点做成 Swarm service task。
- Swarm 只用于提供跨主机 overlay 网络能力。
- StarryNet 节点仍是 standalone container。
- 控制通道使用 SSH 到各物理机/VM，不开放 Docker TCP API。
- 多节点模式只在 `config.json` 中 `starrynet_nodes` 非空时启用；为空时保留旧单机 Docker service 流程。

这样做是因为现有链路模型强依赖逐容器操作：`docker network connect --ip`、接口重命名、`docker exec`、`tc qdisc` 和 BIRD 配置下发。Swarm service 的声明式网络模型不适合直接承载这套动态链路逻辑。

## 主要代码变更

### `starrynet/sn_multi_node.py`

新增多节点执行层：

- `MultiNodeExecutor` 维护 `node_index -> host/container` 映射。
- 通过 Paramiko SSH 到指定 host 执行 Docker 命令。
- 在 Swarm manager 上创建 `overlay --attachable` 网络。
- 在容器所在 host 上执行 `docker network connect --ip`。
- 继续保留现有 ISL/GSL 子网、IP、接口命名和 `tc qdisc` 语义。
- 支持多节点模式下的节点创建、链路创建、BIRD 配置下发、动态延迟更新、damage/recovery、ping、iperf、route 查询和清理。
- 校验同一 host 上重复的 `container_name`，避免 Docker name conflict 延迟到运行期才暴露。
- 过滤远端 shell/容器输出中的 `mesg: ttyname failed` 噪声，避免接口探测把警告文本误判成网卡名。
- 对 ISL 建链按无向节点对去重并跳过自环，避免 2x2 小拓扑下 `1-2` 和 `2-1` 重复创建导致接口重命名冲突。
- 多节点 BIRD 初始化增加逐节点进度输出，并允许通过 `STARRYNET_ROUTING_WAIT_SECONDS` 覆盖路由收敛等待时间。

### `starrynet/sn_synchronizer.py`

新增运行模式切换：

- `starrynet_nodes` 为空：走旧单机路径。
- `starrynet_nodes` 非空：创建 `MultiNodeExecutor`，并在公开 API 中切换到多节点实现。

覆盖的 API 包括：

- `create_nodes`
- `create_links`
- `run_routing_deamon`
- `get_IP`
- `start_emulation`
- `stop_emulation`

### `starrynet/sn_utils.py`

配置读取新增字段：

- `starrynet_nodes`
- `swarm_manager`
- `starrynet_image`

同时保留旧 CLI 兼容行为：当传入默认的 `config.xls` 路径但文件不存在时，仍回退读取 `./config.json`。

### `config.json`

新增默认字段：

```json
"starrynet_image": "lwsen/starlab_node:1.0",
"starrynet_nodes": []
```

`starrynet_nodes` 默认为空，因此默认运行仍是旧单机模式。

### `docs/installation-and-local-runbook.md`

新增“Docker + 实物节点 PoC 模式”说明，记录：

- 启用条件。
- `starrynet_nodes` 配置结构。
- 密码认证和私钥认证示例。
- manager 与物理节点的职责边界。
- 为什么 PoC 不使用 Swarm service task 承载 StarryNet 节点。

## 多节点配置示例

示例只展示结构，不记录真实凭据：

```json
"starrynet_image": "lwsen/starlab_node:1.0",
"starrynet_nodes": [
  {
    "node_index": 1,
    "host": "192.168.1.11",
    "ssh_user": "root",
    "ssh_auth": {"type": "password", "password": "<password>"},
    "role": "physical",
    "container_name": "ovs_container_1"
  },
  {
    "node_index": 2,
    "host": "192.168.1.12",
    "ssh_user": "root",
    "ssh_auth": {"type": "key", "key_filename": "/home/user/.ssh/id_rsa"},
    "role": "physical",
    "container_name": "ovs_container_2"
  }
]
```

约束：

- `starrynet_nodes` 必须覆盖 `1..node_size` 的每个节点。
- 每个 host 需要已安装 Docker，并加入同一个 Swarm。
- manager 需要能创建 overlay 网络。
- 每个物理机/VM 需要能拉取或预加载 `lwsen/starlab_node:1.0`。
- 控制机需要能 SSH 到 manager 和每个节点 host。

## 清理策略变化

多节点 PoC 模式只清理 StarryNet 自己创建的资源：

- 带 `starrynet=true` label 的容器。
- `ovs_container_<n>` 命名容器。
- `La_`、`Le_`、`GSL_`、`GS_` 前缀的网络。
- `constellation-test` service。

避免使用旧逻辑中危险的全量删除命令，例如 `docker rm -f $(docker ps -a -q)`。

## 已做验证

已完成静态和无连接验证：

```bash
python3 -m py_compile starrynet/*.py
```

结果：

- Python 编译通过。
- 新增执行器构造和节点配置归一化检查通过。
- 旧代码中仍有既存的字符串转义 `SyntaxWarning`，不影响本次新增逻辑。

### 2026-06-04 两机实物 PoC 验证

验证环境：

- Swarm manager / 控制机：`192.168.137.101`。
- Swarm worker / 实物节点：`192.168.137.102`。
- 测试拓扑：`2x2` 卫星 + 2 个地面站，共 6 个 StarryNet 节点。
- 节点放置：`node_index=1` 跑在 `192.168.137.102`，`node_index=2..6` 跑在 `192.168.137.101`。
- 启动命令：

```bash
sn -p ./config.json -i 1 -n 6 -g "50.110924/8.682127/46.635700/14.311817"
```

已验证流程：

```text
create_nodes
create_links
run_routing_deamon
get_IP 1
get_IP 2
set_ping 1 2 3
start_emulation
```

结果：

- `create_nodes` 成功创建 6 个 standalone container。
- `create_links` 成功创建 Swarm `overlay --attachable` 链路网络，并在容器所在 host 执行 `docker network connect --ip`。
- `run_routing_deamon` 成功向每个容器复制 BIRD 配置并启动路由进程。
- `get_IP 1` 返回 `['10.0.2.30', '10.0.1.40', '172.17.0.2']`。
- `get_IP 2` 返回 `['10.0.4.30', '10.0.1.10', '172.17.0.2']`。
- `start_emulation` 在 20 秒测试时长内推进到第 19 秒，并在第 5、10、15 秒完成动态 delay update。
- `set_ping 1 2 3` 生成 `starlink-2-2-550-53-grid-LeastDelay/ping-1-2_3.txt`，node 1 到 node 2 的 overlay 链路 `10.0.1.10` ping 结果为 4/4 收包、0% 丢包，RTT 平均约 299 ms。

本轮实测确认：

- manager 可以创建 attachable overlay 网络。
- worker 上可以运行 StarryNet standalone container。
- worker 上的容器可以被加入 manager 创建的 overlay 网络。
- 跨 host `docker exec`、接口重命名、`tc qdisc`、BIRD 启动和 ping 均可执行。
- StarryNet 的 `create_nodes -> create_links -> run_routing_deamon -> start_emulation` 多节点主流程已在 101/102 两机环境跑通。

实测中发现并修复的问题：

- `config.json` 中多个节点误用了同一个 `container_name`，导致 Docker 报容器名冲突；修复为 `ovs_container_<node_index>` 并增加重复名校验。
- 远端命令输出中出现 `mesg: ttyname failed: Inappropriate ioctl for device`，接口探测误将该文本当成接口名；修复为过滤该噪声并校验接口名格式。
- `2x2` 小拓扑中环绕 ISL 会重复创建同一无向链路，导致 `RTNETLINK answers: File exists`；修复为 ISL 无向节点对去重。
- BIRD 初始化阶段原先固定等待 120 秒，PoC 中看起来像卡住；修复为按节点数计算等待时间，并支持环境变量覆盖。

仍未完成的真实环境验证：

- 尚未对比单机 bridge 与多机 overlay 的延迟、丢包、吞吐和路由收敛差异。
- 尚未验证 `iperf`、damage/recovery、动态 GSL 增删和 route 查询在跨 host 场景下的完整表现。
- 尚未扩大到默认 5x5 + 2 GS 规模评估 overlay 开销、MTU 和吞吐上限。

## 后续验证建议

1. 增加 `set_perf` 验证，记录跨 host overlay 下 iperf 吞吐和 StarryNet `tc rate` 的叠加效果。
2. 增加 `set_damage` / `set_recovery` 验证，确认跨 host 场景下 loss 100% 和恢复逻辑可用。
3. 增加动态 GSL 增删验证，检查 overlay 网络创建、连接、断开和删除的稳定性。
4. 增加 `check_routing_table` 验证，记录 BIRD/OSPF 路由收敛结果。
5. 对比单机 bridge 与两机 overlay 的 ping/iperf 基线，记录 overlay 开销和 MTU 风险。
6. 最后扩大到默认 5x5 + 2 GS 规模，观察串行 SSH 执行和 Swarm overlay 网络数量增长后的性能边界。

## 风险与注意事项

- overlay 网络引入 VXLAN 封装，真实延迟和 MTU 会叠加到仿真结果中。
- 多节点模式目前是 PoC 路径，优先保证可验证，不追求最优性能。
- 当前执行器为了避免 SSH 连接并发问题，链路创建和动态操作偏串行。
- `starrynet_nodes` 非空但没有覆盖全部节点时会直接报错，避免拓扑节点被隐式调度到错误机器。
- 不要把真实 SSH 密码提交到仓库。
