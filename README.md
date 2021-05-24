# python-resolver

A Python dependency resolver.

### Issues

- Only supports wheels (no sdists!)

### Usage

#### Python library

```python
import resolvelib
import resolver


resolver = resolvelib.Resolver(
    resolver.Provider(),
    resolvelib.BaseReporter(),
)
resolver.resolve('trampolim==0.0.2')
```

#### Resolver CLI

```
$ python -m resolver build
--- Pinned Candidates ---
build: build 0.3.1.post1
pep517: pep517 0.10.0
toml: toml 0.10.2
packaging: packaging 20.9
pyparsing: pyparsing 2.4.7

--- Dependency Graph ---
pep517 -> toml
(root) -> build
build -> pep517, toml, packaging
pyparsing ->
toml ->
packaging -> pyparsing
```

#### `mindeps` CLI

`resolver.mindeps` will resolve the dependency tree for the minimum supported version.
This is useful when you want to for eg. test your software against the minimum version of the
dependencies that it claims to support.

It can work on projects directly, or on requirement strings, like the normal CLI.
If no argument is provided, it will try to resolve the dependencies for the current project.
If arguments are provided, it will treat them as requirement strings and resolve them instead,
like the normal CLI.
Unlike the normal CLI, the output will be a list of requirement strings that pins the dependency versions.

For resolving the current project, the `python-resolver[mindeps]` extra needs to be installed.

```
$ python -m resolver.mindeps
resolvelib==0.7.0
importlib-metadata==3.2.0
mousebender==2.0.0
zipp==0.5.0
attrs==19.3.0
packaging==20.3
pyparsing==2.0.3
six==1.5.0
```

```
$ python -m resolver.mindeps build==0.3.0
build==0.3.0
pep517==0.9.1
toml==0.9.6
packaging==14.0
```
