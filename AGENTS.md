# validate

Standalone common-repo configuration and managed-file parity validation.

- [`.common-repo.yaml`](.common-repo.yaml): `self:` installs authoring tools
  from common-repo/upstream and dogfoods the payload; the source API exports
  only `src/**`, renamed into consumer roots.
- [`src/.github/workflows/common-repo.yaml`](src/.github/workflows/common-repo.yaml):
  pinned CLI and actions, `common-repo validate`, and drift-failing
  `common-repo diff`. Private upstream credentials are optional, read-only,
  repository-scoped, and removed even if validation fails.
- [`.github/workflows/ci.yaml`](.github/workflows/ci.yaml): hand-written
  authoring lint/tests, excluded from upstream generation. Other root
  maintenance files and `common-repo.yaml` are generated; edit their source.
- [`tests/test_validate.py`](tests/test_validate.py): local consumer fixtures
  cover public/private rendering, preservation of custom CI, clean parity,
  changed/deleted files, auth routing and cleanup. No live secrets needed.
- Run `prek install` on a new checkout; validate with `script/test` and
  `prek run --all-files`. Tests require Python 3, Git, and common-repo 0.38.2.
- Keep the CLI pin in source defaults, `self:` defaults, and CI identical.
- Keep agent indexes outside `src/`; every payload file reaches consumers.

## Maintaining this index

- Update the affected `AGENTS.md` files in the same change when paths,
  responsibilities, commands, dependencies, or conventions change.
- Keep indexes brief: record semantic entry points and non-obvious
  constraints; link to existing documentation instead of duplicating it.
- Add a directory index only when it provides useful navigation beyond its
  parent; omit generated, vendored, and fixture trees.
- Do not add `CLAUDE.md` files; Claude Code reads `AGENTS.md` natively, and
  a `CLAUDE.md` anywhere in the tree stops every `AGENTS.md` from loading.
