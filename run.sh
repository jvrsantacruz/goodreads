#!/bin/sh

readonly HERE="$(realpath $(dirname $0))"
readonly CODE="$HERE"
readonly RENDER_DIR="$(realpath ~/notes/me)"
readonly DATA="$HERE/data"

docker run --rm -v $CODE:/app -v $DATA:/data -v $RENDER_DIR:/render goodreads $@
