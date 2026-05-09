#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
StarryNet: empowering researchers to evaluate futuristic integrated space and terrestrial networks.
author: Zeqi Lai (zeqilai@tsinghua.edu.cn) and Yangtao Deng (dengyt21@mails.tsinghua.edu.cn)
"""

from starrynet.sn_observer import *
from starrynet.sn_synchronizer import *

if __name__ == "__main__":
    # Starlink 5*5: 25 satellite nodes, 2 ground stations.
    # The node index sequence is: 25 sattelites, 2 ground stations.
    # In this example, 25 satellites and 2 ground stations are one AS.

    GS_lat_long = [[50.110924, 8.682127], [46.635700, 14.311817]
                   ]  # latitude and longitude of frankfurt and  Austria
    configuration_file_path = "./config.json"

    print('Start StarryNet.')
    sn = StarryNet(configuration_file_path, GS_lat_long)
    
    sn.create_nodes()
    sn.create_links()
  
    # LLA of a node at a certain time
    LLA = sn.get_position(node='SH1O1S1', t=2)
    print(f'\nLatitude, Longitude, Altitude of SH1O1S1: {LLA}')

    # distance between nodes at a certain time
    node_distance = sn.get_distance(node1='SH1O1S1', node2='SH1O1S2', t=2)
    print(f'\nSH1O1S1 - SH1O1S2 distance(km): {node_distance}')

    # neighbor nodes at a certain time
    neighbors = sn.get_neighbors(node='SH1O1S1', t=2)
    print(f'\nSH1O1S1 neighbors: {neighbors}')

    # GS connected to the node at a certain time
    GSes = sn.get_GSes(node='SH1O1S1', t=2)
    print(f"\nSH1O1S1 GSes: {GSes}")

    # CPU and memory useage
    sn.check_utility(t=2)

    # IP addresses of a node
    IPs = sn.get_IP(node='SH1O1S1')
    print(f'\nSH1O1S1 IP addresses: {IPs}')

    bird_conf_path = "./bird.conf"
    # run OSPF daemon on all nodes
    # sn.run_routing_daemon(bird_conf_path=bird_conf_path)
    # run OSPF daemon on selected nodes
    # sn.run_routing_daemon(bird_conf_path=bird_conf_path, node_lst=['GS0', 'SH1O2S2', 'SH1O2S3', 'SH1O3S3', 'GS1'])

    # set the next hop at a certain time.
    sn.set_static_route(src='SH1O1S1', dst='SH1O1S2', next_hop='SH1O1S2', t=2)

    # routing table of a node at a certain time.
    print(sn.check_routing_table(node='SH1O1S1', t=3))

    # ping msg of two nodes at a certain time.
    sn.set_ping(src='SH1O1S1', dst='SH1O1S2', t=4)

    # perf msg of two nodes at a certain time.
    sn.set_iperf(src='SH1O1S1', dst='SH1O1S2', t=5)

    # random damage of a given ratio at a certain time
    sn.set_damage(damaging_ratio=0.3, t=6)

    # recover the damages at a certain time
    sn.set_recovery(t=7)

    sn.start_emulation()

    if input('clear environment?[y/n]').strip().lower()[:1] == 'y':
        sn.clean()
