#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
mxml2jp.py v0.2.1 — Convert MusicXML to jianpu-ly input format

home: E:\USTC\NMOU\mxml2jp\
depends: jianpu-ly v1.866+ (https://github.com/ssb22/jianpu-ly)

Usage:
    python mxml2jp.py piece.musicxml [-o output.txt]
    python mxml2jp.py piece.xml
    python mxml2jp.py piece.mxl

Supports partwise MusicXML from MuseScore, Sibelius, PhotoScore, etc.
Output is plain text suitable as jianpu-ly input.

Tested with:
    - MuseScore 4.5 exports (.musicxml)
    - Sibelius exports (.musicxml, .xml)
    - PhotoScore XML (.xml)
"""

import xml.etree.ElementTree as ET
import sys, os, re, argparse, zipfile

# ============================================================
# Pitch / Key constants
# ============================================================

STEP_ORDER = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}
DEG2LETTER = {0: 'C', 1: 'D', 2: 'E', 3: 'F', 4: 'G', 5: 'A', 6: 'B'}
LETTER_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
DEG2SEMI = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}

SHARP_ORDER = [3, 0, 4, 1, 5, 2, 6]   # F, C, G, D, A, E, B
FLAT_ORDER = [6, 2, 5, 1, 4, 0, 3]    # B, E, A, D, G, C, F

FIFTHS_TO_MAJOR = {
    0: ('1', 'C'),   1: ('1', 'G'),  2: ('1', 'D'),
    3: ('1', 'A'),   4: ('1', 'E'),  5: ('1', 'B'),
    6: ('1', 'F#'),  7: ('1', 'C#'),
    -1: ('1', 'F'),  -2: ('1', 'Bb'), -3: ('1', 'Eb'),
    -4: ('1', 'Ab'), -5: ('1', 'Db'), -6: ('1', 'Gb'), -7: ('1', 'Cb'),
}

FIFTHS_TO_MINOR = {
    0: ('6', 'Am'),   1: ('6', 'Em'),  2: ('6', 'Bm'),
    3: ('6', 'F#m'),  4: ('6', 'C#m'), 5: ('6', 'G#m'),
    6: ('6', 'D#m'),  7: ('6', 'A#m'),
    -1: ('6', 'Dm'),  -2: ('6', 'Gm'), -3: ('6', 'Cm'),
    -4: ('6', 'Fm'),  -5: ('6', 'Bbm'),-6: ('6', 'Ebm'), -7: ('6', 'Abm'),
}

ACC_MAP = {
    'sharp': 1, 'flat': -1, 'natural': 0,
    'double-sharp': 2, 'flat-flat': -2,
}

DYNAMICS = {
    'p', 'pp', 'ppp', 'pppp', 'mp', 'mf',
    'f', 'ff', 'fff', 'ffff', 'sf', 'sfz', 'fp', 'rfz',
}

BAR_STYLE_MAP = {
    'regular': r'|',   'dashed': r'!',    'dotted': r';',
    'heavy': r'.',     'light-light': r'||',  'light-heavy': r'|.',
    'none': '',
}

ARTICS = {
    'staccato': r'Fr=▼', 'tenuto': r'Fr=_',
    'accent': r'Fr=>', 'marcato': r'\marcato',
    'fermata': r'\fermata',
    'trill-mark': r'\trill', 'mordent': r'\mordent',
    'inverted-mordent': r'\prall', 'turn': r'\turn',
    # v0.2.0 additions
    'staccatissimo': r'\staccatissimo',
    'strong-accent': r'\accent',
    'up-bow': r'\upbow',
    'down-bow': r'\downbow',
    # Multi-arg commands like \bendAfter #4 don't work in jianpu (split tokens)
    # 'doit': 'skip', 'falloff': 'skip', 'plop': 'skip', 'scoop': 'skip',
    # \breathe also may cause issues with placement
}

FR_TECHNICAL = {
    'open': '0',               # 空弦 → Fr=0
    'snap-pizzicato': 'up',    # 左手拨弦 → ↗
}

# One-word LilyPond \commands for technical elements (passed through by jianpu-ly)
LP_TECHNICAL = {
    'harmonic': r'\flageolet',           # natural harmonic
    'stopped': r'\stopped',              # 右手拨弦 / pizzicato
    'open': r'\open',                    # open string
    'snap-pizzicato': r'\snappizzicato', # snap / bartok pizz
}

# One-word LilyPond \commands for technical elements (passed through by jianpu-ly)
LP_TECHNICAL = {
    'harmonic': r'\flageolet',     # natural harmonic (or \harmonic in jianpu)
    'open': r'\open',              # open string
    'snap-pizzicato': r'\snappizzicato',  # snap / bartok pizz
}

# Duration type -> jianpu marker (prefix) and beam count
DUR_INFO = {
    '64th':    ('h', 4),
    '32nd':    ('d', 3),
    '16th':    ('s', 2),
    'eighth':  ('q', 1),
    'quarter': ('', 0),
    'half':    ('', 0),
    'whole':   ('', 0),
    'breve':   ('', 0),
}

# Convert MusicXML type to jianpu 64th-note units (jianpu bar = 64 units per 4/4 bar)
def type_to_64th(ntype, dots):
    base = {'64th': 1, '32nd': 2, '16th': 4, 'eighth': 8,
            'quarter': 16, 'half': 32, 'whole': 64, 'breve': 128}.get(ntype, 16)
    total = float(base)
    for _ in range(dots):
        total *= 1.5
    return int(total + 0.1)  # round for floating point

# Number of dash tokens following a note
# (in jianpu: "1 -" = half, "1 - - -" = whole)
# For long notes, dots on the primary note are NOT used; extra length
# becomes additional dashes. "1 - -" = dotted half, not "1. -".
def dash_count(ntype, dots):
    base = {'64th': 0.25, '32nd': 0.5, '16th': 1, 'eighth': 2,
            'quarter': 4, 'half': 8, 'whole': 16, 'breve': 32}.get(ntype, 4)
    total = base
    for _ in range(dots):
        total *= 1.5
    quarters = total / 4.0
    if ntype in ('half', 'whole', 'breve'):
        # Long notes: primary token is always a quarter-note figure (no dots);
        # remainder becomes dashes.
        return max(0, int(quarters) - 1)
    return 0


# ============================================================
# Key signature helpers
# ============================================================

def get_key_sig_accidentals(fifths):
    """Return {step_letter: alteration (+1=sharp, -1=flat)} for key sig."""
    r = {}
    if fifths > 0:
        for i in range(fifths):
            r[DEG2LETTER[SHARP_ORDER[i]]] = 1
    elif fifths < 0:
        for i in range(-fifths):
            r[DEG2LETTER[FLAT_ORDER[i]]] = -1
    return r


def note_to_jianpu(step, octave, alter_val, fifths, key_sig):
    """
    Convert MusicXML absolute pitch to jianpu (degree, accidental, octave_marks).

    step       : 'C'..'B'
    octave     : 0..9  (MusicXML octave, C4 = middle C)
    alter_val  : float or None (chromatic alteration in semitones; None = use key sig default)
    fifths     : key signature fifths value
    key_sig    : {step: 0|1|-1} precomputed from get_key_sig_accidentals

    Returns: (degree: int 1-7, acc: ''/'#'/'b', octave_marks: str)
    """
    tonic_letter = DEG2LETTER[(fifths * 4) % 7]
    step_idx = STEP_ORDER[step]
    tonic_idx = STEP_ORDER[tonic_letter]

    # Effective alteration of this note in semitones
    key_step_acc = key_sig.get(step, 0)  # +1, -1, or 0 from key signature
    if alter_val is None:
        eff = float(key_step_acc)
    else:
        eff = float(alter_val)

    # Diatonic steps from reference tonic at octave 4
    dTone = step_idx - tonic_idx
    if step_idx < tonic_idx:
        dTone += 7
    dTone += 7 * (octave - 4)

    # Degree (1-7)
    degree = dTone % 7 + 1
    octave_count = dTone // 7
    if octave_count >= 0:
        octave_marks = "'" * octave_count
    else:
        octave_marks = "," * (-octave_count)

    # Jianpu accidental: does the effective alteration differ from the
    # key-signature default?
    if key_step_acc != 0:
        if eff == key_step_acc:
            acc = ''
        elif eff == 0.0:
            # Natural sign countering a key sharp or flat
            acc = 'b' if key_step_acc == 1 else '#'
        else:
            acc = '#' if eff > 0 else 'b'
    else:
        if eff == 0.0:
            acc = ''
        else:
            acc = '#' if eff > 0 else 'b'

    return degree, acc, octave_marks


# ============================================================
# MusicXML Parsing
# ============================================================

class MusicXmlParser:

    def __init__(self, prefer_major=True):
        self.prefer_major = prefer_major

    def parse(self, xml_string):
        root = ET.fromstring(xml_string)
        if root.tag != 'score-partwise':
            raise ValueError(
                "Only partwise MusicXML is supported. "
                "Convert timewise scores to partwise first.")

        # Read metadata
        title = self._get_text(root, './/work/work-title')
        composer = ''
        ident = root.find('identification')
        if ident is not None:
            for cr in ident.findall('creator'):
                if cr.get('type', '') == 'composer':
                    composer = (cr.text or '').strip()
                    break
            if not composer:
                crs = ident.findall('creator')
                if crs:
                    composer = (crs[0].text or '').strip()

        # Part names
        part_names = {}
        pl = root.find('part-list')
        if pl is not None:
            for sp in pl.findall('score-part'):
                pid = sp.get('id', '')
                pn = sp.find('part-name')
                part_names[pid] = pn.text.strip() if pn is not None and pn.text else ''

        # Parse each <part>
        parts = []
        for part_elem in root.findall('part'):
            pid = part_elem.get('id', '')
            name = part_names.get(pid, pid)
            measures = self._parse_part(part_elem)
            parts.append((name, measures))

        return title, composer, parts

    def _get_text(self, element, xpath, default=''):
        found = element.find(xpath)
        if found is not None and found.text:
            return found.text.strip()
        return default

    def _parse_part(self, part_elem):
        """Parse one <part> element into a list of measure dicts."""
        measures = []
        cur_fifths = 0
        cur_time = (4, 4)
        cur_divisions = 1
        part_key_seen = False
        part_time_seen = False

        for m in part_elem.findall('measure'):
            mdata = self._parse_measure(m, cur_fifths, cur_time, cur_divisions,
                                        part_key_seen, part_time_seen)
            if mdata.get('key_change') is not None:
                cur_fifths = mdata['key_change']
                part_key_seen = True
            if mdata.get('time_change') is not None:
                cur_time = mdata['time_change']
                part_time_seen = True
            if mdata.get('divisions'):
                cur_divisions = mdata['divisions']
            measures.append(mdata)

        return measures

    def _parse_measure(self, m_elem, cur_fifths, cur_time, cur_divisions,
                       part_key_seen, part_time_seen):
        """Parse one <measure> element, handling multi-voice via backup/forward."""
        mdata = {
            'number': int(m_elem.get('number', '0')),
            'notes': [],
            'key_change': None,
            'time_change': None,
            'tempo': None,
            'dynamic': None,
            'directions': [],
            'annotations': [],
            'has_repeat_start': False,
            'has_repeat_end': False,
            'is_final': False,
            'bar_style': None,
            'divisions': cur_divisions,
        }

        # Multi-voice tracking
        current_voice = 1
        voice_starts = {1: 0}   # voice → start position in divisions

        for child in m_elem:
            tag = child.tag

            if tag == 'attributes':
                key_e = child.find('key')
                if key_e is not None:
                    f = int(key_e.findtext('fifths', '0'))
                    if f != cur_fifths or not part_key_seen:
                        mdata['key_change'] = f

                time_e = child.find('time')
                if time_e is not None:
                    beats = int(time_e.findtext('beats', '4'))
                    bt = int(time_e.findtext('beat-type', '4'))
                    # Always record explicit time sigs (needed for rubato reset)
                    mdata['time_change'] = (beats, bt)

                div_e = child.find('divisions')
                if div_e is not None:
                    mdata['divisions'] = int(div_e.text)

            elif tag == 'direction':
                self._parse_direction_elem(child, mdata)

            elif tag == 'backup':
                bk_dur = int(child.findtext('duration', '0'))
                current_voice += 1
                max_pos = max(voice_starts.values()) if voice_starts else 0
                if current_voice not in voice_starts:
                    voice_starts[current_voice] = max(0, max_pos - bk_dur)

            elif tag == 'forward':
                fw_dur = int(child.findtext('duration', '0'))
                voice_starts[current_voice] = voice_starts.get(current_voice, 0) + fw_dur

            elif tag == 'note':
                note = self._parse_note(child)
                if note:
                    # Assign to current voice and track position
                    note['_voice'] = current_voice
                    note['_start'] = voice_starts.get(current_voice, 0)
                    dur = int(child.findtext('duration', '0'))
                    voice_starts[current_voice] = note['_start'] + dur
                    mdata['notes'].append(note)

            elif tag == 'barline':
                self._parse_barline_elem(child, mdata)

        # Post-process: merge aligned notes into chords
        mdata['notes'] = self._merge_aligned_notes(mdata['notes'])

        return mdata

    def _parse_direction_elem(self, child, mdata):
        """Parse a <direction> element (refactored from _parse_measure)."""
        for dt in child.findall('direction-type'):
            met = dt.find('metronome')
            if met is not None:
                bu = met.find('beat-unit')
                pm = met.find('per-minute')
                if bu is not None and pm is not None:
                    unit = {'quarter': '4', 'eighth': '8',
                            'half': '2', '16th': '16'}.get(bu.text, '4')
                    mdata['tempo'] = f"{unit}={pm.text}"

            dyn = dt.find('dynamics')
            if dyn is not None:
                for dtag in dyn:
                    if dtag.tag in DYNAMICS:
                        mdata['dynamic'] = '\\' + dtag.tag

            wedge = dt.find('wedge')
            if wedge is not None:
                wt = wedge.get('type', '')
                if wt == 'crescendo':
                    mdata['directions'].append(r'\<')
                elif wt == 'diminuendo':
                    mdata['directions'].append(r'\>')
                elif wt == 'stop':
                    mdata['directions'].append(r'\!')

            words = dt.find('words')
            if words is not None and words.text:
                txt = words.text.strip().replace('"', "'")
                if txt:
                    placement = child.get('placement', 'above')
                    if placement == 'below':
                        mdata['annotations'].append(f'_{chr(34)}{txt}{chr(34)}')
                    else:
                        mdata['annotations'].append(f'^{chr(34)}{txt}{chr(34)}')

    def _parse_barline_elem(self, child, mdata):
        """Parse a <barline> element."""
        rp = child.find('repeat')
        if rp is not None:
            d = rp.get('direction', '')
            if d == 'forward':
                mdata['has_repeat_start'] = True
            elif d == 'backward':
                mdata['has_repeat_end'] = True
        bs = child.find('bar-style')
        if bs is not None and bs.text:
            if bs.text in ('light-light', 'light-heavy', 'final'):
                mdata['is_final'] = True
            mdata['bar_style'] = bs.text

    def _merge_aligned_notes(self, notes):
        """Merge notes that start at the same position into chords.
        Returns list of notes, with chord-merged notes marked is_chord=True."""
        if len(notes) <= 1:
            return notes

        # Group by _start only (ignore voice to merge simultaneous notes)
        from collections import OrderedDict
        groups = OrderedDict()
        for n in notes:
            key = n.get('_start', 0)
            if key not in groups:
                groups[key] = []
            groups[key].append(n)

        result = []
        for start, group in groups.items():
            if len(group) == 1:
                result.extend(group)
            else:
                # Multiple notes at the same start position
                durations = [(n.get('ntype', ''), n.get('dots', 0)) for n in group]
                same_dur = all(d == durations[0] for d in durations)
                if same_dur and not any(n.get('is_rest') for n in group):
                    # Merge into chord: first note stays, others get is_chord
                    for i, n in enumerate(group):
                        if i == 0:
                            n['is_chord'] = False
                        else:
                            n['is_chord'] = True
                    result.extend(group)
                else:
                    # Different durations or contains rests: keep separate, warn
                    result.extend(group)
            prev_start = start

        return result

        return mdata

    def _parse_note(self, note_elem):
        """Parse a single <note> element."""
        is_rest = note_elem.find('rest') is not None
        is_chord = note_elem.find('chord') is not None
        is_grace = note_elem.find('grace') is not None
        is_measure_rest = False

        if is_rest:
            rest_e = note_elem.find('rest')
            if rest_e is not None and rest_e.get('measure') == 'yes':
                is_measure_rest = True

        # Pitch
        step = octave_val = alter_val = None
        if not is_rest:
            pitch = note_elem.find('pitch')
            if pitch is None:
                return None
            step = pitch.findtext('step', 'C')
            octave_val = int(pitch.findtext('octave', '4'))
            alt = pitch.find('alter')
            if alt is not None and alt.text:
                alter_val = float(alt.text)

        dur = int(note_elem.findtext('duration', '0'))
        ntype = note_elem.findtext('type', '')
        dots = len(note_elem.findall('dot'))
        voice = note_elem.findtext('voice', '1')

        # Notations
        tie_start = tie_stop = False
        slur_start = False; slur_stop = False
        artic = []
        fr_marks = []     # Fr= commands for Chinese instrument symbols
        dynamic = None
        fermata = False
        accidental_text = None
        tremolo_beams = 0  # number of /// for tremolo

        notations = note_elem.find('notations')
        if notations is not None:
            for t_e in notations.findall('tied'):
                tp = t_e.get('type', '')
                if tp == 'start': tie_start = True
                elif tp == 'stop': tie_stop = True

            for s_e in notations.findall('slur'):
                tp = s_e.get('type', '')
                if tp == 'start': slur_start = True
                elif tp == 'stop': slur_stop = True

            acc_e = notations.find('accidental')
            if acc_e is not None and acc_e.text:
                accidental_text = acc_e.text
                if alter_val is None and accidental_text in ACC_MAP:
                    alter_val = float(ACC_MAP[accidental_text])

            arts_e = notations.find('articulations')
            if arts_e is not None:
                for a in arts_e:
                    if a.tag in ARTICS:
                        artic.append(ARTICS[a.tag])
                    elif a.tag == 'breath-mark':
                        pass  # breath mark — no jianpu equivalent yet

            orn_e = notations.find('ornaments')
            if orn_e is not None:
                for o in orn_e:
                    if o.tag in ARTICS:
                        artic.append(ARTICS[o.tag])
                    elif o.tag == 'tremolo':
                        # <tremolo type="single">3</tremolo> → 3 beams → ///
                        n_beams = int(o.text) if o.text else 1
                        tremolo_beams = max(tremolo_beams, n_beams)
                    elif o.tag == 'wavy-line':
                        typ = o.get('type', '')
                        if typ == 'start':
                            artic.append(r'\startTrillSpan')
                        elif typ == 'stop':
                            artic.append(r'\stopTrillSpan')

            # Technical (harmonic, stopped, fingering, etc.) → Fr= commands
            tech_e = notations.find('technical')
            if tech_e is not None:
                for t in tech_e:
                    if t.tag == 'harmonic':
                        # Natural harmonic → \flageolet, artificial → Fr=◇
                        if t.find('artificial') is not None:
                            fr_marks.append(r'Fr=◇')       # 人工泛音
                        else:
                            artic.append(r'\flageolet')     # 自然泛音
                    elif t.tag in FR_TECHNICAL:
                        fr_marks.append(f"Fr={FR_TECHNICAL[t.tag]}")
                    elif t.tag == 'fingering':
                        txt = (t.text or '').strip()
                        if txt:
                            fr_marks.append(f"Fr={txt}")

            dyn_e = notations.find('dynamics')
            if dyn_e is not None:
                for d in dyn_e:
                    if d.tag in DYNAMICS:
                        dynamic = '\\' + d.tag

            if notations.find('fermata') is not None:
                artic.append(r'\fermata')

        # Tuplet info
        tuplet_start = False
        tuplet_stop = False
        tuplet_ratio = None
        tmod = note_elem.find('time-modification')
        if tmod is not None:
            an = int(tmod.findtext('actual-notes', '3'))
            nn = int(tmod.findtext('normal-notes', '2'))
            tuplet_ratio = (an, nn)

        # Check for tuplet marks in notations
        if notations is not None:
            for tup in notations.findall('tuplet'):
                if tup.get('type', '') == 'start':
                    tuplet_start = True
                elif tup.get('type', '') == 'stop':
                    tuplet_stop = True

        # Grace type
        grace_slash = False
        if is_grace:
            g = note_elem.find('grace')
            if g is not None and g.get('slash') == 'yes':
                grace_slash = True

        # Tie at note level (MuseScore puts <tie> as child of <note>)
        note_tie_start = note_elem.find('tie')
        if note_tie_start is not None:
            if note_tie_start.get('type') == 'start':
                tie_start = True
            elif note_tie_start.get('type') == 'stop':
                tie_stop = True

        return {
            'is_rest': is_rest,
            'is_measure_rest': is_measure_rest,
            'is_chord': is_chord,
            'is_grace': is_grace,
            'grace_slash': grace_slash,
            'step': step,
            'octave': octave_val,
            'alter': alter_val,
            'duration': dur,
            'ntype': ntype,
            'dots': dots,
            'voice': voice,
            'tie_start': tie_start,
            'tie_stop': tie_stop,
            'slur_start': slur_start,
            'slur_stop': slur_stop,
            'artic': artic,
            'fr_marks': fr_marks,
            'dynamic': dynamic,
            'tuplet_start': tuplet_start,
            'tuplet_stop': tuplet_stop,
            'tuplet_ratio': tuplet_ratio,
            'fermata': fermata,
            'tremolo_beams': tremolo_beams,
        }


# ============================================================
# Jianpu text generator
# ============================================================

class JianpuGenerator:
    """Generate jianpu-ly text from parsed MusicXML."""

    def __init__(self, prefer_major=True, verbose=False, octave_traditional=False):
        self.prefer_major = prefer_major
        self.verbose = verbose
        self.octave_traditional = octave_traditional
        # Feature flags: enable incrementally for testing
        self.feat = {
            'slurs': True, 'ties': True, 'chords': True, 'grace': True,
            'articulations': True,   # Fr=▼/Fr=>/Fr=_ etc
            'dynamics': True,        # per-note \p \f etc
            'wedges': True,          # \< \> \!
            'annotations': True,     # ^"...", _"..." 
            'fr_technical': True,    # Fr=harmonic/◇/souyin
            'tremolo': True, 'trill_span': True,
        }

    def generate(self, title, composer, parts):
        """parts: list of (part_name, [measure_dict, ...])
        Returns complete jianpu-ly input text."""
        out = []

        if title:
            out.append(f"title={title}")
        if composer:
            out.append(f"composer={composer}")

        for idx, (pname, measures) in enumerate(parts):
            if idx > 0:
                out.append('NextPart')
            if pname and pname.strip():
                out.append(f"instrument={pname}")
            if not self.octave_traditional:
                out.append('OctavesBefore')

            part_lines = self._generate_part(measures)
            out.extend(part_lines)

        return '\n'.join(out) + '\n'

    def _best_timesig(self, total_quarters):
        """Compute the cleanest time signature for a given number of quarter-note beats.
        Returns (beats, beat_type) like (14, 4) or (9, 8)."""
        q = total_quarters
        for mult, beat_type in [(1, 4), (2, 8), (4, 16)]:
            v = q * mult
            r = round(v)
            if abs(v - r) < 0.01:
                return (r, beat_type)
        # Fallback: ceil to ensure bar fits all notes
        r = int(q * 4 + 0.999)
        return (r, 16)

    def _generate_part(self, measures):
        """Generate jianpu lines for one part's measures."""
        lines = []
        cur_fifths = 0
        cur_time = (4, 4)
        tempo_emitted = False
        multirest_count = 0
        in_repeat = False  # track repeat nesting

        for mdata in measures:
            # Handle key change
            kc = mdata.get('key_change')
            if kc is not None:
                cur_fifths = kc
                tbl = FIFTHS_TO_MINOR if not self.prefer_major else FIFTHS_TO_MAJOR
                prefix, key_name = tbl.get(kc, ('1', 'C'))
                lines.append(f"{prefix}={key_name}")
                self._cur_key_sig = get_key_sig_accidentals(cur_fifths)

            # Handle time change — always emit if present (resets after rubato)
            tc = mdata.get('time_change')
            if tc is not None:
                cur_time = tc
                lines.append(f"{tc[0]}/{tc[1]}")
            if cur_time is None:
                cur_time = (4, 4)

            # Tempo
            if mdata.get('tempo') and not tempo_emitted:
                tempo_emitted = True
                lines.append(mdata['tempo'])

            if cur_fifths is None:
                cur_fifths = 0
                self._cur_key_sig = get_key_sig_accidentals(0)

            # Check for consecutive full-measure rests (but only if no directions/wedges)
            notes = mdata.get('notes', [])
            has_dirs = bool(mdata.get('directions') or mdata.get('dynamic'))
            if self._is_whole_rest_measure(notes, mdata.get('time_change')) and not has_dirs:
                multirest_count += 1
                continue
            elif multirest_count > 0:
                if multirest_count == 1:
                    lines.append('R*1')
                else:
                    lines.append(f"R*{multirest_count}")
                multirest_count = 0

            # Split oversized MusicXML measures into sub-bars before token generation
            raw_notes = mdata.get('notes', [])

            # Detect oversize measures and rubato / cadenza
            raw_notes = mdata.get('notes', [])

            # Detect rubato from word annotations
            is_rubato = any(
                'rubato' in a.lower() or 'cadenza' in a.lower() or '散' in a
                for a in mdata.get('annotations', []))
            treated_rubato = False  # whether LP blocks were emitted

            divs = mdata.get('divisions', 420)
            total_q = sum(n.get('duration', 0) for n in raw_notes
                        if not n.get('is_grace') and not n.get('is_measure_rest')
                        and not n.get('is_chord')) / float(divs)
            # Also compute jianpu-style total to catch type-based mismatches
            jp_total_q = sum(type_to_64th(n.get('ntype', 'quarter'), n.get('dots', 0))
                           for n in raw_notes if not n.get('is_grace') and not n.get('is_measure_rest')
                           and not n.get('is_chord')) / 16.0
            total_q = max(total_q, jp_total_q)
            expected_q = cur_time[0] * 4.0 / cur_time[1]

            # Detect tuplet presence — replace tuplet measures with rest
            has_tuplet = any(n.get('tuplet_ratio') for n in raw_notes)

            if has_tuplet and total_q > expected_q + 0.005:
                sys.stderr.write(
                    f"WARNING: M{mdata.get('number', '?')}: tuplet measure "
                    f"({total_q:.2f}Q vs {expected_q:.1f}Q) → replaced with rest. "
                    f"Fill manually.\n")
                lines.append('R*1')
                continue  # keep cur_time unchanged  # skip normal processing

            if total_q > expected_q + 0.01:
                bt, bt_type = self._best_timesig(total_q)
                margin = total_q - expected_q
                if is_rubato or margin >= 4.0:
                    treated_rubato = True
                    sys.stderr.write(
                        f"WARNING: M{mdata.get('number', '?')} ({total_q:.1f}Q vs {expected_q:.1f}Q) "
                        f"→ rubato {bt}/{bt_type}, notes replaced with rest. Fill manually.\n")
                    lines.append(r'LP:\once \override Staff.TimeSignature.stencil = '
                        r'#(lambda (grob) (grob-interpret-markup grob #{ \markup \bold \huge "サ" #}))')
                    lines.append(':LP')
                    cur_time = (bt, bt_type)
                    lines.append(f"{bt}/{bt_type}")
                    n_dashes = max(0, int(total_q) - 1)
                    if n_dashes > 0:
                        lines.append('0 ' * (n_dashes + 1))
                    else:
                        lines.append('0')
                    # Emit barline and skip normal note generation
                    if treated_rubato:
                        lines.append(r'LP: \bar "!"')
                        lines.append(':LP')
                    raw_notes = []  # skip normal note generation
                else:
                    sys.stderr.write(
                        f"WARNING: M{mdata.get('number', '?')}: {total_q:.1f}Q in {expected_q:.1f}Q "
                        f"→ using {bt}/{bt_type}.\n")
                    if margin <= 2.0:
                        sys.stderr.write(f"  ↳ {margin:.1f} beats over — input error? Check.\n")
                    cur_time = (bt, bt_type)
                    lines.append(f"{bt}/{bt_type}")

            if self.verbose:
                notes_ct = len(raw_notes)
                sys.stderr.write(
                    f"  M{mdata.get('number', '?'):>4}: time={cur_time[0]}/{cur_time[1]}  "
                    f"key fifths={cur_fifths:>3}  {notes_ct:>3} notes  {total_q:.1f}Q expected={expected_q:.1f}Q\n")

            bar_64th = cur_time[0] * 64 // cur_time[1]
            note_groups = self._split_notes(raw_notes, bar_64th)

            all_groups = []
            for gi, group in enumerate(note_groups):
                temp_mdata = dict(mdata)
                temp_mdata['notes'] = group
                # Only emit per-measure directions/dynamics for the first group
                if gi == 0:
                    temp_dirs = []
                    if self.feat.get('wedges'):
                        temp_dirs = list(mdata.get('directions', []))
                    if self.feat.get('dynamics') and mdata.get('dynamic'):
                        temp_dirs.append(mdata['dynamic'])
                else:
                    temp_dirs = []

                mtokens = self._measure_tokens(temp_mdata, cur_fifths, cur_time)
                if temp_dirs:
                    mtokens = temp_dirs + mtokens
                if mtokens:
                    all_groups.append(mtokens)

            if all_groups:
                if self.feat.get('annotations'):
                    for ann in mdata.get('annotations', []):
                        lines.append(ann)
                if mdata.get('has_repeat_start'):
                    lines.append('R{')
                    in_repeat = True
                joined = ' | '.join(' '.join(g) for g in all_groups)
                lines.append(joined)
                if mdata.get('has_repeat_end') and in_repeat:
                    lines.append('}')
                    in_repeat = False
                # Emit barline LP block if treated as rubato
                if treated_rubato:
                    bar_cmd = BAR_STYLE_MAP.get(mdata.get('bar_style', ''), '!')
                    if bar_cmd:
                        lines.append(fr'LP: \bar "{bar_cmd}"')
                        lines.append(':LP')

        # Flush remaining multirest
        if multirest_count > 0:
            if multirest_count == 1:
                lines.append('R*1')
            else:
                lines.append(f"R*{multirest_count}")

        return lines

    def _split_at_barlines(self, tokens, bar_64th):
        """Insert '|' tokens at bar boundaries to fix oversize measures."""
        result = []
        pos = 0
        for tok in tokens:
            dur = self._token_64th(tok)
            if dur > 0 and pos + dur > bar_64th and pos > 0:
                result.append('|')
                pos = 0
            result.append(tok)
            if dur > 0:
                pos += dur
        return result

    def _token_64th(self, tok):
        """Estimate jianpu token duration in 64th-note units."""
        # Non-duration tokens
        if tok in ('(', ')', '~', '|', 'R{', '}', ']', '['):
            return 0
        if tok.startswith(('g[', 'R*', '\\', 'r', 'Fr=')):
            return 0
        if len(tok) >= 2 and tok[0].isdigit() and tok[1] == '[':
            return 0  # tuplet start
        # Dash
        if tok == '-':
            return 16
        # Extract duration prefix: h/d/s/q from token (first char if it's a marker)
        m = re.match(r'[hdsq]', tok)
        pref = m.group(0) if m else ''
        dots = tok.count('.')
        ntype = {'h': '64th', 'd': '32nd', 's': '16th', 'q': 'eighth'}.get(pref, 'quarter')
        return type_to_64th(ntype, dots)

    def _is_whole_rest_measure(self, notes, time_change):
        """Check if these notes represent a full-measure rest."""
        if not notes:
            return True
        if len(notes) == 1 and notes[0].get('is_measure_rest'):
            return True
        return False

    def _split_notes(self, notes, bar_64th):
        """Split note list into groups, each fitting within bar_64th (64th-note units)."""
        groups = []
        current = []
        pos = 0
        for note in notes:
            if note.get('is_grace'):
                current.append(note)
                continue
            if note.get('is_chord'):
                current.append(note)  # include chord notes but don't count duration
                continue
            dur = type_to_64th(note.get('ntype', 'quarter'), note.get('dots', 0))
            if note.get('is_measure_rest'):
                dur = bar_64th
            if dur > 0 and pos + dur > bar_64th and pos > 0:
                groups.append(current)
                current = []
                pos = 0
            current.append(note)
            if not note.get('is_measure_rest'):
                pos += dur
            else:
                pos = 0  # full-measure rest fills the bar exactly
        if current:
            groups.append(current)
        return groups
        """Check if these notes represent a full-measure rest."""
        if not notes:
            return True
        # A single <rest measure="yes"/> qualifies
        if len(notes) == 1 and notes[0].get('is_measure_rest'):
            return True
        return False

    def _measure_tokens(self, mdata, fifths, cur_time):
        """Generate jianpu token list for one measure."""
        tokens = []
        key_sig = get_key_sig_accidentals(fifths)

        chord_buffer = []

        chord_buffer = []  # list of (token_str, chord_parts)
        grace_before = []   # grace notes BEFORE the next real note
        pending_after = []  # grace notes AFTER the previous real note
        tuplet_open = False
        seen_real = False   # have we emitted a real (non-grace) note yet?

        for note in mdata.get('notes', []):
            if note.get('is_grace'):
                if note.get('step'):
                    gr = self._format_grace_note(note, fifths, key_sig)
                    if seen_real:
                        pending_after.append(gr)  # after-grace
                    else:
                        grace_before.append(gr)   # before-grace
                continue

            # This is a non-grace note.
            if note.get('is_rest'):

                def _flush_chord_and_grace():
                    nonlocal seen_real
                    if chord_buffer:
                        tokens.append(self._format_chord_v2(chord_buffer))
                        chord_buffer.clear()
                    if pending_after:
                        tokens[-1] = tokens[-1].rstrip() + ' [' + ''.join(pending_after) + ']g'
                        pending_after.clear()
                    if grace_before:
                        tokens.append('g[' + ''.join(grace_before) + ']')
                        grace_before.clear()

                _flush_chord_and_grace()

                if note.get('is_measure_rest'):
                    tokens.append('R*1')
                    seen_real = True  # rest counts as "real" for grace tracking
                    continue

                pref = DUR_INFO.get(note['ntype'], ('', 0))[0]
                token = pref + '0'
                if note['dots'] > 0:
                    token += '.' * note['dots']
                tokens.append(token)
                # Output explicit rest tokens instead of dashes
                extra_q = dash_count(note['ntype'], note['dots'])
                if extra_q > 0:
                    tokens.extend(['0'] * extra_q)
                continue

            # Pitched (real) note — flush grace buffers first
            # Emit after-grace on the PREVIOUS real note token
            if pending_after:
                for idx in range(len(tokens) - 1, -1, -1):
                    t = tokens[idx]
                    if t and not t.startswith(('g[', 'R*', '\\', '(')) and t not in ('', '~', '|', 'R{', '}', ']'):
                        tokens[idx] = t.rstrip() + ' [' + ''.join(pending_after) + ']g'
                        break
                pending_after.clear()
                if chord_buffer:
                    chord_buffer.clear()  # after-grace separates chord groups

            # Emit before-grace
            if grace_before:
                tokens.append('g[' + ''.join(grace_before) + ']')
                grace_before.clear()

            # Flush pending chord (before the new note)
            if chord_buffer and not note.get('is_chord'):
                tokens.append(self._format_chord_v2(chord_buffer))
                chord_buffer.clear()

            degree, acc, octave_marks = note_to_jianpu(
                note['step'], note['octave'], note['alter'], fifths, key_sig)

            pref, _ = DUR_INFO.get(note['ntype'], ('', 0))
            is_long = note['ntype'] in ('half', 'whole', 'breve')
            dot_s = '' if is_long else '.' * note['dots']
            # Token: [duration][octave][accidental][degree][dots]
            if self.octave_traditional:
                low = ',' * octave_marks.count(',')
                high = "'" * octave_marks.count("'")
                token = pref + low + acc + str(degree) + high + dot_s
            else:
                token = pref + octave_marks + acc + str(degree) + dot_s

            # Extras (gated by feature flags)
            extras = []
            if self.feat.get('articulations'):
                for a in note.get('artic', []):
                    extras.append(a)
            if self.feat.get('fr_technical'):
                for f in note.get('fr_marks', []):
                    extras.append(f)
            if self.feat.get('dynamics'):
                if note.get('dynamic'):
                    extras.append(note['dynamic'])
            if extras:
                token += ' ' + ' '.join(extras)

            # Tremolo
            if self.feat.get('tremolo'):
                trem_beams = note.get('tremolo_beams', 0)
                if trem_beams >= 3:
                    token += '///'

            # Slurs — gated
            prefix_tokens = []
            suffix_tokens = []
            if self.feat.get('slurs'):
                if note.get('slur_start'):
                    prefix_tokens.append('(')
                if note.get('slur_stop'):
                    suffix_tokens.append(')')

            # Ties — gated
            if self.feat.get('ties'):
                if note.get('tie_stop') and not note.get('is_chord') and tokens:
                    tokens.append('~')

            # Tuplets
            if note.get('tuplet_start') and note.get('tuplet_ratio'):
                tn = note['tuplet_ratio']
                tokens.append(f"{tn[0]}[")
                tuplet_open = True
            if note.get('tuplet_stop') and tuplet_open:
                tokens.append(']')
                tuplet_open = False

            cp_data = (octave_marks, acc, degree, pref, note['dots'])

            if note.get('is_chord'):
                chord_buffer.append((token, cp_data))
            else:
                tokens.extend(prefix_tokens)
                if chord_buffer:
                    chord_buffer.append((token, cp_data))
                    tokens.append(self._format_chord_v2(chord_buffer))
                    chord_buffer.clear()
                else:
                    tokens.append(token)
                    dashes = dash_count(note['ntype'], note['dots'])
                    for _ in range(dashes):
                        tokens.append('-')
                tokens.extend(suffix_tokens)

            seen_real = True

        # Flush remaining
        if chord_buffer:
            tokens.append(self._format_chord_v2(chord_buffer))
        if pending_after and tokens:
            tokens[-1] = tokens[-1].rstrip() + ' [' + ''.join(pending_after) + ']g'
        if tuplet_open:
            tokens.append(']')

        return tokens

    def _format_grace_note(self, note, fifths, key_sig):
        """Format a single grace note for g[...] syntax.
        Output: concatenated characters like '#4', 's6', 'b7', "'5", 'd4s6' etc.
        """
        if not note.get('step'):
            return ''

        degree, acc, octave_marks = note_to_jianpu(
            note['step'], note['octave'], note['alter'], fifths, key_sig)

        pref, _ = DUR_INFO.get(note['ntype'], ('s', 0))
        if self.octave_traditional:
            low = ',' * octave_marks.count(',')
            high = "'" * octave_marks.count("'")
            return pref + low + acc + str(degree) + high
        return pref + octave_marks + acc + str(degree)

    def _format_chord_v2(self, chord_entries):
        """Format chord from list of (token_str, (octave_marks, acc, degree, dur_pref, dots)).

        The chord in jianpu text is: dur_pref + pitch_parts + dot_str
        where pitch_parts = octave1+acc1+deg1 + octave2+acc2+deg2 + ...
        """
        if len(chord_entries) <= 1:
            return ' '.join(t[0] for t in chord_entries)

        pitch_parts = []
        dur_pref = ''
        dot_s = ''
        extras = []

        for token_str, cp in chord_entries:
            o, a, d, dp, dt = cp
            if self.octave_traditional:
                low = ',' * o.count(',')
                high = "'" * o.count("'")
                pitch_parts.append(low + a + str(d) + high)
            else:
                pitch_parts.append(o + a + str(d))
            if dp and not dur_pref:
                dur_pref = dp
            if dt and not dot_s:
                dot_s = '.' * dt

            # Extract extras from token_str (stuff after first space)
            if ' ' in token_str:
                extra_part = token_str.split(' ', 1)[1]
                extras.append(extra_part)

        # Chord format: duration_prefix + pitch_parts + dots
        chord = dur_pref + ''.join(pitch_parts) + dot_s
        if extras:
            chord += ' ' + ' '.join(extras)
        return chord


# ============================================================
# Top-level conversion
# ============================================================

def musicxml_to_jianpu(xml_string, prefer_major=True, verbose=False, octave_traditional=False):
    """Convert MusicXML XML string to jianpu-ly input text."""
    parser = MusicXmlParser(prefer_major)
    title, composer, parts = parser.parse(xml_string)

    gen = JianpuGenerator(prefer_major, verbose=verbose, octave_traditional=octave_traditional)
    return gen.generate(title, composer, parts)


# ============================================================
# File I/O
# ============================================================

def read_input(path):
    """Read MusicXML from .xml, .musicxml, or uncompressed .mxl.
    Tries UTF-8 first, then GBK for Chinese Sibelius exports."""
    if path.endswith('.mxl'):
        with zipfile.ZipFile(path, 'r') as zf:
            for name in zf.namelist():
                if not name.startswith('META-INF/') and name != 'mimetype':
                    data = zf.read(name)
                    for enc in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
                        try: return data.decode(enc)
                        except: continue
                    return data.decode('utf-8', errors='replace')
            raise ValueError(f"No XML content in {path}")
    else:
        data = open(path, 'rb').read()
        for enc in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
            try: return data.decode(enc)
            except: continue
        return data.decode('utf-8', errors='replace')


def main():
    ap = argparse.ArgumentParser(
        description='mxml2jp v0.2.1 — Convert MusicXML to jianpu-ly input text',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python mxml2jp.py piece.musicxml -o piece.txt
  python mxml2jp.py piece.xml
  python mxml2jp.py piece.mxl --minor""")
    ap.add_argument('input', help='MusicXML file (.xml, .musicxml, .mxl)')
    ap.add_argument('-o', '--output', help='Output file (default: stdout)')
    ap.add_argument('--minor', action='store_true',
                    help='Assume minor keys (6=X instead of 1=X)')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='Verbose debug output')
    ap.add_argument('--octave-traditional', action='store_true',
                    help='Traditional octave style: low marks before digit, high marks after')
    args = ap.parse_args()

    try:
        xml_str = read_input(args.input)
    except FileNotFoundError:
        sys.stderr.write(f"Error: file not found: {args.input}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Error reading {args.input}: {e}\n")
        sys.exit(1)

    try:
        result = musicxml_to_jianpu(xml_str, prefer_major=not args.minor,
                                    verbose=args.verbose,
                                    octave_traditional=args.octave_traditional)
    except Exception as e:
        sys.stderr.write(f"Error converting: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        sys.stderr.write(f"Written: {args.output}\n")
    else:
        sys.stdout.write(result)


if __name__ == '__main__':
    main()
