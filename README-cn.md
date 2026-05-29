# mxml2jp v0.3.0 — MusicXML 转 jianpu-ly 转换器

将 MusicXML 文件转换为 [jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html) 的纯文本输入。

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

## 命令行选项

| 选项 | 说明 |
|------|------|
| `-o FILE` | 输出文件（默认 stdout） |
| `--minor` | 小调记谱（`6=X`） |
| `--verbose` / `-v` | 每小节诊断信息输出到 stderr |
| `--octave-traditional` | 传统八度标记：低音在数字前，高音在数字后 |

## 架构

```
MusicXML → MusicXmlParser.parse()
  ├── 提取元数据（title, composer, part-list）
  ├── 逐声部解析（<part> → <measure> → <note>/<direction>/<barline>）
  │     └── 中音备份/前进 → 和弦合并
  └── 返回 (title, composer, [(声部名, [小节数据])])

小节数据 → JianpuGenerator.generate()
  ├── 输出 title=, composer=, instrument=, NextPart, OctavesBefore
  ├── 逐小节：
  │     ├── note_to_jianpu()  — 固定调→首调转换
  │     ├── 超小节检测        — 散板/自由节奏处理
  │     └── 连音小节          — 替换为休止符 + 用户警告
  └── 输出 jianpu-ly 文本行
```

## 核心算法：固定调 → 首调

```
1. 从 fifths 确定主音：tonic_step = (fifths × 4) % 7
2. 计算音级距离：dTone = step_idx - tonic_step_idx（必要时 +7）
3. 唱名与八度：degree = dTone % 7 + 1，八度数 = dTone // 7
4. 变音记号：比较实际半音高度与调号默认值
```

## 超小节 / 散板处理

| 情形 | 处理方式 |
|------|---------|
| 偏差 ≥ 4 拍 | LP 块替代拍号模板为 "サ" + 修正后的拍号 |
| 偏差 < 4 拍 | 修正拍号，警告用户 |
| 连音小节 | 替换为 `R*1`，警告用户 |
| 显式 `<time>` 元素 | 总是发出（散板后恢复拍号） |

## 已知局限

- **多声部对齐**：多个声部同谱时，散板休止长度可能不同步
- **连音精度**：jianpu-ly 使用基于类型的计时，连音密集的小节替换为休止
- **Sibelius 导出的中文**：可能需要用 MuseScore 重新导出以确保 UTF-8 编码
- **草原小姐妹**：Sibelius 导出的中文文本编码问题；可通过手动 lilypond 编译生成 PDF

## TODO

- 多声部散板小节对齐
- 使用 MusicXML `<duration>` divisions 计算连音时长
- 排练记号、八度记号、表情文字
- `.mxl` 压缩格式支持

## 支持的 MusicXML 元素

| 元素 | 支持程度 |
|------|---------|
| 音高（含 `<alter>`） | ✓ |
| 调号 / 拍号 | ✓ |
| 速度（`<metronome>`） | ✓ |
| 力度（p/mp/f/ff…） | ✓ |
| 渐强渐弱（`\<`, `\>`, `\!`） | ✓ |
| 文字标注（`^"…"`, `_"…"`） | ✓ |
| 演奏记号（断奏→Fr=▼, 重音→Fr=>, 保持音→Fr=_） | ✓ |
| 圆滑线 / 延音线 | ✓ |
| 和弦（`<chord/>`） | ✓ |
| 倚音（前 + 后） | ✓ |
| 震音（`///`） | ✓ |
| 颤音延长（`\startTrillSpan`/`\stopTrillSpan`） | ✓ |
| 技法：泛音、顿音、指法 → `Fr=` | ✓ |
| 连音（`N[…]`） | 替换为休止 + 警告 |
| 多小节休止 | ✓ |
| 备份 / 前进 | 合并为和弦 |

## 更新日志

### v0.3.0
- `--octave-traditional` 选项
- 连音替换：`R*1` 不改变拍号
- `read_input()` UTF-8/GBK fallback 编码
- 休止符/节奏符不用 `-`，用显式 `0 0 0` token
- 散板后拍号总是恢复

### v0.2.1
- 特征开关（`self.feat`），逐步编译测试
- 渐强渐弱、力度、标注、Fr= 技法
- `\bendAfter` 移除（多 token 不兼容）

### v0.2.0
- 后倚音、震音、颤音延长、Fr= 映射
- 超小节自动检测

### v0.1.0
- 初始发布

## 许可

Apache 2.0
