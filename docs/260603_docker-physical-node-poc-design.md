# StarryNet Docker + 实物节点 PoC 方案说明

本文总结把 StarryNet 从单机纯 Docker 仿真扩展到 Docker + 实物节点混合部署的 PoC 思路。这里的“实物节点”指一台真实 Linux 板子、物理服务器或非 Docker 虚拟机；每台实物节点上运行一个 StarryNet 容器，该容器代表拓扑中的一个卫星或地面站节点。

## 任务目标

本任务的目标不是一次性完成完整多机重构，而是先验证一个可落地的最小闭环：

- 指定节点位置：能够明确指定 `ovs_container_<n>` 跑在哪台真实机器或 VM 上。
- 保留 StarryNet 语义：继续使用现有 ISL/GSL 命名、静态 IP、接口重命名、`tc qdisc` 延迟/丢包/带宽配置和 BIRD/OSPF 路由流程。
- 跨机器连通：容器分布到多台机器后，ISL/GSL 仍能通过 Docker overlay 网络连通。
- 动态行为可用：链路延迟更新、GSL 增删、damage/recovery、ping、iperf、route 检查仍能运行。
- 明确精度边界：评估 overlay/VXLAN 引入的额外延迟、MTU 损耗和性能抖动是否会影响 StarryNet 的仿真结论。

## 总体方案

采用“Swarm 管网络，SSH 管节点”的 PoC 架构：

```text
控制进程 / StarryNet
  ├─ SSH -> Swarm manager：创建 overlay --attachable 网络，生成/分发配置
  ├─ SSH -> 实物节点 A：运行 ovs_container_1，执行 docker exec/tc/bird
  ├─ SSH -> 实物节点 B：运行 ovs_container_2，执行 docker exec/tc/bird
  └─ SSH -> 实物节点 C：运行 ovs_container_3，执行 docker exec/tc/bird
```

关键决策：

- 不把 StarryNet 节点做成 Swarm service task。
- 每个 StarryNet 节点仍是 standalone container。
- StarryNet 通过 `config.json` 的 `starrynet_nodes` 建立 `node_index -> host -> container_name` 映射。
- ISL/GSL 网络由 manager 创建为 `overlay --attachable`，容器所在 host 再执行 `docker network connect --ip` 接入。
- 跨机器执行统一走 SSH，不开放 Docker TCP API。

## 为什么这样做

StarryNet 当前实现高度依赖“逐容器、逐链路”的命令式操作：

- 先创建一个 Docker 网络表示一条 ISL/GSL。
- 再把两个容器接入该网络，并指定固定 IP。
- 进入容器后按 IP 找到新接口，把接口重命名成 `B<src>-eth<dst>`。
- 在该接口上配置 `tc qdisc`。
- BIRD 配置文件也引用这些稳定的接口名。

Swarm service task 更适合声明式服务编排，不适合作为 PoC 主承载：

- service 网络通常通过 `docker service create/update --network` 管理，而不是运行中逐容器手工 `network connect --ip`。
- service task 被重调度后容器 ID、所在主机和接口状态都可能变化。
- StarryNet 的链路更新、故障注入和路由检查依赖 `docker exec` 到具体容器；跨主机后必须知道容器所在机器。

因此，PoC 选择显式 SSH 到目标机器运行 standalone container。这样可以最大限度复用 StarryNet 原有抽象，同时把风险集中到 overlay 网络和跨主机执行层。

## 任务计划

### 1. 环境准备

- 准备 2 到 3 台 Linux 主机或 VM，均安装 Docker。
- 初始化 Docker Swarm，并让所有实物节点加入同一个 Swarm。
- 确认控制机能 SSH 到 manager 和每个实物节点。
- 每台机器预拉取或导入 `lwsen/starlab_node:1.0`。
- 确认目标用户能直接执行 `docker ps`、`docker run`、`docker network connect`。

### 2. 配置节点映射

在 `config.json` 中配置：

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
  }
]
```

PoC 要求 `starrynet_nodes` 覆盖 `1..node_size` 的所有 StarryNet 节点。为空时继续使用旧的单机 Docker service 流程。

### 3. 验证容器定位

- 执行 `create_nodes`。
- 在每台 host 上检查 `docker ps --filter label=starrynet=true`。
- 确认每个 `ovs_container_<n>` 只出现在配置指定的 host 上。
- 中断后执行 `stop_emulation`，确认只清理 StarryNet 容器和 StarryNet 网络。

### 4. 验证 overlay 替代 ISL/GSL

- 由 manager 创建 `Le_*`、`La_*`、`GSL_*`、`GS_*` overlay attachable 网络。
- 在容器所在 host 上执行 `docker network connect --ip`。
- 进入容器确认 IP、接口名和路由配置。
- 对跨 host 的两个容器运行 `ping`，确认基础连通。
- 对同一条链路配置 `tc qdisc delay/loss/rate`，确认效果可观测。

### 5. 验证 StarryNet 最小闭环

建议从极小拓扑开始，例如 2 个卫星节点 + 1 个地面站，或 4 个容器节点：

```text
create_nodes
create_links
run_routing_deamon
set_ping
check_routing_table
start_emulation
stop_emulation
```

通过后再增加节点规模，避免一开始被大规模链路创建、路由收敛和 overlay 传播问题混在一起。

### 6. 验证动态行为

- 延迟更新：检查 `tc qdisc change` 是否能跨 host 修改目标接口。
- GSL 增删：检查 overlay 网络创建、连接、断开、删除是否稳定。
- damage/recovery：确认 loss 100% 和恢复 loss 配置能生效。
- ping/iperf：确认结果文件仍写入本地输出目录。
- route：确认 BIRD/OSPF 路由表与预期拓扑一致。

## Overlay 对仿真精度的影响

overlay 网络能够解决跨主机容器连通问题，但它不是“零成本替代”原来的单机 bridge 网络。需要单独评估以下影响。

### 1. 额外延迟

Docker overlay 通常基于 VXLAN 封装。报文会经历容器 veth、宿主网络栈、VXLAN 封装、物理网络、对端宿主解封装、对端容器 veth。与单机 bridge 相比，这会增加基础延迟。

处理方式：

- 建立基线：同一链路分别在单机 bridge 和跨主机 overlay 下测 `ping` RTT。
- 将 overlay 基础延迟作为固定偏移记录下来。
- 如果 StarryNet 关注绝对时延，应考虑从 `tc netem delay` 中扣除该基线，或在结果分析中标注 overlay 基础开销。
- 如果 StarryNet 只比较策略相对优劣，也要确认 overlay 抖动不会大到改变策略排序。

### 2. 抖动和不确定性

跨主机 overlay 受物理网络、宿主机负载、Docker 转发路径和内核调度影响，抖动通常高于单机 bridge。动态拓扑更新时，overlay 网络创建和传播也可能带来短暂不可达。

处理方式：

- 每轮实验记录 host CPU、内存、网络负载。
- 对关键 ping/iperf 结果做多轮重复，记录均值、方差、P95/P99。
- 链路创建后增加短暂验证步骤，确认接口和 IP 已出现再配置 `tc`。
- 对路由收敛时间单独记录，不把 overlay 网络传播时间误认为 StarryNet 路由算法本身开销。

### 3. MTU 和分片

VXLAN 封装会消耗额外头部空间，导致 overlay 网络的有效 MTU 小于底层物理网 MTU。常见现象是容器内仍认为自己能发较大包，但跨主机时发生分片或丢包，从而影响 iperf 吞吐、延迟和丢包统计。

处理方式：

- 检查容器内接口、宿主物理网卡和 Docker overlay 网络的 MTU。
- 用 `ping -M do -s <size>` 找到不分片的最大包长。
- PoC 中优先把容器链路 MTU 统一到保守值，例如 1450，实际值以实测为准。
- iperf 结果必须注明 MTU 设置，避免把分片导致的吞吐下降误认为链路带宽配置效果。

### 4. 带宽控制精度

`tc qdisc rate` 配在容器接口上，但 overlay 还会经过宿主机封装和物理网卡。最终吞吐受三层因素共同影响：

- StarryNet 配置的 `tc` rate。
- 宿主机 Docker/VXLAN 转发能力。
- 真实物理网络带宽和拥塞。

处理方式：

- 对每台 host 做本地 iperf 基线和跨 host overlay iperf 基线。
- StarryNet 配置的仿真带宽不要超过真实网络稳定可承载带宽。
- 当 `tc rate` 高于真实网络能力时，结果应判定为物理环境受限，而不是 StarryNet 链路模型有效。

### 5. 丢包模型叠加

StarryNet 用 `tc netem loss` 模拟链路丢包。跨主机后，真实网络丢包、overlay 封装丢包、MTU 分片丢包会与仿真丢包叠加。

处理方式：

- 先测真实 overlay 空载丢包率。
- 只有当真实丢包率足够低且稳定时，才运行需要精确 loss 的实验。
- 结果中区分“配置丢包率”和“观测丢包率”。

## 需要重点处理的问题

- 容器生命周期：只能清理带 `starrynet=true` label 或 `ovs_container_<n>` 的容器，不能全量删除 host 上所有容器。
- SSH 安全：PoC 允许密码或私钥，但真实部署建议使用私钥；不要把真实密码提交到仓库。
- Swarm 健康：所有 host 必须处于同一个 Swarm，overlay 网络才能跨主机使用。
- 镜像一致性：所有 host 上的 `lwsen/starlab_node:1.0` 必须一致，否则 BIRD、tc、ifconfig 行为可能不同。
- 时间同步：多机实验建议启用 NTP/chrony，避免日志和路由收敛时间无法对齐。
- 失败回滚：链路创建失败时要能清理半创建网络和半连接容器。
- 可观测性：每次实验记录 Docker 版本、内核版本、MTU、Swarm 状态、host 负载和 overlay 基线。

## 验收标准

PoC 可以认为通过，需要同时满足：

- 配置中的每个 `node_index` 都在指定 host 上启动为 standalone container。
- 至少一条跨 host ISL 和一条 GSL 能通过 overlay 建立，并保留原有 IP/接口命名规则。
- `tc qdisc` 对跨 host 链路的 delay/loss/rate 配置可观测。
- BIRD/OSPF 能启动并形成符合最小拓扑的路由。
- `ping`、`iperf`、`route`、damage/recovery、动态 GSL 增删至少在小拓扑上跑通。
- 输出报告中包含 overlay 基础延迟、抖动、MTU 和吞吐基线。

## 结论

这个方案的核心是：不要让 Swarm 接管 StarryNet 节点生命周期，而是只借用 Swarm overlay 提供跨主机网络能力。StarryNet 仍然把“节点”当成一个可精确控制的容器，通过 SSH 把命令发送到容器所在机器。这样可以最小化对现有仿真模型的破坏，同时把需要验证的不确定性集中到 overlay 网络精度和跨主机执行可靠性上。
