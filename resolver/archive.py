# SPDX-License-Identifier: MIT

from __future__ import annotations

import functools
import os
import pathlib
import re
import shutil
import typing
import urllib.request
import zipfile

from typing import Iterable

import packaging.tags


try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata  # type: ignore


if typing.TYPE_CHECKING:
    # PackageMetadata is not public - https://bugs.python.org/issue44210
    import importlib_metadata as _importlib_metadata
    import mousebender.simple


_WHEEL_NAME_REGEX = re.compile(
    r'(?P<distribution>.+)-(?P<version>.+)'
    r'(-(?P<build_tag>.+))?-(?P<python_tag>.+)'
    r'-(?P<abi_tag>.+)-(?P<platform_tag>.+).whl'
)


class Archive():
    def __init__(
        self,
        url: str,
        filename: str,
        cache_directory: str,
    ) -> None:
        self._url = url
        self._filename = filename
        self._cache = pathlib.Path(cache_directory)

    @staticmethod
    def from_archive_link(
        archive_link: mousebender.simple.ArchiveLink,
        cache_directory: str,
    ) -> Archive:
        # XXX: Add support for sdists
        if archive_link.filename.endswith('.whl'):
            return WheelArchive(archive_link.url, archive_link.filename, cache_directory)
        raise ValueError('Unsupported distribution')

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self._filename})'

    @functools.cached_property
    def file(self) -> pathlib.Path:
        path = self._cache / self._filename

        if path.exists() and not path.is_file():
            raise ValueError(f'Path `{os.fspath(path)}` exists and is not a file')

        if not path.is_file():
            with urllib.request.urlopen(self._url) as r, path.open('wb') as f:
                shutil.copyfileobj(r, f)

        return path

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def version(self) -> str:
        raise NotImplementedError

    @functools.cached_property
    def metadata(self) -> _importlib_metadata.PackageMetadata:
        raise NotImplementedError

    @functools.cached_property
    def tags(self) -> Iterable[packaging.tags.Tag]:
        raise NotImplementedError


class WheelArchive(Archive):
    def __init__(
        self,
        url: str,
        filename: str,
        cache_directory: str,
    ) -> None:
        super().__init__(url, filename, cache_directory)
        match = _WHEEL_NAME_REGEX.match(filename)
        if not match:
            raise ValueError('Invalid wheel name')
        self._wheel_info = match.groupdict()

    @property
    def name(self) -> str:
        return self._wheel_info['distribution']

    @property
    def version(self) -> str:
        return self._wheel_info['version']

    @property
    def _dist_info(self) -> zipfile.Path:
        return zipfile.Path(self.file) / '{}-{}.dist-info'.format(self.name, self.version)

    @functools.cached_property
    def metadata(self) -> _importlib_metadata.PackageMetadata:
        return importlib_metadata.PathDistribution(
            typing.cast(pathlib.Path, self._dist_info)
        ).metadata

    @functools.cached_property
    def tags(self) -> Iterable[packaging.tags.Tag]:
        '''
        # XXX: Using the metadata is expensive so let's generate from the wheel compressed tag, as per PEP 425
        m = email.message_from_bytes((self._dist_info / 'WHEEL').read_bytes())
        for tag in m.get_all('Tag', []):
            yield from packaging.tags.parse_tag(tag)
        '''
        return {
            packaging.tags.Tag(python, abi, plat)
            for python in self._wheel_info['python_tag'].split('.')
            for abi in self._wheel_info['abi_tag'].split('.')
            for plat in self._wheel_info['platform_tag'].split('.')
        }
