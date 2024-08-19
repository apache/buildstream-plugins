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
from buildstream._testing import cli  # pylint: disable=unused-import

DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "cargo",
)


def generate_project(project_dir):
    project_file = os.path.join(project_dir, "project.conf")
    _yaml.roundtrip_dump(
        {
            "name": "foo",
            "min-version": "2.0",
            "element-path": "elements",
            "plugins": [
                {
                    "origin": "pip",
                    "package-name": "buildstream-plugins",
                    "sources": ["cargo"],
                }
            ],
        },
        project_file,
    )


@pytest.mark.datafiles(os.path.join(DATA_DIR, "minimal"))
def test_cargo_track_fetch_build(cli, datafiles):
    project = str(datafiles)
    generate_project(project)
    result = cli.run(project=project, args=["source", "track", "base64.bst"])
    result.assert_success()
    result = cli.run(project=project, args=["source", "fetch", "base64.bst"])
    result.assert_success()
    result = cli.run(project=project, args=["build", "base64.bst"])
    result.assert_success()
