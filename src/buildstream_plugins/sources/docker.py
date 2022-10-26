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
#        Sam Thursfield <sam.thursfield@codethink.co.uk>
#        Chandan Singh <csingh43@bloomberg.net>

#
# This plugin was originally developped in the https://gitlab.com/BuildStream/bst-plugins-container/
# repository and was copied from 192aa75a62161b655b051d5b69f17d9233cf4dfe
#

"""
docker - stage files from Docker images
=======================================

**Usage:**

.. code:: yaml

   # Specify the docker source kind
   kind: docker

   # Specify the registry endpoint, defaults to Docker Hub (optional)
   registry-url: https://registry.hub.docker.com

   # Image path (required)
   image: library/alpine

   # Image tag to follow (optional)
   track: latest

   # Specify the digest of the exact image to use (required)
   ref: 6c9f6f68a131ec6381da82f2bff978083ed7f4f7991d931bfa767b7965ebc94b

   # Some images are built for multiple platforms. When tracking a tag, we
   # will choose which image to use based on these settings. Default values
   # are chosen based on the output of `uname -m` and `uname -s`, but you
   # can override them.
   #architecture: arm64
   #os: linux

Note that Docker images may contain device nodes. BuildStream elements cannot
contain device nodes so those will be dropped. Any regular files in the /dev
directory will also be dropped.

See `built-in functionality doumentation
<https://docs.buildstream.build/master/buildstream.source.html#core-source-builtins>`_ for
details on common configuration options for sources.
"""

import hashlib
import json
import os
import platform
import shutil
import tarfile
import urllib.parse

import requests

from buildstream import Source, SourceError
from buildstream.utils import (
    save_file_atomic,
    sha256sum,
    link_files,
    move_atomic,
)

_DOCKER_HUB_URL = "https://registry.hub.docker.com"


def parse_bearer_authorization_challenge(text):
    # Hand-written and probably broken parsing of the Www-Authenticate
    # response. I can't find a built-in way to parse this, but I probably
    # didn't look hard enough.
    if not text.startswith("Bearer "):
        raise SourceError("Unexpected Www-Authenticate response: %{}".format(text))

    pairs = {}
    text = text[len("Bearer ") :]
    for pair in text.split(","):
        key, value = pair.split("=")
        pairs[key] = value[1:-1]
    return pairs


def default_architecture():
    machine = platform.machine()
    if machine == "x86_64":
        return "amd64"
    elif machine == "aarch64":
        return "arm64"
    else:
        return machine


def default_os():
    return platform.system().lower()


# Variant of urllib.parse.urljoin() allowing multiple path components at once.
def urljoin(url, *args):
    for arg in args:
        if not url.endswith("/"):
            url += "/"
        url = urllib.parse.urljoin(url, arg.lstrip("/"))
    return url


# DockerManifestError
#
# Raised if something goes wrong while querying an image manifest from a remote
# registry.
#
class DockerManifestError(SourceError):
    def __init__(self, message, manifest=None):
        super().__init__(message)
        self.manifest = manifest


class DockerRegistryV2Client:
    def __init__(self, endpoint, api_timeout=3):
        self.endpoint = endpoint
        self.api_timeout = api_timeout

        self.token = None

    def _request(self, subpath, extra_headers=None, stream=False, _reauthorized=False):
        if not extra_headers:
            extra_headers = {}

        headers = {"content-type": "application/json"}
        headers.update(extra_headers)

        if self.token:
            headers["Authorization"] = "Bearer {}".format(self.token)

        url = urljoin(self.endpoint, "v2", subpath)
        response = requests.get(url, headers=headers, stream=stream, timeout=self.api_timeout)

        if response.status_code == requests.codes["unauthorized"] and not _reauthorized:
            # This request requires (re)authorization. See:
            # https://docs.docker.com/registry/spec/auth/token/
            auth_challenge = response.headers["Www-Authenticate"]
            auth_vars = parse_bearer_authorization_challenge(auth_challenge)
            self._auth(auth_vars["realm"], auth_vars["service"], auth_vars["scope"])
            return self._request(subpath, extra_headers=extra_headers, _reauthorized=True)
        else:
            response.raise_for_status()

            return response

    def _auth(self, realm, service, scope):
        # Respond to an Www-Authenticate challenge by requesting the necessary
        # token from the 'realm' (endpoint) that we were given in the challenge.
        request_url = "{}?service={}&scope={}".format(realm, service, scope)
        response = requests.get(request_url, timeout=self.api_timeout)
        response.raise_for_status()
        self.token = response.json()["token"]

    # digest():
    #
    # Calculate a Docker-compatible digest of an arbitrary string of bytes.
    #
    # Args:
    #    content (bytes): Content to hash
    #
    # Returns:
    #    (str) A Docker-compatible digest of 'content'
    @staticmethod
    def digest(content):
        digest_hash = hashlib.sha256()
        digest_hash.update(content)
        return "sha256:" + digest_hash.hexdigest()

    # manifest():
    #
    # Fetches the image manifest for a given image from the remote registry.
    #
    # If this is a "fat" (multiplatform) image, the 'artitecture' and 'os'
    # parameters control which of the available images is chosen.
    #
    # The manifest is returned verbatim, so you need to parse it yourself
    # with json.loads() to get at its contents. The verbatim text can be used
    # to recalculate the content digest, just encode it and pass to .digest().
    # If we returned only the parsed JSON data you wouldn't be able to do this.
    #
    # Args:
    #    image_path (str): Relative path to the image, e.g. library/alpine
    #    reference (str): Either a tag name (such as 'latest') or the content
    #                     digest of an exact version of the image.
    #    architecture (str): Architecture name (amd64, arm64, etc.)
    #    os_ (str): OS name (e.g. linux)
    #
    # Raises:
    #    requests.RequestException, if network errors occur
    #
    # Returns:
    #    (str, str): A tuple of the manifest content as text, and its content hash
    def manifest(
        self,
        image_path,
        reference,
        architecture=default_architecture(),
        os_=default_os(),
    ):
        # pylint: disable=too-many-locals

        accept_types = [
            "application/vnd.docker.distribution.manifest.v2+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
        ]

        manifest_url = urljoin(image_path, "manifests", urllib.parse.quote(reference))
        response = self._request(manifest_url, extra_headers={"Accept": ",".join(accept_types)})

        try:
            manifest = json.loads(response.text)
        except json.JSONDecodeError as e:
            raise DockerManifestError(
                "Server did not return a valid manifest: {}".format(e),
                manifest=response.text,
            ) from e

        schema_version = manifest.get("schemaVersion")
        if schema_version == 1:
            raise DockerManifestError("Schema version 1 is unsupported.", manifest=response.text)
        if schema_version is None:
            raise DockerManifestError(
                "Manifest did not include the schemaVersion key.",
                manifest=response.text,
            )

        our_digest = self.digest(response.text.encode("utf8"))
        their_digest = response.headers.get("Docker-Content-Digest")

        if not their_digest:
            raise DockerManifestError(
                "Server did not set the Docker-Content-Digest header.",
                manifest=response.text,
            )
        if our_digest != their_digest:
            raise DockerManifestError(
                "Server returned a non-matching content digest. "
                "Our digest: {}, their digest: {}".format(our_digest, their_digest),
                manifest=response.text,
            )

        if manifest["mediaType"] == "application/vnd.docker.distribution.manifest.list.v2+json":
            # This is a "fat manifest", we need to narrow down to a specific
            # architecture.
            for sub in manifest["manifests"]:
                if sub["platform"]["architecture"] == architecture and sub["platform"]["os"]:
                    sub_digest = sub["digest"]
                    return self.manifest(
                        image_path,
                        sub_digest,
                        architecture=architecture,
                        os_=os_,
                    )
                else:
                    raise DockerManifestError(
                        "No images found for architecture {}, OS {}".format(architecture, os_),
                        manifest=response.text,
                    )
        elif manifest["mediaType"] == "application/vnd.docker.distribution.manifest.v2+json":
            return response.text, our_digest
        else:
            raise DockerManifestError(
                "Unsupported manifest type {}".format(manifest["mediaType"]),
                manifest=response.text,
            )

    # blob():
    #
    # Fetch a blob from the remote registry. This is used for getting each
    # layer of an image in tar.gz format.
    #
    # Raises:
    #    requests.RequestException, if network errors occur
    #
    # Args:
    #    image_path (str): Relative path to the image, e.g. library/alpine
    #    blob_digest (str): Content hash of the blob.
    #    download_to (str): Path to a file where the content will be written.
    def blob(self, image_path, blob_digest, download_to):
        blob_url = urljoin(image_path, "blobs", urllib.parse.quote(blob_digest))

        response = self._request(blob_url, stream=True)

        with save_file_atomic(download_to, "wb") as f:
            shutil.copyfileobj(response.raw, f)


class ReadableTarInfo(tarfile.TarInfo):
    """
    The goal is to override`TarFile`'s `extractall` semantics by ensuring that on extraction, the
    files are readable by the owner of the file. This is done by over-riding the accessor for the
    mode` attribute in `TarInfo`, class that encapsulates the internal meta-data of the tarball,
    so that the owner-read bit is always set.
    """

    # The mode attribute is not declared as a property and so
    # this trips up the static type checker, mark this as "ignore"
    #
    @property  # type: ignore
    def mode(self):
        # ensure file is readable by owner
        return self.__permission | 0o400

    @mode.setter
    def mode(self, permission):
        self.__permission = permission


class DockerSource(Source):
    # pylint: disable=too-many-instance-attributes

    BST_MIN_VERSION = "2.0"

    # Docker identifies images by a content digest calculated from the image's
    # manifest. This corresponds well with the concept of a 'ref' in
    # BuildStream. However, Docker theoretically supports multiple hash
    # methods while BuildStream does not. Right now every Docker registry
    # uses sha256 so let's ignore that issue for the time being.
    @staticmethod
    def _digest_to_ref(digest):
        if digest.startswith("sha256:"):
            return digest[len("sha256:") :]
        else:
            method = digest.split(":")[0]
            raise SourceError("Unsupported digest method: {}".format(method))

    @staticmethod
    def _ref_to_digest(ref):
        return "sha256:" + ref

    def configure(self, node):
        # url is deprecated, but accept it as a valid key so that we can raise
        # a nicer warning.
        node.validate_keys(["registry-url", "image", "ref", "track", "url"] + Source.COMMON_CONFIG_KEYS)

        if "url" in node:
            raise SourceError(
                "{}: 'url' parameter is now deprecated, " "use 'registry-url' and 'image' instead.".format(self)
            )

        self.image = node.get_str("image")
        self.original_registry_url = node.get_str("registry-url", _DOCKER_HUB_URL)
        self.registry_url = self.translate_url(self.original_registry_url)

        if "ref" in node:
            self.digest = self._ref_to_digest(node.get_str("ref"))
        else:
            self.digest = None
        self.tag = node.get_str("track", "") or None

        self.architecture = node.get_str("architecture", "") or default_architecture()
        self.os = node.get_str("os", "") or default_os()

        if not (self.digest or self.tag):
            raise SourceError("{}: Must specify either 'ref' or 'track' parameters".format(self))

        self.client = DockerRegistryV2Client(self.registry_url)

        self.manifest = None

    def preflight(self):
        return

    def get_unique_key(self):
        return [self.original_registry_url, self.image, self.digest]

    def get_ref(self):
        return None if self.digest is None else self._digest_to_ref(self.digest)

    def set_ref(self, ref, node):
        node["ref"] = ref
        self.digest = self._ref_to_digest(ref)

    def track(self):
        # pylint: disable=arguments-differ

        # If the tracking ref is not specified it's not an error, just silently return
        if not self.tag:
            return None

        with self.timed_activity(
            "Fetching image manifest for image: '{}:{}' from: {}".format(self.image, self.tag, self.registry_url)
        ):
            try:
                _, digest = self.client.manifest(self.image, self.tag)
            except DockerManifestError as e:
                self.log("Problem downloading manifest", detail=e.manifest)
                raise
            except (OSError, requests.RequestException) as e:
                raise SourceError(e) from e

        return self._digest_to_ref(digest)

    def is_resolved(self):
        return self.digest is not None

    def is_cached(self):
        mirror_dir = self.get_mirror_directory()
        try:
            manifest = self._load_manifest()

            for layer in manifest["layers"]:
                layer_digest = layer["digest"]
                blob_path = os.path.join(mirror_dir, layer_digest + ".tar.gz")
                try:
                    self._verify_blob(blob_path, expected_digest=layer_digest)
                except FileNotFoundError:
                    # digest fetched, but some layer blob not fetched
                    return False
            return True
        except (FileNotFoundError, SourceError):
            return False

    def _load_manifest(self):
        manifest_file = os.path.join(self.get_mirror_directory(), self.digest + ".manifest.json")

        with open(manifest_file, "rb") as f:
            text = f.read()

        real_digest = self.client.digest(text)
        if real_digest != self.digest:
            raise SourceError("Manifest {} is corrupt; got content hash of {}".format(manifest_file, real_digest))

        return json.loads(text.decode("utf-8"))

    def _save_manifest(self, text, path):
        manifest_file = os.path.join(path, self.digest + ".manifest.json")
        with save_file_atomic(manifest_file, "wb") as f:
            f.write(text.encode("utf-8"))

    @staticmethod
    def _verify_blob(path, expected_digest):
        blob_digest = "sha256:" + sha256sum(path)
        if expected_digest != blob_digest:
            raise SourceError("Blob {} is corrupt; got content hash of {}.".format(path, blob_digest))

    def fetch(self):
        # pylint: disable=arguments-differ

        with self.timed_activity(
            "Fetching image {}:{} with digest {}".format(self.image, self.tag, self.digest),
            silent_nested=True,
        ):
            with self.tempdir() as tmpdir:
                # move all files to a tmpdir
                try:
                    manifest = self._load_manifest()
                except FileNotFoundError as e:
                    try:
                        manifest_text, digest = self.client.manifest(self.image, self.digest)
                    except requests.RequestException as ee:
                        raise SourceError(ee) from ee

                    if digest != self.digest:
                        raise SourceError(
                            "Requested image {}, got manifest with digest {}".format(self.digest, digest)
                        ) from e
                    self._save_manifest(manifest_text, tmpdir)
                    manifest = json.loads(manifest_text)
                except DockerManifestError as e:
                    self.log("Unexpected manifest", detail=e.manifest)
                    raise
                except (OSError, requests.RequestException) as e:
                    raise SourceError(e) from e

                for layer in manifest["layers"]:
                    if layer["mediaType"] != "application/vnd.docker.image.rootfs.diff.tar.gzip":
                        raise SourceError("Unsupported layer type: {}".format(layer["mediaType"]))

                    layer_digest = layer["digest"]
                    blob_path = os.path.join(tmpdir, layer_digest + ".tar.gz")

                    if not os.path.exists(blob_path):
                        try:
                            self.client.blob(self.image, layer_digest, download_to=blob_path)
                        except (OSError, requests.RequestException) as e:
                            if os.path.exists(blob_path):
                                shutil.rmtree(blob_path)
                            raise SourceError(e) from e

                    self._verify_blob(blob_path, expected_digest=layer_digest)

                # Only if all sources are successfully fetched, move files to staging directory

                # As both the manifest and blobs are content addressable, we can optimize space by having
                # a flat mirror directory. We check one-by-one if there is any need to copy a file out of the tmpdir.
                for fetched_file in os.listdir(tmpdir):
                    move_atomic(
                        os.path.join(tmpdir, fetched_file),
                        os.path.join(self.get_mirror_directory(), fetched_file),
                    )

    def stage(self, directory):
        mirror_dir = self.get_mirror_directory()

        try:
            manifest = self._load_manifest()
        except (OSError, SourceError) as e:
            raise SourceError("Unable to load manifest: {}".format(e)) from e

        try:
            for layer in manifest["layers"]:
                layer_digest = layer["digest"]
                blob_path = os.path.join(mirror_dir, layer_digest + ".tar.gz")

                self._verify_blob(blob_path, expected_digest=layer_digest)
                (
                    extract_fileset,
                    white_out_fileset,
                ) = self._get_extract_and_remove_files(blob_path)

                # remove files associated with whiteouts
                for white_out_file in white_out_fileset:
                    white_out_file = os.path.join(directory, white_out_file)
                    os.remove(white_out_file)

                # extract files for the current layer
                with tarfile.open(blob_path, tarinfo=ReadableTarInfo) as tar:
                    with self.tempdir() as td:
                        tar.extractall(path=td, members=extract_fileset)
                        link_files(td, directory)

        except (OSError, SourceError, tarfile.TarError) as e:
            raise SourceError("{}: Error staging source: {}".format(self, e)) from e

    @staticmethod
    def _get_extract_and_remove_files(layer_tar_path):
        """Return the set of files to remove and extract for a given layer

        :param layer_tar_path: The path where a layer has been extracted
        :return: Tuple of filesets
          - extract_fileset: files to extract into staging directory
          - delete_fileset: files to remove from staging directory as the current layer
            contains a whiteout corresponding to a staged file in the previous layers

        """

        def strip_wh(white_out_file):
            """Strip the prefixing .wh. for given file

            :param white_out_file: path of file
            :return: path without white-out prefix
            """
            # whiteout files have the syntax of `*/.wh.*`
            file_name = os.path.basename(white_out_file)
            path = os.path.join(os.path.dirname(white_out_file), file_name.split(".wh.")[1])
            return path

        def is_regular_file(info):
            """Check if file is a non-device file

            :param info: tar member metadata
            :return: if the file is a non-device file
            """
            return not (info.name.startswith("dev/") or info.isdev())

        with tarfile.open(layer_tar_path) as tar:
            extract_fileset = []
            delete_fileset = []
            for member in tar.getmembers():
                if os.path.basename(member.name).startswith(".wh."):
                    delete_fileset.append(strip_wh(member.name))
                elif is_regular_file(member):
                    extract_fileset.append(member)

        return extract_fileset, delete_fileset


# Plugin entry point
def setup():
    return DockerSource
