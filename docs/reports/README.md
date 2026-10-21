# Reports

| Report | Read it |
| --- | --- |
| Beta evaluation, October 21, 2026 | [PDF](beta-evaluation-2026-10-21.pdf) (opens in the browser) · [HTML](beta-evaluation-2026-10-21.html) (download and open for the interactive version) |

Each PDF is printed from its HTML page with Chrome:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --no-pdf-header-footer \
  --user-data-dir="$(mktemp -d)" --virtual-time-budget=15000 \
  --print-to-pdf="$PWD/docs/reports/<name>.pdf" "file://$PWD/docs/reports/<name>.html"
```
