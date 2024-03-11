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

**Usage:**

.. code:: yaml

   # Specify the cargo source kind
   kind: cargo

   # Url of the crates repository to download from (default: https://static.crates.io/crates)
   url: https://static.crates.io/crates

   # Internal source reference, this is a list of dictionaries
   # which store the crate names and versions.
   #
   # This will be automatically updated with `bst track`
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
"""

import glob
import json
import os.path
import shutil
import tarfile
import threading
from urllib.parse import urljoin, urlparse

# We prefer tomli that was put into standard library as tomllib
# starting from 3.11
try:
    import tomllib  # type: ignore
except ImportError:
    import tomli as tomllib  # type: ignore

from buildstream import Source, SourceFetcher, SourceError
from buildstream import utils

import dulwich
from dulwich.repo import Repo
import tomli_w

from ._utils import download_file


# This automatically goes into .cargo/config
#
_default_vendor_config_template = (
    "[source.crates-io]\n"
    + 'registry = "{vendorurl}"\n'
    + 'replace-with = "vendored-sources"\n'
    + "{git_vendors}"
    + "\n[source.vendored-sources]\n"
    + 'directory = "{vendordir}"\n'
)

# Added as {git_vendors} in template above
_git_vendor_config_template = '\n[source."git+{git_repo}"]\ngit = "{git_repo}"\nreplace-with = "vendored-sources"\n'


# CrateRegistry()
#
# Use a SourceFetcher class to be the per crate helper.
#
# This one is for crates fetched from registries like crates.io.
#
# Args:
#    cargo (Cargo): The main Source implementation
#    name (str): The name of the crate to depend on
#    version (str): The version of the crate to depend on
#    sha (str|None): The sha256 checksum of the downloaded crate
#
class CrateRegistry(SourceFetcher):
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
        crate_url = self._get_url(alias_override)
        with self.cargo.timed_activity("Downloading: {}".format(crate_url), silent_nested=True):
            sha256 = self._download(crate_url)
            if self.sha is not None and sha256 != self.sha:
                raise SourceError(
                    "File downloaded from {} has sha256sum '{}', not '{}'!".format(crate_url, sha256, self.sha)
                )

    ########################################################
    #        Helper APIs for the Cargo Source to use       #
    ########################################################

    def ref_node(self):
        return {"kind": "registry", "name": self.name, "version": self.version, "sha": self.sha}

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

            if os.path.exists(os.path.join(directory, f"{self.name}-{self.version}")):
                raise SourceError(
                    f"This project requests crate {self.name} {self.version} from multiple sources, "
                    "which is incompatible with vendoring since cargo does not support it."
                )

            with tarfile.open(mirror_file) as tar:
                tar.extractall(path=directory)
                members = tar.getmembers()

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
    def _download(self, url):
        # We do not use etag in case what we have in cache is
        # not matching ref in order to be able to recover from
        # corrupted download.
        if self.sha:
            etag = self._get_etag(self.sha)
        else:
            etag = None

        with self.cargo.tempdir() as td:
            local_file, etag, error = download_file(url, etag, td)

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
        url = self.cargo.translate_url(self.cargo.url, alias_override=alias)
        path = "{name}/{name}-{version}.crate".format(name=self.name, version=self.version)
        return urljoin(f"{url}/", path)

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


# Locks on repositories for write access
REPO_LOCKS = {}  # type: dict[str, threading.Lock]


# CrateGit()
#
# Use a SourceFetcher class to be the per crate helper.
#
# This one is for crates fetched from git repositories.
#
# Args:
#    cargo (Cargo): The main Source implementation
#    name (str): The name of the crate to depend on
#    version (str): The version of the crate to depend on
#    repo (str): Repository URL
#    commit (str): Sha of the git commit
class CrateGit(SourceFetcher):
    def __init__(self, cargo, name, version, repo, commit):
        super().__init__()

        self.cargo = cargo
        self.name = name
        self.version = str(version)
        self.repo = repo
        self.commit = commit
        # TODO: Is this right?
        self.mark_download_url(self.repo)

    ########################################################
    #     SourceFetcher API method implementations         #
    ########################################################

    def fetch(self, alias_override=None, **kwargs):
        lock = REPO_LOCKS.setdefault(self._get_mirror_dir(), threading.Lock())

        with lock, self._mirror_repo() as repo, self.cargo.timed_activity(f"Fetching from {self.repo}"):
            # TODO: Auth not supported
            client, path = dulwich.client.get_transport_and_path(self.repo)
            remote_refs = client.fetch(
                path,
                repo,
                determine_wants=lambda refs, depth=None: [self.commit.encode()],
                depth=1,
            )

    ########################################################
    #        Helper APIs for the Cargo Source to use       #
    ########################################################

    def ref_node(self):
        return {"kind": "git", "name": self.name, "version": self.version, "repo": self.repo, "commit": self.commit}

    # stage()
    #
    # A delegate method to do the work for a single git repo
    # in Source.stage().
    #
    # Args:
    #    (directory): The vendor subdirectory to stage to
    #
    def stage(self, directory):
        self.cargo.status(f"Checking out {self.commit}")

        crate_target_dir = os.path.join(directory, f"{self.name}-{self.version}")
        tmp_dir = os.path.join(directory, f"{self.name}-{self.version}-tmp")

        try:
            os.mkdir(tmp_dir)
        except FileExistsError:
            raise SourceError(
                f"This project requests crate {self.name} {self.version} from multiple sources, "
                "which is incompatible with vendoring since cargo does not support it."
            )

        with Repo(self._get_mirror_dir(), bare=True) as mirror:
            with Repo.init(tmp_dir) as dest:
                dest.object_store.add_object(mirror[self.commit.encode()])
                dest.refs[b"HEAD"] = self.commit.encode()
                dest.update_shallow([self.commit.encode()], [])

            with Repo(tmp_dir, object_store=mirror.object_store) as dest:
                dest.reset_index()

        # Workspace handling
        #
        # When new workspace features are added it is worth checking if
        # <https://github.com/flatpak/flatpak-builder-tools/blob/HEAD/cargo/flatpak-cargo-generator.py>
        # has implemented them already. This implementation is inspired by the mentioned source.

        with open(os.path.join(tmp_dir, "Cargo.toml"), "rb") as f:
            root_toml = tomllib.load(f)

        crates = {}

        if "workspace" in root_toml:
            # Find wanted crate inside workspace
            for member in root_toml["workspace"].get("members", []):
                for crate_toml_path in glob.glob(os.path.join(tmp_dir, member, "Cargo.toml")):
                    crate_path = os.path.normpath(os.path.dirname(crate_toml_path))

                    with open(crate_toml_path, "rb") as f:
                        crate_toml = tomllib.load(f)
                        crates[crate_toml["package"]["name"]] = {
                            "config": crate_toml,
                            "path": crate_path,
                        }

            crate = crates[self.name]
            # Apply information inherited from workspace Cargo.toml
            config_inherit_workspace(crate["config"], root_toml["workspace"])

            with open(os.path.join(crates[self.name]["path"], "Cargo.toml"), "bw") as f:
                tomli_w.dump(crate["config"], f)

            shutil.move(crate["path"], crate_target_dir)
        else:
            # No workspaces involved, just reploy complete dir as is
            shutil.move(tmp_dir, crate_target_dir)

        # Write .cargo-checksum.json required by cargo vendoring
        with open(os.path.join(crate_target_dir, ".cargo-checksum.json"), "w") as f:
            json.dump({"files": {}, "package": None}, f)

        shutil.rmtree(tmp_dir, ignore_errors=True)

    # is_cached()
    #
    # Get whether we have a local cached version of the git commit
    #
    # Returns:
    #   (bool): Whether we are cached or not
    #
    def is_cached(self):
        with Repo(self._get_mirror_dir(), bare=True) as repo:
            return self.commit.encode() in repo

    # is_resolved()
    #
    # Get whether the current git repo is resolved
    #
    # Returns:
    #   (bool): Always true since we always have a commit
    #
    def is_resolved(self):
        return True

    ########################################################
    #                   Private helpers                    #
    ########################################################

    # _get_mirror_dir()
    #
    # Gets the local mirror directory for this upstream git repository
    #
    def _get_mirror_dir(self):
        if self.repo.endswith(".git"):
            norm_url = self.repo[:-4]
        else:
            norm_url = self.repo

        return os.path.join(
            self.cargo.get_mirror_directory(),
            utils.url_directory_name(norm_url) + ".git",
        )

    # _get_url()
    #
    # Gets the git URL to download this crate from
    #
    # Args:
    #    alias (str|None): The URL alias to apply, if any
    #
    # Returns:
    #    (str): The URL for this crate
    #
    def _get_url(self, alias=None):
        return self.cargo.translate_url(self.repo, alias_override=alias)

    # _mirror_repo()
    #
    # Returns the mirror repo, initialized if it doesn not exist yet
    #
    # Returns:
    #    (Repo): The mirror repo crate
    #
    def _mirror_repo(self):
        try:
            return Repo.init_bare(self._get_mirror_dir(), mkdir=True)
        except FileExistsError:
            return Repo(self._get_mirror_dir(), bare=True)


# config_inherit_workspace()
#
# Cargo workspaces can define different values that can be inherited by member crates.
# The values that can be inherited are currently package information like the license
# (see `inherit_package()`) and settings for dependencies like the required version
# (see `inherit_deps`).
#
# Args:
#    config (dict): Crate config
#    workspace_config (dict): Workspace config
def config_inherit_workspace(config, workspace_config):
    workspace_deps = workspace_config.get("dependencies")
    if workspace_deps is not None:
        dependencies = []

        # Find all dependency lists that can inherit from the workspace
        # <https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#inheriting-a-dependency-from-a-workspace>
        for key in ["dependencies", "dev-dependencies", "build-dependencies"]:
            if key in config:
                dependencies.append(config[key])
        if "target" in config:
            for target in config["target"].values():
                if "dependencies" in target:
                    dependencies.append(target["dependencies"])

        for deps in dependencies:
            inherit_deps(deps, workspace_deps)

    workspace_package = workspace_config.get("package")
    if workspace_package is not None:
        inherit_package(config["package"], workspace_package)


# inherit_package()
#
# Modifies the values in `items` that are configured to inherit from the workspace.
# The new values are taken from `workspace_items`.
# <https://doc.rust-lang.org/cargo/reference/workspaces.html#the-package-table>
#
# Args:
#    items (dict): The crate's [package] items
#    workspace_items (dict): Workspace's [package] items
def inherit_package(items, workspace_items):
    for key, value in items.items():
        if isinstance(value, dict) and "workspace" in value:
            workspace_value = workspace_items.get(key)
            if workspace_value is None:
                raise SourceError(
                    f"Failed to inherit 'package.{key}' in crate's Cargo.toml. "
                    "Value missing from workspace's Cargo.toml."
                )

            items[key] = workspace_value


# inherit_deps()
#
# Modifies the values in `deps` if they are set to inherit information from the workspace.
# The new values are taken from `workspace_deps`.
# <https://doc.rust-lang.org/cargo/reference/workspaces.html#the-dependencies-table>
#
# Args:
#    deps (dict): A dependencies section like from [dev-dependencies]
#    workspace_deps (dict): Workspace dependency table
def inherit_deps(deps, workspace_deps):
    for crate, details in deps.items():
        if isinstance(details, dict) and "workspace" in details:
            workspace_details = workspace_deps.get(crate)
            if workspace_details is None:
                raise SourceError(
                    "Failed to inherit dependency information for '{crate}' in crate's Cargo.toml. "
                    "Value missing from workspace's Cargo.toml."
                )

            # Workspace definition is a dict
            if isinstance(workspace_details, dict):
                del details["workspace"]
                details.update(workspace_details)
            # Workspace definition is just a version
            else:
                del details["workspace"]
                details.update({"version": workspace_details})


class CargoSource(Source):
    BST_MIN_VERSION = "2.0"

    # We need the Cargo.lock file to construct our ref at track time
    BST_REQUIRES_PREVIOUS_SOURCES_TRACK = True

    ########################################################
    #       Plugin/Source API method implementations       #
    ########################################################
    def configure(self, node):
        # The url before any aliasing
        #
        self.url = node.get_str("url", "https://static.crates.io/crates")
        self.cargo_lock = node.get_str("cargo-lock", "Cargo.lock")
        self.vendor_dir = node.get_str("vendor-dir", "crates")

        node.validate_keys(Source.COMMON_CONFIG_KEYS + ["url", "ref", "cargo-lock", "vendor-dir"])

        # Needs to be marked here so that `track` can translate it later.
        self.mark_download_url(self.url)

        self.load_ref(node)

    def preflight(self):
        return

    def get_unique_key(self):
        return [self.url, self.cargo_lock, self.vendor_dir, self.ref]

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

            ref = {}

            (kind, url) = package["source"].split("+", 2)
            ref["kind"] = kind

            if kind not in ["git", "registry"]:
                raise SourceError(f"Unkown source kind '{kind}' for crate {package['name']}")

            if kind == "git":
                url_parsed = urlparse(url)
                ref["commit"] = url_parsed.fragment
                # Remove extra information since it confused URL translation
                ref["repo"] = url_parsed._replace(fragment="", query="").geturl()

            ref.update({"name": package["name"], "version": str(package["version"])})

            if kind == "registry":
                ref["sha"] = package.get("checksum")

            new_ref.append(ref)

        # Make sure the order we set it at track time is deterministic
        new_ref = sorted(new_ref, key=lambda c: (c["name"], c["version"], c.get("repo", ""), c.get("commit", "")))

        # Download the crates and get their shas
        for crate_obj in new_ref:
            if crate_obj["kind"] != "registry" or crate_obj["sha"] is not None:
                continue

            crate = CrateRegistry(self, crate_obj["name"], crate_obj["version"])

            crate_url = crate._get_url()
            with self.timed_activity("Downloading: {}".format(crate_url), silent_nested=True):
                crate_obj["sha"] = crate._download(crate_url)

        return new_ref

    def stage(self, directory):
        # Stage the crates into the vendor directory
        vendor_dir = os.path.join(directory, self.vendor_dir)

        git_repos = set()
        for crate in self.crates:
            crate.stage(vendor_dir)
            if isinstance(crate, CrateGit):
                git_repos.add(crate.repo)

        # Every git repo needs an extra entry in the config
        # Using a set since the config entry cannot appear twice
        vendor_cfg_git = ""
        for repo in git_repos:
            vendor_cfg_git += _git_vendor_config_template.format(git_repo=repo)

        # Stage our vendor config
        vendor_config = _default_vendor_config_template.format(
            vendorurl=self.translate_url(self.url), vendordir=self.vendor_dir, git_vendors=vendor_cfg_git
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

        self.ref = [crate.ref_node() for crate in self.crates]

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

        crates = []

        for crate in refs:
            kind = crate.get_str("kind", default="registry")
            if kind == "git":
                crates.append(
                    CrateGit(
                        self,
                        crate.get_str("name"),
                        crate.get_str("version"),
                        crate.get_str("repo"),
                        crate.get_str("commit"),
                    )
                )
            else:
                crates.append(
                    CrateRegistry(
                        self,
                        crate.get_str("name"),
                        crate.get_str("version"),
                        sha=crate.get_str("sha", None),
                    )
                )

        return crates


def setup():
    return CargoSource
