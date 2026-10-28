#!/usr/bin/env python3
"""Run public tests and synthetic examples in an unprivileged Linux sandbox.

Requires bubblewrap and ldd. The host mounts only the Python runtime and the
repository's src/tests/examples directories, all read-only. No installation,
network download, sudo, Git metadata, or home directory access is needed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import sysconfig


_RUNNER = r'''
import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
if int(status["CapEff"].strip(), 16) != 0 or status["NoNewPrivs"].strip() != "1":
    raise SystemExit("Sandbox must have CapEff=0 and NoNewPrivs=1")
if os.readlink("/proc/self/ns/net") == sys.argv[1]:
    raise SystemExit("Sandbox must use a separate network namespace")
if Path("/home").exists() or Path("/root").exists() or Path("/workspace/.git").exists():
    raise SystemExit("Sandbox must not expose home directories or Git metadata")
if any(Path(p).exists() for p in ("/dev/dri", "/dev/nvidia0", "/dev/kfd")):
    raise SystemExit("Sandbox must not expose GPU devices")
print("Isolation verified: CapEff=0 NoNewPrivs=1; separate network; no home/.git/GPU", flush=True)
package_root = Path(sys.argv[2])
sys.path.insert(0, str(package_root))
package = importlib.import_module("http_range_tools")
if Path(package.__file__).resolve() != package_root / "http_range_tools" / "__init__.py":
    raise SystemExit("Package import did not come from the selected read-only mount")
print("Package origin:", package.__file__, flush=True)
suite = unittest.defaultTestLoader.discover("/workspace/tests", pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful() or result.testsRun == 0:
    raise SystemExit(1)
for example in sorted(Path("/workspace/examples").glob("*.py")):
    print("Example:", example.name, flush=True)
    runpy.run_path(str(example), run_name="__main__")
if package_root == Path("/workspace/package"):
    console = subprocess.run(
        [sys.executable, "-S", "-B", str(package_root / "bin/http-range-tools"),
         "--size", "12", "bytes=2-4,-2"],
        capture_output=True, text=True, timeout=10,
    )
    expected = {"size": 12, "ranges": [{"start": 2, "stop": 5, "length": 3},
                                       {"start": 10, "stop": 12, "length": 2}],
                "satisfiable": True, "unsatisfied_count": 0}
    if console.returncode != 0 or console.stderr or json.loads(console.stdout) != expected:
        raise SystemExit("Installed console-script smoke failed")
    print("Installed console script verified inside the sandbox", flush=True)
'''


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-package", type=Path, metavar="DIR",
                        help="fresh pip --target directory to test instead of src")
    options = parser.parse_args()
    if sys.platform != "linux":
        print("Offline sandbox checks require Linux and bubblewrap.", file=sys.stderr)
        return 2
    bwrap, ldd = shutil.which("bwrap"), shutil.which("ldd")
    if not bwrap or not ldd:
        print("Install bubblewrap and libc ldd to run isolated checks.", file=sys.stderr)
        return 2

    repo = Path(__file__).resolve().parent
    sources = {repo / name: Path("/workspace") / name for name in ("tests", "examples")}
    package_root = Path("/workspace/src")
    if options.installed_package is None:
        sources[repo / "src"] = package_root
    else:
        staged = options.installed_package.absolute()
        if staged.is_symlink() or not staged.is_dir():
            parser.error("--installed-package must name a real, fresh pip --target directory")
        staged = staged.resolve()
        if not (staged / "http_range_tools/__init__.py").is_file() or not (
            staged / "bin/http-range-tools"
        ).is_file():
            parser.error("staged package and generated console script are required")
        package_root = Path("/workspace/package")
        sources[staged] = package_root
    if any(not path.is_dir() or path.is_symlink() for path in sources):
        print("Expected real package, tests, and examples directories.", file=sys.stderr)
        return 2
    executable = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    dynload = Path(sysconfig.get_config_var("DESTSHARED") or stdlib / "lib-dynload").resolve()
    runtime = {executable: executable, stdlib: stdlib}
    if not dynload.is_relative_to(stdlib):
        runtime[dynload] = dynload
    binaries = [executable, *sorted(dynload.glob("*.so"))]
    dependencies = subprocess.run([ldd, *map(str, binaries)], check=False,
                                  capture_output=True, text=True, timeout=30)
    if dependencies.returncode != 0 or "not found" in dependencies.stdout:
        print("Could not resolve Python runtime shared libraries.", file=sys.stderr)
        return 2
    library_directories = set()
    for name in re.findall(r"(/[^\s()]+)", dependencies.stdout):
        path = Path(name)
        if path.is_file() and not any(path.is_relative_to(parent) for parent in (stdlib, dynload)):
            runtime[path] = path
            library_directories.add(str(path.parent))
    if any(str(path).startswith(("/home/", "/root/")) for path in runtime):
        print("Use a system Python runtime outside user home directories.", file=sys.stderr)
        return 2

    mounts = {**runtime, **sources}
    directories = {Path("/workspace"), Path("/tmp"), Path("/proc"), Path("/dev")}
    for destination in mounts.values():
        directories.update(parent for parent in destination.parents if parent != Path("/"))
    args = [bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL", "--clearenv"]
    for directory in sorted(directories, key=lambda path: (len(path.parts), str(path))):
        args.extend(["--dir", str(directory)])
    for source, destination in sorted(mounts.items(), key=lambda item: str(item[1])):
        args.extend(["--ro-bind", str(source), str(destination)])
    args.extend([
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--setenv", "PATH", str(executable.parent),
        "--setenv", "LD_LIBRARY_PATH", ":".join(sorted(library_directories)),
        "--setenv", "PYTHONPATH", str(package_root),
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "LC_ALL", "C.UTF-8", "--chdir", "/workspace",
        str(executable), "-I", "-S", "-B", "-c", _RUNNER,
        os.readlink("/proc/self/ns/net"), str(package_root),
    ])
    try:
        return subprocess.run(args, timeout=90, preexec_fn=_limits, check=False).returncode
    except subprocess.TimeoutExpired:
        print("Offline checks exceeded their 90-second limit.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
