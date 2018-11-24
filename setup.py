#!/usr/bin/env python3
"""
Set it up!!!!
"""

import re
from setuptools import setup


def version():
    """Thanks python!"""
    with open("mouselounge/_version.py") as filep:
        return re.search('__version__ = "(.+?)"', filep.read()).group(1)


def description():
    """Thanks python!"""
    with open("mouselounge/_version.py") as filep:
        return re.search('__desc__ = "(.+?)"', filep.read()).group(1)

setup(
    name="mouselounge",
    version=version(),
    description=description(),
    url="https://github.com/Szero/mouselounge",
    license="MIT",
    author="Szero",
    author_email="singleton@tfwno.gf",
    packages=['mouselounge', 'mouselounge.managers'],
    include_package_data=True,
    entry_points={"console_scripts": ["mouselounge = mouselounge.__main__:run"]},
    options={"build_scripts": {"executable": "/usr/bin/python3.7"}},
    classifiers=[
        "Development Status :: Beta",
        "Environment :: Console",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: Linux",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Utilities",
    ],
    install_requires=[l.strip() for l in open("requirements.txt").readlines()])
