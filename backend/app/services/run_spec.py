"""Parsing helpers for the 'run a container from an image' form.

The UI takes free-text input (one entry per line) and these helpers turn it
into the keyword arguments docker-py expects. Every helper raises ValueError
with a message meant to be shown to the user as-is.
"""
import re

ALLOWED_PROTOCOLS = ("tcp", "udp", "sctp")
ALLOWED_RESTART_POLICIES = ("no", "always", "unless-stopped", "on-failure")


def split_lines(text: str | None) -> list[str]:
    """Split user input into entries, ignoring blank lines.

    Newlines always separate entries. Commas are only honoured by the port
    parser, where a comma can never be part of a value.
    """
    if not text:
        return []
    return [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]


def _port(value: str, raw: str) -> int:
    value = value.strip()
    if not value.isdigit():
        raise ValueError(f"端口必须是数字：{raw}")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"端口超出范围 (1-65535)：{raw}")
    return port


def parse_ports(text: str | None) -> dict:
    """Parse port mappings into docker-py's `ports` argument.

    Accepted forms (one per line, commas also allowed):
        8080:80              host 8080 -> container 80
        127.0.0.1:8080:80    bind to a specific host address
        80                   publish container port 80 on a random host port
        53:53/udp            explicit protocol (default tcp)
    """
    ports: dict = {}
    for line in split_lines(text):
        for raw in [p.strip() for p in line.split(",") if p.strip()]:
            spec, proto = raw, "tcp"
            if "/" in spec:
                spec, proto = spec.rsplit("/", 1)
                proto = proto.strip().lower()
                if proto not in ALLOWED_PROTOCOLS:
                    raise ValueError(f"端口协议只能是 {'/'.join(ALLOWED_PROTOCOLS)}：{raw}")

            parts = spec.split(":")
            if len(parts) == 1:
                key = f"{_port(parts[0], raw)}/{proto}"
                ports[key] = None  # publish on a random host port
            elif len(parts) == 2:
                host, container = _port(parts[0], raw), _port(parts[1], raw)
                ports[f"{container}/{proto}"] = host
            elif len(parts) == 3:
                ip = parts[0].strip()
                if not ip:
                    raise ValueError(f"绑定地址不能为空：{raw}")
                host, container = _port(parts[1], raw), _port(parts[2], raw)
                ports[f"{container}/{proto}"] = (ip, host)
            else:
                raise ValueError(f"端口映射格式应为 宿主机端口:容器端口：{raw}")
    return ports


def parse_env(text: str | None) -> list[str]:
    """Parse KEY=VALUE entries (one per line) into docker-py's `environment`."""
    out: list[str] = []
    for raw in split_lines(text):
        key, sep, value = raw.partition("=")
        key = key.strip()
        if not sep:
            raise ValueError(f"环境变量需要 KEY=VALUE 格式：{raw}")
        if not key:
            raise ValueError(f"环境变量名不能为空：{raw}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"环境变量名不合法（字母/数字/下划线，不能以数字开头）：{raw}")
        out.append(f"{key}={value}")
    return out


def parse_volumes(text: str | None) -> dict:
    """Parse 'host:container[:ro|rw]' entries into docker-py's `volumes`.

    A named volume works as the host side too, e.g. `app-data:/var/lib/data`.
    """
    volumes: dict = {}
    for raw in split_lines(text):
        parts = raw.split(":")
        # Keep a Windows drive letter attached to its path.
        if len(parts) > 1 and len(parts[0]) == 1 and parts[0].isalpha():
            parts = [f"{parts[0]}:{parts[1]}", *parts[2:]]

        mode = "rw"
        if len(parts) >= 2 and parts[-1].strip().lower() in ("ro", "rw"):
            mode = parts[-1].strip().lower()
            parts = parts[:-1]

        if len(parts) != 2:
            raise ValueError(f"挂载格式应为 宿主机路径:容器路径[:ro]：{raw}")

        host, container = parts[0].strip(), parts[1].strip()
        if not host or not container:
            raise ValueError(f"挂载路径不能为空：{raw}")
        if not container.startswith("/"):
            raise ValueError(f"容器内路径必须是绝对路径：{raw}")

        volumes[host] = {"bind": container, "mode": mode}
    return volumes


def parse_restart_policy(value: str | None) -> dict | None:
    """Validate a restart policy and render docker-py's `restart_policy`."""
    policy = (value or "").strip()
    if not policy:
        return None
    if policy not in ALLOWED_RESTART_POLICIES:
        raise ValueError(
            f"重启策略只能是 {'/'.join(ALLOWED_RESTART_POLICIES)}：{policy}"
        )
    return {"Name": policy}


def build_run_kwargs(
    image: str,
    name: str | None = None,
    ports: str | None = None,
    env: str | None = None,
    volumes: str | None = None,
    command: str | None = None,
    restart_policy: str | None = None,
) -> dict:
    """Assemble `containers.run()` / `containers.create()` keyword arguments."""
    image = (image or "").strip()
    if not image:
        raise ValueError("镜像不能为空")

    kwargs: dict = {"image": image}
    if name and name.strip():
        kwargs["name"] = name.strip()
    if command and command.strip():
        kwargs["command"] = command.strip()

    parsed_ports = parse_ports(ports)
    if parsed_ports:
        kwargs["ports"] = parsed_ports
    parsed_env = parse_env(env)
    if parsed_env:
        kwargs["environment"] = parsed_env
    parsed_volumes = parse_volumes(volumes)
    if parsed_volumes:
        kwargs["volumes"] = parsed_volumes
    policy = parse_restart_policy(restart_policy)
    if policy:
        kwargs["restart_policy"] = policy
    return kwargs
