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
#        Jonathan Maw <jonathan.maw@codethink.co.uk>

#
# This plugin was originally developped in the https://github.com/apache/buildstream/
# repository and was copied from 1a3c707a6c46573ab159de64ac9cd92e7f6027e6
#

"""
bzr - stage files from a bazaar repository
==========================================

**Host dependencies:**

  * bzr

**Usage:**

.. code:: yaml

   # Specify the bzr source kind
   kind: bzr

   # Specify the bzr url. Bazaar URLs come in many forms, see
   # `bzr help urlspec` for more information. Using an alias defined
   # in your project configuration is encouraged.
   url: https://launchpad.net/bzr

   # Specify the tracking branch. This is mandatory, as bzr cannot identify
   # an individual revision outside its branch. bzr URLs that omit the branch
   # name implicitly specify the trunk branch, but bst requires this to be
   # explicit.
   track: trunk

   # Specify the ref. This is a revision number. This is usually a decimal,
   # but revisions on a branch are of the form
   # <revision-branched-from>.<branch-number>.<revision-since-branching>
   # e.g. 6622.1.6.
   # The ref must be specified to build, and 'bst source track' will update the
   # revision number to the one on the tip of the branch specified in 'track'.
   ref: 6622

   # Specify the version to be reported as the *guess_version* when reporting
   # SourceInfo
   #
   # Since 2.5
   #
   version: 1.2

See `built-in functionality doumentation
<https://docs.buildstream.build/master/buildstream.source.html#core-source-builtins>`_ for
details on common configuration options for sources.


Reporting `SourceInfo <https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceInfo>`_
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The bzr source reports the URL of the bzr repository as the *url*.

Further, the bzr source reports the `SourceInfoMedium.BZR
<https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceInfoMedium.BZR>`_
*medium* and the` `SourceVersionType.COMMIT
<https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceVersionType.COMMIT>`_
*version_type*, for which it reports the bzr revision number as the *version*.

Since the bzr source does not have a way to know what the release version
corresponds to the revision number, the bzr source exposes the ``version`` configuration
attribute to allow explicit specification of the *guess_version*.
"""

import os
import shutil
import fcntl
from contextlib import contextmanager

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


class BzrSource(Source):
    # pylint: disable=attribute-defined-outside-init

    BST_MIN_VERSION = "2.5"

    def configure(self, node):
        node.validate_keys(["url", "track", "ref", "version", *Source.COMMON_CONFIG_KEYS])

        self.original_url = node.get_str("url")
        self.tracking = node.get_str("track")
        self.ref = node.get_str("ref", None)
        self.url = self.translate_url(self.original_url)
        self.version = node.get_str("version", None)

    def preflight(self):
        # Check if bzr is installed, get the binary at the same time.
        self.host_bzr = utils.get_host_tool("bzr")

    def get_unique_key(self):
        unique_key = [self.original_url, self.tracking, self.ref]

        # Backwards compatible method of supporting configuration
        # attributes which affect SourceInfo generation.
        if self.version is not None:
            unique_key.append(self.version)

        return unique_key

    def is_cached(self):
        with self._locked():
            return self._check_ref()

    def load_ref(self, node):
        self.ref = node.get_str("ref", None)

    def get_ref(self):
        return self.ref

    def set_ref(self, ref, node):
        node["ref"] = self.ref = ref

    def track(self):  # pylint: disable=arguments-differ
        with self.timed_activity("Tracking {}".format(self.url), silent_nested=True), self._locked():
            self._ensure_mirror(skip_ref_check=True)
            ret, out = self.check_output(
                [
                    self.host_bzr,
                    "version-info",
                    "--custom",
                    "--template={revno}",
                    self._get_branch_dir(),
                ],
                fail="Failed to read the revision number at '{}'".format(self._get_branch_dir()),
            )
            if ret != 0:
                raise SourceError("{}: Failed to get ref for tracking {}".format(self, self.tracking))

            return out

    def fetch(self):  # pylint: disable=arguments-differ
        with self.timed_activity("Fetching {}".format(self.url), silent_nested=True), self._locked():
            self._ensure_mirror()

    def stage(self, directory):
        self.call(
            [
                self.host_bzr,
                "checkout",
                "--lightweight",
                "--revision=revno:{}".format(self.ref),
                self._get_branch_dir(),
                directory,
            ],
            fail="Failed to checkout revision {} from branch {} to {}".format(
                self.ref, self._get_branch_dir(), directory
            ),
        )
        # Remove .bzr dir
        shutil.rmtree(os.path.join(directory, ".bzr"))

    def init_workspace(self, directory):
        url = os.path.join(self.url, self.tracking)
        with self.timed_activity('Setting up workspace "{}"'.format(directory), silent_nested=True):
            # Checkout from the cache
            self.call(
                [
                    self.host_bzr,
                    "branch",
                    "--use-existing-dir",
                    "--revision=revno:{}".format(self.ref),
                    self._get_branch_dir(),
                    directory,
                ],
                fail="Failed to branch revision {} from branch {} to {}".format(
                    self.ref, self._get_branch_dir(), directory
                ),
            )
            # Switch the parent branch to the source's origin
            self.call(
                [
                    self.host_bzr,
                    "switch",
                    "--directory={}".format(directory),
                    url,
                ],
                fail="Failed to switch workspace's parent branch to {}".format(url),
            )

    def collect_source_info(self):
        return [
            self.create_source_info(
                self.url, SourceInfoMedium.BAZAAR, SourceVersionType.COMMIT, self.ref, version_guess=self.version
            )
        ]

    # _locked()
    #
    # This context manager ensures exclusive access to the
    # bzr repository.
    #
    @contextmanager
    def _locked(self):
        lockdir = os.path.join(self.get_mirror_directory(), "locks")
        lockfile = os.path.join(lockdir, utils.url_directory_name(self.original_url) + ".lock")
        os.makedirs(lockdir, exist_ok=True)
        with open(lockfile, "wb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _check_ref(self):
        # If the mirror doesnt exist yet, then we dont have the ref
        if not os.path.exists(self._get_branch_dir()):
            return False

        return (
            self.call(
                [
                    self.host_bzr,
                    "revno",
                    "--revision=revno:{}".format(self.ref),
                    self._get_branch_dir(),
                ]
            )
            == 0
        )

    def _get_branch_dir(self):
        return os.path.join(self._get_mirror_dir(), self.tracking)

    def _get_mirror_dir(self):
        return os.path.join(
            self.get_mirror_directory(),
            utils.url_directory_name(self.original_url),
        )

    def _ensure_mirror(self, skip_ref_check=False):
        mirror_dir = self._get_mirror_dir()
        bzr_metadata_dir = os.path.join(mirror_dir, ".bzr")
        if not os.path.exists(bzr_metadata_dir):
            self.call(
                [self.host_bzr, "init-repo", "--no-trees", mirror_dir],
                fail="Failed to initialize bzr repository",
            )

        branch_dir = os.path.join(mirror_dir, self.tracking)
        branch_url = self.url + "/" + self.tracking
        if not os.path.exists(branch_dir):
            # `bzr branch` the branch if it doesn't exist
            # to get the upstream code
            self.call(
                [self.host_bzr, "branch", branch_url, branch_dir],
                fail="Failed to branch from {} to {}".format(branch_url, branch_dir),
            )

        else:
            # `bzr pull` the branch if it does exist
            # to get any changes to the upstream code
            self.call(
                [
                    self.host_bzr,
                    "pull",
                    "--directory={}".format(branch_dir),
                    branch_url,
                ],
                fail="Failed to pull new changes for {}".format(branch_dir),
            )

        if not skip_ref_check and not self._check_ref():
            raise SourceError(
                "Failed to ensure ref '{}' was mirrored".format(self.ref),
                reason="ref-not-mirrored",
            )


def setup():
    return BzrSource
