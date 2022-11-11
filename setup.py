#!/usr/bin/env python3
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import os
import sys

try:
    from setuptools import setup, find_packages
except ImportError:
    print(
        "BuildStream requires setuptools in order to locate plugins. Install "
        "it using your package manager (usually python3-setuptools) or via "
        "pip (pip3 install setuptools)."
    )
    sys.exit(1)

###############################################################################
#                             Parse README                                    #
###############################################################################
with open(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "README.rst"),
    encoding="utf-8",
) as readme:
    long_description = readme.read()

###############################################################################
#                             Load the version                                #
###############################################################################
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from buildstream_plugins import __version__  # pylint: disable=wrong-import-position


setup(
    name="buildstream-plugins",
    version=__version__,
    author="The Apache Software Foundation",
    author_email="dev@buildstream.apache.org",
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Software Development :: Build Tools",
    ],
    description="A collection of plugins for BuildStream.",
    long_description=long_description,
    long_description_content_type="text/x-rst; charset=UTF-8",
    license="Apache License Version 2.0",
    url="https://buildstream.build",
    project_urls={
        "Documentation": "https://apache.github.io/buildstream-plugins/",
    },
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    entry_points={
        "buildstream.plugins.elements": [
            "autotools = buildstream_plugins.elements.autotools",
            "cmake = buildstream_plugins.elements.cmake",
            "make = buildstream_plugins.elements.make",
            "meson = buildstream_plugins.elements.meson",
            "pip = buildstream_plugins.elements.pip",
            "setuptools = buildstream_plugins.elements.setuptools",
        ],
        "buildstream.plugins.sources": [
            "bzr = buildstream_plugins.sources.bzr",
            "cargo = buildstream_plugins.sources.cargo",
            "docker = buildstream_plugins.sources.docker",
            "git = buildstream_plugins.sources.git",
            "patch = buildstream_plugins.sources.patch",
            "pip = buildstream_plugins.sources.pip",
            "zip = buildstream_plugins.sources.zip",
        ],
    },
    extras_require={
        "cargo": ['tomli; python_version < "3.11"'],
    },
    zip_safe=False,
)
# eof setup()
