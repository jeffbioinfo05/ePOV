# ePOV — package status

## Ready and tested
The data pipeline is COMPLETE and import-checked:
build.py + app/{config,utils,taxonomy,exporter,specieslink,flora_funga,gbif_client}.py
all compile and import cleanly. `python build.py` will construct the CSV.
requirements.txt already includes the web stack (fastapi/uvicorn/jinja2/python-multipart).

## Still to add from your machine (web interface only)
`python run.py` imports app.api:app — copy these in before publishing the UI:
- app/api.py
- templates/         (index.html …)
- static/            (css, js)

The build pipeline works without them; only the browser interface needs them.

## Recommended before release
1. Copy app/api.py, templates/, static/ into this tree.
2. pip install -r requirements.txt
3. python build.py --phase checklist    # smoke-test Flora e Funga after the fix
4. Commit a small sample CSV in data/output/ so the UI is demonstrable
   without waiting for the full overnight build.
