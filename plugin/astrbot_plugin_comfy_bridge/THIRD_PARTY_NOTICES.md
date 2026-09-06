# Third-party notices

## Prompt corpus notice

The public release contains no third-party or private prompt corpus. Both the main
pool and the optional K pool are empty. Users must import only material they have
reviewed and are permitted to use. The N/H/S fields remain as compatibility and
routing metadata; they are not a substitute for moderation or platform policy.

## Optional character dictionary sources

The plugin does not redistribute either external character database. The included
`tools/build_character_dictionary.py` only converts files supplied by the server
administrator into the plugin's compact offline format.

- Structured character traits: `tcpassos/mcp-danbooru-characters` (MIT), whose
  character data is derived from `Sn0w123/booru-characters`.
- Optional Chinese names: `ffdkj/ffdkj-Danbooru_Tag-Chinese-English-Translation-Table`.
  No license was visible in the upstream repository when this release was made,
  so its SQLite database is never copied into an AstrAutoAnima release.

The original projects and their authors are not affiliated with AstrAutoAnima.

The optional `tools/install_character_dictionary.py` installer downloads these
files only after the server administrator explicitly runs it. The Chinese SQLite
file is downloaded directly to that server and remains excluded from every
AstrAutoAnima release archive. Administrators should review the upstream terms
before use.
