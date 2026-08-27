import argparse
import pandas as pd

"""
Author: GA
Description: Script description
"""


def main():
    parser = argparse.ArgumentParser(
        prog='novelty_analysis.py',
        usage='novelty_analysis.py --input <InputPath> --out_dir <OutDir>'
    )
    parser.add_argument(
        '--input',
        dest='in_path',
        required=True,
        help='novelty results file'
    )
    parser.add_argument(
        '--out_dir',
        dest='out_dir',
        required=True,
        help='novelty results file'
    )


    args = parser.parse_args()
    in_path = args.in_path
    out_dir = args.out_dir


    # read in novel data
    nv_df = pd.read_csv(in_path, sep="/t")

    # run each analysis type

    # add motif size analysis

    # add 




if __name__ == "__main__":
    main()