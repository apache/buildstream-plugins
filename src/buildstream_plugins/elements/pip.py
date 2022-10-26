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
#        Mathieu Bridon <bochecha@daitauha.fr>

#
# This plugin was originally developped in the https://gitlab.com/BuildStream/bst-plugins-experimental/
# repository and was copied from a60426126e5bec2d630fcd889a9f5af13af00ea6
#

"""
pip - Pip build element
=======================
A `BuildElement
<https://docs.buildstream.build/master/buildstream.buildelement.html#module-buildstream.buildelement>`_
implementation for installing Python modules with pip

The pip default configuration:
  .. literalinclude:: ../../../src/buildstream_plugins/elements/pip.yaml
     :language: yaml

See `built-in functionality documentation
<https://docs.buildstream.build/master/buildstream.buildelement.html#core-buildelement-builtins>`_ for
details on common configuration options for build elements.
"""

from buildstream import BuildElement


# Element implementation for the 'pip' kind.
class PipElement(BuildElement):

    BST_MIN_VERSION = "2.0"


# Plugin entry point
def setup():
    return PipElement
