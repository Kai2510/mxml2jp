# mxml2jp v0.3.0 — MusicXML to jianpu-ly Converter

Convert MusicXML files to plain-text input for
[jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html),
the numbered musical notation (简谱/jianpu) engraver for LilyPond.

## Table of Contents

- [Quick Start](#quick-start)
- [What This Program Does](#what-this-program-does)
- [Architecture](#architecture)
- [Core Algorithm: Fixed-do → Movable-do](#core-algorithm-fixed-do--movable-do)
- [Duration & Time Representation](#duration--time-representation)
- [Note Parsing Details](#note-parsing-details)
- [Oversize Measure / Rubato Handling](#oversize-measure--rubato-handling)
- [Multi-Voice & Chord Handling](#multi-voice--chord-handling)
- [CLI Options](#cli-options)
- [Supported MusicXML Elements](#supported-musicxml-elements)
- [Output Format Reference](#output-format-reference)
- [Test Files](#test-files)
- [Known Issues & Limitations](#known-issues--limitations)
- [Code Issues](#code-issues)
- [TODO / Future Work](#todo--future-work)
- [Changelog](#changelog)
- [Dependencies](#dependencies)
- [License](#license)

---

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

---

## What This Program Does

`mxml2jp` takes a **MusicXML file** (from MuseScore, Sibelius, PhotoScore, etc.) and
produces a **plain text file** that can be fed to `jianpu-ly.py` to generate a
LilyPond `.ly` file, which is then compiled to a PDF score.

The core task is a **notation system translation**:

| MusicXML (五线谱思维) | jianpu-ly (简谱思维) |
|-----------------------|-----------------------|
| Absolute pitch (C4, D#5…) | Scale degree in the current key (1, 2, #4…) |
| Key signature via accidentals | Movable-do tonic (1=Eb, 6=Am…) |
| Staff lines for octave | Octave marks (`,`, `'`, `''`) |
| Note shape for duration | Prefix letters (`q`, `s`, `d`, `h`) + dots |

The program does **not** render sheet music. It only produces the text tokens
that `jianpu-ly` consumes. The LilyPond compilation step is separate.

---

## Architecture

```
┌───────────────────┐
│  MusicXML file    │  (.musicxml / .xml / .mxl)
└────────┬──────────┘
         │ read_input()
         ▼
┌───────────────────┐
│   XML string      │
└────────┬──────────┘
         │ MusicXmlParser.parse()
         ▼
┌───────────────────┐
│  Parsed structure  │  (title, composer, [(part_name, [measure_dict])])
└────────┬──────────┘
         │ JianpuGenerator.generate()
         ▼
┌───────────────────┐
│  jianpu-ly text    │  plain text in jianpu-ly input format
└───────┬───────────┘
        │ jianpu-ly.py → lilypond
        ▼
┌───────────────────┐
│     PDF score      │
└───────────────────┘
```

### Component 1: `MusicXmlParser` (lines 221–631)

Parses **partwise** MusicXML (the `<score-partwise>` root element) and
produces a structured representation.

**`parse(xml_string) → (title, composer, parts)`**

1. Extracts **metadata**: `<work-title>`, `<creator type="composer">`, `<part-name>` for each part.
2. For each `<part>` element:
   - Iterates `<measure>` elements, tracking current key (fifths), time signature, and divisions.
   - Within each measure, iterates child elements in document order:
     - `<attributes>` → key change, time change, divisions
     - `<direction>` → tempo, dynamics, wedges, word annotations
     - `<note>` → full note data (pitch, duration, articulations, etc.)
     - `<backup>` → voice switch (backtracks time position for next voice)
     - `<forward>` → silent advance (for rests in other voices)
     - `<barline>` → repeats, final barline, bar style
   - After collecting all notes, calls `_merge_aligned_notes()` to group simultaneous notes as chords.

**`_parse_note(note_elem) → dict`**

Parses a single `<note>` element and returns a flat dictionary with these keys:

| Key | Type | Source | Example |
|-----|------|--------|---------|
| `is_rest` | bool | `<rest/>` presence | `True` |
| `is_measure_rest` | bool | `<rest measure="yes"/>` | `True` |
| `is_chord` | bool | `<chord/>` presence | `True` |
| `is_grace` | bool | `<grace/>` presence | `True` |
| `grace_slash` | bool | `<grace slash="yes"/>` | `True` |
| `step` | str | `<step>` | `'C'` |
| `octave` | int | `<octave>` | `4` |
| `alter` | float or None | `<alter>` | `0.0`, `-1.0`, `None` |
| `duration` | int | `<duration>` (divisions) | `420` |
| `ntype` | str | `<type>` | `'quarter'`, `'eighth'` |
| `dots` | int | count of `<dot/>` | `1` |
| `voice` | str | `<voice>` | `'1'`, `'2'` |
| `tie_start` / `tie_stop` | bool | `<tied type="start"/>` | — |
| `slur_start` / `slur_stop` | bool | `<slur type="start"/>` | — |
| `artic` | list[str] | `<articulations>` | `['Fr=▼', '\\fermata']` |
| `fr_marks` | list[str] | `<technical>` | `['Fr=0', 'Fr=◇']` |
| `dynamic` | str or None | `<dynamics>` | `'\\p'`, `'\\ff'` |
| `tuplet_start` / `tuplet_stop` | bool | `<tuplet type="start"/>` | — |
| `tuplet_ratio` | tuple or None | `<time-modification>` | `(3, 2)` |
| `tremolo_beams` | int | `<tremolo>` beam count | `3` |

### Component 2: `JianpuGenerator` (lines 637–1157)

Takes parsed data and emits jianpu-ly input text line by line.

**`generate(title, composer, parts) → str`**

For each part:
1. Emits header lines: `title=`, `composer=`, `instrument=`, `OctavesBefore`
2. For each measure:
   - **Key change**: converts fifths to `1=X` or `6=X` format
   - **Time change**: emits `beats/beat-type`
   - **Tempo**: emits first `<metronome>` as `unit=bpm`
   - **Full-measure rests**: accumulates consecutive empty bars into `R*N`
   - **Oversize detection**: compares total note durations to the current time signature; triggers rubato/cadenza logic if the gap is too large (see below)
   - **Note token generation**: calls `_measure_tokens()` to produce the bar content
   - **Repeat marks**: `R{` before, `}` after
   - **Barline LP blocks**: for final bars and special bar styles

**`_measure_tokens(mdata, fifths, cur_time) → list[str]`**

The heart of token generation (lines 939–1101). Iterates notes in order:

```
For each note in the measure:
  1. If grace note → accumulate in grace_before[] or pending_after[]
  2. If rest → flush grace/chord buffers, emit "0" token + extra "0" for long rests
  3. If pitched note:
     a. Flush after-grace from previous note
     b. Flush before-grace
     c. Call note_to_jianpu() to get degree, accidental, octave_marks
     d. Build token: [dur_prefix] + octave_marks + accidental + degree + dots
     e. Append articulations (Fr=▼), dynamics (\p), tremolo (///)
     f. Handle slurs: prefix "(" before, suffix ")" after
     g. If is_chord → buffer for _format_chord_v2()
     h. If not chord → emit token + dashes, flush chord buffer before
```

---

## Core Algorithm: Fixed-do → Movable-do

The function `note_to_jianpu()` (line 161) is where the critical pitch
transformation happens. MusicXML stores notes as **absolute pitches**
(C4, D#5, etc., with octave and chromatic alteration). Jianpu uses
**movable-do notation**: "1" is always the tonic of the current key,
and the numbers 1–7 represent the diatonic scale degrees.

### Step-by-step Walkthrough

**Given**: note `Eb4` in the key of `Eb major` (fifths = -3).

```
1. Determine tonic letter from key signature:
     tonic_letter = DEG2LETTER[(fifths * 4) % 7]
     = DEG2LETTER[(-3 * 4) % 7]
     = DEG2LETTER[-12 % 7]
     = DEG2LETTER[2]
     = 'E'       (E♭ is the tonic of E♭ major)

2. Get step indices:
     step_idx  = STEP_ORDER['E'] = 2  (the note itself: E)
     tonic_idx = STEP_ORDER['E'] = 2  (the tonic: also E)

3. Compute diatonic distance from tonic at octave 4:
     dTone = step_idx - tonic_idx
           = 2 - 2 = 0
     Since step_idx >= tonic_idx, no +7 wrap.
     dTone += 7 * (octave - 4) = 0 + 7 * 0 = 0

4. Degree and octave:
     degree = 0 % 7 + 1 = 1     → "1" (the tonic)
     octave_count = 0 // 7 = 0  → no octave marks
     Result: "1" with no marks. Correct: E♭ is the tonic.
```

**Given**: note `F4` (F-natural) in `Eb major` (fifths = -3).

```
1. tonic_letter = 'E' (as above)

2. step_idx  = STEP_ORDER['F'] = 3
   tonic_idx = STEP_ORDER['E'] = 2

3. dTone = 3 - 2 = 1
   dTone += 7 * 0 = 1

4. degree = 1 % 7 + 1 = 2     → "2"
   octave_count = 1 // 7 = 0  → no octave marks

5. Accidental calculation:
   key_step_acc = key_sig['F'] = -1  (F is flat in Eb major, but this note is F-natural)
   eff = 0.0  (no explicit <alter>, so F-natural)
   key_step_acc (-1) != 0 and eff (0.0) != key_step_acc (-1):
     eff (0.0) == 0.0 → natural against a flat → acc = '#'
   Result: "#2" (F-natural, a raised 2nd degree in Eb major)
```

### Accidental Logic Summary

The accidental logic (lines 198–212) compares the note's effective alteration
against the key signature's default for that step letter:

| Key default | Effective pitch | Accidental | Meaning |
|-------------|-----------------|------------|---------|
| 0 (natural) | 0 (natural) | `''` | No mark needed |
| 0 (natural) | +1 (sharp) | `'#'` | Sharp |
| 0 (natural) | -1 (flat) | `'b'` | Flat |
| +1 (sharp) | +1 (same) | `''` | In key, no mark |
| +1 (sharp) | 0 (natural) | `'b'` | Natural (= lowered from key sharp) |
| -1 (flat) | -1 (same) | `''` | In key, no mark |
| -1 (flat) | 0 (natural) | `'#'` | Natural (= raised from key flat) |

Note: In jianpu-ly, `b` and `#` are relative to the **diatonic scale degree**,
not absolute pitch. `#2` means "scale degree 2 raised by a semitone above its
key-signature default."

---

## Duration & Time Representation

### MusicXML duration model

MusicXML uses a **divisions** system: `<divisions>N</divisions>` means one
quarter note = N ticks. Each `<note>` has a `<duration>` in ticks. This allows
arbitrary tuplets and rhythmic precision.

### jianpu-ly duration model

jianpu-ly uses **type-based** durations with prefix letters and dots:

| Duration | Prefix | In 64th-note units | Dash count (extra tokens) |
|----------|--------|--------------------|---------------------------|
| 64th | `h` | 1 | 0 |
| 32nd | `d` | 2 | 0 |
| 16th | `s` | 4 | 0 |
| 8th | `q` | 8 | 0 |
| Quarter | (none) | 16 | 0 |
| Dotted quarter | (none) | 24 | 0 (dot on note) |
| Half | (none) | 32 | 1 (`-`) |
| Dotted half | (none) | 48 | 2 (`- -`) |
| Whole | (none) | 64 | 3 (`- - -`) |

Key design choice: **long notes (half and longer) never use dots**. The primary
token is always a bare quarter-note figure; extra length is communicated via
dash tokens (`-`). Each dash adds one quarter-beat of length. So a whole note
is emitted as `1 - - -`, not `1---`.

The function `dash_count()` (line 131) computes how many dashes follow a note.
The function `type_to_64th()` (line 119) converts a MusicXML type+dots to
64th-note units for bar-length checking.

### Bar-length checking

Each jianpu-ly bar holds exactly `64 × beats / beat-type` units. A 4/4 bar
holds 64 units. The generator compares the total duration of notes in a bar
against the expected length to detect oversize measures (from rubato sections
or encoding errors).

---

## Tuplet Timing Deep Dive

### How MusicXML Encodes Tuplets

MusicXML encodes tuplets with two layers of information:

**1. Visual layer (`<type>`):** Each note within a tuplet still reports its
"nominal" type, such as `16th`, `eighth`, etc. This determines the drawing
style of beams/flags but does **not** represent the actual duration.

**2. Timing layer (`<duration>`):** Each note's `<duration>` (in divisions-based
ticks) **already incorporates the tuplet compression ratio**. For example, in a
score with `divisions=420`:

```
Normal 16th note duration = 105   (420/4)
16th note in a 7-tuplet  duration = 120  (already compressed)
```

Seven 16th notes total divisions = 7 × 120 = 840 ticks = 2.0 beats, which is only
the sum of nominal types. The tuplet `(7, 4)` means 7 sixteenths should occupy the
space of 4 sixteenths, i.e. 4 × 105 = 420 ticks = 1.0 beat. The MusicXML
`<duration>` values are ultimately assigned by the notation software to match the
correct total beat count.

**3. Ratio layer (`<time-modification>`):**

```xml
<time-modification>
  <actual-notes>7</actual-notes>   <!-- how many notes -->
  <normal-notes>4</normal-notes>   <!-- how many normal-note spaces they occupy -->
</time-modification>
```

`(actual-notes, normal-notes)` = `(7, 4)` means 7 notes occupy the space of 4
normal notes.

**4. Group boundaries (`<tuplet>`):**

```xml
<notations>
  <tuplet type="start"/>   <!-- tuplet begins -->
  <tuplet type="stop"/>    <!-- tuplet ends -->
</notations>
```

### Mixed-Type Tuplets

Notes within a tuplet group are not necessarily all the same type. The following
are all valid:

- `3[ q4 s5 ]`: A triplet with one eighth + one 16th
- `7[ 4 q3 s2 ]`: A septuplet with one quarter + one eighth + one 16th

In these cases, the `<time-modification>` ratio applies to the total duration of
the entire group, not to each individual note. Therefore, estimating each note's
duration via `<type>` × ratio is incorrect.

### mxml2jp's Handling Strategy

**Measure beat detection:** For measures containing tuplets, only the divisions
sum (`<duration>` accumulation) is used, without participating in the
`max(total_q, jp_total_q)` merge. Since MusicXML `<duration>` values already
incorporate the compression ratio, the divisions sum aligns precisely with the
time signature.

**`_split_notes` measure splitting:** For each note within a tuplet group, the
actual 64th-note unit count is computed via `note['duration'] * 16.0 / divisions`,
replacing the `type_to_64th()` estimation. This ensures correct calculation for
both mixed-type and uniform tuplets.

**`N[...]` bracket generation:** `tuplet_start` → emits `N[` (prefix);
`tuplet_stop` → emits `]` (suffix, placed after the last note's dash tokens).
The brackets enclose all notes in the tuplet group.

**Relies on jianpu-ly's `$j2ly_sloppy_bars` tolerance:** Even if the measure
length has slight deviations, jianpu-ly tolerates them and lays out correctly
during LilyPond compilation.

### Related Technical Notes

1. **`<time-modification>` and `<tuplet>` cooperation:**
   - `<time-modification>` only appears on the first note of a group (some
     notation software may repeat it on all notes), providing the ratio.
   - `<tuplet type="start">` / `<tuplet type="stop">` mark bracket boundaries.
   - Both must be used together to correctly generate `N[...]` markup.

2. **`<accidental>` position differences:**
   - In standard MusicXML, `<accidental>` is a child of `<notations>`.
   - However, in MuseScore 4.x exports, `<accidental>` may appear as a direct
     child of `<note>`.
   - mxml2jp checks both locations to ensure accidentals are correctly parsed.

---

## Note Parsing Details

### Articulation mapping

Articulations from `<articulations>` and `<ornaments>` are mapped to jianpu-ly
tokens:

| MusicXML tag | jianpu-ly token | Category |
|-------------|-----------------|----------|
| `<staccato>` | `Fr=▼` | Articulation |
| `<tenuto>` | `Fr=_` | Articulation |
| `<accent>` | `Fr=>` | Articulation |
| `<marcato>` | `\marcato` | LilyPond command |
| `<fermata>` | `\fermata` | LilyPond command |
| `<trill-mark>` | `\trill` | LilyPond command |
| `<mordent>` | `\mordent` | Ornament |
| `<turn>` | `\turn` | Ornament |
| `<staccatissimo>` | `\staccatissimo` | LilyPond command |
| `<strong-accent>` | `\accent` | LilyPond command |
| `<up-bow>` | `\upbow` | LilyPond command |
| `<down-bow>` | `\downbow` | LilyPond command |

`Fr=` is jianpu-ly's mechanism for attaching arbitrary markup above the note,
heavily used for Chinese instrument-specific performance symbols.

### Technical → Fr= mapping

`<technical>` elements map to `Fr=` commands for Chinese instrument
techniques:

| MusicXML `<technical>` child | jianpu-ly token | Meaning |
|------------------------------|-----------------|---------|
| `<open>` (string) | `Fr=0` | 空弦 (open string) |
| `<harmonic natural>` | `\flageolet` | 自然泛音 (natural harmonic) |
| `<harmonic artificial>` | `Fr=◇` | 人工泛音 (artificial harmonic) |
| `<snap-pizzicato>` | `Fr=up` | 左手拨弦 / 勺音 |
| `<fingering>` text | `Fr={text}` | 指法标记 (fingering) |

The patched `jianpu-ly_patched.py` extends this with Unicode glyph support for
Erhu-specific symbols (0/1/2/3/4 fingering, souyin, harmonic, up, down, bend, tilde).

### Slurs and Ties

- **Slurs** (`<slur>`) → jianpu-ly `(` (start) and `)` (stop) tokens,
  placed around the affected notes.
- **Ties** (`<tied>`) → jianpu-ly `~` token between the tied notes.
  Also handles `<tie>` at the `<note>` level (MuseScore places ties there).

### Grace Notes

Grace notes use jianpu-ly's `g[...]` syntax:

- **Before-grace** (acciaccatura/appoggiatura): `g[...]` before the main note
  - With slash: concatenated short notes like `g[#4s6]`
  - Without slash: same format, typically longer
- **After-grace**: `[...]g` appended to the previous real note's token

The program distinguishes before-grace vs after-grace by tracking whether
a real (non-grace) note has been seen yet in the current measure.

### Dynamics and Wedges

- `<dynamics>` → per-note `\p`, `\f`, `\mp`, etc.
- `<wedge type="crescendo">` → per-measure `\<`, `\>`, `\!`

### Trill Spans

`<wavy-line>` ornaments with type="start"/"stop" map to `\startTrillSpan` and
`\stopTrillSpan`, allowing sustained trills across multiple notes.

---

## Oversize Measure / Rubato Handling

Some MusicXML scores contain measures that are longer than the notated time
signature. This happens in:

1. **Rubato / cadenza sections** (散板/自由节奏): the composer intends free rhythm,
   typically annotated with "Rubato" or "散" in the score.
2. **Encoding errors**: mismatched durations from export bugs.
3. **Tuplet sections**: complex tuplets that don't fit the expected bar length.

### Detection

For each measure, the generator computes:

```
total_q = sum(note durations in quarter-note beats)
expected_q = beats × 4 / beat-type
margin = total_q - expected_q
```

If `total_q > expected_q + 0.01`, the bar is oversize.

### Handling strategies

| Margin | Condition | Action |
|--------|-----------|--------|
| ≥ 4 beats or rubato | `is_rubato` or `margin >= 4.0` | Emit LP block: override time sig stencil with "サ" (free rhythm glyph); correct time sig; notes preserved; warn user |
| < 4 beats | `margin < 4.0` | Correct time sig to fit; warn user; notes preserved |
| Exact | `total_q == expected_q` | Normal processing |

**Note**: For measures containing tuplet marks, the total beat count is computed
using MusicXML divisions (which already include compression ratios), rather than
relying on `<type>` durations. Tuplet measures are therefore no longer falsely
detected as oversize. See [Tuplet Timing Deep Dive](#tuplet-timing-deep-dive)
below for details.

---

## Multi-Voice & Chord Handling

### Voice tracking during parsing

MusicXML uses `<backup>` and `<forward>` elements to represent multiple
independent voices within a measure. The parser tracks the current position
for each voice separately:

```
Voice 1: |===notes===|=backup=|==notes==|
Voice 2:            |=notes==|=forward=| =notes=|
```

Each note gets:
- `_voice`: which voice it belongs to (1, 2, 3…)
- `_start`: its tick position within the measure

### Chord detection (`_merge_aligned_notes`)

After parsing, notes with the same `_start` position are grouped. If they
have the same duration and none is a rest, they are merged as a chord:

- The first note in the group keeps `is_chord = False` (the "anchor" note).
- Subsequent notes get `is_chord = True` (they collapse together in output).

**Note**: The current implementation merges across **all voices**, not just
within the same voice. This means independent melodic lines with simultaneous
attacks may be incorrectly merged into chords. For single-voice parts this
is not an issue, but for multi-voice scores it can produce spurious chords.

### Chord output formatting

`_format_chord_v2()` (line 1120) combines chord notes into a single jianpu-ly
token:

```
Input:  [('q1', ('', '', 1, 'q', 0)), ('q3', ('', '', 3, 'q', 0))]
Output: "q13"        (both degrees share the "q" prefix)
```

The prefix letter and dot count come from the first chord entry; pitch parts
(octave + accidental + degree) from all entries are concatenated.

---

## CLI Options

| Option | Description |
|--------|-------------|
| `input` (required) | MusicXML file: `.xml`, `.musicxml`, or `.mxl` |
| `-o FILE`, `--output FILE` | Write output to file instead of stdout |
| `--minor` | Use minor key notation: `6=X` instead of `1=X` |
| `--verbose`, `-v` | Per-measure diagnostics to stderr |
| `--octave-traditional` | Traditional octave marks: low before digit, high after (`,,1` vs `1'`) |

Examples:

```sh
# Basic conversion
python mxml2jp.py piece.musicxml -o piece.txt

# Minor key (la = tonic)
python mxml2jp.py piece.xml --minor

# Verbose mode for debugging bar lengths
python mxml2jp.py piece.mxl -v -o piece.txt 2> debug.log

# Traditional octave style (兼容旧版jianpu-ly习惯)
python mxml2jp.py piece.musicxml --octave-traditional
```

---

## Supported MusicXML Elements

| MusicXML Element | Support | Details |
|-----------------|---------|---------|
| Pitch (`<step>`, `<octave>`, `<alter>`) | Full | Converted via `note_to_jianpu()` |
| Key signature (`<key><fifths>`) | Full | Emitted as `1=X` or `6=X` |
| Time signature (`<time>`) | Full | Emitted as `beats/beat-type` |
| Tempo (`<metronome>`) | First only | `unit=bpm` on first occurrence |
| Dynamics (`p`, `mp`, `f`, `ff`…) | Full | Per-note `\p`, `\f`, etc. |
| Crescendo / Diminuendo wedges | Full | `\<`, `\>`, `\!` per measure |
| Text annotations (`<words>`) | Full | `^"text"` (above) or `_"text"` (below) |
| Slurs (`<slur>`) | Full | `(` and `)` |
| Ties (`<tied>`, `<tie>`) | Full | `~` |
| Articulations (staccato, tenuto, accent…) | Full | `Fr=▼`, `Fr=_`, `Fr=>`, etc. |
| Ornaments (trill, mordent, turn, tremolo) | Full | `\trill`, `\mordent`, `///`, etc. |
| Trill spans (`<wavy-line>`) | Full | `\startTrillSpan` / `\stopTrillSpan` |
| Technical: harmonic, open, fingering, etc. | Partial | `Fr=` commands (see table above) |
| Chords (`<chord/>`) | Full | Merged pitch parts, shared duration prefix |
| Grace notes (before + after) | Full | `g[...]` and `[...]g` |
| Tuplets (`<time-modification>`) | **Replaced** | Entire measure → `R*1` + stderr warning |
| Multi-measure rests | Full | Accumulated into `R*N` |
| Backup / Forward | Full | Merged into chords by `_merge_aligned_notes()` |
| Repeats | Partial | `R{` start, `}` end (no volta/ending support) |
| Barline styles | Partial | `\|` regular, `!` dashed, `;` dotted, `\|\|` double |

**Not yet supported**: rehearsal marks, ottava (8va), expression tempo text (`<words>`
with tempo meaning), glissando, arpeggio, volta brackets (1st/2nd endings).

---

## Output Format Reference

The generated text follows the jianpu-ly input format. Example excerpt:

```
title=未命名乐谱
composer=作曲 / 编排
instrument=二泉琴
OctavesBefore
1=Eb
4/4
^"Rubato"
\p ( ,3 - ,4 - )
1 - 7 -
\mp ,3 - 6 -
\> \! 7 - - -
\p ( ,3 - ,4 - )
...
NextPart
instrument=竹笛
OctavesBefore
1=Eb
4/4
...
```

Key syntax elements:
- `title=` / `composer=` / `instrument=` — metadata headers
- `OctavesBefore` — octave marks appear before the digit (default in v0.3.0)
- `1=Eb` — key signature: tonic is scale degree 1, pitch is E♭
- `4/4`, `3/4` — time signatures
- `\p`, `\mp`, `\<`, `\>` — dynamics and wedges
- `(` / `)` — slur start / end
- `,3` — low octave (comma before digit)
- `'7` — high octave (apostrophe before digit with `OctavesBefore`)
- `-` — dash (extends previous note by one beat)
- `q` — eighth note prefix; `s` = 16th; `d` = 32nd; `h` = 64th
- `Fr=▼` — staccato mark; `Fr=0` — open string
- `\fermata`, `\prall`, `\trill` — LilyPond commands passed through by jianpu-ly
- `R*1` — one bar rest; `R*5` — five bars rest
- `g[...]` — before-grace notes; `[...]g` — after-grace notes
- `LP: ...` / `:LP` — raw LilyPond block (for special overrides)
- `NextPart` — separates parts in multi-part scores

---

## Test Files

The following MusicXML files are available for testing in `../lilypond教学/`:

| File | Source | Type | Notes |
|------|--------|------|-------|
| `YiNian.musicxml` | MuseScore 4.5 | Single voice (二胡) | Clean, well-structured |
| `一念.musicxml` | MuseScore 4.5 | Two voices (竹笛 + 二泉琴) | Multi-part test |
| `Barber-Excursions_III.musicxml` | MuseScore | Full score, multi-voice with tuplets | Tests tuplet warning |
| `Barber-Excursions_III-木琴.musicxml` | MuseScore | Single percussion part | Xylophone |
| `Barber-Excursions_III-马林巴琴（大谱表）.musicxml` | MuseScore | Grand staff (marimba) | Two-staff part |
| `草原小姐妹总谱.musicxml` | Sibelius | Full orchestral score (~15 MB) | Chinese text encoding issues |
| `浮生听风3.xml` | PhotoScore | Four-part score (~1 MB) | Tests PhotoScore XML format |

Use these for regression testing during development:
```sh
# Batch test on all available files
Get-ChildItem ..\lilypond教学\*.musicxml,..\lilypond教学\*.xml | ForEach-Object {
    Write-Host "--- Testing $($_.Name) ---"
    python mxml2jp.py $_.FullName -v -o "$($_.BaseName).txt" 2>&1
}
```

---

## Known Issues & Limitations

### Design limitations

1. **Multi-voice chords merged across voices** — `_merge_aligned_notes()` does
   not respect the `voice` attribute. Independent voices with simultaneous
   attacks get merged into spurious chords.

2. **No multi-voice bar synchronization for rubato** — When two parts share
   a rubato section, their rest fillers may differ in length, causing
   misalignment in the final score.

3. **Chinese text from Sibelius may encode as gibberish** — Sibelius exports
   Chinese text in non-UTF-8 encodings. The `read_input()` function tries
   UTF-8 then GBK/GB2312 fallback, but this does not cover all cases.
   Known affected file: `草原小姐妹总谱.musicxml`.

4. **Only partwise MusicXML is supported** — Timewise MusicXML (score-timewise)
   will raise an error. Most modern notation software exports partwise by
   default, so this is rarely a problem.

### Code bugs

5. **Unreachable code** — Line 462–463: a second `return mdata` after
   `_merge_aligned_notes()` has already returned. Lines 927–937: duplicate
   `_is_whole_rest_measure` code after `_split_notes()` return.

6. **`LP_TECHNICAL` dict overwritten** — Defined twice (lines 92–98 and
   100–104). The second definition overwrites the first, losing the
   `'stopped': r'\stopped'` entry.

7. **Hardcoded Windows path** — Line 6 contains `E:\USTC\NMOU\mxml2jp\`,
   which is a local Windows path and should be removed.

8. **README lists `.mxl` as TODO** — But `read_input()` already implements
   `.mxl` decompression via `zipfile.ZipFile`. The TODO item is stale.

---

## TODO / Future Work

- **Multi-voice bar synchronization**: Ensure that rubato rest lengths are
  consistent across parts sharing the same measure, so the final score aligns
  correctly.

- **Voice-aware chord merging**: Modify `_merge_aligned_notes()` to only
  merge notes within the same voice; cross-voice simultaneous notes should
  remain separate (handled as independent lines).

- **Rehearsal marks**: Parse `<rehearsal>` elements and emit `^"A"`, `^"B"`,
  etc.

- **Volta / endings**: Handle `<ending>` elements for 1st/2nd ending brackets.

- **Ottava (8va)**: Parse `<octave-shift>` for automatic octave transposition.

- **More Chinese instrument techniques**: Expand `FR_TECHNICAL` and
  `LP_TECHNICAL` to cover 滑音 (glissando/portamento), 打音 (trill with
  lower neighbor), 揉弦 (vibrato), 拨弦 (pizzicato variations), etc.

- **Unit tests**: Add a pytest-based test suite using the existing test
  MusicXML files. Start with YiNian.musicxml (single voice, known good
  output).

- **Remove dead code**: Clean up unreachable `return mdata` and duplicate
  function definitions.

- **Fix `LP_TECHNICAL` duplication**: Merge the two definitions into one
  complete dict.

---

## Changelog

### v0.3.1 (in development)
- **Tuplet support**: Tuplet measures no longer replaced with rests; actual
  timing computed from MusicXML divisions
  - `_split_notes` uses `<duration>` divisions rather than `<type>` estimation
    for notes within tuplets
  - Mixed-type tuplets supported (e.g. `3[q4 s5]`, `7[4 q3 s2]`)
  - `N[...]` brackets correctly enclose the entire tuplet group (`tuplet_stop`
    `]` is now a suffix, not a prefix)
- **Rubato note preservation**: Oversize/rubato measures no longer discard
  notes; only time sig is adjusted + "サ" stencil override
- **Slur convention fix**: `(` is now a suffix (LilyPond convention:
  `c4 ( d4 e4 )` rather than `( c4 d4 e4 )`)
- **`<accidental>` dual-location**: Checks both direct `<note>` children and
  `<notations>` content (compatible with MuseScore 4.x exports)
- **`--part` / `-p` option**: Filter specific parts by 1-based index or name
  substring
- **Tuplet boundary splitting**: Tuplet groups are not split across barlines,
  preserving complete `N[...]` boundaries

### v0.3.0
- `--octave-traditional` flag for old-style octave marks
- Tuplet measures replaced with `R*1` without time sig change
- `read_input()`: UTF-8/GBK fallback encoding for Chinese text
- Rests use explicit `0` tokens instead of dashes
- Time signature always restored after rubato oversize sections

### v0.2.1
- Feature flags (`self.feat`) for incremental compile testing
- Wedges (`\<`, `\>`, `\!`), per-note dynamics, word annotations
- `Fr=` technical markup for instrument techniques
- `\bendAfter` removed (multi-token incompatibility with jianpu-ly)

### v0.2.0
- After-grace notes, tremolo (`///`), trill spans
- `Fr=` mappings for harmonic, fingering, open string
- Oversize measure auto-detection and handling

### v0.1.0
- Initial release: basic pitch, key, time, slurs, ties, chords

---

## Dependencies

- Python 3.7+
- Standard library only: `xml.etree.ElementTree`, `argparse`, `zipfile`, `re`, `sys`, `os`
- No external pip packages

For compiling output to PDF:
- [jianpu-ly.py](https://github.com/ssb22/jianpu-ly) (v1.866+; the patched version `jianpu-ly_patched.py` is recommended for chord octave alignment and Chinese instrument symbols)
- [LilyPond](https://lilypond.org/) 2.24+

---

## License

Apache 2.0 — see the jianpu-ly project for the upstream license.
