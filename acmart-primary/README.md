# EgoLink 技术报告编译说明

这个目录用于编写和编译 EgoLink 2026 Track 2 技术报告，报告使用 ACM
`acmart` 模板。

## 文件说明

- `egolink_technical_report.tex`：技术报告主文件。
- `egolink_refs.bib`：报告引用文献。
- `compile-report.sh`：一键编译脚本。
- `egolink_technical_report.pdf`：当前已经编译好的 PDF。
- `acmart.cls`：ACM LaTeX 模板类文件。
- `ACM-Reference-Format.bst`：ACM BibTeX 样式文件。
- `acmart.ins`、`acmart.dtx`：ACM 模板源码，用于在 `acmart.cls` 缺失时重新生成。

## 环境要求

Tex Live 2026 pdflatex

## 编译方式

在仓库根目录运行：

```bash
cd acmart-primary
./compile-report.sh
```

脚本会依次执行：

```bash
pdflatex egolink_technical_report
bibtex egolink_technical_report
pdflatex egolink_technical_report
pdflatex egolink_technical_report
```

编译成功后，输出文件为：

```bash
acmart-primary/egolink_technical_report.pdf
```

## 修改报告

通常只需要修改：

- `egolink_technical_report.tex`
- `egolink_refs.bib`

修改后重新运行：

```bash
cd acmart-primary
./compile-report.sh
```

编译过程中生成的 `.aux`、`.bbl`、`.blg`、`.log`、`.out` 等文件是 LaTeX
中间产物，不需要手动维护，也不建议提交到代码仓库。

## 当前报告内容

当前报告包含：

- EgoLink benchmark 和官方交互流程说明；
- 我们的 frame-based service agent 设计；
- algorithm 伪代码；
- TikZ 系统流程图；
- experimental settings；
- final evaluation results；
- README 风格的实验复现说明；
- limitations 和 references。
