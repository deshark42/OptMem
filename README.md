# OptMem

Permanent memory for AI agents. A prompt, a script, plug and play.

![how OptMem works](<anim/optmem.gif>)

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/deshark42/OptMem/main/install.sh | sh
```

It prints a `## Memory` block. Paste that at the top of your agent's
`AGENTS.md` (or `CLAUDE.md`), and you are done. Run the same line again to
update.

The tool lands at `~/.optmem/memo`; put `~/.optmem` on `PATH` to type `memo`.

Memory has three scopes, all personal and stored locally:
- `user`: the user's preferences and background, across workspaces.
- `global`: reusable knowledge, across workspaces.
- `workspace`: context for the current directory.

## Commands

| | |
|---|---|
| `memo init` | initialize user and global memory |
| `memo wake` | read the memory — the first command of every session |
| `memo note --scope SCOPE "..."` | record one memory: one line, up to 280 bytes |
| `memo nap --scope SCOPE` | answer the merges that came due |
| `memo recall <regex>` | search every memory in the active scopes, word for word |
| `memo zoom --scope SCOPE <lo>-<hi>` | open a tree node into its two halves |
| `memo forget --scope SCOPE <lo>-<hi>` | drop a bad summary; the next nap rebuilds it |

`SCOPE` is `user`, `global`, or `workspace`. `wake` and `recall` read user, global,
and the current workspace by default; add `--scope SCOPE` to read just one.
`wake` creates a missing workspace. Use `--workspace PATH` to select another directory.

Merges arrive one at a time, in the output of `note`. Nothing ever runs in the
background.

## Files

```
~/.optmem/
  memo          the tool: one file of Python 3, no dependencies
  memory/
    config      the sizes, written by `memo config`
    user/       LOG.txt and TREE/ for user memories
    global/     LOG.txt and TREE/ for global memories
    workspaces/<path-id>/  LOG.txt and TREE/ for each workspace
```

Each scope has its own `LOG.txt` (every memory, one per line, append-only, never
edited) and `TREE/` (the summaries: a cache, rebuildable from the log alone).

```sh
memo config                  # show the sizes
memo config WAKE_LINES=300   # total reading budget (default: 96 lines)
memo config WAKE_LINES=      # back to the default
```

`WAKE_LINES` is a reading budget, not
a storage budget: change it whenever, in either direction, and nothing is
recomputed.

The scopes share the budget with weights 1:1:2; unused shares go to scopes that
can use them. Set `USER_WAKE_WEIGHT`, `GLOBAL_WAKE_WEIGHT`, or
`WORKSPACE_WAKE_WEIGHT` with `memo config` to change the weights.

Records are fixed width, so position *is* identity and every lookup is one
seek.

Set `$MEMORY_DIR` to keep `memory/` elsewhere — a synced folder, a git repo.

## The prompt

This is what the installer prints, and the whole of the integration.

```markdown
## Memory

Your memory is OptMem:
- The tool is `memo`
- Your memories are in `~/.optmem/memory`
- Scopes: `user` for the user's preferences and background, `global` for reusable knowledge, `workspace` for the current directory.

### At startup: activating OptMem (mandatory)

Run `memo wake` before any other tool call, in every session, to read the memory.

### While working: register memories (mandatory)

Call `memo note --scope SCOPE "<1 line, max 280 bytes>"` whenever you learn something new, or something worth keeping happens. That covers a task worth real effort, a fact or insight the user teaches you, anything you learn about the user's life (even indirectly), any event of lasting effect.

Start each note with one short topic in square brackets, e.g. `[Git] ...`. Reuse existing topics when possible.

Ask the user with `ask_user_question` before every `memo note`, and record only what the user approves.

Do not register redundant memories.

If `memo note` asks a compression: do it before your next action.

Never edit or delete anything under `~/.optmem/memory`: the tool manages it.

### When you need an old memory: search, or navigate

`memo recall <regex>` searches every memory, word for word.

Your memories also form a binary tree: #0-1, #2-3 ... exist as one-line summaries, pairs of those as #0-3, and so on -- every `#a-b` line wake prints is one node of it. `memo zoom --scope SCOPE <a-b>` opens a node into its two halves, down to the raw memories.

### If you're a subagent: skip everything above

Parallel sessions on this machine are all you, and may all write memories. A subagent is not: it must never run `memo`, because it cannot judge what is already known, and its notes would arrive duplicated and incorrectly. When you spawn one, write: `You are a subagent. Don't run memo.`
```
