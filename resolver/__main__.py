# SPDX-License-Identifier: MIT

import os
import sys

import packaging.requirements
import resolvelib

import resolver


def task() -> None:
    package_resolver = resolvelib.Resolver(
        resolver.Provider('/tmp/resolver-cache' if os.name == 'posix' else None),
        resolvelib.BaseReporter(),
    )
    result = package_resolver.resolve(
        packaging.requirements.Requirement(arg)
        for arg in sys.argv[1:]
    )

    print('--- Pinned Candidates ---')
    for key, candidate in result.mapping.items():
        print(f'{key.name}: {candidate.name} {candidate.version}')

    print('\n--- Dependency Graph ---')
    for key in result.graph:
        targets = ', '.join(str(child) for child in result.graph.iter_children(key))
        print(f'{key} -> {targets}')


def main() -> None:
    try:
        task()
    except KeyboardInterrupt:
        print('Exiting...')


def entrypoint() -> None:
    main()


if __name__ == '__main__':
    main()
