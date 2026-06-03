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

未完成真实环境验证：

- 尚未在 2-3 台真实 host 上跑 Swarm overlay 联通测试。
- 尚未跑完整 `create_nodes -> create_links -> run_routing_deamon -> start_emulation` 的跨机验证。
- 尚未对比单机 bridge 与多机 overlay 的延迟、丢包、吞吐和路由收敛差异。

## 后续验证建议

1. 用 2 台 host + 2 个节点验证 standalone 容器是否按 `node_index` 跑在指定机器。
2. 创建一条 `Le_*` overlay 链路，验证跨 host `docker network connect --ip`、接口重命名和 `tc qdisc`。
3. 用 2 卫星 + 1 地面站的小拓扑验证 BIRD 路由、ping、route。
4. 加入动态 GSL 增删、delay update、damage/recovery。
5. 最后再扩大到默认 5x5 + 2 GS 规模，记录 overlay 开销和 MTU 风险。

## 风险与注意事项

- overlay 网络引入 VXLAN 封装，真实延迟和 MTU 会叠加到仿真结果中。
- 多节点模式目前是 PoC 路径，优先保证可验证，不追求最优性能。
- 当前执行器为了避免 SSH 连接并发问题，链路创建和动态操作偏串行。
- `starrynet_nodes` 非空但没有覆盖全部节点时会直接报错，避免拓扑节点被隐式调度到错误机器。
- 不要把真实 SSH 密码提交到仓库。
