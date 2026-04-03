import os
import json
import argparse
import paramiko
import numpy
import random

def sn_load_file(path):
    f = open(path, 'r', encoding='utf8')
    table = json.load(f)
    parser = argparse.ArgumentParser(description='manual to this script')
    parser.add_argument('--cons_name', type=str, default=table['Name'])
    parser.add_argument('--link_style', type=str, default=table['Satellite link'])
    parser.add_argument('--IP_version', type=str, default=table['IP version'])
    parser.add_argument('--link_policy', type=str, default=table['Link policy'])
    # link delay updating granularity
    parser.add_argument('--step',
                        type=int,
                        default=table['step (s)'])
    parser.add_argument('--duration', type=int, default=(table['Duration (s)'] if 'Duration (s)' in table else 0))
    parser.add_argument('--sat_bandwidth',
                        type=int,
                        default=table['satellite link bandwidth ("X" Gbps)'])
    parser.add_argument('--sat_ground_bandwidth',
                        type=int,
                        default=table['sat-ground bandwidth ("X" Gbps)'])
    parser.add_argument('--sat_loss',
                        type=int,
                        default=table['satellite link loss ("X"% )'])
    parser.add_argument('--sat_ground_loss',
                        type=int,
                        default=table['sat-ground loss ("X"% )'])
    parser.add_argument('--antenna_number',
                        type=int,
                        default=table['antenna number'])
    parser.add_argument('--antenna_elevation',
                        type=int,
                        default=table['antenna elevation angle'])
    # TODO: parser.add_argument('--handover', default=table["Handover policy"])
    # TODO: parser.add_argument('--time_slot', type=int, default=100)
    # TODO: parser.add_argument('--user_num', type=int, default=0)
    sn_args = parser.parse_args()
    sn_args.__setattr__('machine_lst', table['Machines'])
    shell_lst = table['Shells']
    for shell in shell_lst:
        # for compatibility
        update_keys = [
            ('Altitude (km)', 'altitude'), ('Inclination', 'inclination'),
            ('Phase shift', 'phase_shift'), ('Orbits', 'orbit'), ('Satellites per orbit', 'sat')]
        for key, new_key in update_keys:
            if key in shell:
                shell[new_key] = shell[key]
    sn_args.__setattr__('shell_lst', shell_lst)
    return sn_args

def sn_connect_remote(host, port, username, password):
    remote_ssh = paramiko.SSHClient()
    remote_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    remote_ssh.connect(hostname=host, port=port, username=username, password=password)
    return remote_ssh, remote_ssh.open_sftp()

def sn_remote_cmd(remote_ssh, cmd):
    return remote_ssh.exec_command(cmd)[1].read().decode().strip()

def sn_remote_wait_output(remote_ssh, cmd):
    for line in remote_ssh.exec_command(cmd, get_pty=True)[1]:
        print(line, end='')

