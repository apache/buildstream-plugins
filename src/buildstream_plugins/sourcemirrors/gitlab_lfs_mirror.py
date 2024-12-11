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

"""
gitlab_lfs_mirror - plugin for accessing files stored in git-lfs on GitLab
==========================================================================

.. note::

   The ``gitlab_lfs_mirror`` plugin is available *Since 2.4.0*

If you store files in a git-lfs repository on gitlab.com, you can access
them using a URL like

https://gitlab.com/path/to/repo/-/raw/master/path/to/file

which you can then use as a mirror for buildstream. However this only works for
public repositories. For internal (on self-hosted GitLab instances) and private
repositories, the above doesn't work since buildstream cannot authenticate with
the GitLab web UI.

This plugin solves this by going through the GitLab REST API. You need an
access token that access the Repository Files API (i.e. with read_api or
read_repository scope). As of this writing, the GitLab CI/CD job token doesn't
allow access to this API endpoint, so you need a dedicated access token.

**Usage:**

.. code:: yaml

   - name: my-mirror
     kind: gitlab_lfs_mirror
     config:
       url: https://gitlab.example.com/
       project: mirrors/{alias}
       ref: main # optional, defaults to master
       aliases:
       - my-alias
       - another-alias
"""

from posixpath import join
from urllib.parse import quote

from buildstream import SourceMirror


class GitlabLFSMirror(SourceMirror):
    BST_MIN_VERSION = "2.2"

    def configure(self, node):
        node.validate_keys(["aliases", "url", "project", "ref"])
        self.set_supported_aliases(node.get_str_list("aliases"))

        self.url = node.get_str("url")
        self.project = node.get_str("project")
        self.ref = node.get_str("ref", "master")

    def translate_url(self, *, alias, alias_url, source_url, extra_data):
        project_id = quote(self.project.format(alias=alias), safe="")
        filename = quote(source_url, safe="")

        translated_url = join(
            self.url,
            "api/v4/projects",
            project_id,
            "repository/files",
            filename,
            f"raw?ref={self.ref}&lfs=true",
        )

        if extra_data is not None:
            extra_data["http-auth"] = "bearer"

        return translated_url


def setup():
    return GitlabLFSMirror
