# mxml2jp — MusicXML to jianpu-ly Converter

Convert MusicXML files (`.xml`, `.musicxml`, `.mxl`) to plain-text
input for [jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html),
a LilyPond-based numbered musical notation (简谱) engraver.

## Quick Start

```sh
python mxml2jp.py piece.musicxml -o piece.txt
python mxml2jp.py piece.xml
```

## Features

- Reads **partwise MusicXML** exported from MuseScore 4+, Sibelius, PhotoScore
- Converts absolute pitch to movable-do jianpu notation (1=tonic)
- Handles key signatures, time signatures, multiple parts (`NextPart`)
- Preserves ties, slurs, dynamics, articulations (staccato, tenuto, accent, fermata)
- Collapses consecutive full-measure rests into `R*N` markup
- Basic support for tuplets, chords, grace notes
- Option `--minor` for minor-key notation (`6=X` instead of `1=X`)

## Limitations

- **Grace notes** are converted but need manual review
- **Tuplets** are represented as bare `N[...]` — adjust ratios after conversion
- **Multi-voice** within a single part is not separated; use separate parts in MusicXML
- **Tremolo**, trills, and other advanced ornaments are not mapped
- **Rehearsal marks**, ottava, and text expressions are lost
- The output is a **starting point** for manual editing, not a finished score

## Recommended Workflow

1. Export MusicXML from your notation software
2. Run `mxml2jp.py` to get jianpu-ly text
3. Inspect the output and fix grace notes, tuplets, and dynamics
4. Run `jianpu-ly < piece.txt > piece.ly && lilypond piece.ly`
5. Iterate

## Supported MusicXML Elements

| Element | Support |
|---------|---------|
| `<pitch>` with `<alter>` | ✓ |
| `<accidental>` (sharp/flat/natural) | ✓ |
| Key signatures (`<fifths>`) | ✓ |
| Time signatures | ✓ |
| Tempo (`<metronome>`) | ✓ |
| Dynamics (`p/mp/mf/f/ff/...`) | ✓ |
| Articulations (staccato, tenuto, accent) | ✓ |
| Fermata | ✓ |
| Ties (`<tied>`) | ✓ |
| Slurs | ✓ |
| Chords (`<chord/>`) | ✓ |
| Grace notes | Partial |
| Tuplets | Partial |
| Multi-bar rests | ✓ |

## License

Apache 2.0 — see LICENSE file.
