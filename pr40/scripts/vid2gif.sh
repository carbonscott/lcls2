#!/bin/bash
# vid2gif.sh IN.webm OUT.gif "caption"  -- browser recording to GIF with a caption bar
IN=$1; OUT=$2; CAP=$(printf '%s' "$3" | sed "s/:/\\\\:/g; s/'/’/g")
FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
ffmpeg -v error -y -i "$IN" -vf "fps=6,scale=720:-1:flags=lanczos,pad=iw:ih+30:0:30:color=0x3a3a3a,drawtext=fontfile=$FONT:text='$CAP':x=10:y=8:fontsize=13:fontcolor=white,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" -loop 0 "$OUT"
echo "$OUT: $(du -h "$OUT" | cut -f1), $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN") s"
