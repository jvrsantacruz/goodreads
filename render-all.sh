#!/bin/bash -eu

readonly HERE="$(realpath $(dirname $0))"
readonly RUN="$HERE/run.sh"

$RUN render read --listas-dir /notes/Listas/ --books-dir /notes/Libros/
$RUN render want --listas-dir /notes/Listas/ --books-dir /notes/Libros/
