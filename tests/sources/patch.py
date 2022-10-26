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
import socket
import pytest

from buildstream.exceptions import ErrorDomain, LoadErrorReason
from buildstream._testing import cli  # pylint: disable=unused-import

DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "patch",
)


# generate_file_types()
#
# Generator that creates a regular file directory, symbolic link, fifo
# and socket at the specified path.
#
# Args:
#  path: (str) path where to create each different type of file
#
def generate_file_types(path):
    def clean():
        if os.path.exists(path):
            if os.path.isdir(path):
                os.rmdir(path)
            else:
                os.remove(path)

    clean()

    with open(path, "w", encoding="utf-8"):
        pass
    yield
    clean()

    os.makedirs(path)
    yield
    clean()

    os.symlink("project.conf", path)
    yield
    clean()

    os.mkfifo(path)
    yield
    clean()

    # Change directory because the full path may be longer than the ~100
    # characters permitted for a unix socket
    old_dir = os.getcwd()
    parent, child = os.path.split(path)
    os.chdir(parent)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        s.bind(child)
        os.chdir(old_dir)
        yield
    finally:
        s.close()

    clean()


@pytest.mark.datafiles(os.path.join(DATA_DIR, "basic"))
def test_missing_patch(cli, datafiles):
    project = str(datafiles)

    # Removing the local file causes preflight to fail
    localfile = os.path.join(project, "file_1.patch")
    os.remove(localfile)

    result = cli.run(project=project, args=["show", "target.bst"])
    result.assert_main_error(ErrorDomain.LOAD, LoadErrorReason.MISSING_FILE)


@pytest.mark.datafiles(os.path.join(DATA_DIR, "basic"))
def test_non_regular_file_patch(cli, datafiles):
    project = str(datafiles)

    patch_path = os.path.join(project, "irregular_file.patch")
    for _file_type in generate_file_types(patch_path):
        result = cli.run(project=project, args=["show", "irregular.bst"])
        if os.path.isfile(patch_path) and not os.path.islink(patch_path):
            result.assert_success()
        else:
            result.assert_main_error(ErrorDomain.LOAD, LoadErrorReason.PROJ_PATH_INVALID_KIND)


@pytest.mark.datafiles(os.path.join(DATA_DIR, "basic"))
def test_invalid_absolute_path(cli, datafiles):
    project = str(datafiles)

    with open(os.path.join(project, "target.bst"), "r", encoding="utf-8") as f:
        old_yaml = f.read()
    new_yaml = old_yaml.replace("file_1.patch", os.path.join(project, "file_1.patch"))
    assert old_yaml != new_yaml

    with open(os.path.join(project, "target.bst"), "w", encoding="utf-8") as f:
        f.write(new_yaml)

    result = cli.run(project=project, args=["show", "target.bst"])
    result.assert_main_error(ErrorDomain.LOAD, LoadErrorReason.PROJ_PATH_INVALID)


@pytest.mark.datafiles(os.path.join(DATA_DIR, "invalid-relative-path"))
def test_invalid_relative_path(cli, datafiles):
    project = str(datafiles)

    result = cli.run(project=project, args=["show", "irregular.bst"])
    result.assert_main_error(ErrorDomain.LOAD, LoadErrorReason.PROJ_PATH_INVALID)


@pytest.mark.datafiles(os.path.join(DATA_DIR, "basic"))
def test_stage_and_patch(cli, tmpdir, datafiles):
    project = str(datafiles)
    checkoutdir = os.path.join(str(tmpdir), "checkout")

    # Build, checkout
    result = cli.run(project=project, args=["build", "target.bst"])
    result.assert_success()
    result = cli.run(project=project, args=["artifact", "checkout", "target.bst", "--directory", checkoutdir])
    result.assert_success()

    # Test the file.txt was patched and changed
    with open(os.path.join(checkoutdir, "file.txt"), encoding="utf-8") as f:
        assert f.read() == "This is text file with superpowers\n"


@pytest.mark.datafiles(os.path.join(DATA_DIR, "basic"))
def test_stage_file_nonexistent_dir(cli, datafiles):
    project = str(datafiles)

    # Fails at build time because it tries to patch into a non-existing directory
    result = cli.run(project=project, args=["build", "failure-nonexistent-dir.bst"])
    result.assert_main_error(ErrorDomain.STREAM, None)
    result.assert_task_error(ErrorDomain.SOURCE, "patch-no-files")


@pytest.mark.datafiles(os.path.join(DATA_DIR, "basic"))
def test_stage_file_empty_dir(cli, datafiles):
    project = str(datafiles)

    # Fails at build time because it tries to patch with nothing else staged
    result = cli.run(project=project, args=["build", "failure-empty-dir.bst"])
    result.assert_main_error(ErrorDomain.STREAM, None)
    result.assert_task_error(ErrorDomain.SOURCE, "patch-no-files")


@pytest.mark.datafiles(os.path.join(DATA_DIR, "separate-patch-dir"))
def test_stage_separate_patch_dir(cli, tmpdir, datafiles):
    project = str(datafiles)
    checkoutdir = os.path.join(str(tmpdir), "checkout")

    # Track, fetch, build, checkout
    result = cli.run(project=project, args=["build", "target.bst"])
    result.assert_success()
    result = cli.run(project=project, args=["artifact", "checkout", "target.bst", "--directory", checkoutdir])
    result.assert_success()

    # Test the file.txt was patched and changed
    with open(os.path.join(checkoutdir, "test-dir", "file.txt"), encoding="utf-8") as f:
        assert f.read() == "This is text file in a directory with superpowers\n"


@pytest.mark.datafiles(os.path.join(DATA_DIR, "multiple-patches"))
def test_stage_multiple_patches(cli, tmpdir, datafiles):
    project = str(datafiles)
    checkoutdir = os.path.join(str(tmpdir), "checkout")

    # Track, fetch, build, checkout
    result = cli.run(project=project, args=["build", "target.bst"])
    result.assert_success()
    result = cli.run(project=project, args=["artifact", "checkout", "target.bst", "--directory", checkoutdir])
    result.assert_success()

    # Test the file.txt was patched and changed
    with open(os.path.join(checkoutdir, "file.txt"), encoding="utf-8") as f:
        assert f.read() == "This is text file with more superpowers\n"


@pytest.mark.datafiles(os.path.join(DATA_DIR, "different-strip-level"))
def test_patch_strip_level(cli, tmpdir, datafiles):
    project = str(datafiles)
    checkoutdir = os.path.join(str(tmpdir), "checkout")

    # Track, fetch, build, checkout
    result = cli.run(project=project, args=["build", "target.bst"])
    result.assert_success()
    result = cli.run(project=project, args=["artifact", "checkout", "target.bst", "--directory", checkoutdir])
    result.assert_success()

    # Test the file.txt was patched and changed
    with open(os.path.join(checkoutdir, "file.txt"), encoding="utf-8") as f:
        assert f.read() == "This is text file with superpowers\n"
