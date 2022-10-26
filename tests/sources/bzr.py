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
import subprocess

import pytest

from buildstream import _yaml
from buildstream._testing import cli  # pylint: disable=unused-import
from buildstream._testing import create_repo
from buildstream._testing import generate_element

from tests.testutils.site import HAVE_BZR

pytestmark = pytest.mark.skipif(HAVE_BZR is False, reason="bzr is not available")
DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "bzr")


@pytest.mark.datafiles(os.path.join(DATA_DIR))
def test_fetch_checkout(cli, tmpdir, datafiles):
    project = str(datafiles)
    checkoutdir = os.path.join(str(tmpdir), "checkout")

    repo = create_repo("bzr", str(tmpdir))
    ref = repo.create(os.path.join(project, "basic"))

    # Write out our test target
    element = {"kind": "import", "sources": [repo.source_config(ref=ref)]}
    generate_element(project, "target.bst", element)

    # Fetch, build, checkout
    result = cli.run(project=project, args=["source", "fetch", "target.bst"])
    assert result.exit_code == 0
    result = cli.run(project=project, args=["build", "target.bst"])
    assert result.exit_code == 0
    result = cli.run(project=project, args=["artifact", "checkout", "target.bst", "--directory", checkoutdir])
    assert result.exit_code == 0

    # Assert we checked out the file as it was commited
    with open(os.path.join(checkoutdir, "test"), encoding="utf-8") as f:
        text = f.read()

    assert text == "test\n"


@pytest.mark.datafiles(DATA_DIR)
def test_open_bzr_customize(cli, tmpdir, datafiles):
    project = str(datafiles)
    repo = create_repo("bzr", str(tmpdir))
    ref = repo.create(os.path.join(project, "basic"))

    element = {"kind": "import", "sources": [repo.source_config(ref=ref)]}
    generate_element(project, "target.bst", element)

    workspace = os.path.join(datafiles, "bzr-workspace")
    result = cli.run(cwd=project, project=project, args=["workspace", "open", "--directory", workspace, "target.bst"])
    result.assert_success()

    # Check that the .bzr dir exists
    assert os.path.isdir(os.path.join(workspace, ".bzr"))

    # Check that the correct origin branch is set
    element_config = _yaml.load(os.path.join(project, "target.bst"), shortname=None)
    source_config = element_config.get_sequence("sources").mapping_at(0)
    output = subprocess.check_output(["bzr", "info"], cwd=workspace)
    stripped_url = source_config.get_str("url").lstrip("file:///")
    expected_output_str = "checkout of branch: /{}/{}".format(stripped_url, source_config.get_str("track"))
    assert expected_output_str in str(output)
