"""Generate the Homebrew formula for orchestra-cli.

The formula is pinned to a published PyPI release and vendors every runtime
dependency as a Homebrew ``resource`` block, because Homebrew builds Python
formulae in a network-isolated sandbox.

Dependencies listed in :data:`WHEEL_PACKAGES` are pinned to prebuilt wheels
rather than source distributions. Only ``pydantic-core`` needs this: it is a
Rust extension module, and building it from source would force every user to
download a Rust toolchain. Everything else is installed from an sdist, which is
what Homebrew expects.

Usage:
    uv run python scripts/generate_brew_formula.py --output Formula/orchestra-cli.rb
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
import urllib.request
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

PYPI_URL = "https://pypi.org/pypi/{name}/{version}/json"
PROJECT_NAME = "orchestra-cli"

# Bounded so that a PyPI connection which opens but never responds fails the
# release job instead of hanging it.
PYPI_TIMEOUT_SECONDS = 30

# The Python that the formula builds against. PYTHON_TAG must be the CPython
# interpreter tag matching PYTHON_FORMULA, since wheels are selected by it.
PYTHON_FORMULA = "python@3.13"
PYTHON_TAG = "cp313"
PYTHON_BINARY = "python3.13"

# Packages installed from prebuilt wheels instead of source. Add a package here
# when compiling it from source would require a toolchain we do not want to
# make users install.
WHEEL_PACKAGES = frozenset({"pydantic-core"})

# Environment markers from `uv export` that never apply to a Homebrew install.
# Anything not listed here raises, so a new marker fails the build loudly rather
# than silently dropping or including a dependency.
IGNORED_MARKERS = frozenset(
    {
        "sys_platform == 'win32'",
        "python_full_version < '3.11'",
    },
)


@dataclass(frozen=True)
class WheelTarget:
    """A platform Homebrew can install on, and the wheel tags that serve it."""

    os_block: str
    arch_block: str
    platform_glob: str


WHEEL_TARGETS = (
    WheelTarget("on_macos", "on_arm", "macosx_*_arm64"),
    WheelTarget("on_macos", "on_intel", "macosx_*_x86_64"),
    WheelTarget("on_linux", "on_arm", "manylinux*_aarch64*"),
    WheelTarget("on_linux", "on_intel", "manylinux*_x86_64*"),
)


@dataclass(frozen=True)
class Download:
    """A single downloadable artefact on PyPI."""

    url: str
    sha256: str


def read_project_version(project_root: Path) -> str:
    """Return the version declared in pyproject.toml."""
    # Read pyproject.toml directly rather than shelling out to `uv version`,
    # which only reports the project version on uv >= 0.7 and reports uv's own
    # version before that.
    data = tomllib.loads((project_root / "pyproject.toml").read_text())
    return data["project"]["version"]


def resolve_runtime_dependencies(project_root: Path) -> dict[str, str]:
    """Return the locked runtime dependency closure as ``{name: version}``.

    Reads `uv.lock` via `uv export` so the formula always matches the versions
    the project is actually tested against.
    """
    result = subprocess.run(
        ["uv", "export", "--no-dev", "--no-emit-project", "--no-hashes"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )

    dependencies: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        requirement, _, marker = line.partition(";")
        marker = marker.strip()
        if marker:
            if marker not in IGNORED_MARKERS:
                raise ValueError(
                    f"Unrecognised environment marker {marker!r} on {requirement.strip()!r}. "
                    f"Add it to IGNORED_MARKERS if it never applies to a Homebrew install, "
                    f"otherwise handle it explicitly.",
                )
            continue

        name, _, version = requirement.strip().partition("==")
        if not version:
            raise ValueError(f"Expected a pinned requirement, got {line!r}")
        dependencies[name] = version

    return dependencies


def fetch_pypi_files(name: str, version: str) -> list[dict]:
    """Return the PyPI file listing for one release."""
    url = PYPI_URL.format(name=name, version=version)
    with urllib.request.urlopen(url, timeout=PYPI_TIMEOUT_SECONDS) as response:
        return json.load(response)["urls"]


def select_sdist(name: str, version: str, files: list[dict]) -> Download:
    """Return the source distribution for a release."""
    for entry in files:
        if entry["packagetype"] == "sdist":
            return Download(entry["url"], entry["digests"]["sha256"])
    raise ValueError(f"No sdist published for {name} {version}")


def select_wheels(name: str, version: str, files: list[dict]) -> dict[WheelTarget, Download]:
    """Return one wheel per supported platform.

    Prefers a wheel built for :data:`PYTHON_TAG` exactly, falling back to a
    stable-ABI (``abi3``) wheel where a package publishes one.
    """
    wheels: dict[WheelTarget, Download] = {}
    for target in WHEEL_TARGETS:
        candidates = [
            entry
            for entry in files
            if entry["packagetype"] == "bdist_wheel"
            and _matches_platform(entry["filename"], target.platform_glob)
            and _matches_interpreter(entry["filename"])
        ]
        if not candidates:
            raise ValueError(
                f"No {PYTHON_TAG} wheel for {name} {version} matching "
                f"{target.platform_glob!r}. Remove it from WHEEL_PACKAGES to build "
                f"it from source instead.",
            )
        chosen = sorted(candidates, key=lambda entry: _wheel_preference(entry["filename"]))[0]
        wheels[target] = Download(chosen["url"], chosen["digests"]["sha256"])

    return wheels


def _wheel_tags(filename: str) -> tuple[str, str, str]:
    """Return the (interpreter, abi, platform) tags of a wheel filename."""
    parts = filename.removesuffix(".whl").split("-")
    return parts[-3], parts[-2], parts[-1]


def _platform_baseline(platform_tag: str) -> tuple[int, int]:
    """Return the minimum OS version a platform tag requires.

    ``macosx_10_12_x86_64`` is (10, 12) and ``manylinux_2_17_aarch64`` is the
    glibc version (2, 17). A wheel may carry several compatible tags joined by
    dots, as in ``manylinux_2_17_x86_64.manylinux2014_x86_64``; the lowest
    baseline among them is what the wheel actually requires.

    An unrecognised tag returns (0, 0) so it sorts as most compatible, which
    keeps selection working rather than discarding the wheel.
    """
    baselines = [_component_baseline(part) for part in platform_tag.split(".")]
    return min(baselines)


def _component_baseline(component: str) -> tuple[int, int]:
    """Return the OS baseline of a single platform tag component."""
    # The pre-PEP 600 spellings name a policy rather than a glibc version.
    legacy_glibc = {"manylinux1": (2, 5), "manylinux2010": (2, 12), "manylinux2014": (2, 17)}
    for name, baseline in legacy_glibc.items():
        if component.startswith(name):
            return baseline

    match = re.match(r"(?:macosx|manylinux|musllinux)_(\d+)_(\d+)", component)
    if match is None:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _wheel_preference(filename: str) -> tuple[int, tuple[int, int], str]:
    """Return a sort key ranking wheels best-first.

    An exact-interpreter wheel beats a stable-ABI one, and among equals the
    lowest OS baseline wins because it runs on the widest range of machines.
    The filename breaks any remaining tie so runs stay deterministic.
    """
    _, abi_tag, platform_tag = _wheel_tags(filename)
    return (1 if abi_tag == "abi3" else 0), _platform_baseline(platform_tag), filename


def _matches_platform(filename: str, platform_glob: str) -> bool:
    _, _, platform_tag = _wheel_tags(filename)
    return fnmatch(platform_tag, platform_glob)


def _cpython_version(interpreter_tag: str) -> tuple[int, int] | None:
    """Return the (major, minor) version of a CPython tag such as ``cp313``.

    The tag concatenates major and minor without a separator, so the first
    digit is the major version and the remainder is the minor: ``cp39`` is 3.9
    and ``cp313`` is 3.13. Returns None for non-CPython tags such as ``py3``.
    """
    if not interpreter_tag.startswith("cp"):
        return None
    digits = interpreter_tag.removeprefix("cp")
    if not digits.isdigit():
        return None
    return int(digits[0]), int(digits[1:])


def _matches_interpreter(filename: str) -> bool:
    interpreter_tag, abi_tag, _ = _wheel_tags(filename)
    if abi_tag == "abi3":
        # A stable-ABI wheel works on its own version and every later one.
        wheel_version = _cpython_version(interpreter_tag)
        target_version = _cpython_version(PYTHON_TAG)
        return (
            wheel_version is not None
            and target_version is not None
            and wheel_version <= target_version
        )
    return interpreter_tag == PYTHON_TAG and abi_tag == PYTHON_TAG


def ruby_class_name(name: str) -> str:
    """Convert a formula name to its Ruby class name, as Homebrew expects."""
    return "".join(part.capitalize() for part in name.replace("_", "-").split("-"))


def render_simple_resource(name: str, download: Download) -> str:
    return (
        f'  resource "{name}" do\n'
        f'    url "{download.url}"\n'
        f'    sha256 "{download.sha256}"\n'
        f"  end\n"
    )


def render_wheel_resource(name: str, wheels: dict[WheelTarget, Download]) -> str:
    """Render a resource whose URL varies by OS and CPU architecture."""
    lines = [f'  resource "{name}" do']
    for os_block in ("on_macos", "on_linux"):
        lines.append(f"    {os_block} do")
        for target in WHEEL_TARGETS:
            if target.os_block != os_block:
                continue
            download = wheels[target]
            lines.append(f"      {target.arch_block} do")
            lines.append(f'        url "{download.url}", using: :nounzip')
            lines.append(f'        sha256 "{download.sha256}"')
            lines.append("      end")
        lines.append("    end")
    lines.append("  end\n")
    return "\n".join(lines)


def render_formula(version: str, dependencies: dict[str, str]) -> str:
    """Render the complete formula source."""
    project_files = fetch_pypi_files(PROJECT_NAME, version)
    project_sdist = select_sdist(PROJECT_NAME, version, project_files)

    resources: list[str] = []
    for name in sorted(dependencies):
        dependency_version = dependencies[name]
        files = fetch_pypi_files(name, dependency_version)
        if name in WHEEL_PACKAGES:
            wheels = select_wheels(name, dependency_version, files)
            resources.append(render_wheel_resource(name, wheels))
        else:
            sdist = select_sdist(name, dependency_version, files)
            resources.append(render_simple_resource(name, sdist))

    wheel_names = sorted(WHEEL_PACKAGES & dependencies.keys())
    wheel_reject = " || ".join(f'r.name == "{name}"' for name in wheel_names)
    wheel_installs = "\n".join(
        f'    resource("{name}").stage do\n'
        f'      venv.pip_install Pathname.pwd/Dir["*.whl"].fetch(0)\n'
        f"    end"
        for name in wheel_names
    )

    return f"""# This file is generated by scripts/generate_brew_formula.py in
# orchestra-hq/orchestra-cli. Do not edit it by hand.
class {ruby_class_name(PROJECT_NAME)} < Formula
  include Language::Python::Virtualenv

  desc "Command-line tool for working with Orchestra pipelines"
  homepage "https://github.com/orchestra-hq/orchestra-cli"
  url "{project_sdist.url}"
  sha256 "{project_sdist.sha256}"

  depends_on "{PYTHON_FORMULA}"

{chr(10).join(resources)}
  # Homebrew's default pip arguments include --no-binary=:all:, which would
  # reject the prebuilt wheels above. ":none:" lifts that restriction; every
  # other resource is still a source distribution.
  def std_pip_args(prefix: self.prefix, build_isolation: false)
    super.map {{ |arg| (arg == "--no-binary=:all:") ? "--no-binary=:none:" : arg }}
  end

  def install
    venv = virtualenv_create(libexec, "{PYTHON_BINARY}")

    # Homebrew only resolves the filename of pure-Python wheel resources, so
    # platform-specific wheels have to be staged and installed by path.
{wheel_installs}

    venv.pip_install resources.reject {{ |r| {wheel_reject} }}
    venv.pip_install_and_link buildpath
  end

  test do
    assert_match "pipeline", shell_output("#{{bin}}/orchestra --help")
    assert_match "pipeline", shell_output("#{{bin}}/orchestra-cli --help")
  end
end
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the formula to.",
    )
    parser.add_argument(
        "--version",
        help="Release to pin. Defaults to the version in pyproject.toml.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    version = args.version or read_project_version(project_root)
    dependencies = resolve_runtime_dependencies(project_root)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_formula(version, dependencies))
    print(f"Wrote {args.output} for {PROJECT_NAME} {version}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
