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
# This plugin was originally developped in the https://gitlab.com/BuildStream/bst-plugins-experimental/
# repository and was copied from a60426126e5bec2d630fcd889a9f5af13af00ea6
#

"""
meson - Meson build element
===========================
This is a `BuildElement
<https://docs.buildstream.build/master/buildstream.buildelement.html#module-buildstream.buildelement>`_
implementation for using `Meson <http://mesonbuild.com/>`_ build scripts.

You will often want to pass additional arguments to ``meson``. This should
be done on a per-element basis by setting the ``meson-local`` variable.  Here is
an example:

.. code:: yaml

   variables:
     meson-local: |
       -Dmonkeys=yes

If you want to pass extra options to ``meson`` for every element in your
project, set the ``meson-global`` variable in your project.conf file. Here is
an example of that:

.. code:: yaml

   elements:
     meson:
       variables:
         meson-global: |
           -Dmonkeys=always

Here is the default configuration for the ``meson`` element in full:

  .. literalinclude:: ../../../src/buildstream_plugins/elements/meson.yaml
     :language: yaml

See `built-in functionality documentation
<https://docs.buildstream.build/master/buildstream.buildelement.html#core-buildelement-builtins>`_ for
details on common configuration options for build elements.
"""

from buildstream import BuildElement


# Element implementation for the 'meson' kind.
class MesonElement(BuildElement):

    BST_MIN_VERSION = "2.0"


# Plugin entry point
def setup():
    return MesonElement
