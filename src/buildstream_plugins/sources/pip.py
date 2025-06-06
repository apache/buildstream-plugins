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
#  Authors:
#        Chandan Singh <csingh43@bloomberg.net>

#
# This plugin was originally developped in the https://github.com/apache/buildstream/
# repository and was copied from 1a3c707a6c46573ab159de64ac9cd92e7f6027e6
#

"""
pip - stage python packages using pip
=====================================

**Host depndencies:**

  * ``pip`` python module

This plugin will download source distributions for specified packages using
``pip`` but will not install them. It is expected that the elements using this
source will install the downloaded packages.

Downloaded tarballs will be stored in a directory called ".bst_pip_downloads".

**Usage:**

.. code:: yaml

   # Specify the pip source kind
   kind: pip

   # Optionally specify index url, defaults to PyPi
   # This url is used to discover new versions of packages and download them
   # Projects intending to mirror their sources to a permanent location should
   # use an aliased url, and declare the alias in the project configuration
   url: https://mypypi.example.com/simple

   # Optionally specify the path to requirements files
   # Note that either 'requirements-files' or 'packages' must be defined
   requirements-files:
   - requirements.txt

   # Optionally specify a list of additional packages
   # Note that either 'requirements-files' or 'packages' must be defined
   packages:
   - flake8

   # Specify the ref. It is a list of strings of format
   # "<package-name>==<version>", separated by "\\n".
   # Usually this will be contents of a requirements.txt file where all
   # package versions have been frozen.
   ref: "flake8==3.5.0\\nmccabe==0.6.1\\npkg-resources==0.0.0\\npycodestyle==2.3.1\\npyflakes==1.6.0"

See `built-in functionality doumentation
<https://docs.buildstream.build/master/buildstream.source.html#core-source-builtins>`_ for
details on common configuration options for sources.


Reporting `SourceInfo <https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceInfo>`_
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The pip source reports the python package index (PyPI) instance as the *url*.

Further, the pip source reports the `SourceInfoMedium.PYTHON_PACKAGE_INDEX
<https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceInfoMedium.PYTHON_PACKAGE_INDEX>`_
*medium* and the `SourceVersionType.INDEXED_VERSION
<https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceVersionType.INDEXED_VERSION>`_
*version_type*, for which it reports the tracked package version as the *version* and the *version_guess*.

Additionally, the pip source reports the package name through
the ``package-name`` key of the *extra_data*.

The pip source will report one SourceInfo instance for each of the packages discovered in tracking.
"""

import hashlib
import os
import re

from buildstream import Source, SourceError
from buildstream import utils

#
# Soft import of buildstream symbols only available in newer versions
#
# The BST_MIN_VERSION will provide a better user experience.
#
try:
    from buildstream import SourceInfoMedium, SourceVersionType
except ImportError:
    pass

_OUTPUT_DIRNAME = ".bst_pip_downloads"
_PYPI_INDEX_URL = "https://pypi.org/simple/"

# Used only for finding pip command
_PYTHON_VERSIONS = [
    "python",  # when running in a venv, we might not have the exact version
    "python2.7",
    "python3.0",
    "python3.1",
    "python3.2",
    "python3.3",
    "python3.4",
    "python3.5",
    "python3.6",
    "python3.7",
    "python3.8",
    "python3.9",
    "python3.10",
    "python3.11",
    "python3.12",
    "python3",
]

# List of allowed extensions taken from
# https://docs.python.org/3/distutils/sourcedist.html.
# Names of source distribution archives must be of the form
# '%{package-name}-%{version}.%{extension}'.
_SDIST_RE = re.compile(
    r"^([\w.-]+?)-((?:[\d.]+){2,})\.(?:tar|tar.bz2|tar.gz|tar.xz|tar.Z|zip)$",
    re.IGNORECASE,
)


class PipSource(Source):
    # pylint: disable=attribute-defined-outside-init
    BST_MIN_VERSION = "2.5"

    # We need access to previous sources at track time to use requirements.txt
    # but not at fetch time as self.ref should contain sufficient information
    # for this plugin
    BST_REQUIRES_PREVIOUS_SOURCES_TRACK = True

    def configure(self, node):
        node.validate_keys(["url", "packages", "ref", "requirements-files"] + Source.COMMON_CONFIG_KEYS)
        self.ref = node.get_str("ref", None)
        self.original_url = node.get_str("url", _PYPI_INDEX_URL)
        self.index_url = self.translate_url(self.original_url)
        self.packages = node.get_str_list("packages", [])
        self.requirements_files = node.get_str_list("requirements-files", [])

        if not (self.packages or self.requirements_files):
            raise SourceError("{}: Either 'packages' or 'requirements-files' must be specified".format(self))

    def preflight(self):
        # Try to find a pip version that spports download command
        self.host_pip = None
        for python in reversed(_PYTHON_VERSIONS):
            try:
                host_python = utils.get_host_tool(python)
                rc = self.call([host_python, "-m", "pip", "download", "--help"])
                if rc == 0:
                    self.host_pip = [host_python, "-m", "pip"]
                    break
            except utils.ProgramNotFoundError:
                pass

        if self.host_pip is None:
            raise SourceError("{}: Unable to find a suitable pip command".format(self))

    def get_unique_key(self):
        return [self.original_url, self.ref]

    def is_cached(self):
        return os.path.exists(self._mirror) and os.listdir(self._mirror)

    def get_ref(self):
        return self.ref

    def load_ref(self, node):
        self.ref = node.get_str("ref", None)

    def set_ref(self, ref, node):
        node["ref"] = self.ref = ref

    def track(self, previous_sources_dir):  # pylint: disable=arguments-differ
        # XXX pip does not offer any public API other than the CLI tool so it
        # is not feasible to correctly parse the requirements file or to check
        # which package versions pip is going to install.
        # See https://pip.pypa.io/en/stable/user_guide/#using-pip-from-your-program
        # for details.
        # As a result, we have to wastefully install the packages during track.
        with self.tempdir() as tmpdir:
            install_args = self.host_pip + [
                "download",
                "--no-binary",
                ":all:",
                "--index-url",
                self.index_url,
                "--dest",
                tmpdir,
            ]
            for requirement_file in self.requirements_files:
                fpath = os.path.join(previous_sources_dir, requirement_file)
                install_args += ["-r", fpath]
            install_args += self.packages

            self.call(install_args, fail="Failed to install python packages")
            reqs = self._parse_sdist_names(tmpdir)

        return "\n".join(["{}=={}".format(pkg, ver) for pkg, ver in reqs])

    def fetch(self):  # pylint: disable=arguments-differ
        with self.tempdir() as tmpdir:
            packages = self.ref.strip().split("\n")
            package_dir = os.path.join(tmpdir, "packages")
            os.makedirs(package_dir)
            self.call(
                [
                    *self.host_pip,
                    "download",
                    "--no-binary",
                    ":all:",
                    "--index-url",
                    self.index_url,
                    "--dest",
                    package_dir,
                    *packages,
                ],
                fail="Failed to install python packages: {}".format(packages),
            )

            # If the mirror directory already exists, assume that some other
            # process has fetched the sources before us and ensure that we do
            # not raise an error in that case.
            try:
                utils.move_atomic(package_dir, self._mirror)
            except utils.DirectoryExistsError:
                # Another process has beaten us and has fetched the sources
                # before us.
                pass
            except OSError as e:
                raise SourceError(
                    "{}: Failed to move downloaded pip packages from '{}' to '{}': {}".format(
                        self, package_dir, self._mirror, e
                    )
                ) from e

    def stage(self, directory):
        with self.timed_activity("Staging Python packages", silent_nested=True):
            utils.copy_files(self._mirror, os.path.join(directory, _OUTPUT_DIRNAME))

    def collect_source_info(self):
        infos = []
        packages_versions = self.ref.splitlines()
        for package_version in packages_versions:
            split = package_version.split("==")
            package = split[0]
            version = split[1]
            infos.append(
                self.create_source_info(
                    self.index_url,
                    SourceInfoMedium.PYTHON_PACKAGE_INDEX,
                    SourceVersionType.INDEXED_VERSION,
                    version,
                    version_guess=version,
                    extra_data={"package-name": package},
                )
            )
        return infos

    # Directory where this source should stage its files
    #
    @property
    def _mirror(self):
        if not self.ref:
            return None
        return os.path.join(
            self.get_mirror_directory(),
            utils.url_directory_name(self.original_url),
            hashlib.sha256(self.ref.encode()).hexdigest(),
        )

    # Parse names of downloaded source distributions
    #
    # Args:
    #    basedir (str): Directory containing source distribution archives
    #
    # Returns:
    #    (list): List of (package_name, version) tuples in sorted order
    #
    def _parse_sdist_names(self, basedir):
        reqs = []
        for f in os.listdir(basedir):
            pkg = _match_package_name(f)
            if pkg is not None:
                reqs.append(pkg)

        return sorted(reqs)


# Extract the package name and version of a source distribution
#
# Args:
#    filename (str): Filename of the source distribution
#
# Returns:
#    (tuple): A tuple of (package_name, version)
#
def _match_package_name(filename):
    pkg_match = _SDIST_RE.match(filename)
    if pkg_match is None:
        return None
    return pkg_match.groups()


def setup():
    return PipSource
