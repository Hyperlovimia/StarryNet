"""Interactive CLI for StarryNet."""

from cmd import Cmd
import shlex
import sys
import time

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

    def _stringify_cell(self, value):
        if value is None:
            return "-"
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value) if value else "-"
        if isinstance(value, dict):
            if not value:
                return "-"
            return ", ".join(f"{key}={val}" for key, val in value.items())
        return str(value)

    def _format_wall_time(self, value):
        if value is None:
            return "-"
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
        except (TypeError, ValueError, OSError):
            return str(value)

    def _render_table(self, headers, rows):
        if not rows:
            return ""

        rendered_rows = [
            [self._stringify_cell(cell) for cell in row]
            for row in rows
        ]
        widths = [
            max(len(str(header)), *(len(row[idx]) for row in rendered_rows))
            for idx, header in enumerate(headers)
        ]

        def build_row(values):
            return "| " + " | ".join(
                value.ljust(widths[idx]) for idx, value in enumerate(values)
            ) + " |"

        separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
        lines = [separator, build_row(headers), separator]
        lines.extend(build_row(row) for row in rendered_rows)
        lines.append(separator)
        return "\n".join(lines)

    def _render_kv_table(self, title, mapping):
        rows = [
            (key, value)
            for key, value in mapping.items()
            if value not in (None, "", [], {}, ())
        ]
        table = self._render_table(["Field", "Value"], rows)
        if not table:
            return f"{title}: <empty>"
        return f"{title}:\n{table}"

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
            "  check_utility TIME\n"
            "  check_routing_table NODE TIME\n"
            "  set_damage RATIO TIME\n"
            "  set_recovery TIME\n"
            "  set_static_route SRC DST NEXT_HOP TIME\n"
            "  set_ping SRC DST TIME\n"
            "  set_iperf SRC DST TIME\n"
            "  events\n"
            "  event EVENT_ID\n"
            "  event_result EVENT_ID\n"
            "  tasks [NODE]\n"
            "  task TASK_ID\n"
            "  task_output TASK_ID [NODE]\n"
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
            f"duration: {self.sn.duration}s\n"
            f"step: {self.sn.step}s\n"
            f"nodes: {len(self.sn.nodes)}\n"
            f"workers: {len(self.sn.worker_lst)}\n"
            f"events: {len(self.sn.list_events())}\n"
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
        output(f"{node1} <-> {node2} at {t} s: {distance:.2f} km\n")

    def do_get_neighbors(self, line):
        args = self._require_args(line, 2, "get_neighbors NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        neighbors = self.sn.get_neighbors(node=args[0], t=t)
        output(f"neighbors of {args[0]} at {t} s: {neighbors}\n")

    def do_get_GSes(self, line):
        args = self._require_args(line, 2, "get_GSes NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        gses = self.sn.get_GSes(node=args[0], t=t)
        output(f"connected ground stations of {args[0]} at {t} s: {gses}\n")

    def do_get_position(self, line):
        args = self._require_args(line, 2, "get_position NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        position = self.sn.get_position(node=args[0], t=t)
        output(f"position of {args[0]} at {t} s: {position}\n")

    def do_get_IP(self, line):
        args = self._require_args(line, 1, "get_IP NODE")
        if args is None or not self._check_node(args[0]):
            return
        ip_list = self.sn.get_IP(node=args[0])
        output(f"IPs of {args[0]}: {ip_list}\n")

    def do_check_utility(self, line):
        args = self._require_args(line, 1, "check_utility TIME")
        if args is None:
            return
        t = self._parse_int(args[0], "TIME")
        if t is None:
            return
        event_id = self.sn.check_utility(t=t)
        output(f"utility check scheduled: {event_id}\n")

    def do_set_damage(self, line):
        args = self._require_args(line, 2, "set_damage RATIO TIME")
        if args is None:
            return
        ratio = self._parse_float(args[0], "RATIO")
        t = self._parse_int(args[1], "TIME")
        if ratio is None or t is None:
            return
        event_id = self.sn.set_damage(damaging_ratio=ratio, t=t)
        output(f"damage event scheduled: {event_id}\n")

    def do_set_recovery(self, line):
        args = self._require_args(line, 1, "set_recovery TIME")
        if args is None:
            return
        t = self._parse_int(args[0], "TIME")
        if t is None:
            return
        event_id = self.sn.set_recovery(t=t)
        output(f"recovery event scheduled: {event_id}\n")

    def do_check_routing_table(self, line):
        args = self._require_args(line, 2, "check_routing_table NODE TIME")
        if args is None or not self._check_node(args[0]):
            return
        t = self._parse_int(args[1], "TIME")
        if t is None:
            return
        event_id = self.sn.check_routing_table(node=args[0], t=t)
        output(f"routing table dump scheduled: {event_id}\n")

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
        event_id = self.sn.set_static_route(src=src, dst=dst, next_hop=next_hop, t=t)
        output(f"static route scheduled: {event_id}\n")

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
        event_id = self.sn.set_ping(src=src, dst=dst, t=t)
        output(f"ping scheduled: {event_id}\n")

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
        event_id = self.sn.set_iperf(src=src, dst=dst, t=t)
        output(f"iperf scheduled: {event_id}\n")

    def do_set_perf(self, line):
        self.do_set_iperf(line)

    def do_events(self, _line):
        events = self.sn.list_events()
        if not events:
            output("No events.\n")
            return
        rows = [
            (
                item.get("event_id"),
                item.get("time"),
                item.get("type"),
                item.get("status"),
                item.get("result_mode"),
                item.get("params"),
            )
            for item in events
        ]
        output(self._render_table(["Event ID", "Time", "Type", "Status", "Result", "Params"], rows) + "\n")

    def do_event(self, line):
        args = self._require_args(line, 1, "event EVENT_ID")
        if args is None:
            return
        event = self.sn.get_event(args[0])
        if not event:
            output("Event not found.\n")
            return
        event_fields = {
            "event_id": event.get("event_id"),
            "time": event.get("time"),
            "type": event.get("type"),
            "status": event.get("status"),
            "result_mode": event.get("result_mode"),
            "params": event.get("params"),
            "created_at": self._format_wall_time(event.get("created_at")),
            "triggered_at": self._format_wall_time(event.get("triggered_at")),
            "finished_at": self._format_wall_time(event.get("finished_at")),
            "error": event.get("error"),
            "task_refs": event.get("task_refs"),
        }
        output(self._render_kv_table("Event", event_fields) + "\n")

    def do_event_result(self, line):
        args = self._require_args(line, 1, "event_result EVENT_ID")
        if args is None:
            return
        event = self.sn.get_event(args[0])
        if not event:
            output("Event not found.\n")
            return

        if event.get("error"):
            output(f"{event.get('error')}\n")
        else:
            output(f"{event.get('result', 'No result available.')}\n")

    def do_tasks(self, line):
        args = self._parse_args(line)
        node = args[0] if args else None
        if node is not None and not self._check_node(node):
            return
        tasks = self.sn.list_tasks(node=node)
        if not tasks:
            output("No tasks running.\n")
            return
        rows = [
            (
                task.get("task_id"),
                task.get("task_type"),
                task.get("node"),
                task.get("status"),
                task.get("output_file"),
                self._format_wall_time(task.get("scheduled_at")),
                self._format_wall_time(task.get("started_at")),
                self._format_wall_time(task.get("finished_at")),
            )
            for task in tasks
        ]
        output(
            self._render_table(
                ["Task ID", "Type", "Node", "Status", "Output", "Scheduled", "Started", "Finished"],
                rows,
            ) + "\n"
        )

    def do_task(self, line):
        args = self._require_args(line, 1, "task TASK_ID")
        if args is None:
            return
        task_id = args[0]
        task = self.sn.get_task(task_id)
        if not task:
            output("Task not found.\n")
            return
        task_fields = {
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "node": task.get("node"),
            "status": task.get("status"),
            "cmd": task.get("cmd"),
            "output_file": task.get("output_file"),
            "created_at": self._format_wall_time(task.get("created_at")),
            "scheduled_at": self._format_wall_time(task.get("scheduled_at")),
            "started_at": self._format_wall_time(task.get("started_at")),
            "finished_at": self._format_wall_time(task.get("finished_at")),
            "returncode": task.get("returncode"),
            "metadata": task.get("metadata"),
        }
        output(self._render_kv_table("Task", task_fields) + "\n")

    def do_task_output(self, line):
        args = self._require_at_least_args(line, 1, "task_output TASK_ID [NODE]")
        if args is None:
            return
        task_id = args[0]
        node = args[1] if len(args) > 1 else None
        if node is not None and not self._check_node(node):
            return
        result = self.sn.get_task_output(task_id, node=node)
        if not result:
            output("Task not found.\n")
            return
        output(result.get('output', '') + "\n")

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
