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

# Pylint doesn't play well with fixtures and dependency injection from pytest
# pylint: disable=redefined-outer-name

import os
import pytest

from buildstream import _yaml

from buildstream._testing import cli_integration as cli  # pylint: disable=unused-import
from buildstream._testing.integration import assert_contains
from buildstream._testing.integration import integration_cache  # pylint: disable=unused-import
from buildstream._testing._utils.site import HAVE_SANDBOX

from tests.testutils.python_repo import setup_pypi_repo  # pylint: disable=unused-import


pytestmark = pytest.mark.integration


DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "pip-build")


@pytest.mark.datafiles(DATA_DIR)
def test_pip_source_import_packages(cli, datafiles, setup_pypi_repo):
    project = str(datafiles)
    checkout = os.path.join(cli.directory, "checkout")
    element_path = os.path.join(project, "elements")
    element_name = "pip/hello.bst"

    # check that exotically named packages are imported correctly
    myreqs_packages = "hellolib"
    dependencies = [
        "app2",
        "app.3",
        "app-4",
        "app_5",
        "app.no.6",
        "app-no-7",
        "app_no_8",
    ]
    mock_packages = {myreqs_packages: {package: {} for package in dependencies}}

    # create mock pypi repository
    pypi_repo = os.path.join(project, "files", "pypi-repo")
    os.makedirs(pypi_repo, exist_ok=True)
    setup_pypi_repo(mock_packages, pypi_repo)

    element = {
        "kind": "import",
        "sources": [
            {"kind": "local", "path": "files/pip-source"},
            {
                "kind": "pip",
                "url": "file://{}".format(os.path.realpath(pypi_repo)),
                "packages": [myreqs_packages],
            },
        ],
    }
    os.makedirs(
        os.path.dirname(os.path.join(element_path, element_name)),
        exist_ok=True,
    )
    _yaml.roundtrip_dump(element, os.path.join(element_path, element_name))

    result = cli.run(project=project, args=["source", "track", element_name])
    assert result.exit_code == 0

    result = cli.run(project=project, args=["build", element_name])
    assert result.exit_code == 0

    result = cli.run(
        project=project,
        args=["artifact", "checkout", element_name, "--directory", checkout],
    )
    assert result.exit_code == 0

    assert_contains(
        checkout,
        [
            "/.bst_pip_downloads",
            "/.bst_pip_downloads/hellolib-0.1.tar.gz",
            "/.bst_pip_downloads/app2-0.1.tar.gz",
            "/.bst_pip_downloads/app_3-0.1.tar.gz",
            "/.bst_pip_downloads/app_4-0.1.tar.gz",
            "/.bst_pip_downloads/app_5-0.1.tar.gz",
            "/.bst_pip_downloads/app_no_6-0.1.tar.gz",
            "/.bst_pip_downloads/app_no_7-0.1.tar.gz",
            "/.bst_pip_downloads/app_no_8-0.1.tar.gz",
        ],
    )


@pytest.mark.datafiles(DATA_DIR)
def test_pip_source_import_requirements_files(cli, datafiles, setup_pypi_repo):
    project = str(datafiles)
    checkout = os.path.join(cli.directory, "checkout")
    element_path = os.path.join(project, "elements")
    element_name = "pip/hello.bst"

    # check that exotically named packages are imported correctly
    myreqs_packages = "hellolib"
    dependencies = [
        "app2",
        "app.3",
        "app-4",
        "app_5",
        "app.no.6",
        "app-no-7",
        "app_no_8",
    ]
    mock_packages = {myreqs_packages: {package: {} for package in dependencies}}

    # create mock pypi repository
    pypi_repo = os.path.join(project, "files", "pypi-repo")
    os.makedirs(pypi_repo, exist_ok=True)
    setup_pypi_repo(mock_packages, pypi_repo)

    element = {
        "kind": "import",
        "sources": [
            {"kind": "local", "path": "files/pip-source"},
            {
                "kind": "pip",
                "url": "file://{}".format(os.path.realpath(pypi_repo)),
                "requirements-files": ["myreqs.txt"],
            },
        ],
    }
    os.makedirs(
        os.path.dirname(os.path.join(element_path, element_name)),
        exist_ok=True,
    )
    _yaml.roundtrip_dump(element, os.path.join(element_path, element_name))

    result = cli.run(project=project, args=["source", "track", element_name])
    assert result.exit_code == 0

    result = cli.run(project=project, args=["build", element_name])
    assert result.exit_code == 0

    result = cli.run(
        project=project,
        args=["artifact", "checkout", element_name, "--directory", checkout],
    )
    assert result.exit_code == 0

    assert_contains(
        checkout,
        [
            "/.bst_pip_downloads",
            "/.bst_pip_downloads/hellolib-0.1.tar.gz",
            "/.bst_pip_downloads/app2-0.1.tar.gz",
            "/.bst_pip_downloads/app_3-0.1.tar.gz",
            "/.bst_pip_downloads/app_4-0.1.tar.gz",
            "/.bst_pip_downloads/app_5-0.1.tar.gz",
            "/.bst_pip_downloads/app_no_6-0.1.tar.gz",
            "/.bst_pip_downloads/app_no_7-0.1.tar.gz",
            "/.bst_pip_downloads/app_no_8-0.1.tar.gz",
        ],
    )


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason="Only available with a functioning sandbox")
def test_pip_source_build(cli, datafiles, setup_pypi_repo):
    project = str(datafiles)
    element_path = os.path.join(project, "elements")
    element_name = "pip/hello.bst"

    # check that exotically named packages are imported correctly
    myreqs_packages = "hellolib"
    dependencies = [
        "app2",
        "app.3",
        "app-4",
        "app_5",
        "app.no.6",
        "app-no-7",
        "app_no_8",
    ]
    mock_packages = {myreqs_packages: {package: {} for package in dependencies}}

    # create mock pypi repository
    pypi_repo = os.path.join(project, "files", "pypi-repo")
    os.makedirs(pypi_repo, exist_ok=True)
    setup_pypi_repo(mock_packages, pypi_repo)
    realpath_repo = os.path.realpath(pypi_repo)

    element = {
        "kind": "manual",
        "depends": ["base.bst"],
        "sources": [
            {"kind": "local", "path": "files/pip-source"},
            {
                "kind": "pip",
                "url": "file://{}".format(realpath_repo),
                "requirements-files": ["myreqs.txt"],
                "packages": dependencies,
            },
        ],
        "config": {
            "install-commands": [
                "pip3 install --no-index --prefix %{install-root}/usr .bst_pip_downloads/*.tar.gz",
                "install app1.py %{install-root}/usr/bin/",
            ]
        },
    }
    os.makedirs(
        os.path.dirname(os.path.join(element_path, element_name)),
        exist_ok=True,
    )
    _yaml.roundtrip_dump(element, os.path.join(element_path, element_name))

    result = cli.run(project=project, args=["source", "track", element_name])
    assert result.exit_code == 0

    #
    # Lets sneak in here and test out that Source.collect_source_info() works as expected
    #
    # The ref for this generated pip source is:
    #
    #    "app2==0.1\napp_3==0.1\napp_4==0.1\napp_5==0.1\napp_no_6==0.1\napp_no_7==0.1\napp_no_8==0.1\nhellolib==0.1"
    #
    # Lets just make an assertion on the first dependency app2, which is the second in the list after the local source for this element
    #
    result = cli.run(
        project=project,
        silent=True,
        args=["show", "--deps", "none", "--format", "element:\n%{source-info}", element_name],
    )
    result.assert_success()
    loaded = _yaml.load_data(result.output)
    sources = loaded.get_sequence("element")
    source_info = sources.mapping_at(1)
    assert source_info.get_str("kind") == "pip"
    assert source_info.get_str("url") == f"file://{realpath_repo}"
    assert source_info.get_str("medium") == "pypi"
    assert source_info.get_str("version-type") == "indexed-version"
    assert source_info.get_str("version") == "0.1"
    assert source_info.get_str("version-guess") == "0.1"
    extra_data = source_info.get_mapping("extra-data", None)
    assert extra_data is not None
    assert extra_data.get_str("package-name", "app2")

    # Go ahead and build
    result = cli.run(project=project, args=["build", element_name])
    assert result.exit_code == 0

    # Use a build shell to assert the output of something we installed
    result = cli.run(project=project, args=["shell", element_name, "/usr/bin/app1.py"])
    assert result.exit_code == 0
    assert result.output == "Hello App1! This is hellolib\n"
