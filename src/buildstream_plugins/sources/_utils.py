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
# Mostly copied from downloadablefilesource.py in buildstream.
#

import contextlib
import shutil
import os
import netrc
import urllib.parse
import urllib.request
import urllib.error


class _NetrcPasswordManager:
    def __init__(self, netrc_config):
        self.netrc = netrc_config

    def add_password(self, realm, uri, user, passwd):
        pass

    def find_user_password(self, realm, authuri):
        if not self.netrc:
            return None, None
        parts = urllib.parse.urlsplit(authuri)
        entry = self.netrc.authenticators(parts.hostname)
        if not entry:
            return None, None
        else:
            login, _, password = entry
            return login, password


def _parse_netrc():
    netrc_config = None
    try:
        netrc_config = netrc.netrc()
    except (OSError, netrc.NetrcParseError):
        # If the .netrc file was not found, FileNotFoundError will be
        # raised, but OSError will be raised directly by the netrc package
        # in the case that $HOME is not set.
        #
        # This will catch both cases.
        pass

    return netrc_config


class _UrlOpenerCreator:
    def __init__(self, netrc_config):
        self.netrc_config = netrc_config

    def get_url_opener(self, bearer_auth):
        if self.netrc_config and not bearer_auth:
            netrc_pw_mgr = _NetrcPasswordManager(self.netrc_config)
            http_auth = urllib.request.HTTPBasicAuthHandler(netrc_pw_mgr)
            return urllib.request.build_opener(http_auth)
        return urllib.request.build_opener()


def download_file(url, etag, directory, auth_scheme):
    opener_creator = _UrlOpenerCreator(_parse_netrc())
    opener = opener_creator.get_url_opener(auth_scheme == "bearer")
    default_name = os.path.basename(url)
    request = urllib.request.Request(url)
    request.add_header("Accept", "*/*")
    request.add_header("User-Agent", "BuildStream/2")

    if opener_creator.netrc_config and auth_scheme == "bearer":
        parts = urllib.parse.urlsplit(url)
        entry = opener_creator.netrc_config.authenticators(parts.hostname)
        if entry:
            _, _, password = entry
            auth_header = "Bearer " + password
            request.add_header("Authorization", auth_header)

    if etag is not None:
        request.add_header("If-None-Match", etag)

    try:
        with contextlib.closing(opener.open(request)) as response:
            info = response.info()

            # some servers don't honor the 'If-None-Match' header
            if etag and info["ETag"] == etag:
                return None, None, None

            etag = info["ETag"]
            length = info.get("Content-Length")

            filename = info.get_filename(default_name)
            filename = os.path.basename(filename)
            local_file = os.path.join(directory, filename)
            with open(local_file, "wb") as dest:
                shutil.copyfileobj(response, dest)

                actual_length = dest.tell()
                if length and actual_length < int(length):
                    raise ValueError(f"Partial file {actual_length}/{length}")

    except urllib.error.HTTPError as e:
        if e.code == 304:
            # 304 Not Modified.
            # Because we use etag only for matching ref, currently specified ref is what
            # we would have downloaded.
            return None, None, None

        return None, None, str(e)
    except (urllib.error.URLError, OSError, ValueError) as e:
        # Note that urllib.request.Request in the try block may throw a
        # ValueError for unknown url types, so we handle it here.
        return None, None, str(e)

    return local_file, etag, None
