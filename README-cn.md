# mxml2jp v0.3.0 — MusicXML 转 jianpu-ly 简谱转换器

将 MusicXML 文件转换为 [jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html)
的纯文本输入格式，进而用 LilyPond 编译为简谱 PDF。

## 目录

- [快速开始](#快速开始)
- [程序做了什么](#程序做了什么)
- [程序架构](#程序架构)
- [核心算法：固定调 → 首调](#核心算法固定调--首调)
- [时值系统](#时值系统)
- [音符解析细节](#音符解析细节)
- [超小节 / 散板处理](#超小节--散板处理)
- [多声部与和弦处理](#多声部与和弦处理)
- [命令行选项](#命令行选项)
- [已支持的 MusicXML 元素](#已支持的-musicxml-元素)
- [输出格式参考](#输出格式参考)
- [测试文件](#测试文件)
- [已知问题与局限](#已知问题与局限)
- [代码缺陷](#代码缺陷)
- [待完善事项](#待完善事项)
- [更新日志](#更新日志)
- [依赖](#依赖)
- [许可](#许可)

---

## 快速开始

```sh
python mxml2jp.py 乐谱.musicxml -o 乐谱.txt
python mxml2jp.py 乐谱.xml --octave-traditional
python mxml2jp.py 乐谱.mxl -v -o 乐谱.txt
```

用 jianpu-ly 和 LilyPond 编译：

```sh
$env:j2ly_sloppy_bars=1
python jianpu-ly.py 乐谱.txt > 乐谱.ly
lilypond 乐谱.ly
```

---

## 程序做了什么

`mxml2jp` 读入一个 **MusicXML 文件**（来自 MuseScore、Sibelius、PhotoScore 等制谱软件），
输出一个**纯文本文件**，可送入 `jianpu-ly.py` 生成 LilyPond `.ly` 文件，最终编译为简谱 PDF。

核心工作是一次**记谱体系的翻译**：

| MusicXML（五线谱思维） | jianpu-ly（简谱思维） |
|------------------------|-----------------------|
| 绝对音高（C4, D#5…） | 首调唱名（1, 2, #4…） |
| 调号通过升降号体现 | 首调主音标注（1=Eb, 6=Am…） |
| 五线位置表示八度 | 八度标记（`,`, `'`, `''`） |
| 符头形状表示时值 | 前缀字母（`q`, `s`, `d`, `h`）+ 附点 |

程序**并不渲染乐谱**。它只生成 jianpu-ly 能吃的文本 token。LilyPond 编译是后续独立的步骤。

---

## 程序架构

```
┌───────────────────┐
│  MusicXML 文件     │  (.musicxml / .xml / .mxl)
└────────┬──────────┘
         │ read_input()  多编码尝试（UTF-8 → GBK → GB2312 → latin-1）
         ▼
┌───────────────────┐
│   XML 字符串       │
└────────┬──────────┘
         │ MusicXmlParser.parse()  逐声部解析小节/音符/力度/标注
         ▼
┌───────────────────┐
│  解析后的数据结构   │  (title, composer, [(声部名, [小节数据字典])])
└────────┬──────────┘
         │ JianpuGenerator.generate()  首调转换 + token 拼装
         ▼
┌───────────────────┐
│  jianpu-ly 文本    │  纯文本，符合 jianpu-ly 输入格式
└───────┬───────────┘
        │ jianpu-ly.py → lilypond
        ▼
┌───────────────────┐
│     PDF 乐谱       │
└───────────────────┘
```

### 组件一：MusicXmlParser（第 221–631 行）

解析 **partwise** MusicXML（`<score-partwise>` 根元素），产出结构化的数据。

**`parse(xml_string) → (title, composer, parts)`**

1. 提取**元数据**：`<work-title>`（曲名）、`<creator type="composer">`（作曲者）、每个 `<score-part>` 的 `<part-name>`（声部名/乐器名）。
2. 对每个 `<part>` 元素：
   - 逐小节（`<measure>`）迭代，追踪当前的调号（fifths）、拍号、divisions 分辨率。
   - 在每个小节内，按文档顺序遍历子元素：
     - `<attributes>` → 调号变化、拍号变化、divisions
     - `<direction>` → 速度、力度、渐强渐弱楔形、文字标注
     - `<note>` → 完整音符数据（音高、时值、演奏记号等）
     - `<backup>` → 声部切换（时间回退，为下一声部腾空间）
     - `<forward>` → 静默推进（其他声部的休止）
     - `<barline>` → 反复记号、终止线、小节线样式
   - 收集完音符后调用 `_merge_aligned_notes()` 将同时触发的音符合并为和弦。

**`_parse_note(note_elem) → dict`**

解析单个 `<note>` 元素，返回一个扁平的字典：

| 键 | 类型 | 来源 | 示例 |
|---|------|------|------|
| `is_rest` | bool | `<rest/>` 存在 | `True` |
| `is_measure_rest` | bool | `<rest measure="yes"/>` | `True` |
| `is_chord` | bool | `<chord/>` 存在 | `True` |
| `is_grace` | bool | `<grace/>` 存在 | `True` |
| `grace_slash` | bool | `<grace slash="yes"/>` | `True` |
| `step` | str | `<step>` | `'C'` |
| `octave` | int | `<octave>` | `4` |
| `alter` | float 或 None | `<alter>` | `0.0`, `-1.0`, `None` |
| `duration` | int | `<duration>`（divisions 单位） | `420` |
| `ntype` | str | `<type>` | `'quarter'`, `'eighth'` |
| `dots` | int | `<dot/>` 计数 | `1` |
| `voice` | str | `<voice>` | `'1'`, `'2'` |
| `tie_start` / `tie_stop` | bool | `<tied type="start"/>` | — |
| `slur_start` / `slur_stop` | bool | `<slur type="start"/>` | — |
| `artic` | list[str] | `<articulations>` | `['Fr=▼', '\\fermata']` |
| `fr_marks` | list[str] | `<technical>` | `['Fr=0', 'Fr=◇']` |
| `dynamic` | str 或 None | `<dynamics>` | `'\\p'`, `'\\ff'` |
| `tuplet_start` / `tuplet_stop` | bool | `<tuplet type="start"/>` | — |
| `tuplet_ratio` | tuple 或 None | `<time-modification>` | `(3, 2)` |
| `tremolo_beams` | int | `<tremolo>` 符杠数 | `3` |

### 组件二：JianpuGenerator（第 637–1157 行）

接受解析后的数据，逐行输出 jianpu-ly 文本。

**`generate(title, composer, parts) → str`**

对每个声部：
1. 输出头部行：`title=`、`composer=`、`instrument=`、`OctavesBefore`
2. 对每个小节：
   - **调号变化**：将 fifths 转为 `1=X` 或 `6=X` 格式
   - **拍号变化**：输出 `beats/beat-type`
   - **速度**：输出第一个 `<metronome>` 为 `音值=bpm`
   - **整小节休止**：将连续空小节累积为 `R*N`
   - **超小节检测**：比较音符总时值与当前拍号，偏差过大时触发散板逻辑
   - **音符 token 生成**：调用 `_measure_tokens()` 产出该小节内容
   - **反复记号**：开头加 `R{`、结尾加 `}`
   - **小节线 LP 块**：终止线和特殊样式

**`_measure_tokens(mdata, fifths, cur_time) → list[str]`**

Token 生成的核心（第 939–1101 行）。按顺序遍历音符：

```
对每个音符：
  1. 若是倚音 → 暂存到 grace_before[] 或 pending_after[]
  2. 若是休止 → 清空倚音/和弦缓冲区，输出 "0" token
  3. 若是实音：
     a. 将上一音的 after-grace 追加到前一个实音 token 后
     b. 输出 before-grace: g[...]
     c. 调用 note_to_jianpu() 得到唱名、变音、八度标记
     d. 拼装 token: [时值前缀] + 八度标记 + 变音 + 唱名 + 附点
     e. 追加演奏记号（Fr=▼）、力度（\p）、震音（///）
     f. 处理连音线：前缀 "(" 在前，后缀 ")" 在后
     g. 若是和弦音 → 暂存到 chord_buffer，等集齐后调用 _format_chord_v2()
     h. 若不是和弦音 → 输出 token + 增时线，先清空 chord_buffer
```

---

## 核心算法：固定调 → 首调

`note_to_jianpu()` 函数（第 161 行）是音高转换的关键。MusicXML 用**绝对音高**
存储音符（C4、D#5…，附带八度和半音变化量），而简谱使用**首调唱名**：
"1" 永远是当前调的 tonic，数字 1–7 代表自然音阶级数。

### 算法步骤详解

**已知**：音符 `Eb4`，调号为 `Eb major`（fifths = -3）。

```
1. 从调号确定主音字母：
     tonic_letter = DEG2LETTER[(fifths × 4) % 7]
     = DEG2LETTER[(-3 × 4) % 7]
     = DEG2LETTER[-12 % 7]
     = DEG2LETTER[2]
     = 'E'       （Eb major 的主音是 E♭）

2. 获取音名字母的索引：
     step_idx  = STEP_ORDER['E'] = 2   （音符本身：E）
     tonic_idx = STEP_ORDER['E'] = 2   （主音：也是 E）

3. 计算与第4八度主音的自然音级距离：
     dTone = step_idx - tonic_idx
           = 2 - 2 = 0
     因为 step_idx >= tonic_idx，不需要 +7 回绕。
     dTone += 7 × (octave - 4) = 0 + 7 × 0 = 0

4. 唱名与八度标记：
     degree = 0 % 7 + 1 = 1        → "1"（主音）
     octave_count = 0 // 7 = 0     → 无八度标记
     结果："1"。正确——E♭ 是主音。
```

**已知**：音符 `F4`（还原 F），调号为 `Eb major`（fifths = -3）。

```
1. tonic_letter = 'E'（同上）

2. step_idx  = STEP_ORDER['F'] = 3
   tonic_idx = STEP_ORDER['E'] = 2

3. dTone = 3 - 2 = 1
   dTone += 7 × 0 = 1

4. degree = 1 % 7 + 1 = 2        → "2"
   octave_count = 1 // 7 = 0     → 无八度标记

5. 变音记号判定：
   key_step_acc = key_sig['F'] = -1  （Eb 调中 F 是降的，但此音是还原 F）
   eff = 0.0  （无 <alter>，即还原 F）
   key_step_acc (-1) ≠ 0，且 eff (0.0) ≠ key_step_acc (-1)：
     eff (0.0) == 0.0 → 还原号抵抗了降号 → acc = '#'
   结果："#2"（F 还原，Eb 调中升高的二级音）
```

### 变音记号逻辑总结

变音判断（第 198–212 行）比较音符的实际半音高度与调号默认值：

| 调号默认 | 实际音高 | 变音标记 | 含义 |
|---------|---------|---------|------|
| 0（本位） | 0（本位） | `''` | 不需标记 |
| 0（本位） | +1（升） | `'#'` | 升号 |
| 0（本位） | -1（降） | `'b'` | 降号 |
| +1（升） | +1（与调号一致） | `''` | 调内音，不标 |
| +1（升） | 0（还原） | `'b'` | 还原记号（相对调号降低了） |
| -1（降） | -1（与调号一致） | `''` | 调内音，不标 |
| -1（降） | 0（还原） | `'#'` | 还原记号（相对调号升高了） |

注意：jianpu-ly 中的 `b` 和 `#` 是相对于**自然音阶级数**的，不是绝对音高。
`#2` 的意思是"将该调的二级音升高半音"。

---

## 时值系统

### MusicXML 时值模型

MusicXML 使用 **divisions** 体系：`<divisions>N</divisions>` 表示一个四分音符 = N tick。
每个 `<note>` 有 `<duration>`（tick 数）。这支持任意连音和精确节奏。

### jianpu-ly 时值模型

jianpu-ly 使用**基于音符类型**的时值，以前缀字母和附点表示：

| 时值 | 前缀 | 64分音符单位 | 增时线（- 数量） |
|------|------|-------------|----------------|
| 64分 | `h` | 1 | 0 |
| 32分 | `d` | 2 | 0 |
| 16分 | `s` | 4 | 0 |
| 8分 | `q` | 8 | 0 |
| 四分 | （无） | 16 | 0 |
| 附点四分 | （无） | 24 | 0（附点在音符上） |
| 二分 | （无） | 32 | 1（`-`） |
| 附点二分 | （无） | 48 | 2（`- -`） |
| 全音符 | （无） | 64 | 3（`- - -`） |

关键设计选择：**长音符（二分及以上）不使用附点**。主 token 永远是一个光杆四分音符数字；
多余的长度用增时线 `-` 表示。每条 `-` 增加一个四分拍的长度。所以全音符输出为 `1 - - -`，
而不是 `1---`。

`dash_count()`（第 131 行）计算一个音后面需要跟几条增时线。
`type_to_64th()`（第 119 行）将 MusicXML 类型+附点转为 64 分音符单位，用于小节长度检查。

### 小节长度检查

每个 jianpu-ly 小节容纳恰好 `64 × beats / beat-type` 单位。4/4 小节就是 64 单位。
生成器比较小节中音符总时长与预期时长，以检测超长小节（散板或编码错误导致）。

---

## 音符解析细节

### 演奏记号映射

来自 `<articulations>` 和 `<ornaments>` 的演奏记号映射到 jianpu-ly token：

| MusicXML 标签 | jianpu-ly token | 分类 |
|-------------|-----------------|------|
| `<staccato>` | `Fr=▼` | 演奏记号 |
| `<tenuto>` | `Fr=_` | 演奏记号 |
| `<accent>` | `Fr=>` | 演奏记号 |
| `<marcato>` | `\marcato` | LilyPond 命令 |
| `<fermata>` | `\fermata` | LilyPond 命令 |
| `<trill-mark>` | `\trill` | LilyPond 命令 |
| `<mordent>` | `\mordent` | 装饰音 |
| `<turn>` | `\turn` | 装饰音 |
| `<staccatissimo>` | `\staccatissimo` | LilyPond 命令 |
| `<strong-accent>` | `\accent` | LilyPond 命令 |
| `<up-bow>` | `\upbow` | LilyPond 命令 |
| `<down-bow>` | `\downbow` | LilyPond 命令 |

`Fr=` 是 jianpu-ly 提供的机制，用于在音符上方附加任意标记，广泛用于中国乐器特有的演奏符号。

### 技法（Technical）→ Fr= 映射

`<technical>` 元素映射为中国乐器技法的 `Fr=` 命令：

| MusicXML `<technical>` 子元素 | jianpu-ly token | 含义 |
|------------------------------|-----------------|------|
| `<open>`（空弦） | `Fr=0` | 空弦 |
| `<harmonic>`（自然泛音） | `\flageolet` | 自然泛音 |
| `<harmonic>`（人工泛音） | `Fr=◇` | 人工泛音 |
| `<snap-pizzicato>` | `Fr=up` | 左手拨弦 / 勺音 |
| `<fingering>` 文本 | `Fr={文本}` | 指法标记 |

定制版 `jianpu-ly_patched.py` 在此基础上扩展了二胡专用符号的 Unicode 字形支持
(0/1/2/3/4 指法、勺音、泛音、上、下、弯音、波浪线)。

### 圆滑线与延音线

- **圆滑线**（`<slur>`）→ jianpu-ly `(` 起始和 `)` 终止 token，包围在受影响的音符两侧。
- **延音线**（`<tied>`）→ jianpu-ly `~` token，放置于被连接的两个音符之间。
  同时处理 `<note>` 级别的 `<tie>`（MuseScore 将延音线放在此处）。

### 倚音

倚音使用 jianpu-ly 的 `g[...]` 语法：

- **前倚音**（before-grace）：`g[...]` 放在主音之前
  - 带斜线（短倚音）：如 `g[#4s6]`
  - 不带斜线（长倚音）：格式相同，时值前缀可能不同
- **后倚音**（after-grace）：`[...]g` 追加到前一个实音 token 后面

程序通过跟踪当前小节中"是否已出现实音"来区分前倚音和后倚音。

### 力度与渐强渐弱

- `<dynamics>` → 每音 `\p`、`\f`、`\mp` 等
- `<wedge type="crescendo">` → 每小节 `\<`、`\>`、`\!`

### 颤音延长

`<wavy-line>` 装饰音（type="start"/"stop"）映射为 `\startTrillSpan` 和 `\stopTrillSpan`，
支持跨音符延续的颤音。

---

## 超小节 / 散板处理

有些 MusicXML 乐谱的某些小节比标称拍号更长。这发生在以下情况：

1. **散板 / cadenza 段落**（自由节奏）：作曲者意在自由节奏，乐谱上常注有"Rubato"或"散"。
2. **编码错误**：导出时的时值错误导致小节超长。
3. **连音段落**：复杂的连音导致小节内总时值超出预期。

### 检测机制

对每个小节，生成器计算：

```
total_q = 所有音符的总时值（以四分音符为单位）
expected_q = beats × 4 / beat-type
margin = total_q - expected_q
```

若 `total_q > expected_q + 0.01`，该小节判定为超长。

### 处理策略

| 偏差 | 条件 | 处理方式 |
|------|------|---------|
| 任意 | 含连音记号 | 整小节替换为 `R*1`；警告用户；拍号不变 |
| ≥ 4 拍 或 散板 | `is_rubato` 或 `margin >= 4.0` | 发 LP 块：将拍号模板替换为"サ"（散板记号）；修正拍号；音符替换为 `0` 休止；警告用户 |
| < 4 拍 | `margin < 4.0` | 修正拍号以匹配；警告用户；音符保留但可能对不齐 |
| 精确 | `total_q == expected_q` | 正常处理 |

**重要局限**：当超长小节以休止符处理（散板或连音）时，**原始音符被丢弃**。用户必须手动
填入正确的音符，并调整拍号。此情况会在 stderr 输出警告。

---

## 多声部与和弦处理

### 解析时的声部追踪

MusicXML 使用 `<backup>` 和 `<forward>` 元素来表示一个小节内的多个独立声部。
解析器分别追踪每个声部的当前时间位置：

```
声部 1: |===音符===|=回退=|==音符==|
声部 2:            |=音符==|=推进=| =音符=|
```

每个音符被标记：
- `_voice`：所属声部（1, 2, 3…）
- `_start`：小节内的 tick 位置

### 和弦检测（`_merge_aligned_notes`）

解析后，`_start` 位置相同的音符被分组。如果它们时值相同且都不是休止，则合并为和弦：

- 组内第一个音符保持 `is_chord = False`（"锚"音符）。
- 后续音符标记 `is_chord = True`（在输出中折叠在一起）。

**注意**：当前实现**跨所有声部**合并，而不是仅在同一个声部内合并。这意味着不同声部中
同时触发的独立旋律线可能被错误合并为和弦。对于单声部分谱这不是问题，但对于多声部总谱
可能产生虚假和弦。

### 和弦输出格式化

`_format_chord_v2()`（第 1120 行）将和弦音符合并为单个 jianpu-ly token：

```
输入:  [('q1', ('', '', 1, 'q', 0)), ('q3', ('', '', 3, 'q', 0))]
输出: "q13"        （两个唱名共享 "q" 前缀）
```

前缀字母和附点取自第一个和弦条目的；音高部分（八度 + 变音 + 唱名）出自所有条目并拼接。

---

## 命令行选项

| 选项 | 说明 |
|------|------|
| `input`（必需） | MusicXML 文件：`.xml`、`.musicxml` 或 `.mxl` |
| `-o FILE`, `--output FILE` | 输出到文件（默认 stdout） |
| `--minor` | 小调记谱：`6=X` 代替 `1=X` |
| `--verbose`, `-v` | 逐小节诊断信息输出到 stderr |
| `--octave-traditional` | 传统八度标记：低音在数字前，高音在数字后（`,,1` 和 `1'`） |

示例：

```sh
# 基本转换
python mxml2jp.py 乐谱.musicxml -o 乐谱.txt

# 小调记谱（la = 主音）
python mxml2jp.py 乐谱.xml --minor

# 调试小节长度
python mxml2jp.py 乐谱.mxl -v -o 乐谱.txt 2> debug.log

# 传统八度格式
python mxml2jp.py 乐谱.musicxml --octave-traditional
```

---

## 已支持的 MusicXML 元素

| MusicXML 元素 | 支持程度 | 细节 |
|-------------|---------|------|
| 音高（`<step>`, `<octave>`, `<alter>`） | 完整 | 通过 `note_to_jianpu()` 转换 |
| 调号（`<key><fifths>`） | 完整 | 输出为 `1=X` 或 `6=X` |
| 拍号（`<time>`） | 完整 | 输出为 `beats/beat-type` |
| 速度（`<metronome>`） | 仅首次 | 首次出现时输出 `音值=bpm` |
| 力度（`p`, `mp`, `f`, `ff`…） | 完整 | 每音 `\p`, `\f` 等 |
| 渐强渐弱楔形 | 完整 | 每小节 `\<`, `\>`, `\!` |
| 文字标注（`<words>`） | 完整 | 上方 `^"文本"`，下方 `_"文本"` |
| 圆滑线（`<slur>`） | 完整 | `(` 和 `)` |
| 延音线（`<tied>`, `<tie>`） | 完整 | `~` |
| 演奏记号（断奏、保持音、重音…） | 完整 | `Fr=▼`, `Fr=_`, `Fr=>` 等 |
| 装饰音（颤音、波音、回音、震音） | 完整 | `\trill`, `\mordent`, `///` 等 |
| 颤音延长（`<wavy-line>`） | 完整 | `\startTrillSpan` / `\stopTrillSpan` |
| 技法：泛音、空弦、指法… | 部分 | `Fr=` 命令（见上表） |
| 和弦（`<chord/>`） | 完整 | 音高拼接，共享时值前缀 |
| 倚音（前 + 后） | 完整 | `g[...]` 和 `[...]g` |
| 连音（`<time-modification>`） | **替换** | 整小节 → `R*1` + stderr 警告 |
| 多小节休止 | 完整 | 累积为 `R*N` |
| Backup / Forward | 完整 | 合并为和弦 |
| 反复记号 | 部分 | `R{` 起始，`}` 终止（无跳房子支持） |
| 小节线样式 | 部分 | `\|` 普通、`!` 虚线、`;` 点线、`\|\|` 双线 |

**暂不支持**：排练记号、八度记号（8va）、表情术语、滑音/刮奏、琶音、跳房子（1房子/2房子）。

---

## 输出格式参考

生成的文本遵循 jianpu-ly 输入格式。示例节选：

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

关键语法元素：
- `title=` / `composer=` / `instrument=` — 元数据头
- `OctavesBefore` — 八度标记在数字前（v0.3.0 默认）
- `1=Eb` — 调号：首调唱名 1 = 绝对音高 E♭
- `4/4`, `3/4` — 拍号
- `\p`, `\mp`, `\<`, `\>` — 力度与渐强渐弱
- `(` / `)` — 圆滑线起止
- `,3` — 低八度（逗号在数字前，OctavesBefore 模式）
- `'7` — 高八度（单引号在数字前）
- `-` — 增时线（每个延长一拍）
- `q` — 八分音符前缀；`s` = 16分；`d` = 32分；`h` = 64分
- `Fr=▼` — 断奏记号；`Fr=0` — 空弦
- `\fermata`, `\prall`, `\trill` — jianpu-ly 透传的 LilyPond 命令
- `R*1` — 一小节休止；`R*5` — 五小节休止
- `g[...]` — 前倚音；`[...]g` — 后倚音
- `LP: ...` / `:LP` — 原始 LilyPond 块（用于特殊覆写）
- `NextPart` — 多声部乐谱中分隔各声部

---

## 测试文件

以下 MusicXML 文件位于 `../lilypond教学/`，可用于测试：

| 文件 | 来源 | 类型 | 备注 |
|------|------|------|------|
| `YiNian.musicxml` | MuseScore 4.5 | 单声部（二胡） | 格式标准，输出已知良好 |
| `一念.musicxml` | MuseScore 4.5 | 双声部（竹笛 + 二泉琴） | 多声部测试 |
| `Barber-Excursions_III.musicxml` | MuseScore | 总谱，多声部含连音 | 测试连音警告 |
| `Barber-Excursions_III-木琴.musicxml` | MuseScore | 单打击乐声部 | 木琴 |
| `Barber-Excursions_III-马林巴琴（大谱表）.musicxml` | MuseScore | 大谱表（马林巴） | 双谱表声部 |
| `草原小姐妹总谱.musicxml` | Sibelius | 管弦乐总谱（~15 MB） | 中文编码问题 |
| `浮生听风3.xml` | PhotoScore | 四声部乐谱（~1 MB） | 测试 PhotoScore XML |

开发时可用于回归测试：
```sh
Get-ChildItem ..\lilypond教学\*.musicxml,..\lilypond教学\*.xml | ForEach-Object {
    Write-Host "--- 测试 $($_.Name) ---"
    python mxml2jp.py $_.FullName -v -o "$($_.BaseName).txt" 2>&1
}
```

---

## 已知问题与局限

### 设计局限

1. **连音小节被丢弃** — 任何包含连音的小节被替换为 `R*1`（整小节休止）。用户收到 stderr
   警告后必须手动填入。这是实际使用中最大的缺口，因为大多数真实乐谱都使用三连音等。

2. **散板/cadenza 音符被丢弃** — 超长小节（判定为散板）将所有音符替换为 `0` 休止。
   小节线、拍号和"サ"模板被保留，但音符内容丢失。

3. **多声部和弦跨声部合并** — `_merge_aligned_notes()` 不尊重 `voice` 属性。
   不同声部中同时触发的独立旋律被错误合并为和弦。

4. **多声部散板小节尚未同步** — 当两个声部共用一个散板段落时，它们的休止填充长度可能
   不同，导致最终乐谱中声部不对齐。

5. **Sibelius 导出的中文可能乱码** — Sibelius 以非 UTF-8 编码导出中文文本。
   `read_input()` 尝试 UTF-8 然后 GBK/GB2312 fallback，但不能覆盖所有情况。
   已知受影响的文件：`草原小姐妹总谱.musicxml`。

6. **仅支持 partwise MusicXML** — Timewise MusicXML（score-timewise）会抛出错误。
   大多数现代制谱软件默认导出 partwise 格式，因此这很少成为问题。

### 代码缺陷

7. **不可达代码** — 第 462–463 行：`_merge_aligned_notes()` 已 return 后还有一个
   `return mdata`。第 927–937 行：`_split_notes()` return 后有一段重复的
   `_is_whole_rest_measure` 代码。

8. **`LP_TECHNICAL` 字典被覆盖** — 定义了两次（第 92–98 行和第 100–104 行）。
   第二次覆盖第一次，丢失了 `'stopped': r'\stopped'` 条目。

9. **硬编码 Windows 路径** — 第 6 行含 `E:\USTC\NMOU\mxml2jp\`，应删除。

10. **README 说 `.mxl` 是 TODO** — 但 `read_input()` 已通过 `zipfile.ZipFile` 实现
    了 `.mxl` 解压。该 TODO 条目已过时。

---

## 待完善事项

- **连音时值计算**：利用 MusicXML `<duration>` divisions 计算连音组内实际音符到音符
  的时值，以生成正确的 `N[...]` 输出，替代目前的替换策略。

- **多声部小节同步**：确保散板休止长度在各声部间一致，使最终乐谱对齐。

- **按声部合并和弦**：修改 `_merge_aligned_notes()` 使之仅在单个声部内合并；跨声部的
  同时音符应保持独立。

- **排练记号**：解析 `<rehearsal>` 元素，输出 `^"A"`、`^"B"` 等。

- **跳房子 / 结尾**：处理 `<ending>` 元素以支持 1房子/2房子。

- **八度记号（8va）**：解析 `<octave-shift>` 实现自动八度移调。

- **更多中国乐器技法**：扩展 `FR_TECHNICAL` 和 `LP_TECHNICAL`，覆盖滑音
  (glissando/portamento)、打音、揉弦、拨弦等。

- **单元测试**：利用现有测试 MusicXML 文件建立 pytest 测试套件。可从 YiNian.musicxml
  （单声部、已知良好输出）开始。

- **清理死代码**：移除不可达的 `return mdata` 和重复函数定义。

- **修复 `LP_TECHNICAL` 重复定义**：合并两个定义为一个完整字典。

---

## 更新日志

### v0.3.0
- `--octave-traditional` 传统八度格式选项
- 连音小节替换为 `R*1`，不改变拍号
- `read_input()`：UTF-8/GBK 多编码 fallback
- 休止符用显式 `0` 替代增时线
- 散板后拍号总是恢复

### v0.2.1
- 特征开关（`self.feat`）支持逐步编译测试
- 渐强渐弱（`\<`, `\>`, `\!`）、逐音力度、文字标注
- `Fr=` 技法标记
- `\bendAfter` 移除（与 jianpu-ly 多 token 不兼容）

### v0.2.0
- 后倚音、震音（`///`）、颤音延长
- 泛音、指法、空弦的 `Fr=` 映射
- 超小节自动检测与处理

### v0.1.0
- 初版：基础音高、调号、拍号、圆滑线、延音线、和弦

---

## 依赖

- Python 3.7+
- 仅标准库：`xml.etree.ElementTree`、`argparse`、`zipfile`、`re`、`sys`、`os`
- 无需额外 pip 包

编译输出为 PDF 需要：
- [jianpu-ly.py](https://github.com/ssb22/jianpu-ly)（v1.866+；推荐使用定制版 `jianpu-ly_patched.py` 以获得和弦八度对齐和二胡符号支持）
- [LilyPond](https://lilypond.org/) 2.24+

---

## 许可

Apache 2.0 — 上游 jianpu-ly 项目的许可见其代码仓库。
