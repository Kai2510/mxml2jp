# mxml2jp — MusicXML 转 jianpu-ly 转换器

将 MusicXML 文件（`.xml`, `.musicxml`, `.mxl`）转换为
[jianpu-ly](https://ssb22.user.srcf.net/mwrhome/jianpu-ly.html) 的纯文本输入格式，
jianpu-ly 是一个基于 LilyPond 的简谱排版工具。

## 快速开始

```sh
python mxml2jp.py 乐谱.musicxml -o 乐谱.txt
python mxml2jp.py 乐谱.xml
```

## 功能

- 读取 MuseScore 4+、Sibelius、PhotoScore 等软件导出的 **partwise MusicXML**
- 将固定调音高转换为首调简谱（1=主音）
- 处理调号、拍号、多声部（`NextPart`）
- 保留连线（延音线）、圆滑线、力度记号、演奏记号（断奏、保持音、重音、延长音）
- 连续的整小节休止合并为 `R*N` 写法
- 基本支持连音（三连音等）、和弦、倚音
- `--minor` 选项使用小调记谱（`6=X` 而非 `1=X`）

## 局限性

- **倚音**已转换，但需人工检查调整
- **连音**仅作简单标记（`N[...]`），转换后需核对比例
- **多声部**（同乐器内的多Voice）不做区分，请在 MusicXML 中用独立的声部处理
- **震音**、颤音等高级装饰音未做映射
- **排练记号**、八度符号、文本说明会丢失
- 转换结果是**半成品**，需要人工润色

## 推荐工作流

1. 从制谱软件导出 MusicXML
2. 运行 `mxml2jp.py` 得到 jianpu-ly 文本
3. 检查输出，修正倚音、连音、力度等细节
4. 运行 `jianpu-ly < 乐谱.txt > 乐谱.ly && lilypond 乐谱.ly`
5. 迭代修改

## 支持的 MusicXML 元素

| 元素 | 支持程度 |
|------|---------|
| `<pitch>` 含 `<alter>` | ✓ |
| `<accidental>` (升/降/还原) | ✓ |
| 调号 (`<fifths>`) | ✓ |
| 拍号 | ✓ |
| 速度 (`<metronome>`) | ✓ |
| 力度 (`p/mp/mf/f/ff/...`) | ✓ |
| 演奏记号 (断奏、保持音、重音) | ✓ |
| 延长音 (fermata) | ✓ |
| 延音线 (`<tied>`) | ✓ |
| 圆滑线 | ✓ |
| 和弦 (`<chord/>`) | ✓ |
| 倚音 | 部分支持 |
| 连音 (tuplet) | 部分支持 |
| 多小节休止 | ✓ |

## 许可

Apache 2.0 — 参见 LICENSE 文件。
