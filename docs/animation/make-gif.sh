#!/bin/sh
# out/baton.mp4 -> ../img/baton-demo.gif (two-pass palette for clean colors; loops forever)
set -e
ffmpeg -loglevel error -y -i out/baton.mp4 -vf "fps=15,scale=800:-1:flags=lanczos,palettegen=stats_mode=diff" out/palette.png
ffmpeg -loglevel error -y -i out/baton.mp4 -i out/palette.png \
  -lavfi "fps=15,scale=800:-1:flags=lanczos[v];[v][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
  -loop 0 ../img/baton-demo.gif
ls -lh ../img/baton-demo.gif
