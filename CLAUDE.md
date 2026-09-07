<!-- This project's agent guide lives in AGENTS.md, the cross-agent standard, so that Codex,
     Cursor, Amp and anything else that reads AGENTS.md gets the same instructions rather than
     none. Claude Code does not read AGENTS.md itself — its own documentation says so in as many
     words ("Claude Code reads CLAUDE.md, not AGENTS.md") — but it does expand `@` imports, so
     this one line is the whole bridge.

     Deliberately NOT a symlink, which is what the usual advice suggests. Committed as one, git
     stores mode 120000 and a checkout with `core.symlinks=false` — Windows without developer
     mode — writes a 9-byte TEXT file whose entire content is the target's name. An agent reading
     that gets one word and no instructions, which is worse than an absent file because it looks
     present. Verified against the sibling `rlm-harness`, which is committed that way: its
     AGENTS.md blob is 9 bytes reading `CLAUDE.md`. Measured, not assumed.

     And not the other way round either: only Claude Code expands `@`, so an AGENTS.md pointing at
     CLAUDE.md would hand every other agent that same one line. -->

@AGENTS.md
