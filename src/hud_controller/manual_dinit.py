import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class ServiceError(RuntimeError):
    """Raised when a service fails to start."""

logger = logging.getLogger(__name__)

@dataclass
class Service:
    """Representation of a single service definition."""

    name: str
    type: str = "process"  # process | scripted | internal
    command: Optional[str] = None
    logfile: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)


class ServiceLoader:
    """Loads service definitions from a dinit-style directory."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.services: dict[str, Service] = {}

    # -------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------
    def load_all(self) -> dict[str, Service]:
        """Load every service definition found under *root_dir*."""
        logger.info("Loading service definitions from %s", self.root_dir)
        for svc_file in self.root_dir.iterdir():
            if svc_file.is_file():
                if svc_file.name.endswith(".sh"):
                    logger.debug("Skipping shell-script service file %s", svc_file.name)
                    continue
                logger.debug("Loading service file %s", svc_file.name)
                self._load_service_file(svc_file)
        return self.services

    # -------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------
    def _load_service_file(self, filepath: Path, *, explicit_name: Optional[str] = None) -> None:
        logger.debug("Parsing service definition file %s", filepath)
        name = explicit_name or filepath.name
        if name in self.services:
            # Already loaded – avoid duplicating effort or clobbering data.
            logger.debug("Service %s already loaded, skipping", name)
            return

        logger.debug("Registering service '%s' from file %s", name, filepath)
        raw_config = self._parse_config_file(filepath)
        logger.debug("Parsed config for %s: %s", name, raw_config)
        svc_type = raw_config.get("type", ["process"])[0]
        command = raw_config.get("command", [None])[-1]
        logfile = raw_config.get("logfile", [None])[-1]
        depends_on = list(raw_config.get("depends-on", []))  # copy
        # Handle the `waits-for` directive as additional dependencies
        for wf in raw_config.get("waits-for", []):
            logger.debug("Service %s declares waits-for dependency %s", name, wf)
            depends_on.append(wf)

        # Handle the special `waits-for.d` directive (only legal for type=internal)
        if svc_type.lower() == "internal" and "waits-for.d" in raw_config:
            waits_dir_rel = raw_config["waits-for.d"][-1]
            waits_dir = (self.root_dir / waits_dir_rel).resolve()
            if not waits_dir.is_dir():
                raise ServiceError(f"Service '{name}' references unknown directory '{waits_dir_rel}'.")
            logger.debug("Service %s is internal; scanning directory %s for dependencies", name, waits_dir)
            # Every file in the directory becomes an implicit dependency.
            for sub_file in waits_dir.iterdir():
                if sub_file.is_file():
                    if sub_file.name.endswith(".sh"):
                        logger.debug("Skipping shell-script in waits-for.d: %s", sub_file.name)
                        continue
                    logger.debug("Found internal dependency file %s for service %s", sub_file.name, name)
                    depends_on.append(sub_file.name)
                    self._load_service_file(sub_file)

        svc = Service(
            name=name,
            type=svc_type,
            command=command,
            logfile=logfile,
            depends_on=depends_on,
        )
        logger.info("Registered service %s (type=%s) with dependencies %s", name, svc_type, depends_on)
        self.services[name] = svc

        # Recursively load dependencies declared via `depends-on`.
        for dep_name in depends_on:
            logger.debug("Service %s declares dependency %s", name, dep_name)
            dep_path = self.root_dir / dep_name
            if not dep_path.exists():
                # Dependency might have already been loaded from a waits_for dir
                if dep_name not in self.services:
                    logger.error("Service '%s' depends on missing service '%s'", name, dep_name)
                    raise ServiceError(f"Service '{name}' depends on missing service '{dep_name}'.")
            elif dep_name not in self.services:
                logger.debug("Loading explicit dependency file %s for service %s", dep_path, name)
                self._load_service_file(dep_path)

        # Enforce that services which produce output define a logfile (requirement #2)
        if svc_type.lower() in {"process", "scripted"} and logfile is None:
            logger.error("Service '%s' of type '%s' has no logfile", name, svc_type)
            raise ServiceError(f"Service '{name}' of type '{svc_type}' must specify a logfile.")

    def _parse_config_file(self, path: Path) -> dict[str, list[str]]:
        """Parse a dinit service file into a *dict* of lists."""
        config: dict[str, list[str]] = {}
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                raise ServiceError(f"Malformed line in {path}: {line}")
            key = key.strip()
            value = value.strip()
            config.setdefault(key, []).append(value)
        return config


class SimpleDinit:
    """Very small subset of the behaviour of Dinit, just enough to start services."""

    def __init__(self, services: dict[str, Service]) -> None:
        self._services = services
        self._started: set[str] = set()
        self._starting: set[str] = set()
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    # -------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------
    def start(self, service_name: str) -> None:
        if service_name not in self._services:
            raise ServiceError(f"Unknown service '{service_name}'.")
        self._start_recursive(service_name)

    # -------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------
    def _start_recursive(self, name: str) -> None:
        if name in self._started:
            return  # Nothing to do.
        if name in self._starting:
            raise ServiceError(f"Circular dependency detected at '{name}'.")

        self._starting.add(name)
        svc = self._services[name]
        # Log dependency resolution
        logger.debug("Resolving dependencies for service '%s': %s", name, svc.depends_on)
        for dep in svc.depends_on:
            logger.debug("Service '%s' depends on '%s'; starting dependency", name, dep)
            self._start_recursive(dep)

        logger.info("Starting service '%s' (type=%s)...", name, svc.type)
        # Log dispatch decision before handling service type
        logger.debug("Dispatching service '%s' to handler for type '%s'", name, svc.type)
        if svc.type == "internal":
            # Nothing to launch – success if we reached this point.
            pass
        elif svc.type == "scripted":
            self._run_scripted(svc)
        elif svc.type == "process":
            self._run_process(svc)
        else:
            raise ServiceError(f"Service '{name}' has unknown type '{svc.type}'.")

        self._starting.remove(name)
        self._started.add(name)
        logger.info("Service '%s' started successfully.", name)

    def _ensure_logfile(self, logfile_path: str | None) -> Optional[Path]:
        if logfile_path is None:
            return None
        path = Path(logfile_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        except OSError as exc:
            # Fall back to current directory.
            logger.warning(
                "Unable to create log directory for '%s' (reason: %s). Falling back to local file.",
                logfile_path,
                exc,
            )
            return Path(f"{Path(logfile_path).name}")

    def _run_scripted(self, svc: Service) -> None:
        if svc.command is None:
            raise ServiceError(f"Scripted service '{svc.name}' lacks a command.")
        logfile = self._ensure_logfile(svc.logfile)
        if logfile is None:
            raise ServiceError(f"Scripted service '{svc.name}' missing logfile path.")
        stdout_dest = logfile.open("ab")
        try:
            result = subprocess.run(svc.command, shell=True, stdin=subprocess.DEVNULL, stdout=stdout_dest, stderr=subprocess.STDOUT)
        finally:
            stdout_dest.close()
        if result.returncode != 0:
            logger.error(
                "Service '%s' failed with exit code %s.", svc.name, result.returncode
            )
            raise ServiceError(f"Service '{svc.name}' failed with exit code {result.returncode}.")

    def _run_process(self, svc: Service) -> None:
        if svc.command is None:
            raise ServiceError(f"Process service '{svc.name}' lacks a command.")
        logfile = self._ensure_logfile(svc.logfile)
        if logfile is None:
            raise ServiceError(f"Process service '{svc.name}' missing logfile path.")
        stdout_dest = logfile.open("ab")
        try:
            proc = subprocess.Popen(
                svc.command,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=stdout_dest,
                stderr=subprocess.STDOUT,
            )
            self._processes[svc.name] = proc
            # pause for 0.5 seconds to ensure the process is running
            time.sleep(0.5)
        except Exception as exc:
            logger.error("Unable to launch service '%s': %s", svc.name, exc)
            raise ServiceError(f"Unable to launch service '{svc.name}': {exc}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiny subset of the Dinit service manager (start-only). Command-line entry mainly for testing.")
    parser.add_argument("service", nargs="?", default="boot", help="Service to start (default: boot)")
    parser.add_argument(
        "-d", "--directory", default="dinit.d", help="Directory containing service definitions (default: ./dinit.d)"
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    root = Path(args.directory).resolve()
    if not root.is_dir():
        logging.error("Directory '%s' does not exist or is not a directory.", root)
        sys.exit(1)

    loader = ServiceLoader(root)
    try:
        services = loader.load_all()
        engine = SimpleDinit(services)
        engine.start(args.service)
    except ServiceError as exc:
        logging.error("Error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main() 