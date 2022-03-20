import pytest

from buildstream._testing import sourcetests_collection_hook
from buildstream._testing import register_repo_kind

from .testutils.repo import Bzr, Git


#################################################
#            Implement pytest option            #
#################################################
def pytest_addoption(parser):
    parser.addoption(
        "--integration", action="store_true", default=False, help="Run integration tests",
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
