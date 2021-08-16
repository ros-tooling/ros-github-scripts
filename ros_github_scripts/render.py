import argparse
import markdown2

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mdfile', type=str)
    parser.add_argument('htmlfile', type=str)
    args = parser.parse_args()

    with open(args.mdfile, 'r') as f:
        mdcontents = f.read()
    htmlcontents = markdown2.markdown(mdcontents, extras=['tables', 'code-friendly', 'fenced-code-blocks'])
    with open(args.htmlfile, 'w') as f:
        f.write(htmlcontents)


if __name__ == '__main__':
    main()
