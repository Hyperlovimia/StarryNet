#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
Starrynet Cleanup
author: Yangtao Deng (dengyt21@mails.tsinghua.edu.cn)
"""
import subprocess


def _run_quietly(args):
    subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _starrynet_network_names():
    result = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return []

    prefixes = ("La", "Le", "GS")
    return [
        name for name in result.stdout.splitlines()
        if name.startswith(prefixes)
    ]


def _starrynet_container_ids():
    result = subprocess.run(
        [
            "docker", "ps", "-a", "--filter",
            "ancestor=lwsen/starlab_node:1.0", "--format", "{{.ID}}"
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return []

    return result.stdout.splitlines()


def cleanup():
    print("Deleting all native bridges and containers...")
    _run_quietly(["docker", "service", "rm", "constellation-test"])

    container_ids = _starrynet_container_ids()
    if container_ids:
        _run_quietly(["docker", "rm", "-f"] + container_ids)

    for network_name in _starrynet_network_names():
        print('docker network rm ' + network_name)
        _run_quietly(["docker", "network", "rm", network_name])


if __name__ == "__main__":
    cleanup()
