# mxml2jp v0.3.0 — MusicXML to jianpu-ly Converter

Convert MusicXML files to plain-text input for
[jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html).

## Quick Start

```sh
python mxml2jp.py piece.musicxml -o piece.txt
python mxml2jp.py piece.xml --octave-traditional
python mxml2jp.py piece.mxl -v -o piece.txt
```

Compile with jianpu-ly and LilyPond:

```sh
$env:j2ly_sloppy_bars=1
python jianpu-ly.py piece.txt > piece.ly
lilypond piece.ly
```

## CLI Options

| Option | Description |
|--------|-------------|
| `-o FILE` | Output file (default: stdout) |
| `--minor` | Minor-key notation (`6=X` instead of `1=X`) |
| `--verbose` / `-v` | Per-measure diagnostic output to stderr |
| `--octave-traditional` | Traditional octave style: low marks before digit, high marks after |

## Architecture

```
MusicXML file → MusicXmlParser.parse()
  ├── Extract metadata (title, composer, part-list)
  ├── For each <part>:
  │     ├── Per-measure parsing (<attributes>, <note>, <direction>, <barline>)
  │     │     └── Note dict: {step, octave, alter, ntype, dots, tie, slur, ...}
  │     ├── Detect key_change / time_change / oversize
  │     └── Multi-voice handling: <backup>/<forward> → chord merging
  └── Return (title, composer, [(part_name, [measure_dict])])

Parsed data → JianpuGenerator.generate()
  ├── Emit title=, composer=, instrument=, NextPart, OctavesBefore
  ├── For each measure:
  │     ├── note_to_jianpu()     — pitch conversion (fixed-do → movable-do)
  │     ├── _measure_tokens()    — jianpu token assembly
  │     ├── Oversize detection   — rubato/cadenza handling
  │     └── Tuplet measures      — replaced with rest + user warning
  └── Emit jianpu-ly text lines
```

## Core Algorithm: Fixed-do → Movable-do

```
1. Determine tonic from fifths: tonic_step = (fifths * 4) % 7
2. Compute diatonic steps: dTone = step_idx - tonic_step_idx (+ 7 if wrap)
3. Degree & octave: degree = dTone % 7 + 1, octave = dTone // 7
4. Accidental: compare effective alteration vs key signature default
```

## Oversize / Rubato Handling

| Scenario | Action |
|----------|--------|
| Margin ≥ 4 beats | LP block with "サ" stencil override + corrected time sig |
| Margin < 4 beats | Correct time sig, warn user |
| Tuplet measure | Replaced with `R*1`, warn user |
| Explicit `<time>` | Always emitted (restores time sig after rubato) |

## Known Limitations

- **Multi-voice alignment**: when two parts share the same score, rubato
  rest lengths may not synchronize between parts
- **Tuplet precision**: jianpu-ly uses type-based durations (not MusicXML
  divisions); tuplet-heavy measures are replaced with rests and flagged
- **Chinese text in Sibelius exports**: may require re-export from MuseScore
  for correct UTF-8 encoding
- **草原小姐妹**: known encoding issue with Sibelius-exported Chinese text;
  PDF generation works via manual lilypond compilation

## TODO

- Multi-voice bar synchronization for rubato sections
- Tuplet timing using MusicXML `<duration>` divisions
- Rehearsal marks, ottava, expression text
- `.mxl` compressed format support

## Supported MusicXML Elements

| Element | Support |
|---------|---------|
| Pitch with `<alter>` | ✓ |
| Key / Time signatures | ✓ |
| Tempo (`<metronome>`) | ✓ |
| Dynamics (p/mp/f/ff…) | ✓ |
| Wedges (`\<`, `\>`, `\!`) | ✓ |
| Text annotations (`^"…"`, `_"…"`) | ✓ |
| Articulations (staccato→Fr=▼, accent→Fr=>, tenuto→Fr=_) | ✓ |
| Slurs / Ties | ✓ |
| Chords (`<chord/>`) | ✓ |
| Grace notes (before + after) | ✓ |
| Tremolo (`///`) | ✓ |
| Trill spans (`\startTrillSpan`/`\stopTrillSpan`) | ✓ |
| Technical: harmonic, stopped, fingering → `Fr=` | ✓ |
| Tuplets (`N[…]`) | Replaced with rest + warning |
| Multi-bar rests | ✓ |
| Backup / Forward | Merged into chords |

## Changelog

### v0.3.0
- `--octave-traditional` flag
- Tuplet replacement: `R*1` without time sig change
- `read_input()` UTF-8/GBK fallback encoding
- Rest/perucssion: no dashes, explicit `0 0 0` tokens
- Time sig always restored after rubato/oversize

### v0.2.1
- Feature gating (`self.feat`), incremental compile testing
- Wedges, dynamics, annotations, Fr= technical
- `\bendAfter` removed (multi-token incompatibility)

### v0.2.0
- After-grace, tremolo, trill spans, Fr= mappings
- Oversize measure auto-detection

### v0.1.0
- Initial release

## License

Apache 2.0
