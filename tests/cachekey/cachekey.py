# Pylint doesn't play well with fixtures and dependency injection from pytest
# pylint: disable=redefined-outer-name

import os
import pytest

from buildstream._testing._cachekeys import check_cache_key_stability
from buildstream._testing.runcli import cli  # pylint: disable=unused-import
from buildstream._testing._utils.site import HAVE_BZR, HAVE_GIT, IS_LINUX, MACHINE_ARCH


# Project directory
DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "project",
)


# The cache key test uses a project which exercises all plugins,
# so we cant run it at all if we dont have them installed.
#
@pytest.mark.skipif(MACHINE_ARCH != "x86-64", reason="Cache keys depend on architecture")
@pytest.mark.skipif(not IS_LINUX, reason="Only available on linux")
@pytest.mark.skipif(HAVE_BZR is False, reason="bzr is not available")
@pytest.mark.skipif(HAVE_GIT is False, reason="git is not available")
@pytest.mark.datafiles(DATA_DIR)
def test_cache_key(datafiles, cli):
    project = str(datafiles)

    # Workaround bug in recent versions of setuptools: newer
    # versions of setuptools fail to preserve symbolic links
    # when creating a source distribution, causing this test
    # to fail from a dist tarball.
    goodbye_link = os.path.join(project, "files", "local", "usr", "bin", "goodbye")
    os.unlink(goodbye_link)
    os.symlink("hello", goodbye_link)
    # pytest-datafiles does not copy mode bits
    # https://github.com/omarkohl/pytest-datafiles/issues/11
    os.chmod(goodbye_link, 0o755)

    check_cache_key_stability(project, cli)
