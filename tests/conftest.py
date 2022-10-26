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
import pytest

from buildstream._testing import sourcetests_collection_hook
from buildstream._testing import register_repo_kind

from .testutils.repo import Bzr, Git


#################################################
#            Implement pytest option            #
#################################################
def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests",
    )


def pytest_runtest_setup(item):
    # Without --integration: skip tests not marked with 'integration'
    if not item.config.getvalue("integration"):
        if item.get_closest_marker("integration"):
            pytest.skip("skipping integration test")


register_repo_kind("bzr", Bzr, "buildstream_plugins")
register_repo_kind("git", Git, "buildstream_plugins")


# This hook enables pytest to collect the templated source tests from
# buildstream._testing
def pytest_sessionstart(session):
    sourcetests_collection_hook(session)
