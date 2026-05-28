# StarryNet

StarryNet is a satellite-network emulator for building constellation topologies, creating links between satellites and ground stations, and scheduling runtime events such as link/routing changes, ping, iperf, link damage, and recovery.

## Current Runtime Model

StarryNet no longer depends on Docker. It uses:

- Python code for topology generation and control
- a small CPython C extension for namespace/container orchestration
- remote StarryNet worker daemons described in `config.json`

If you are migrating from older documentation, ignore Docker-specific setup steps.

## Repository Layout

- `config.json`: sample topology and worker configuration
- `example.py`: Python API example
- `bin/sn`: interactive CLI entrypoint
- `bird.conf`: sample BIRD routing config
- `starrynet/`: library code

## Requirements

The exact system packages depend on your Linux distribution, but in practice you need:

- Python 3
- `pip`
- (Optional) [BIRD](https://bird.network.cz/)
- reachable worker machines matching the `Machines` section in `config.json` (`127.0.0.1` recommended for initial trials)

Python packages are listed in `tools/requirements.txt`.

If you install StarryNet from this source tree with `python3 setup.py install`, you also need:

- a C compiler such as `gcc`
- `make`
- Python development headers for compiling the `pyctr` and `pynetlink` extensions
- StellarNet backend sources under `./stellarnet`, which `setup.py` builds into `libpreload.so` and `liblkl-posix.so`

Those build dependencies are needed at install time, not for normal use after a successful install.

## Installation

### Quick install:

```bash
bash ./install.sh
```

### Manual install (recommended for explicit control):

1. Install system dependencies (Ubuntu example):

```bash
sudo apt update
sudo apt install python3 python3-pip python3-dev gcc make bird
```

2. (Optional) Create a Python virtual environment:

```bash
sudo apt install python3-venv
python3 -m venv sn-env
source sn-env/bin/activate
```

3. Install Python dependencies:

```bash
sudo python3 -m pip install -r tools/requirements.txt
```

4. Install the package and CLI:

```bash
sudo python3 setup.py install
```


## Quick Start

### 1. Start a worker daemon

Before running `example.py` or `sn`, start at least one worker daemon that matches the machine entry in `config.json`.

Example:

```bash
sudo sn-worker \
  --workdir test \
  --machine-id 0 \
  --ssh-username abc \
  --ssh-password 123456
```

Important details:

- `--ssh-username` and `--ssh-password` must match the `username` and `password` fields in `config.json`
- `--ssh-port` defaults to `18888`, which should match the `port` field in `config.json`
- `--workdir` is where the daemon writes logs, SSH host keys, and runtime artifacts
- for the sample `config.json`, `127.0.0.1:18888` is the expected local worker endpoint

You can inspect all daemon options with:

```bash
sn-worker --help
```

### 2. Update `config.json`

At minimum, review the `Machines` section:

```json
"Machines": [
  {
    "IP": "127.0.0.1",
    "port": 18888,
    "username": "abc",
    "password": "123456"
  }
]
```

Other commonly changed fields:

- `Shells`
- `Duration (s)`
- `step (s)`
- `satellite link bandwidth ("X" Gbps)`
- `sat-ground bandwidth ("X" Gbps)`
- `satellite link loss ("X"% )`
- `sat-ground loss ("X"% )`
- `antenna number`
- `antenna elevation angle`

### 3. Run the Python example

```bash
python3 example.py
```

The example:

- loads `./config.json`
- creates nodes and links
- queries topology state
- schedules ping, iperf, damage, recovery, and route dump events
- starts the emulation

The example uses node names such as `SH1O1S1` and `GS0`. This is the naming style used by the current API and CLI.

### 4. Run the interactive CLI

```bash
sn
```

Useful options:

```bash
sn --help
sn --path ./config.json
sn --gs 50.110924/8.682127/46.635700/14.311817
sn --bird-conf ./bird.conf
sn --clean
```

## CLI Workflow

Start with:

```text
starrynet> create_nodes
starrynet> create_links
starrynet> run_routing_daemon
starrynet> start_emulation
```

Useful inspection commands:

```text
starrynet> status
starrynet> nodes
starrynet> nodes SH1O1
starrynet> path
starrynet> get_distance SH1O1S1 SH1O1S2 2
starrynet> get_neighbors SH1O1S1 2
starrynet> get_GSes SH1O1S1 2
starrynet> get_position SH1O1S1 2
starrynet> get_IP SH1O1S1
```

Dynamic commands:

```text
starrynet> check_utility 2
starrynet> check_routing_table SH1O1S1 3
starrynet> set_static_route SH1O1S1 SH1O1S2 SH1O1S2 4
starrynet> set_ping SH1O1S1 SH1O1S2 5
starrynet> set_iperf SH1O1S1 SH1O1S2 6
starrynet> set_damage 0.3 7
starrynet> set_recovery 8
starrynet> events
starrynet> start_emulation
starrynet> tasks
starrynet> task w0-t1
starrynet> task_output w0-t1
```

Notes:

- `run_routing_daemon` uses `./bird.conf` by default.
- You may pass a different BIRD config path:

```text
starrynet> run_routing_daemon ./bird.conf
```

- You may restrict routing startup to selected nodes:

```text
starrynet> run_routing_daemon ./bird.conf GS0 SH1O1S1 SH1O1S2
```

- Event commands are queued first and executed when `start_emulation` advances to the target time.

## Python API Example

The current Python API looks like this:

```python
from starrynet.sn_synchronizer import StarryNet

gs_lat_long = [[50.110924, 8.682127], [46.635700, 14.311817]]
sn = StarryNet("./config.json", gs_lat_long)

sn.create_nodes()
sn.create_links()
sn.run_routing_daemon("./bird.conf")

print(sn.get_distance("SH1O1S1", "SH1O1S2", 2))
print(sn.get_neighbors("SH1O1S1", 2))
print(sn.get_GSes("SH1O1S1", 2))
print(sn.get_position("SH1O1S1", 2))
print(sn.get_IP("SH1O1S1"))

sn.set_ping("SH1O1S1", "SH1O1S2", 4)
sn.set_iperf("SH1O1S1", "SH1O1S2", 5)
sn.set_damage(0.3, 6)
sn.set_recovery(7)
sn.start_emulation()
sn.clean()
```

## Output

StarryNet writes generated files under a directory derived from the config location and experiment name, for example:

```text
./starlink-Grid-LeastDelay/
```

You can print the active output path in the CLI with:

```text
starrynet> path
```

## Known Gaps

- The project still contains some legacy files and names from older interfaces.
- The CLI is node-name based; older numeric examples are obsolete.
- Worker connectivity and host namespace permissions are not auto-validated yet.
