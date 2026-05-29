# mxml2jp — MusicXML to jianpu-ly Converter

Convert MusicXML files (`.xml`, `.musicxml`, `.mxl`) to plain-text
input for [jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html).

## Quick Start

```sh
python mxml2jp.py piece.musicxml -o piece.txt
python mxml2jp.py piece.xml

# Verbose debug output:
python mxml2jp.py piece.musicxml -v -o piece.txt

# Minor-key notation (6=X instead of 1=X):
python mxml2jp.py piece.xml --minor
```

Compile the output with jianpu-ly:

```sh
# PowerShell
$env:j2ly_sloppy_bars=1
python jianpu-ly.py piece.txt > piece.ly
lilypond piece.ly
```

## Features

- Reads partwise MusicXML from MuseScore 4+, Sibelius, PhotoScore
- Fixed-do → movable-do pitch conversion (1 = tonic)
- Key signatures, time signatures, multiple parts (`NextPart`)
- Ties, slurs (as separate tokens), dynamics, articulations
- Full-measure rest collapsing (`R*N`)
- Grace notes (`g[...]`), tuplets (`N[...]`), chords
- **Auto-corrects oversize measures**: if a MusicXML `<measure>` contains more notes
  than its time signature allows (common MuseScore export quirk), the converter
  emits the correct time signature and warns on stderr
- **`--verbose`** mode prints per-measure diagnostics
- **`--minor`** flag for minor-key notation

## Limitations

- Grace notes: before-the-beat only (`g[...]`); after-grace (`[...]g`) not yet distinguished
- Tuplets: emitted as bare `N[...]` — manually verify ratios
- Multi-voice within one part is not separated (use separate MusicXML parts)
- Tremolo, ottava, rehearsal marks, expression text are not mapped
- The output is a **starting point** for manual editing, not finished notation

---

## Implementation Details

### Architecture

```
MusicXML file
     │
     ▼
MusicXmlParser.parse()
     │  ┌─── extract metadata (title, composer, part names)
     │  ├─── for each <part>:
     │  │      ├── per-measure parse (<attributes>, <note>, <direction>, <barline>)
     │  │      │      └── note dict: {step, octave, alter, ntype, dots, tie, slur, ...}
     │  │      └── detect key_change / time_change / oversize
     │  └── return (title, composer, [(part_name, [measure_dict])])
     │
     ▼
JianpuGenerator.generate()
     │  ├── emit title=, composer=, instrument=, NextPart
     │  ├── for each measure:
     │  │      ├── note_to_jianpu()  ── pitch conversion
     │  │      ├── _measure_tokens() ── jianpu token assembly
     │  │      ├── _split_notes()    ── oversize measure splitting
     │  │      └── _best_timesig()   ── correct time sig for oversize
     │  └── emit lines of jianpu-ly text
     │
     ▼
jianpu-ly input text (plain .txt)
```

### Fixed-do → Movable-do Pitch Conversion

This is the core algorithm — converting absolute pitch names (C, D, E...) to
jianpu scale degrees (1-7) with octave marks (`, `'`) and accidentals (`#`, `b`).

**Algorithm** (`note_to_jianpu`, roughly lines 93-142):

1. **Determine the tonic letter** from `fifths` (circle of fifths index):
   ```
   tonic_step_idx = (fifths * 4) % 7   # e.g., fifths=1 → tonic=G
   ```
   The tonic letter comes from the `DEG2LETTER` mapping:
   `C=0, D=1, E=2, F=3, G=4, A=5, B=6`

2. **Compute diatonic steps** from the tonic at octave 4 (reference register):
   ```
   dTone = step_idx - tonic_step_idx
   if step_idx < tonic_step_idx: dTone += 7   # wrap around
   dTone += 7 * (octave - 4)                    # octave shift
   ```

3. **Degree and octave marks**:
   ```
   degree = dTone % 7 + 1                   # 1-7
   octave_count = dTone // 7                 # positive → ', negative → ,
   octave_marks = "'" * octave_count  OR  "," * (-octave_count)
   ```

4. **Accidental** — compare the note's effective alteration against the key
   signature's default:
   ```
   key_step_acc = key_sig.get(step, 0)       # +1, -1, or 0
   eff = alter_val if given else key_step_acc # actual semitone alteration

   if key_step_acc != 0:
       if eff == key_step_acc:  acc = ''      # matches key, no mark needed
       elif eff == 0:           acc = 'b' if key_step_acc == 1 else '#'
       else:                    acc = '#' if eff > 0 else 'b'
   else:
       acc = '' if eff == 0 else ('#' if eff > 0 else 'b')
   ```

**Example**: Key of G major (fifths=1, tonic=G). Note F4 (step=F, octave=4).
- F is sharped in G major → `key_step_acc = +1`
- `<alter>` not present → `eff = +1` (inherits key)
- `eff == key_step_acc` → `acc = ''`
- `dTone = 3-4+7 = 6` → `degree = 7`, `octave_marks = ""`
- Result: `7` (no accidental, no octave marks)

**Example**: Key of G major, note F♮4 (F-natural with `<accidental>natural</accidental>`):
- `key_step_acc = +1`, `eff = 0` (natural sign)
- `eff != key_step_acc` AND `eff == 0` → `acc = 'b'` (lower than expected)
- Result: `b7` (flat-7, representing F-natural in G major)

### Token Order

Each jianpu token follows the format:
```
[duration_prefix][octave_marks][accidental][degree][dots]
```
Examples: `q,4` (quaver, lower octave, degree 4), `s'#5` (16th, upper octave, sharp-5),
`1.` (dotted quarter, degree 1).

Duration prefixes: `h` (64th), `d` (32nd), `s` (16th), `q` (eighth),
`""` (quarter and longer).

For half/whole/breve notes, dots are **absorbed into dashes** (not written on the
primary note). E.g., `1 - -` = dotted half (3 quarters), not `1. - -`.

Slurs `(` `)` and ties `~` are emitted as **separate tokens** (space-delimited),
never glued to notes. This avoids "Unrecognised command" errors in jianpu-ly.

For chords, pitch components are concatenated: `,135'` = three notes
(lower-octave 1, default 3, upper-octave 5), prefixed by the shared duration:
`s,135'` = 16th-note chord.

### Oversize Measure Handling

When a MusicXML `<measure>` contains more notes than its time signature allows
(common in MuseScore exports for cadenza-like passages), the converter:

1. Computes total duration in quarter-note units from note `<type>` + `<dot>`
2. Compares against the current time signature's expected quarters
3. If oversize:
   - Computes the best-fit time signature via `_best_timesig()`:
     - Tries `/4`, `/8`, `/16` denominator to find exact or closest match
     - E.g., 14.0Q → `14/4`, 4.5Q → `9/8`, 2.8Q → `11/16`
   - Emits a **WARNING** to stderr with the measure number
   - If the margin is ≤ 2 beats, appends **"possible input error?"** hint
   - Inserts the corrected time signature in the output, and resets
     `cur_time` for subsequent measures

### Grace Notes

Grace notes from MusicXML are collected into `g[...]` syntax:
```
g[#45] 1    — grace notes (sharp-4, 5) before degree 1
g[s'6q5] 1  — grace with durations (16th upper-6, 8th 5)
```

Only **before-the-beat** grace notes are supported. After-grace notes
(`[...]g`) are not yet distinguished.

### Tuplets

Triplets and other tuplets use jianpu's `N[...]` syntax:
```
3[ q1 q1 q1 ]    — triplet of quavers
6[ s1 s2 s3 s4 s5 s6 ]    — sextuplet
```

The actual-notes / normal-notes ratio from MusicXML's `<time-modification>`
is used for the bracket number.

### Multi-bar Rest Compression

Consecutive full-measure rests are collapsed into `R*N`:
```
R*5    — 5 bars of rest
0 - - -  — single whole-bar rest (4/4)
```

---

## CLI Options

| Flag | Description |
|------|-------------|
| `-o FILE` | Output file (default: stdout) |
| `--minor` | Minor-key notation (`6=X` instead of `1=X`) |
| `--verbose` / `-v` | Print per-measure diagnostics to stderr |

---

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
| Up-bow / down-bow | ✓ (v0.2.0) |
| Staccatissimo | ✓ (v0.2.0) |
| Fermata | ✓ |
| Ties (`<tied>`) | ✓ |
| Slurs | ✓ |
| Chords (`<chord/>`) | ✓ |
| Grace notes (before + after) | ✓ (v0.2.0) |
| Tremolo (`///`) | ✓ (v0.2.0) |
| Trill extensions (`\startTrillSpan`/`\stopTrillSpan`) | ✓ (v0.2.0) |
| Wedges / hairpins (`\<`, `\>`, `\!`) | ✓ (v0.2.0) |
| Text annotations (`^"text"`, `_"text"`) | ✓ (v0.2.0) |
| Rubato / cadenza (LP blocks + "サ" stencil) | ✓ (v0.2.0) |
| Technical: harmonic, stopped, fingering → `Fr=` | ✓ (v0.2.0) |
| Tuplets | `N[...]`; verify ratios |
| Multi-bar rests | ✓ |

## License

Apache 2.0

---

## Changelog

### v0.2.0

- After-grace notes (`[...]g`) support
- Tremolo (`///`) from MusicXML `<tremolo>` ornaments
- Trill extensions (`\startTrillSpan` / `\stopTrillSpan`) from `<wavy-line>`
- Wedges / hairpins (`\<`, `\>`, `\!`) from `<wedge>` directions
- Per-measure dynamics from `<direction><dynamics>` elements
- Chinese instrument techniques via `Fr=` commands:
  - `<harmonic/>` → `Fr=harmonic` (natural harmonic)
  - `<harmonic><artificial/></harmonic>` → `Fr=◇`
  - `<stopped/>` → `Fr=souyin` (stopped note / 顿音)
  - `<fingering>` → `Fr=N` (fingering)
- Articulations as Fr=: `staccato`→`Fr=▼`, `accent`→`Fr=>`, `tenuto`→`Fr=_`
- New articulations: `\upbow`, `\downbow`, `\staccatissimo`
- Oversize measure auto-detection with corrected time signatures
- `--verbose` mode for per-measure diagnostics
- Token order: `[duration][octave][accidental][degree][dots]`
- Slurs and ties as independent space-delimited tokens

### v0.1.0

- Initial release
