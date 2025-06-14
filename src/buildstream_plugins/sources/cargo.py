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
#        Tristan Van Berkom <tristan.vanberkom@codethink.co.uk>

#
# This plugin was originally developped in the https://gitlab.com/BuildStream/bst-plugins-experimental/
# repository and was copied from a60426126e5bec2d630fcd889a9f5af13af00ea6
#

"""
cargo - Automatically stage crate dependencies
==============================================
A convenience Source element for vendoring rust project dependencies.

Placing this source in the source list, after a source which stages a
Cargo.lock file, will allow this source to read the Cargo.lock file and
obtain the crates automatically into %{vendordir}.

Set the `ref` field to an empty list like so: `ref: []`, and then run
`bst source track path_to_bst_file.bst`.

**Usage:**

.. code:: yaml

   # Specify the cargo source kind
   kind: cargo

   # Url of the crates repository to download from (default: https://static.crates.io/crates)
   url: https://static.crates.io/crates

   # Internal source reference, this is a list of dictionaries
   # which store the crate names and versions.
   #
   # This will be automatically updated with `bst source track`
   ref:
   - name: packagename
     version: 1.2.1
   - name: packagename
     version: 1.3.0

   # Specify a directory for the vendored crates (defaults to ./crates)
   vendor-dir: crates

   # Optionally specify the name of the lock file to use (defaults to Cargo.lock)
   cargo-lock: Cargo.lock


See `built-in functionality doumentation
<https://docs.buildstream.build/master/buildstream.source.html#core-source-builtins>`_ for
details on common configuration options for sources.


Reporting `SourceInfo <https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceInfo>`_
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The cargo source reports the URL of the archive crates as the *url* for each crate.

Further, the cargo source reports the `SourceInfoMedium.REMOTE_FILE
<https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceInfoMedium.REMOTE_FILE>`_
*medium* and the `SourceVersionType.SHA256
<https://docs.buildstream.build/master/buildstream.source.html#buildstream.source.SourceVersionType.SHA256>`_
*version_type*, for which it reports the checksum of the archive as the *version*.

The versions extracted from the Cargo.lock at tracking time are used to report the *guess_version*.
"""

import json
import os.path
import tarfile

# We prefer tomli that was put into standard library as tomllib
# starting from 3.11
try:
    import tomllib  # type: ignore
except ImportError:
    import tomli as tomllib  # type: ignore

from buildstream import Source, SourceFetcher, SourceError
from buildstream import utils

from ._utils import download_file

#
# Soft import of buildstream symbols only available in newer versions
#
# The BST_MIN_VERSION will provide a better user experience.
#
try:
    from buildstream import SourceInfoMedium, SourceVersionType
except ImportError:
    pass


# This automatically goes into .cargo/config
#
_default_vendor_config_template = (
    "[source.crates-io]\n"
    + 'registry = "{vendorurl}"\n'
    + 'replace-with = "vendored-sources"\n'
    + "[source.vendored-sources]\n"
    + 'directory = "{vendordir}"\n'
)


# Crate()
#
# Use a SourceFetcher class to be the per crate helper
#
# Args:
#    cargo (Cargo): The main Source implementation
#    name (str): The name of the crate to depend on
#    version (str): The version of the crate to depend on
#    sha (str|None): The sha256 checksum of the downloaded crate
#
class Crate(SourceFetcher):
    def __init__(self, cargo, name, version, sha=None):
        super().__init__()

        self.cargo = cargo
        self.name = name
        self.version = str(version)
        self.sha = sha
        self.mark_download_url(cargo.url)

    ########################################################
    #     SourceFetcher API method implementations         #
    ########################################################

    def fetch(self, alias_override=None, **kwargs):

        # Just a defensive check, it is impossible for the
        # file to be already cached because Source.fetch() will
        # not be called if the source is already cached.
        #
        if os.path.isfile(self._get_mirror_file()):
            return  # pragma: nocover

        # Download the crate
        crate_url, auth_scheme = self._get_url(alias_override)
        with self.cargo.timed_activity("Downloading: {}".format(crate_url), silent_nested=True):
            sha256 = self._download(crate_url, auth_scheme)
            if self.sha is not None and sha256 != self.sha:
                raise SourceError(
                    "File downloaded from {} has sha256sum '{}', not '{}'!".format(crate_url, sha256, self.sha)
                )

    def get_source_info(self):
        url, _ = self._get_url()
        return self.cargo.create_source_info(
            url, SourceInfoMedium.REMOTE_FILE, SourceVersionType.SHA256, self.sha, version_guess=self.version
        )

    ########################################################
    #        Helper APIs for the Cargo Source to use       #
    ########################################################

    # stage()
    #
    # A delegate method to do the work for a single crate
    # in Source.stage().
    #
    # Args:
    #    (directory): The vendor subdirectory to stage to
    #
    def stage(self, directory):
        try:
            mirror_file = self._get_mirror_file()
            with tarfile.open(mirror_file) as tar:
                members = tar.getmembers()
                if hasattr(tarfile, "tar_filter"):
                    # Python 3.12+ (and older versions with backports)
                    tar.extractall(path=directory, filter="tar")
                else:
                    for member in members:
                        self._assert_tarinfo_safe(member, directory)
                    tar.extractall(path=directory, members=members)

            if members:
                dirname = members[0].name.split("/")[0]
                package_dir = os.path.join(directory, dirname)
                checksum_file = os.path.join(package_dir, ".cargo-checksum.json")
                with open(checksum_file, "w", encoding="utf-8") as f:
                    checksum_data = {"package": self.sha, "files": {}}
                    json.dump(checksum_data, f)

        except (tarfile.TarError, OSError) as e:
            raise SourceError("{}: Error staging source: {}".format(self, e)) from e

    # is_cached()
    #
    # Get whether we have a local cached version of the source
    #
    # Returns:
    #   (bool): Whether we are cached or not
    #
    def is_cached(self):
        return os.path.isfile(self._get_mirror_file())

    # is_resolved()
    #
    # Get whether the current crate is resolved
    #
    # Returns:
    #   (bool): Whether we have a sha or not
    #
    def is_resolved(self):
        return self.sha is not None

    ########################################################
    #                   Private helpers                    #
    ########################################################

    # Assert that a tarfile is safe to extract; specifically, make
    # sure that we don't do anything outside of the target
    # directory (this is possible, if, say, someone engineered a
    # tarfile to contain paths that start with ..).
    def _assert_tarinfo_safe(self, member: tarfile.TarInfo, target_dir: str):
        final_path = os.path.abspath(os.path.join(target_dir, member.path))
        if not final_path.startswith(target_dir):
            raise SourceError(
                "{}: Tarfile attempts to extract outside the staging area: "
                "{} -> {}".format(self, member.path, final_path)
            )

        if member.islnk():
            linked_path = os.path.abspath(os.path.join(target_dir, member.linkname))
            if not linked_path.startswith(target_dir):
                raise SourceError(
                    "{}: Tarfile attempts to hardlink outside the staging area: "
                    "{} -> {}".format(self, member.path, final_path)
                )

        # Don't need to worry about symlinks because they're just
        # files here and won't be able to do much harm once we are
        # in a sandbox.

    # _download()
    #
    # Downloads the crate from the url and caches it.
    #
    # Args:
    #    url (str): The url to download from
    #
    # Returns:
    #    (str): The sha256 checksum of the downloaded crate
    #
    def _download(self, url, auth_scheme):
        # We do not use etag in case what we have in cache is
        # not matching ref in order to be able to recover from
        # corrupted download.
        if self.sha:
            etag = self._get_etag(self.sha)
        else:
            etag = None

        with self.cargo.tempdir() as td:
            local_file, etag, error = download_file(url, etag, td, auth_scheme)

            if error:
                raise SourceError("{}: Error mirroring {}: {}".format(self, url, error), temporary=True)

            # Make sure url-specific mirror dir exists.
            os.makedirs(self._get_mirror_dir(), exist_ok=True)

            # Store by sha256sum
            sha256 = utils.sha256sum(local_file)
            # Even if the file already exists, move the new file over.
            # In case the old file was corrupted somehow.
            os.rename(local_file, self._get_mirror_file(sha256))

            if etag:
                self._store_etag(sha256, etag)
            return sha256

    # _get_url()
    #
    # Fetches the URL to download this crate from
    #
    # Args:
    #    alias (str|None): The URL alias to apply, if any
    #
    # Returns:
    #    (str): The URL for this crate
    #
    def _get_url(self, alias=None):
        path = "{name}/{name}-{version}.crate".format(name=self.name, version=self.version)
        extra_data = {}
        if utils.get_bst_version() >= (2, 2):
            translated_url = self.cargo.translate_url(
                self.cargo.url, suffix=path, alias_override=alias, extra_data=extra_data
            )
        else:
            translated_url = self.cargo.translate_url(self.cargo.url, alias_override=alias) + path

        return translated_url, extra_data.get("http-auth")

    # _get_etag()
    #
    # Fetches the locally stored ETag information for this
    # crate's download.
    #
    # Args:
    #    sha (str): The sha256 checksum of the downloaded crate
    #
    # Returns:
    #    (str|None): The ETag to use for requests, or None if nothing is
    #                locally downloaded
    #
    def _get_etag(self, sha):
        etagfilename = os.path.join(self._get_mirror_dir(), "{}.etag".format(sha))
        if os.path.exists(etagfilename):
            with open(etagfilename, "r", encoding="utf-8") as etagfile:
                return etagfile.read()

        return None

    # _store_etag()
    #
    # Stores the locally cached ETag information for this crate.
    #
    # Args:
    #    sha (str): The sha256 checksum of the downloaded crate
    #    etag (str): The ETag to use for requests of this crate
    #
    def _store_etag(self, sha, etag):
        etagfilename = os.path.join(self._get_mirror_dir(), "{}.etag".format(sha))
        with utils.save_file_atomic(etagfilename) as etagfile:
            etagfile.write(etag)

    # _get_mirror_dir()
    #
    # Gets the local mirror directory for this upstream cargo repository
    #
    def _get_mirror_dir(self):
        return os.path.join(
            self.cargo.get_mirror_directory(),
            utils.url_directory_name(self.cargo.url),
            self.name,
            self.version,
        )

    # _get_mirror_file()
    #
    # Gets the local mirror filename for this crate
    #
    # Args:
    #    sha (str|None): The sha256 checksum of the downloaded crate
    #
    def _get_mirror_file(self, sha=None):
        return os.path.join(self._get_mirror_dir(), sha or self.sha)


class CargoSource(Source):
    BST_MIN_VERSION = "2.5"

    # We need the Cargo.lock file to construct our ref at track time
    BST_REQUIRES_PREVIOUS_SOURCES_TRACK = True

    ########################################################
    #       Plugin/Source API method implementations       #
    ########################################################
    def configure(self, node):

        # The url before any aliasing
        #
        self.original_url = node.get_str("url", "https://static.crates.io/crates")
        self.cargo_lock = node.get_str("cargo-lock", "Cargo.lock")
        self.vendor_dir = node.get_str("vendor-dir", "crates")

        # If the specified URL is just an alias, require the alias to resolve
        # to a URL with a trailing slash. Otherwise, append a trailing slash if
        # it's missing, for backward compatibility.
        self.url = self.original_url
        if not self.url.endswith(":") and not self.url.endswith("/"):
            self.url += "/"

        node.validate_keys(Source.COMMON_CONFIG_KEYS + ["url", "ref", "cargo-lock", "vendor-dir"])

        # Needs to be marked here so that `track` can translate it later.
        self.mark_download_url(self.url)

        self.load_ref(node)

    def preflight(self):
        return

    def get_unique_key(self):
        return [self.original_url, self.cargo_lock, self.vendor_dir, self.ref]

    def is_resolved(self):
        return (self.ref is not None) and all(crate.is_resolved() for crate in self.crates)

    def is_cached(self):
        return all(crate.is_cached() for crate in self.crates)

    def load_ref(self, node):
        ref = node.get_sequence("ref", None)
        self._recompute_crates(ref)

    def get_ref(self):
        return self.ref

    def set_ref(self, ref, node):
        node["ref"] = ref
        self._recompute_crates(node.get_sequence("ref"))

    def track(self, *, previous_sources_dir):
        new_ref = []
        lockfile = os.path.join(previous_sources_dir, self.cargo_lock)

        try:
            with open(lockfile, "rb") as f:
                try:
                    lock = tomllib.load(f)
                except tomllib.TOMLDecodeError as e:
                    raise SourceError(
                        "Malformed Cargo.lock file at: {}".format(self.cargo_lock),
                        detail="{}".format(e),
                    ) from e
        except FileNotFoundError as e:
            raise SourceError(
                "Failed to find Cargo.lock file at: {}".format(self.cargo_lock),
                detail="The cargo plugin expects to find a Cargo.lock file in\n"
                + "the sources staged before it in the source list, but none was found.",
            ) from e

        # FIXME: Better validation would be good here, so we can raise more
        #        useful error messages in the case of a malformed Cargo.lock file.
        #
        for package in lock["package"]:
            if "source" not in package:
                continue
            new_ref += [{"name": package["name"], "version": str(package["version"]), "sha": package.get("checksum")}]

        # Make sure the order we set it at track time is deterministic
        new_ref = sorted(new_ref, key=lambda c: (c["name"], c["version"]))

        # Download the crates and get their shas
        for crate_obj in new_ref:
            if crate_obj["sha"] is not None:
                continue

            crate = Crate(self, crate_obj["name"], crate_obj["version"])

            crate_url, auth_scheme = crate._get_url()
            with self.timed_activity("Downloading: {}".format(crate_url), silent_nested=True):
                crate_obj["sha"] = crate._download(crate_url, auth_scheme)

        return new_ref

    def stage(self, directory):

        # Stage the crates into the vendor directory
        vendor_dir = os.path.join(directory, self.vendor_dir)
        for crate in self.crates:
            crate.stage(vendor_dir)

        # Stage our vendor config
        vendor_config = _default_vendor_config_template.format(
            vendorurl=self.translate_url(self.url), vendordir=self.vendor_dir
        )
        conf_dir = os.path.join(directory, ".cargo")
        conf_file = os.path.join(conf_dir, "config")
        os.makedirs(conf_dir, exist_ok=True)
        with open(conf_file, "w", encoding="utf-8") as f:
            f.write(vendor_config)

    def get_source_fetchers(self):
        return self.crates

    ########################################################
    #                   Private helpers                    #
    ########################################################

    def _recompute_crates(self, ref):
        self.crates = self._parse_crates(ref)
        if not self.crates:
            self.ref = None
        else:
            self.ref = [{"name": crate.name, "version": crate.version, "sha": crate.sha} for crate in self.crates]

    # _parse_crates():
    #
    # Generates a list of crates based on the passed ref
    #
    # Args:
    #    (list|None) refs: The list of name/version dictionaries
    #
    # Returns:
    #    (list): A list of Crate objects
    #
    def _parse_crates(self, refs):

        # Return an empty list for no ref
        if refs is None:
            return []

        return [
            Crate(
                self,
                crate.get_str("name"),
                crate.get_str("version"),
                sha=crate.get_str("sha", None),
            )
            for crate in refs
        ]


def setup():
    return CargoSource
