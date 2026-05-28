#!/usr/bin/env python3
"""Build and installation metadata for StarryNet."""

import sys
import shutil
import subprocess
from pathlib import Path

from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py


ROOT = Path(__file__).resolve().parent
README = ROOT / "README.md"
REQUIREMENTS = ROOT / "tools" / "requirements.txt"
STELLARNET = ROOT / "stellarnet"
STARRYNET_PACKAGE = ROOT / "starrynet"
BACKEND_LIBS = ("libpreload.so", "liblkl-posix.so")


def read_requirements():
    requirements = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#"):
            continue
        requirements.append(requirement)
    return requirements


def build_stellarnet_backend():
    if (STELLARNET / "Makefile").exists():
        if shutil.which("make") is None:
            raise RuntimeError("Building the StellarNet backend requires make.")
        subprocess.check_call(["make", "-C", str(STELLARNET)])
        for lib in BACKEND_LIBS:
            src = STELLARNET / lib
            dst = STARRYNET_PACKAGE / lib
            if not src.exists():
                raise RuntimeError(f"StellarNet build did not produce {src}")
            if dst.is_symlink():
                dst.unlink()
            shutil.copy2(src, dst)
        return

    if all((STARRYNET_PACKAGE / lib).exists() for lib in BACKEND_LIBS):
        return

    missing = ", ".join(BACKEND_LIBS)
    raise RuntimeError(
        "StellarNet backend sources are missing. "
        f"Expected {STELLARNET}/Makefile or prebuilt {missing} in "
        f"{STARRYNET_PACKAGE}."
    )


class BuildPyWithStellarNet(build_py):
    def run(self):
        build_stellarnet_backend()
        super().run()


class BuildExtWithStellarNet(build_ext):
    def run(self):
        build_stellarnet_backend()
        super().run()

if sys.platform != "linux":
    raise RuntimeError(
        f"This package only supports Linux. "
        f"Detected platform: {sys.platform}"
    )

setup(
    name="starrynet",
    version="1.0.0",
    description="StarryNet satellite-network emulator",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Yangtao Deng",
    author_email="dengyt21@mails.tsinghua.edu.cn",
    maintainer="Xin Xie",
    maintainer_email="xiex24@mails.tsinghua.edu.cn",
    url="https://github.com/SpaceNetLab/StarryNet",
    license="BSD",
    packages=find_packages(include=["starrynet", "starrynet.*"]),
    package_data={"starrynet": list(BACKEND_LIBS)},
    zip_safe=False,
    python_requires=">=3.7",
    install_requires=read_requirements(),
    scripts=["bin/sn", "bin/sn-worker"],
    cmdclass={
        "build_py": BuildPyWithStellarNet,
        "build_ext": BuildExtWithStellarNet,
    },
    ext_modules=[
        Extension("pyctr", [str(ROOT / "starrynet" / "pyctr.c")]),
    ],
    platforms=["Linux"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: System :: Emulators",
    ],
    keywords="satellite network emulator constellation protocol",
)
