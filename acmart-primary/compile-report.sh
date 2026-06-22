#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
JOB_NAME=egolink_technical_report

cd "$SCRIPT_DIR"

actual_pdflatex="$(command -v pdflatex)"
echo "pdflatex: $actual_pdflatex"

if [ ! -f acmart.cls ]; then
  pdflatex -interaction=nonstopmode -halt-on-error acmart.ins
fi

pdflatex -interaction=nonstopmode -halt-on-error "$JOB_NAME"
bibtex "$JOB_NAME"
pdflatex -interaction=nonstopmode -halt-on-error "$JOB_NAME"
pdflatex -interaction=nonstopmode -halt-on-error "$JOB_NAME"

echo "Built $SCRIPT_DIR/$JOB_NAME.pdf"
