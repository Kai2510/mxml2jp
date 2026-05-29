# mxml2jp — MusicXML 转 jianpu-ly 转换器

将 MusicXML 文件（`.xml`, `.musicxml`, `.mxl`）转换为
[jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html) 的纯文本输入。

## 快速开始

```sh
python mxml2jp.py 乐谱.musicxml -o 乐谱.txt
python mxml2jp.py 乐谱.xml

# verbose 调试模式：
python mxml2jp.py 乐谱.musicxml -v -o 乐谱.txt

# 小调记谱（6=X 而非 1=X）：
python mxml2jp.py 乐谱.xml --minor
```

用 jianpu-ly 编译输出文件：

```sh
# PowerShell
$env:j2ly_sloppy_bars=1
python jianpu-ly.py 乐谱.txt > 乐谱.ly
lilypond 乐谱.ly
```

## 功能

- 读取 MuseScore 4+、Sibelius、PhotoScore 等导出的 partwise MusicXML
- 固定调音高 → 首调简谱转换（1=主音）
- 处理调号、拍号、多声部（`NextPart`）
- 保留连线（~）、圆滑线（( )）、力度记号、演奏记号
- 连续整小节休止合并为 `R*N`
- 支持倚音（`g[...]`）、连音（`N[...]`）、和弦
- **超小节自动修正**：若 MusicXML 某 `<measure>` 内含音符数量超过声明拍号
  （MuseScore 导出常见问题），转换器会自动计算正确拍号并写入输出，同时在
  stderr 输出警告
- **`--verbose`** 模式逐小节打印诊断信息
- **`--minor`** 标志支持小调记谱

## 局限性

- 倚音：仅支持前倚音（`g[...]`），后倚音（`[...]g`）尚未区分
- 连音：以裸 `N[...]` 形式输出，需人工核对比例
- 同乐器内的多声部不拆分（请在 MusicXML 中用独立声部）
- 震音、八度记号、排练记号、表情文字不做映射
- 转换结果为**半成品**，需人工润色

---

## 实现细节

### 架构

```
MusicXML 文件
     │
     ▼
MusicXmlParser.parse()
     │  ┌─── 提取元数据（title, composer, part names）
     │  ├─── 遍历每个 <part>：
     │  │      ├── 逐小节解析（<attributes>, <note>, <direction>, <barline>）
     │  │      │      └── note dict: {step, octave, alter, ntype, dots, tie, slur, ...}
     │  │      └── 检测 key_change / time_change / oversize
     │  └── 返回 (title, composer, [(part_name, [measure_dict])])
     │
     ▼
JianpuGenerator.generate()
     │  ├── 输出 title=, composer=, instrument=, NextPart
     │  ├── 逐小节处理：
     │  │      ├── note_to_jianpu()     ── 音高转换
     │  │      ├── _measure_tokens()    ── jianpu token 拼装
     │  │      ├── _split_notes()       ── 超小节拆分
     │  │      └── _best_timesig()      ── 超小节修正拍号
     │  └── 输出 jianpu-ly 文本行
     │
     ▼
jianpu-ly 输入文本（.txt 纯文本）
```

### 固定调 → 首调转换算法

这是核心算法——将绝对音名（C, D, E...）转换为 jianpu 的唱名（1-7），
附带八度记号（, / '）和变音记号（# / b）。

**算法流程**（`note_to_jianpu` 函数）：

1. **确定主音音名**（从 `fifths` 即五度圈索引计算）：
   ```
   tonic_step_idx = (fifths × 4) % 7    # 例如 fifths=1 → tonic=G
   ```

2. **计算音级距离**（以八度4为基准）：
   ```
   dTone = step_idx - tonic_step_idx
   如果 step_idx < tonic_step_idx: dTone += 7    # 向前绕回
   dTone += 7 × (octave - 4)                       # 八度偏移
   ```

3. **得出唱名和八度记号**：
   ```
   degree = dTone % 7 + 1        # 1-7
   八度数 = dTone // 7
   正数 → ' 记号，负数 → , 记号
   ```

4. **变音记号判定**——比较音符的实际半音高度与调号默认值：
   ```
   key_step_acc = 调号对该音名的升降（+1=升, -1=降, 0=自然）
   eff = alter_val（若MusicXML有 <alter>）否则 key_step_acc

   如果 key_step_acc ≠ 0:
       若 eff == key_step_acc: acc = ''       # 与调号一致，不写记号
       若 eff == 0:   acc = 'b'（若调号是升）或 '#'（若调号是降）
       否则:           acc = '#'（若 eff>0）或 'b'（若 eff<0）
   否则（该音在调内是自然音）:
       acc = ''（若 eff==0）否则 '#'/`b'
   ```

**举例**：G 大调（fifths=1, 主音=G），音符 F4（step=F, octave=4）
- G 大调中 F 需升 → `key_step_acc = +1`
- MusicXML 无 `<alter>` 元素 → `eff = +1`（继承调号）
- `eff == key_step_acc` → `acc = ''`
- `dTone = 3-4+7 = 6` → `degree = 7`
- 结果：`7`（无变音记号，无八度记号）

**举例**：G 大调，音符 F♮4（还原号 `<accidental>natural</accidental>`）
- `key_step_acc = +1`, `eff = 0`（还原号强制为自然）
- `eff ≠ key_step_acc` 且 `eff == 0` → `acc = 'b'`（比调号预期低半音）
- 结果：`b7`（G 大调中的降7级 = F♮）

### Token 书写顺序

每个 jianpu token 的格式为：
```
[时值前缀][八度记号][变音记号][唱名][附点]
```
示例：`q,4`（八分音符、低八度、4 级）、`s'#5`（十六分音符、高八度、升 5 级）、
`1.`（附点四分音符、1 级）。

时值前缀：`h`（64分）、`d`（32分）、`s`（16分）、`q`（8分）、
`""`（四分音符及以上为空白）。

对于二分/全音/倍全音符，附点**不写在主音符上**，而是吸收进增时线。
例如：`1 - -` = 附点二分音符（3 拍），而非 `1. - -`。

圆滑线 `(` `)` 和延音线 `~` 作为**独立 token** 输出（以空格分隔），
绝不粘连到音符上。这样可以避免 jianpu-ly 的 "Unrecognised command" 错误。

和弦的书写规则：将各音高成分首尾相连。例如 `,135'` 表示三个音
（低八度1、自然八度3、高八度5），前面加时值前缀：`s,135'` = 十六分和弦。

### 超小节处理（散板自动修正）

当 MusicXML 某个 `<measure>` 内含音符总时长超过当前拍号允许值
（MuseScore 导出的常见问题，如 cadenza 段落），转换器会：

1. 从各音符的 `<type>` + `<dot>` 累加计算实际时值（以四分音符为单位）
2. 与当前拍号的预期时值比较
3. 如果超出：
   - 调用 `_best_timesig()` 计算最佳拍号：
     - 依次用 `/4`、`/8`、`/16` 做分母，找精确匹配或最接近的分数
     - 例如：14.0Q → `14/4`, 4.5Q → `9/8`, 2.8Q → `11/16`
   - 在 stderr 输出 **WARNING**，注明小节号
   - 若偏差 ≤ 2 拍，额外提示 **"possible input error?"**
   - 在输出文本中插入修正后的拍号，并更新后续小节的 `cur_time`

### 倚音

MusicXML 的倚音被收集为 `g[...]` 语法：
```
g[#45] 1    — 两个倚音（升4、5），后面是主音 1
g[s'6q5] 1  — 带时值的倚音（16分高6、8分5）
```

目前仅支持前倚音。后倚音（`[...]g`）尚未区分处理。

### 连音（三连音等）

连音使用 jianpu 的 `N[...]` 语法：
```
3[ q1 q1 q1 ]         — 三连音（三个八分音符占两拍）
6[ s1 s2 s3 s4 s5 s6 ] — 六连音
```

括号数字取自 MusicXML 的 `<time-modification>` 中的 `<actual-notes>` 值。

### 多小节休止压缩

连续的整小节休止合并为 `R*N`：
```
R*5            — 5 小节休止
0 - - -        — 单小节全休止（4/4拍）
```

---

## 命令行选项

| 选项 | 说明 |
|------|------|
| `-o FILE` | 输出文件（默认 stdout） |
| `--minor` | 小调记谱（`6=X` 替代 `1=X`） |
| `--verbose` / `-v` | 逐小节诊断输出（stderr） |

---

## 环境变量

| 变量 | 用途 |
|------|------|
| `j2ly_sloppy_bars` | 设为 `1` 后，jianpu-ly 的 barcheck 从致命错误降为警告 |
| `j2ly_staff_size` | 五线谱尺寸（默认 20） |
| `j2ly_lyric_size` | 歌词字号（默认取 `staff_size`） |

---

## 支持的 MusicXML 元素

| 元素 | 支持程度 |
|------|---------|
| `<pitch>` 含 `<alter>` | ✓ |
| `<accidental>`（升/降/还原） | ✓ |
| 调号 (`<fifths>`) | ✓ |
| 拍号 | ✓ |
| 速度 (`<metronome>`) | ✓ |
| 力度 (`p/mp/mf/f/ff/...`) | ✓ |
| 演奏记号（断奏、保持音、重音） | ✓ |
| 延长音 (fermata) | ✓ |
| 延音线 (`<tied>`) | ✓ |
| 圆滑线 | ✓ |
| 和弦 (`<chord/>`) | ✓ |
| 倚音 | 仅前倚音 `g[...]` |
| 连音 (tuplet) | `N[...]`；需核对比例 |
| 多小节休止 | ✓ |

## 许可

Apache 2.0
