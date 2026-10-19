"""Build and verify the exact wheel/source pair without uploading anything."""

import argparse
import base64
import csv
import email.parser
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "headless_spreadsheets"
MODULES = {
    "__init__.py", "core.py", "errors.py", "file_io.py", "formats.py",
    "rendering.py", "serialization.py", "table.py", "py.typed",
}


def run(*arguments, cwd=ROOT):
    subprocess.run([str(value) for value in arguments], cwd=cwd, check=True)


def check_metadata(raw, project):
    message = email.parser.BytesParser().parsebytes(raw)
    for key, expected in (
        ("Name", "headless-spreadsheets"), ("Version", project["version"]),
        ("Requires-Python", ">=3.14"), ("Summary", project["description"]),
        ("Description-Content-Type", "text/markdown"),
        ("License-Expression", "MIT"), ("License-File", "LICENSE"),
    ):
        assert message.get_all(key) == [expected], (key, message.get_all(key))
    assert not message.get_all("Requires-Dist"), "Runtime dependencies are forbidden."
    assert message.get_payload(decode=True).decode("utf-8").strip() == (ROOT / "README.md").read_text(encoding="utf-8").strip()
    expected_urls = {f"{key}, {value}" for key, value in project["urls"].items()}
    assert set(message.get_all("Project-URL")) == expected_urls


def check_wheel(path, version, project):
    info = f"{PACKAGE}-{version}.dist-info"
    expected = {f"{PACKAGE}/{name}" for name in MODULES} | {
        f"{info}/{name}" for name in ("METADATA", "WHEEL", "RECORD", "licenses/LICENSE")
    }
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        assert len(entries) == len({item.filename for item in entries}), "Duplicate ZIP names."
        assert all(stat.S_IFMT(item.external_attr >> 16) != stat.S_IFLNK for item in entries), "ZIP links are forbidden."
        files = [item.filename for item in entries if not item.is_dir()]
        assert set(files) == expected, files
        content = {name: archive.read(name) for name in files}
    for name in MODULES:
        assert content[f"{PACKAGE}/{name}"] == (ROOT / "src" / PACKAGE / name).read_bytes(), name
    assert content[f"{info}/licenses/LICENSE"] == (ROOT / "LICENSE").read_bytes()
    check_metadata(content[f"{info}/METADATA"], project)
    wheel_metadata = email.parser.BytesParser().parsebytes(content[f"{info}/WHEEL"])
    assert wheel_metadata["Root-Is-Purelib"] == "true"
    assert wheel_metadata.get_all("Tag") == ["py3-none-any"]
    record = list(csv.reader(io.StringIO(content[f"{info}/RECORD"].decode())))
    assert len(record) == len(content) and {row[0] for row in record} == set(content)
    for name, digest, length in record:
        if name == f"{info}/RECORD":
            assert digest == length == ""
        else:
            expected_hash = base64.urlsafe_b64encode(hashlib.sha256(content[name]).digest()).rstrip(b"=").decode()
            assert digest == f"sha256={expected_hash}" and length == str(len(content[name])), name
    return content


def check_source(path, version, project, work):
    prefix = f"{PACKAGE}-{version}"
    expected = {f"{prefix}/src/{PACKAGE}/{name}" for name in MODULES} | {
        f"{prefix}/{name}" for name in ("pyproject.toml", "pyproject.toml.orig", "README.md", "LICENSE", "PKG-INFO")
    }
    with tarfile.open(path) as archive:
        entries = archive.getmembers()
        assert len(entries) == len({item.name for item in entries}), "Duplicate archive names."
        assert all(item.isfile() or item.isdir() for item in entries), "Archive links are forbidden."
        files = [item.name for item in entries if item.isfile()]
        assert set(files) == expected, files
        check_metadata(archive.extractfile(f"{prefix}/PKG-INFO").read(), project)
        for name in MODULES:
            assert archive.extractfile(f"{prefix}/src/{PACKAGE}/{name}").read() == (ROOT / "src" / PACKAGE / name).read_bytes(), name
        for name in ("README.md", "LICENSE"):
            assert archive.extractfile(f"{prefix}/{name}").read() == (ROOT / name).read_bytes()
        for name in ("pyproject.toml", "pyproject.toml.orig"):
            parsed = tomllib.loads(archive.extractfile(f"{prefix}/{name}").read().decode())
            assert parsed == tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        archive.extractall(work / "source", filter="data")
    return work / "source" / prefix


def check_installed(artifact, work, label, version):
    environment = work / label
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run("uv", "pip", "install", "--python", python, "--no-deps", artifact, cwd=work)
    probe = (
        "import importlib.metadata as m, pathlib, sys, headless_spreadsheets as h; "
        f"assert m.version('headless-spreadsheets') == h.__version__ == {version!r}; "
        "assert not m.requires('headless-spreadsheets'); "
        "assert pathlib.Path(h.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()); "
        "assert pathlib.Path(h.__file__).with_name('py.typed').is_file(); "
        "assert not any(name in sys.modules for name in ('pandas', 'numpy', 'openpyxl', 'pretty_notebook'))"
    )
    run(python, "-I", "-c", probe, cwd=work)
    run(python, "-I", "-W", "error::ResourceWarning", "-m", "unittest", "discover", "-s", work / "tests", "-q", cwd=work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    assert project["dependencies"] == []
    assert project["license"] == "MIT"
    if args.tag and args.tag != f"v{version}":
        parser.error("Tag does not match the project version.")
    if args.output_dir and args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Output directory must be new or empty.")
    with tempfile.TemporaryDirectory(prefix="headless-spreadsheets-distribution-") as directory:
        work = Path(directory)
        artifacts = work / "artifacts"
        run("uv", "build", "--no-sources", "--no-create-gitignore", "--out-dir", artifacts)
        wheel = artifacts / f"{PACKAGE}-{version}-py3-none-any.whl"
        source = artifacts / f"{PACKAGE}-{version}.tar.gz"
        assert {item.name for item in artifacts.iterdir() if item.is_file()} == {wheel.name, source.name}
        original = check_wheel(wheel, version, project)
        source_root = check_source(source, version, project, work)
        rebuilt = work / "rebuilt"
        run("uv", "build", "--wheel", "--no-sources", "--no-create-gitignore", "--out-dir", rebuilt, source_root)
        assert check_wheel(rebuilt / wheel.name, version, project) == original, "Source rebuild differs."
        for name in ("tests", "examples"):
            shutil.copytree(ROOT / name, work / name, ignore=shutil.ignore_patterns("__pycache__"))
        check_installed(wheel, work, "wheel-install", version)
        check_installed(source, work, "source-install", version)
        receipts = {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in (wheel, source)}
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for item in (wheel, source):
                shutil.copy2(item, args.output_dir / item.name)
        print(json.dumps({"version": version, "sha256": receipts}, indent=2))


if __name__ == "__main__":
    main()
