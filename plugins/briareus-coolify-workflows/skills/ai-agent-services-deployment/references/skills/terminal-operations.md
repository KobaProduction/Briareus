# Terminal / Remote Operations

## Mandatory trigger

Load this skill before emitting any human-operated shell/PowerShell/WSL/SSH/UART/bootloader command block. This is a hard routing rule, not an optional optimization.

If command-format rules were just violated or the user reports they were forgotten, reload this skill before issuing the next command block.

Use for shell, PowerShell, WSL, SSH, UART, bootloader or remote command execution.

## Lanes
Know which lane every command belongs to:
- local host;
- WSL/container;
- remote SSH target;
- UART/serial target;
- bootloader;
- privileged/service host.

Do not silently switch lanes.

## Human-operated command format
- one current decision boundary per copyable code block; keep commands required for that boundary together so the operator copies once;
- do not split one current-stage evidence collection or routine check into separate blocks merely because it contains multiple commands;
- each command on its own physical line;
- explicit `cd` before cwd-dependent commands;
- avoid ordinary `&&`, `;` and backslash continuation when separate lines are clearer;
- group proven routine commands, but stop at real decision boundaries;
- do not combine separate decision boundaries merely to reduce the number of code blocks;
- do not split one proven routine stage into one-code-block-per-command noise.
- in an interactive shell clear the screen only when its existing output is no longer needed as evidence or comparison; when appropriate, put the shell-native clear command at the beginning of that same copyable block, not in a separate step.

## Minimal targets
Do not assume GNU coreutils, Python, `file`, full shell features, SSH/SFTP or writable storage.

Use the project/local-context transport contract.

Legacy flags such as `scp -O` belong in project/local context, not global prompts.

## UART
Avoid long multiline pasted scripts, complex quoting and fragile loops. Prefer a helper/script plus one simple invocation.

## Safety
Before destructive commands confirm lane, target, current state and recovery/rollback when relevant.


## Local contract precedence

A generic/default command pattern must never silently override a known project/local transport or execution contract.

Examples:
- if the project/local context defines legacy SCP with `scp -O`, use that exact contract;
- if the project defines a normal firmware-update procedure as routine operation, do not relabel it as exceptional/destructive merely from a generic safety template.

Before emitting a command:
1. check whether repository/project/local context defines a transport or operation-specific contract;
2. if defined, that local contract overrides the generic default;
3. if the local contract is expected but cannot be recovered, stop at that boundary and report the missing context;
4. do **not** fall back to a familiar/default command merely because the universal skill does not encode the project-specific flag.

“Not universal” means “resolve from project/local context”, not “ignore the rule”.


## Pre-send compliance gate

Before sending any human-operated command response, perform one final compliance pass against the active terminal skill and project/local contract.

Check at minimum:
- does the response stop at the next real decision boundary;
- did a completeness/end-to-end optimization accidentally add later dependent steps;
- are all commands in the correct execution lane;
- are required local transport flags/options preserved;
- are separate decision boundaries kept separate;
- are proven routine steps grouped without turning into microstep noise.

Hard skill/project constraints outrank response-completeness, convenience, compactness, or “give the whole path now” goals.

If the draft violates a hard constraint, rewrite the draft before sending it.


## Exact execution-mode validation

Shell syntax validation does not prove the production invocation.

When a script is actually executed through a wrapper, stdin, `bash -s`, `sh -c`, sourcing, `set -e/-u`, `nsenter`, generated helper command or orchestrator entrypoint, include a test that reproduces that invocation shape before rollout.

Examples of failures syntax-only checks miss:

- variables such as `BASH_SOURCE[0]` are unavailable or differ under stdin execution;
- `set -u` turns an otherwise harmless absent variable into a fatal error;
- an orchestrator wrapper changes arguments/environment/cwd;
- namespace entry changes which filesystem/process/systemd state the script observes.

Keep `bash -n`/`sh -n` as fast checks, but bind runtime readiness to the path production really uses.

## WSL environment isolation

WSL is a separate execution lane even when it inherits environment from Windows.

Windows environment leakage can make Linux-native build systems fail or select the wrong tools. In particular, Windows `PATH` entries such as `/mnt/c/Program Files/...` may contain spaces and are invalid for build systems such as Buildroot.

For Linux-native build/toolchain work inside WSL:
1. check whether the build contract requires a Linux-clean environment;
2. if yes, do not rely on inherited Windows `PATH`;
3. use the project-defined Linux-only `PATH`, then run `hash -r` before the build;
4. do not silently keep Windows toolchain/program directories in the active build environment;
5. prefer a Linux filesystem workspace rather than a Windows-mounted source tree when the build system/toolchain is known to depend on normal Linux filesystem semantics.

A Windows-integrated WSL shell is not the same thing as a clean Linux build environment.
