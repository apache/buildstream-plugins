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

# Pylint and responses don't play well together
# pylint: disable=no-member

import os
import pytest
import responses
from ruamel.yaml import YAML

from buildstream.exceptions import ErrorDomain
from buildstream._testing import cli  # pylint: disable=unused-import

DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "docker")


def create_element(yaml, element_name, element_payload, project):
    with open(os.path.join(project, "elements", element_name), "w", encoding="utf-8") as element_handle:
        yaml.dump(element_payload, element_handle)


@pytest.mark.datafiles(DATA_DIR)
def test_docker_fetch(cli, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    result = cli.run(project=project, args=["source", "fetch", "dockerhub-alpine.bst"])
    result.assert_success()


@pytest.mark.datafiles(DATA_DIR)
def test_docker_source_checkout(cli, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    checkout = os.path.join(cli.directory, "checkout")
    result = cli.run(
        project=project,
        args=[
            "source",
            "checkout",
            "--directory",
            checkout,
            "dockerhub-alpine.bst",
        ],
    )
    result.assert_success()
    # Rather than make assertions about the whole Alpine Linux image, verify
    # that the /etc/os-release file exists as a sanity check.
    assert os.path.isfile(os.path.join(checkout, "dockerhub-alpine/etc/os-release"))


@pytest.mark.datafiles(DATA_DIR)
@responses.activate
def test_handle_network_error(cli, datafiles):
    # allow manifest to be fetched
    responses.add_passthru(
        "https://registry.hub.docker.com/v2/library/alpine/manifests/"
        "sha256%3A4b8ffaaa896d40622ac10dc6662204f429f1c8c5714be62a6493a7895f66409"
    )
    # allow authentication to go through
    responses.add_passthru(
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/alpine:pull"
    )
    # By not adding a rule for the blob, accessing
    # "https://registry.hub.docker.com/v2/" \
    #           "library/alpine/blobs/sha256%3Ab56ae66c29370df48e7377c8f9baa744a3958058a766793f821dadcb144a4647"
    # will throw a `ConnectionError`.

    # attempt to fetch source
    project = os.path.join(datafiles.dirname, datafiles.basename)
    result = cli.run(project=project, args=["source", "fetch", "dockerhub-alpine.bst"])
    # check that error is thrown
    result.assert_task_error(ErrorDomain.SOURCE, None)

    # check that BuildStream still runs normally
    result = cli.run(project=project, args=["show", "dockerhub-alpine.bst"])
    result.assert_success()


@pytest.mark.datafiles(DATA_DIR)
def test_fetch_duplicate_layers(cli, datafiles):
    # test that fetching a layer twice does not break the mirror directory

    project = str(datafiles)
    yaml = YAML()
    yaml.default_flow_style = False

    # images to pull
    alpine_element = "alpine.bst"
    alpine310 = {
        "kind": "import",
        "sources": [{"kind": "docker", "image": "library/alpine", "track": "3.10"}],
    }
    create_element(yaml, alpine_element, alpine310, project)
    cli.run(project=project, args=["source", "track", alpine_element]).assert_success()
    cli.run(project=project, args=["source", "fetch", alpine_element]).assert_success()

    # this image uses alpine3:10 as base a base layer
    # shared layer has digest 03901b4a2ea88eeaad62dbe59b072b28b6efa00491962b8741081c5df50c65e0
    python36_element = "python36.bst"
    python36_alpine310 = {
        "kind": "import",
        "sources": [
            {
                "kind": "docker",
                "image": "library/python",
                "track": "3.6-alpine3.10",
            }
        ],
    }
    create_element(yaml, python36_element, python36_alpine310, project)
    cli.run(project=project, args=["source", "track", python36_element]).assert_success()
    cli.run(project=project, args=["source", "fetch", python36_element]).assert_success()
