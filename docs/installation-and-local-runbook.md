# StarryNet 安装、本地运行与排障记录

本文记录本次安装脚本调整、本地运行方式，以及从实际排障过程中确认的常见错误处理方法。

## 变更摘要

`install.sh` 已从直接写入系统 Python 的安装方式，调整为“系统依赖 + 项目虚拟环境 + 全局命令 wrapper”的方式：

- 使用 `set -euo pipefail`，安装步骤失败时立即退出。
- Ubuntu/Debian 使用 `/etc/os-release` 识别发行版，安装 `python3-setuptools`、`python3-venv`、`python3-pip` 等现代包名。
- Docker 未安装时，自动配置 Docker 官方 apt/yum 源，再安装 `docker-ce`、`docker-ce-cli`、`containerd.io` 等包。
- Python 依赖安装到项目目录下的 `.venv`，避免 Ubuntu 24.04 等系统的 PEP 668 `externally-managed-environment` 问题。
- 不再直接运行 `sudo python3 setup.py install`；改为：

```bash
"$VENV_DIR/bin/python" -m pip install "$SCRIPT_DIR"
```

该命令会通过 pip 安装当前项目，并间接读取 `setup.py` 的构建信息。

- 安装完成后写入 `/usr/local/bin/sn` wrapper，使 `sn` 和通常的 `sudo sn` 调用方式仍然可用。
- 安装 Python 包前会清理旧的 `build/` 和 `starrynet.egg-info/`，避免之前 `sudo setup.py install` 生成的 root-owned 构建产物阻塞 pip。

## 安装方式

在仓库根目录运行：

```bash
bash ./install.sh
```

安装完成后，CLI wrapper 位于：

```bash
/usr/local/bin/sn
```

实际 Python 环境位于：

```bash
.venv/
```

可以用以下命令确认：

```bash
which sn
sn -h
```

## 本地测试配置

StarryNet 当前代码即使在单机模式下，也会通过 SSH 连接 `config.json` 中指定的 `remote_machine_IP`，然后在目标机器上执行 Docker 命令。

因此本地测试时，`config.json` 应指向本机 SSH：

```json
"remote_machine_IP": "127.0.0.1",
"remote_machine_username": "<your-local-ssh-user>",
"remote_machine_password": "<your-local-ssh-password>"
```

注意：

- 不要把真实 SSH 密码提交到 git。
- 代码当前使用密码登录 SSH，未实现私钥登录。
- 建议在仓库根目录运行，因为部分代码默认读取 `./config.json`。
- 目标用户需要能直接执行 `docker`，否则远程命令会失败。

本机测试前确认：

```bash
ssh <your-local-ssh-user>@127.0.0.1
ssh <your-local-ssh-user>@127.0.0.1 'docker ps'
docker info --format 'Swarm={{.Swarm.LocalNodeState}}'
```

如果 Swarm 未启用：

```bash
sudo docker swarm init
```

## Docker 镜像要求

项目创建容器时硬编码使用：

```text
lwsen/starlab_node:1.0
```

运行前建议先手动拉取：

```bash
docker pull lwsen/starlab_node:1.0
```

如果使用镜像源拉取失败，可以尝试直接指定可用代理并重新打 tag：

```bash
docker pull <mirror-host>/lwsen/starlab_node:1.0
docker tag <mirror-host>/lwsen/starlab_node:1.0 lwsen/starlab_node:1.0
```

如果本机网络无法拉取 Docker Hub，可以在另一台可拉取的机器上导出镜像：

```bash
docker pull lwsen/starlab_node:1.0
docker save lwsen/starlab_node:1.0 | gzip > starlab_node_1.0.tar.gz
```

拷回本机后导入：

```bash
gunzip -c starlab_node_1.0.tar.gz | docker load
docker image ls lwsen/starlab_node
```

## 运行示例

激活虚拟环境后运行：

```bash
source .venv/bin/activate
python3 ./example.py
```

或使用 CLI：

```bash
sn -h
sn
```

成功运行时会看到类似输出：

```text
Start StarryNet.
Constellation initialization done. 27 have been created.
Link initialization done.
Routing initialized!
Bird routing in all containers are running.
node_distance (km): ...
neighbors_index: ...
Emulation in No.2 second.
Emulation in No.3 second.
```

默认 `config.json` 中 `"Duration (s)"` 为 `100`，因此会按秒推进到接近 100 秒。输出目录形如：

```text
starlink-5-5-550-53-grid-LeastDelay/
```

其中会生成 `delay/`、`ping-*.txt`、`route-*.txt` 等结果文件。

## 清理方式

如果运行被中断，可能会留下 Docker service、容器或网络。可以运行：

```bash
python3 starrynet/clean.py
```

也可以手动检查：

```bash
docker service ls
docker ps -a
docker network ls
```

必要时删除 StarryNet service：

```bash
docker service rm constellation-test
```

## 重要风险

StarryNet 会在目标 Docker 主机上清理旧环境。当前逻辑会执行类似命令：

```bash
docker service rm constellation-test
docker rm -f $(docker ps -a -q)
```

因此请尽量使用专门的测试机、虚拟机或没有重要容器的 Docker 环境。不要在承载其他业务容器的机器上直接运行示例。

## 常见错误处理

### `Package python-setuptools is not available`

旧包名问题。Ubuntu/Debian 新版应使用：

```bash
python3-setuptools
```

新的 `install.sh` 已处理。

### `docker-ce has no installation candidate`

通常是未配置 Docker 官方 apt 源。新的 `install.sh` 会在 Docker 不存在时配置官方源后再安装。

### `externally-managed-environment`

Ubuntu 24.04 等系统禁止直接 `sudo pip install` 写系统 Python。新的安装方式使用 `.venv`，避免该问题。

### `Cannot update time stamp of directory 'starrynet.egg-info'`

通常是之前用 sudo 安装留下了 root-owned `build/` 或 `starrynet.egg-info/`。新的 `install.sh` 会在 pip 安装前清理这些构建产物。

### `SyntaxWarning: invalid escape sequence`

例如：

```text
SyntaxWarning: invalid escape sequence '\('
```

这是 Python 3.12 对字符串转义的警告，不是阻塞原因。程序仍可继续运行。

### `Start StarryNet.` 后长时间无输出

通常卡在 SSH 连接目标机器。检查：

```bash
ssh <user>@<remote_machine_IP>
```

本地测试时推荐使用：

```json
"remote_machine_IP": "127.0.0.1"
```

同时确认用户名和密码可用于 SSH 密码登录。

### `root@127.0.0.1 Authentication failed`

本机通常不允许 root 密码 SSH 登录，且示例密码只是占位值。改用本机普通用户，并确保该用户能执行 Docker。

### `Swarm=inactive`

项目使用 `docker service create`，需要 Docker Swarm：

```bash
sudo docker swarm init
```

### `service constellation-test not found`

首次运行时没有旧 service，这是清理阶段的正常提示。通常可以忽略。

### `docker rm requires at least 1 argument`

首次运行时没有旧容器，`docker rm -f $(docker ps -a -q)` 参数为空。通常可以忽略。

### `*.txt: No such file or directory`

首次运行时没有旧输出文件。通常可以忽略。

### `Creating new containers...` 后卡住或 `0/27`

检查 Docker service：

```bash
docker service ls
docker service ps constellation-test --no-trunc
```

如果看到：

```text
No such image: lwsen/starlab_node:1.0
```

说明镜像未拉取成功。先解决 `docker pull lwsen/starlab_node:1.0`。

### 镜像源返回 `403 Forbidden`

例如：

```text
unexpected status from HEAD request ... 403 Forbidden
```

这说明当前 registry mirror 拒绝了该 manifest 请求，不一定代表 Docker Hub 原始镜像不存在。可以尝试：

```bash
docker pull lwsen/starlab_node:1.0
docker pull <another-mirror>/lwsen/starlab_node:1.0
```

如果通过代理拉到了不同镜像名，记得打回项目硬编码的 tag：

```bash
docker tag <another-mirror>/lwsen/starlab_node:1.0 lwsen/starlab_node:1.0
```

### 仿真结束后容器仍在

如果 `example.py` 被中断，`sn.stop_emulation()` 可能没有执行。运行：

```bash
python3 starrynet/clean.py
```

确认清理结果：

```bash
docker service ls
docker ps -a
```
