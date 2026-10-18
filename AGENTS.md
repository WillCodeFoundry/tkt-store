# AGENTS.md

A briefing for coding agents: the rules to know before changing anything, each with
where it is explained. Everything else (what tkt-store is, setting up, and a map of
every document) is in the [README](README.md).

## Design

- `docs/design.md` is the authority on concepts, boundaries and invariants. If code and
  design disagree, fix one or amend the design in the same change; never deviate
  silently. See [`docs/design.md`](docs/design.md).
- A change to the on-branch format bumps `PROTOCOL_VERSION` and updates
  `docs/format.md` in the same change. See [`docs/format.md`](docs/format.md#changing-the-format).

## Working

- Use `uv` for everything, never `pip`. Set up once per clone with
  `uv sync --group dev` and `uv run pre-commit install`. See the
  [README](README.md#getting-started-as-a-developer).
- The checks run through git's hooks on commit and push; never bypass them. See
  [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md#checks).
- Tests inject fakes and never patch internals; a change to store behaviour is expressed
  in `tests/contract/`. See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md#testing).

## Committing

- Commits are signed, carry no `Co-Authored-By` trailer, and never use `--no-verify`.
  See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md#commits).
