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
simple_mirror - plugin for simplifying mirror definitions
=========================================================

.. note::

   The ``simple_mirror`` plugin is available *Since 2.4.0*

**Usage:**

.. code:: yaml

   - name: my-mirror
     kind: simple_mirror
     config:
       url: https://example.com/mirrors/{alias}/
       aliases:
       - my-alias
       - another-alias

This plugin simplifies defining mirrors for projects where the mirrors follow
a predictable URL format that only varies with the alias name.
"""

from posixpath import join
from buildstream import SourceMirror


class SimpleMirror(SourceMirror):
    BST_MIN_VERSION = "2.2"

    def configure(self, node):
        node.validate_keys(["url", "aliases"])
        self.set_supported_aliases(node.get_str_list("aliases"))

        self.url = node.get_str("url")

    def translate_url(self, alias, alias_url, source_url, extra_data):
        base_url = self.url.format(alias=alias)
        translated_url = join(base_url, source_url)

        return translated_url


def setup():
    return SimpleMirror
