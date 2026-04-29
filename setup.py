#!/usr/bin/env python3
"""Build and installation metadata for StarryNet."""

from pathlib import Path

from setuptools import Extension, find_packages, setup


ROOT = Path(__file__).resolve().parent
README = ROOT / "README.md"
REQUIREMENTS = ROOT / "tools" / "requirements.txt"


def read_requirements():
    requirements = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#"):
            continue
        requirements.append(requirement)
    return requirements


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
    python_requires=">=3.7",
    install_requires=read_requirements(),
    scripts=["bin/sn"],
    ext_modules=[
        Extension("pyctr", [str(ROOT / "starrynet" / "pyctr.c")]),
        Extension("pynetlink", [str(ROOT / "starrynet" / "pynetlink.c")]),
    ],
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
