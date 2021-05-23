# SPDX-License-Identifier: MIT

import io
import os
import os.path
import pathlib
import sys
import tempfile
import zipfile

from typing import Sequence

import packaging
import resolvelib

import resolver
import resolver.mindeps


try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata  # type: ignore


def _project_requirements() -> Sequence[str]:
    import build
    import pep517.wrappers

    old_stdout, sys.stdout = sys.stdout, io.StringIO()
    builder = build.ProjectBuilder('.', runner=pep517.wrappers.quiet_subprocess_runner)
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            path = pathlib.Path(builder.prepare('wheel', tmpdir))
        except TypeError:
            wheel = builder.build('wheel', tmpdir)
            match = resolver._WHEEL_NAME_REGEX.match(os.path.basename(wheel))
            if not match:
                raise ValueError('Invalid wheel')
            path = zipfile.Path(wheel) / '{}-{}.dist-info'.format(
                match['distribution'],
                match['version'],
            )

        requirements = importlib_metadata.PathDistribution(path).metadata.get_all('Requires-Dist', [])

    sys.stdout = old_stdout
    assert isinstance(requirements, list)
    return requirements


def task() -> None:
    package_resolver = resolvelib.Resolver(
        resolver.mindeps.MinimumDependencyProvider(
            '/tmp/resolver-cache' if os.name == 'posix' else None
        ),
        resolvelib.BaseReporter(),
    )

    requirements = sys.argv[1:] if sys.argv[1:] else _project_requirements()

    extras = {''}
    result = package_resolver.resolve(
        requirement
        for extra in extras
        for requirement in map(packaging.requirements.Requirement, requirements)
        if not requirement.marker or requirement.marker.evaluate({'extra': extra})
    )

    pinned = {
        candidate.name: candidate.version
        for candidate in result.mapping.values()
    }
    for name, version in pinned.items():
        print(f'{name}=={str(version)}')


def main() -> None:
    try:
        task()
    except KeyboardInterrupt:
        print('Exiting...')


def entrypoint() -> None:
    main()


if __name__ == '__main__':
    main()
