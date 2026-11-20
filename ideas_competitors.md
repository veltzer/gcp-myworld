# Competing systems

Taken from the Claude doc "My World - Competing Systems" on 2026-11-20
(<https://claude.ai/artifact/KWdLtmp9WjeGwiQPU3ocxB>). Notes only, like
`ideas_features.md` and `ideas_datamodel.md`.

No existing system covers everything My World does, but several overlap
with parts of it. Dogsheep and HPI are the closest in spirit: minimal,
self-hosted, and built around importers.

| System | What it is | Overlap with My World |
| --- | --- | --- |
| [Dogsheep](https://dogsheep.github.io/) (Simon Willison) | A set of importers that pull personal data (Goodreads, GitHub, photos, and more) into SQLite, browsed and searched with Datasette | Closest match: importers into one searchable personal database |
| [HPI](https://github.com/karlicoss/HPI) (Human Programming Interface, karlicoss) | A Python library that unifies personal data exports from dozens of services | Importer design and a unified data model |
| [Perkeep](https://perkeep.org/) | A self-hosted store for a whole life's data | Long-term personal storage |
| [Exist.io](https://exist.io/) | A commercial app that tracks your life and pulls in data from many services | Recurring imports and stats |
| [Gyroscope](https://gyrosco.pe/) | A commercial life-tracking app that integrates many services | Dashboards and life overview |
| [Monica](https://www.monicahq.com/) | An open-source personal CRM for friends and relationships | Friends and people records |

Worth studying: Dogsheep and HPI for importer ideas and structure.
