import argparse
import json
from .products import PRODUCTS
from .catalog import scan
from .hdf import subdatasets
from .download import download_product

def main(argv=None):
    p = argparse.ArgumentParser(prog="modis-to-wps")
    s = p.add_subparsers(dest="command", required=True)
    s.add_parser("products", help="List supported MODIS product plans")
    inspect = s.add_parser("inspect-hdf", help="List HDF subdatasets")
    inspect.add_argument("file")
    cat = s.add_parser("scan", help="Group local HDF granules by date")
    cat.add_argument("directory")
    cat.add_argument("--product")
    cat.add_argument("--year", type=int)
    dl = s.add_parser("download", help="Search and download MODIS granules with earthaccess")
    dl.add_argument("product", choices=sorted(set(p.product for p in PRODUCTS.values())))
    dl.add_argument("year", type=int)
    dl.add_argument("output_dir")
    dl.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    args = p.parse_args(argv)
    if args.command == "products":
        for kind, item in PRODUCTS.items():
            print(f"{kind:12} {item.product:9} {item.frequency:8} -> {item.target} | {item.notes}")
    elif args.command == "inspect-hdf":
        for name, description in subdatasets(args.file):
            print(name, "\n  ", description)
    elif args.command == "scan":
        print(json.dumps(scan(args.directory, args.product, args.year), indent=2))
    elif args.command == "download":
        print(download_product(args.product, args.year, args.output_dir, bounding_box=args.bbox))

if __name__ == "__main__":
    main()
