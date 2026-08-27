#!/bin/bash

vcf="$1"
out="$2"

awk '
BEGIN { OFS="\t" }

/^#/ { next }

length($5) > length($4) {
		print ">" $1 "_" $2 "_" $3
		print $5
}
' "$vcf" > "$out"
