# SPDX-License-Identifier: MIT

import argparse
import io
import os
import os.path
import pathlib
import sys
import tempfile
import zipfile

from typing import Iterable, Sequence, Set

import packaging
import resolvelib

import resolver
import resolver.mindeps


try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata  # type: ignore


_MARKER_KEYS = (
    'implementation_version',
    'platform_python_implementation',
    'implementation_name',
    'python_full_version',
    'platform_release',
    'platform_version',
    'platform_machine',
    'platform_system',
    'python_version',
    'sys_platform',
    'os_name',
    'python_implementation',
)


def _error(msg: str, code: int = 1) -> None:  # pragma: no cover
    prefix = 'ERROR'
    if sys.stdout.isatty():
        prefix = '\33[91m' + prefix + '\33[0m'
    print('{} {}'.format(prefix, msg))
    exit(code)


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


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'requirements',
        type=str,
        nargs='*',
        help='requirement strings',
    )
    parser.add_argument(
        '--extras',
        '-e',
        type=str,
        default=argparse.SUPPRESS,
        nargs='*',
        help='project extras',
    )
    marker_args = parser.add_argument_group(
        title='marker arguments',
        description='values used to evaluate the project requirements',
    )
    for key in _MARKER_KEYS:
        marker_args.add_argument(
            f'--{key}',
            type=str,
            default=argparse.SUPPRESS,
        )
    return parser


def task() -> None:
    parser = main_parser()
    args = parser.parse_args()

    if args.requirements:
        for bad_arg in _MARKER_KEYS + ('extras',):
            if bad_arg in args:
                _error(f'Option --{bad_arg} not supported when specifying bare requirements')

    package_resolver = resolvelib.Resolver(
        resolver.mindeps.MinimumDependencyProvider(
            '/tmp/resolver-cache' if os.name == 'posix' else None
        ),
        resolvelib.BaseReporter(),
    )

    requirements: Iterable[packaging.requirements.Requirement] = map(
        packaging.requirements.Requirement,
        args.requirements or _project_requirements(),
    )

    extras = set(vars(args).get('extras', {})) | {''}
    marker_env = {
        k: v for k, v in vars(args).items()
        if k in _MARKER_KEYS
    }

    resolver_requirements: Set[packaging.requirements.Requirement] = set()
    for requirement in requirements:
        for extra in extras:
            if not requirement.marker:
                resolver_requirements.add(requirement)
            elif requirement.marker.evaluate(marker_env | {'extra': extra}):
                requirement.marker = None
                resolver_requirements.add(requirement)

    result = package_resolver.resolve(resolver_requirements)

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
