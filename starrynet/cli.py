"""Interactive CLI for StarryNet."""

from cmd import Cmd
import shlex
import sys

from .log import error, info, output


class CLI(Cmd):
    """Simple command-line interface for StarryNet."""

    prompt = "starrynet> "

    def __init__(self, starrynet, default_bird_conf="./bird.conf",
                 stdin=sys.stdin, *args, **kwargs):
        self.sn = starrynet
        self.default_bird_conf = default_bird_conf
        super().__init__(*args, stdin=stdin, **kwargs)
        info("*** Starting CLI. Type 'help' for commands.\n")
        self.run()

    def run(self):
        while True:
            try:
                self.cmdloop()
                break
            except KeyboardInterrupt:
                output("\nInterrupt\n")

    def emptyline(self):
        pass

    def _parse_args(self, line):
        return shlex.split(line)

    def _require_args(self, line, expected, usage):
        args = self._parse_args(line)
        if len(args) != expected:
            error(f"usage: {usage}\n")
            return None
        return args

    def _require_at_least_args(self, line, minimum, usage):
        args = self._parse_args(line)
        if len(args) < minimum:
            error(f"usage: {usage}\n")
            return None
        return args

    def _parse_int(self, value, name):
        try:
            return int(value)
        except ValueError:
            error(f"{name} must be an integer: {value}\n")
            return None

    def _parse_float(self, value, name):
        try:
            return float(value)
        except ValueError:
            error(f"{name} must be a number: {value}\n")
            return None

    def _check_node(self, node):
        if node not in self.sn.nodes:
            error(f"unknown node: {node}\n")
            return False
        return True

    def do_help(self, line):
        if line:
            return super().do_help(line)
        output(
            "Common workflow:\n"
            "  create_nodes\n"
            "  create_links\n"
            "  run_routing_daemon [bird.conf] [node1 node2 ...]\n"
            "  start_emulation\n\n"
            "Useful commands:\n"
            "  status\n"
            "  nodes [prefix]\n"
            "  path\n"
            "  get_distance NODE1 NODE2 TIME\n"
            "  get_neighbors NODE TIME\n"
            "  get_GSes NODE TIME\n"
            "  get_position NODE TIME\n"
            "  get_IP NODE\n"
            "  get_utility TIME\n"
            "  set_damage RATIO TIME\n"
            "  set_recovery TIME\n"
            "  check_routing_table NODE TIME\n"
            "  set_static_route SRC DST NEXT_HOP TIME\n"
            "  set_ping SRC DST TIME\n"
            "  set_iperf SRC DST TIME\n"
            "  clean\n"
            "  exit\n\n"
            "Notes:\n"
            "  NODE values use names such as SH1O1S1 or GS0.\n"
            "  Scheduled commands run when start_emulation is executed.\n"
        )

    def do_status(self, _line):
        output(
            f"experiment: {self.sn.experiment_name}\n"
            f"config dir: {self.sn.configuration_dir}\n"
            f"output dir: {self.sn.local_dir}\n"
            f"duration: {self.sn.duration}s\n"
            f"step: {self.sn.step}s\n"
            f"nodes: {len(self.sn.nodes)}\n"
            f"workers: {len(self.sn.worker_lst)}\n"
            f"queued events: {len(self.sn.events)}\n"
        )

    def do_nodes(self, line):
        args = self._parse_args(line)
        prefix = args[0] if args else ""
        nodes = sorted(name for name in self.sn.nodes if name.startswith(prefix))
        if not nodes:
            output("No nodes matched.\n")
            return
        output("\n".join(nodes) + "\n")

    def do_create_nodes(self, _line):
        self.sn.create_nodes()

    def do_create_links(self, _line):
        self.sn.create_links()

    def do_run_routing_daemon(self, line):
        args = self._parse_args(line)
        bird_conf_path = args[0] if args else self.default_bird_conf
        node_lst = args[1:] if len(args) > 1 else "all"
        self.sn.run_routing_daemon(bird_conf_path=bird_conf_path,
                                   node_lst=node_lst)

    def do_run_routing_deamon(self, line):
        self.do_run_routing_daemon(line)

    def do_get_distance(self, line):
        args = self._require_args(
            line, 3, "get_distance NODE1 NODE2 TIME")
        if args is None:
            return
        node1, node2 = args[0], args[1]
        if not self._check_node(node1) or not self._check_node(node2):
            return
        t = self._parse_int(args[2], "TIME")
        if t is None:
            return
        distance = self.sn.get_distance(node1=node1, node2=node2, t=t)
        output(f"{node1} <-> {node2}: {distance:.2f} km\n")

    def do_get_neighbors(self, line):
        args = self._require_args(line, 2, "get_neighbors NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        neighbors = self.sn.get_neighbors(node=args[0], t=t)
        output(f"neighbors: {neighbors}\n")

    def do_get_GSes(self, line):
        args = self._require_args(line, 2, "get_GSes NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        gses = self.sn.get_GSes(node=args[0], t=t)
        output(f"ground stations: {gses}\n")

    def do_get_position(self, line):
        args = self._require_args(line, 2, "get_position NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        position = self.sn.get_position(node=args[0], t=t)
        output(f"position: {position}\n")

    def do_get_IP(self, line):
        args = self._require_args(line, 1, "get_IP NODE")
        if args is None or not self._check_node(args[0]):
            return
        ip_list = self.sn.get_IP(node=args[0])
        output(f"IPs: {ip_list}\n")

    def do_get_utility(self, line):
        args = self._require_args(line, 1, "get_utility TIME")
        if args is None:
            return
        t = self._parse_int(args[0], "TIME")
        if t is None:
            return
        self.sn.get_utility(t=t)
        output("utility check scheduled.\n")

    def do_set_damage(self, line):
        args = self._require_args(line, 2, "set_damage RATIO TIME")
        if args is None:
            return
        ratio = self._parse_float(args[0], "RATIO")
        t = self._parse_int(args[1], "TIME")
        if ratio is None or t is None:
            return
        self.sn.set_damage(damaging_ratio=ratio, t=t)
        output("damage event scheduled.\n")

    def do_set_recovery(self, line):
        args = self._require_args(line, 1, "set_recovery TIME")
        if args is None:
            return
        t = self._parse_int(args[0], "TIME")
        if t is None:
            return
        self.sn.set_recovery(t=t)
        output("recovery event scheduled.\n")

    def do_check_routing_table(self, line):
        args = self._require_args(line, 2, "check_routing_table NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        self.sn.check_routing_table(node=args[0], t=t)
        output("routing table dump scheduled.\n")

    def do_set_static_route(self, line):
        args = self._require_args(
            line, 4, "set_static_route SRC DST NEXT_HOP TIME")
        if args is None:
            return
        src, dst, next_hop = args[:3]
        if not all(self._check_node(node) for node in [src, dst, next_hop]):
            return
        t = self._parse_int(args[3], "TIME")
        if t is None:
            return
        self.sn.set_static_route(src=src, dst=dst, next_hop=next_hop, t=t)
        output("static route scheduled.\n")

    def do_set_next_hop(self, line):
        self.do_set_static_route(line)

    def do_set_ping(self, line):
        args = self._require_args(line, 3, "set_ping SRC DST TIME")
        if args is None:
            return
        src, dst = args[:2]
        if not self._check_node(src) or not self._check_node(dst):
            return
        t = self._parse_int(args[2], "TIME")
        if t is None:
            return
        self.sn.set_ping(src=src, dst=dst, t=t)
        output("ping scheduled.\n")

    def do_set_iperf(self, line):
        args = self._require_args(line, 3, "set_iperf SRC DST TIME")
        if args is None:
            return
        src, dst = args[:2]
        if not self._check_node(src) or not self._check_node(dst):
            return
        t = self._parse_int(args[2], "TIME")
        if t is None:
            return
        self.sn.set_iperf(src=src, dst=dst, t=t)
        output("iperf scheduled.\n")

    def do_set_perf(self, line):
        self.do_set_iperf(line)

    def do_start_emulation(self, _line):
        self.sn.start_emulation()

    def do_clean(self, _line):
        self.sn.clean()

    def do_path(self, _line):
        output(self.sn.local_dir + "\n")

    def do_stop_emulation(self, _line):
        self.sn.clean()
        return "exited by user command"

    def do_exit(self, _line):
        return "exited by user command"

    def do_quit(self, line):
        return self.do_exit(line)

    def do_EOF(self, line):
        output("\n")
        return self.do_exit(line)

    def default(self, line):
        error(f"*** Unknown command: {line}\n")
