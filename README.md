# AutoScout structure

A generated page that shows how AutoScout is built: which parts are plain code, which call a model, and which are left to the agent.

Page: https://chillyweather.github.io/autoscout-structure-graph/

## Updating

```
./update
```

It fetches `origin/main` of the AutoScout checkout at `../auto-scout`, rebuilds `docs/index.html`, and commits and pushes when the page changed.
Pass another checkout path as the first argument.
The build reads the Git ref, never the working tree, so local edits in the checkout do not reach the page.

## What comes from where

| File | Holds |
|---|---|
| `structure.json` | The wording: each stage's name, kind, description and files; the sections outside the run. |
| `template.html` | The page layout and styles. |
| `build.py` | Reads the code and the two files above, writes `docs/index.html`. |
| `docs/index.html` | Generated. Never edit it by hand. |

Read from the code on every build:

- the stage order, from the tuple in `WeeklyWorkflow._stages()`;
- the counts in the tiles;
- every value listed under `facts` in `structure.json` (model names, Jev weights, answer options).

## When the build fails

The build exits 1 and names each disagreement:

- a stage in the code with no entry in `structure.json`;
- an entry in `structure.json` for a stage the code no longer has;
- a file, or a `file::symbol`, that no longer exists.

Fix `structure.json` and run `./update` again.

For an agent fixing it: read the stage's method in `autoscout/weekly_workflow.py` and the module it calls, at `origin/main`.
Mark it `model` only when the stage sends a request to a model; a lookup in a catalogue such as Open Library is `code`.
Write the description in one or two plain sentences, and add the stage to its phase in `phases`.

The build cannot see a stage whose behaviour changed while its name stayed.
After a large change to AutoScout, reread the descriptions against the code.

## What must stay out

This repository is public and AutoScout is private.
Keep out credentials, mailbox addresses, server addresses, the editor's identity, and any text taken from a source.
