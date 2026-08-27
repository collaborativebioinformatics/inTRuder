import sys

chrom = ''
with open(sys.argv[1]) as fh:
    for line in fh:
        line = line.strip()
        if line.startswith('Sequence'):
            chrom = line.split(' ')[1].strip()
        else:
            line = line.split(' ')
            try:
                line[0] = int(line[0])
                line[1] = int(line[1])
                line[2] = int(line[2])
                print(chrom, *line, sep='\t')
            except: pass


